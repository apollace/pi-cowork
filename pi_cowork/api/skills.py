"""API: Skills filesystem scan, ZIP import/export, and folder deletion."""

import io
import os
import zipfile

from flask import Blueprint, jsonify, request, send_file

from pi_cowork.db import query_db
from pi_cowork.skill_packages import (
    delete_skill_package,
    get_built_in_skills_folder,
    get_global_skill_dir,
    get_skill_dir,
    get_skills_folder,
    import_skill_from_github,
    import_skill_from_zip,
    is_built_in_skill,
    list_skills,
    validate_skill_dir_name,
    write_skill_package,
)

skills_bp = Blueprint("skills", __name__)


@skills_bp.route("/api/skills", methods=["GET"])
def api_skills():
    workflow_id = request.args.get("workflow_id", type=int)
    skills = list_skills(workflow_id)
    # Enrich with used_by agents
    if workflow_id is not None:
        agents = query_db("SELECT id, name, skill_names FROM agents WHERE workflow_id = ?", (workflow_id,))
    else:
        agents = query_db("SELECT id, name, skill_names FROM agents")
    used_by = {}
    for a in agents:
        try:
            names = __import__("json").loads(a["skill_names"] or "[]")
        except (ValueError, TypeError):
            names = []
        for name in names:
            used_by.setdefault(name, []).append(a["name"])
    for sk in skills:
        sk["used_by"] = used_by.get(sk["name"], [])
    return jsonify(skills)


@skills_bp.route("/api/skills", methods=["POST"])
def api_create_skill():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    content = (data.get("content") or "").strip()
    workflow_id = data.get("workflow_id")

    error = validate_skill_dir_name(name)
    if error:
        return jsonify({"error": error}), 400

    skill_dir = get_skill_dir(workflow_id, name) if workflow_id is not None else get_global_skill_dir(name)

    if os.path.exists(skill_dir):
        return jsonify({"error": f"Skill '{name}' already exists"}), 409

    write_skill_package(skill_dir, name, description, content)

    subdirs = []
    for sub in sorted(os.listdir(skill_dir)):
        if os.path.isdir(os.path.join(skill_dir, sub)) and not sub.startswith("."):
            subdirs.append(sub)

    return jsonify({"name": name, "description": description, "content": content, "subdirs": subdirs}), 201


@skills_bp.route("/api/skills/import-github", methods=["POST"])
def api_import_skill_github():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    workflow_id = data.get("workflow_id")
    if workflow_id is not None:
        try:
            workflow_id = int(workflow_id)
        except (ValueError, TypeError):
            return jsonify({"error": "workflow_id must be an integer"}), 400

    if not url:
        return jsonify({"error": "url is required"}), 400

    skill_info, error = import_skill_from_github(url, workflow_id)
    if error:
        if "already exists" in error.lower():
            status = 409
        elif "not found" in error.lower():
            status = 404
        else:
            status = 400
        return jsonify({"error": error}), status

    return jsonify(skill_info), 201


@skills_bp.route("/api/skills/import", methods=["POST"])
def api_import_skill():
    workflow_id = request.form.get("workflow_id", type=int)

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "file is required"}), 400

    skill_info, error = import_skill_from_zip(file, workflow_id)
    if error:
        status = 409 if "already exists" in error else 400
        return jsonify({"error": error}), status

    return jsonify(skill_info), 201


@skills_bp.route("/api/skills/<name>/export", methods=["GET"])
def api_export_skill(name):
    workflow_id = request.args.get("workflow_id", type=int)
    skill_dir = None
    if workflow_id is not None:
        skill_dir = get_skill_dir(workflow_id, name)
    if not skill_dir or not os.path.isdir(skill_dir):
        skill_dir = os.path.join(get_skills_folder(), "global", name)
    if not os.path.isdir(skill_dir):
        skill_dir = os.path.join(get_built_in_skills_folder(), name)
    if not os.path.isdir(skill_dir):
        return jsonify({"error": "Skill not found"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(skill_dir):
            for f in files:
                fpath = os.path.join(root, f)
                arcname = os.path.relpath(fpath, skill_dir)
                zf.write(fpath, arcname)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{name}.zip",
    )


@skills_bp.route("/api/skills/<name>", methods=["DELETE"])
def api_delete_skill(name):
    workflow_id = request.args.get("workflow_id", type=int)
    error = validate_skill_dir_name(name)
    if error:
        return jsonify({"error": error}), 400
    # Reject deletion of built-in/system skills
    if is_built_in_skill(name):
        return jsonify({"error": "System skills cannot be deleted"}), 403
    if workflow_id is not None:
        skill_dir = get_skill_dir(workflow_id, name)
    else:
        skill_dir = os.path.join(get_skills_folder(), "global", name)
    if not os.path.isdir(skill_dir):
        return jsonify({"error": "Skill not found"}), 404
    delete_skill_package(skill_dir)
    return jsonify({"success": True})
