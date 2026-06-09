"""API: Skills CRUD."""

import re
import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.models import create_skill, delete_skill, get_skill, get_skills, update_skill

skills_bp = Blueprint("skills", __name__)

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_skill_name(name):
    """Validate that a skill name matches pi CLI conventions."""
    if not name:
        return "name is required"
    if len(name) > 64:
        return "name must be 64 characters or fewer"
    if not _SKILL_NAME_RE.match(name):
        return "name must be lowercase letters, numbers, and single hyphens (no leading/trailing/consecutive hyphens)"
    return None


@skills_bp.route("/api/skills", methods=["GET"])
def api_skills():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    return jsonify(get_skills(workflow_id))


@skills_bp.route("/api/skills", methods=["POST"])
def api_create_skill():
    data = request.get_json() or {}
    workflow_id = data.get("workflow_id")
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip() or None
    content = data.get("content") or ""
    sort_order = data.get("sort_order", 0)

    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    error = _validate_skill_name(name)
    if error:
        return jsonify({"error": error}), 400

    try:
        skill = create_skill(workflow_id, name, description, content, sort_order=sort_order)
        return jsonify(skill), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Skill name already exists in this workflow"}), 409


@skills_bp.route("/api/skills/<int:skill_id>", methods=["GET"])
def api_get_skill(skill_id):
    skill = get_skill(skill_id)
    if not skill:
        return jsonify({"error": "Skill not found"}), 404
    return jsonify(skill)


@skills_bp.route("/api/skills/<int:skill_id>", methods=["PUT"])
def api_update_skill(skill_id):
    skill = get_skill(skill_id)
    if not skill:
        return jsonify({"error": "Skill not found"}), 404
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description")
    content = data.get("content")
    sort_order = data.get("sort_order")

    error = None
    if name is not None:
        error = _validate_skill_name(name.strip())
    if error:
        return jsonify({"error": error}), 400

    updates = {}
    if name is not None:
        updates["name"] = name.strip()
    if description is not None:
        updates["description"] = description
    if content is not None:
        updates["content"] = content
    if sort_order is not None:
        updates["sort_order"] = sort_order
    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    try:
        updated = update_skill(skill_id, **updates)
        return jsonify(updated)
    except sqlite3.IntegrityError:
        return jsonify({"error": "Skill name already exists in this workflow"}), 409


@skills_bp.route("/api/skills/<int:skill_id>", methods=["DELETE"])
def api_delete_skill(skill_id):
    skill = get_skill(skill_id)
    if not skill:
        return jsonify({"error": "Skill not found"}), 404
    delete_skill(skill_id)
    return jsonify({"success": True})
