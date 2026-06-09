"""API: Workflows."""

import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import get_workflow
from pi_cowork.system_logs import add_log

workflows_bp = Blueprint("workflows", __name__)


@workflows_bp.route("/api/workflows", methods=["GET"])
def api_workflows():
    rows = query_db("SELECT * FROM workflows ORDER BY name")
    return jsonify([row_to_dict(r) for r in rows])


@workflows_bp.route("/api/workflows", methods=["POST"])
def api_create_workflow():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip() or None
    git_enabled = bool(data.get("git_enabled", False))
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        cur = run_db(
            "INSERT INTO workflows (name, description, git_enabled) VALUES (?, ?, ?)",
            (name, description, int(git_enabled)),
        )
        add_log(
            "INFO",
            "db_change",
            f"INSERT workflows/{cur.lastrowid}",
            details={"operation": "INSERT", "table": "workflows", "record_id": cur.lastrowid},
        )
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Workflow name already exists"}), 409


@workflows_bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
def api_get_workflow(workflow_id):
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    return jsonify(wf)


@workflows_bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
def api_update_workflow(workflow_id):
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    data = request.get_json() or {}
    updates = []
    args = []
    if "name" in data:
        updates.append("name = ?")
        args.append(data["name"].strip())
    if "description" in data:
        updates.append("description = ?")
        args.append((data["description"] or "").strip() or None)
    if "git_enabled" in data:
        updates.append("git_enabled = ?")
        args.append(int(bool(data["git_enabled"])))
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(workflow_id)
    try:
        run_db(f"UPDATE workflows SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    except sqlite3.IntegrityError:
        return jsonify({"error": "Workflow name already exists"}), 409
    add_log(
        "INFO",
        "db_change",
        f"UPDATE workflows/{workflow_id}",
        details={"operation": "UPDATE", "table": "workflows", "record_id": workflow_id},
    )
    return jsonify({"success": True})


@workflows_bp.route("/api/workflows/<int:workflow_id>", methods=["DELETE"])
def api_delete_workflow(workflow_id):
    in_use = query_db("SELECT 1 FROM boards WHERE workflow_id = ? LIMIT 1", (workflow_id,), one=True)
    if in_use:
        return jsonify({"error": "Cannot delete workflow assigned to boards"}), 409
    run_db("DELETE FROM labels WHERE workflow_id = ?", (workflow_id,))
    run_db("DELETE FROM transitions WHERE workflow_id = ?", (workflow_id,))
    run_db("DELETE FROM quality_gates WHERE workflow_id = ?", (workflow_id,))
    run_db("DELETE FROM statuses WHERE workflow_id = ?", (workflow_id,))
    run_db("DELETE FROM agents WHERE workflow_id = ?", (workflow_id,))
    # Cleanup filesystem skill packages before DB cascade removes skill rows
    import os
    import shutil

    from pi_cowork.skill_packages import get_skills_folder

    wf_skills_dir = os.path.join(get_skills_folder(), str(workflow_id))
    if os.path.isdir(wf_skills_dir):
        shutil.rmtree(wf_skills_dir, ignore_errors=True)
    run_db("DELETE FROM workflows WHERE id = ?", (workflow_id,))
    add_log(
        "INFO",
        "db_change",
        f"DELETE workflows/{workflow_id}",
        details={"operation": "DELETE", "table": "workflows", "record_id": workflow_id},
    )
    return jsonify({"success": True})
