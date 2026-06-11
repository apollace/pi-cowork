"""API: Agents CRUD."""

import json
import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.api.pi_models import get_model_ids, get_thinking_levels
from pi_cowork.api_docs import _REGISTRY_MAP
from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import (
    get_agent,
    get_agent_excluded_skill_names,
    get_agent_skill_names,
    get_workflow,
    set_agent_excluded_skill_names,
    set_agent_skill_names,
)

agents_api_bp = Blueprint("agents_api", __name__)


@agents_api_bp.route("/api/agents", methods=["GET"])
def api_agents():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    rows = query_db("SELECT * FROM agents WHERE workflow_id = ? ORDER BY name", (workflow_id,))
    result = []
    for r in rows:
        agent = row_to_dict(r)
        agent["skill_names"] = get_agent_skill_names(agent["id"])
        agent["excluded_skill_names"] = get_agent_excluded_skill_names(agent["id"])
        result.append(agent)
    return jsonify(result)


@agents_api_bp.route("/api/agents", methods=["POST"])
def api_create_agent():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    workflow_id = data.get("workflow_id")
    model = data.get("model") or None
    thinking = data.get("thinking") or None
    if not name or not description:
        return jsonify({"error": "name and description are required"}), 400
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    if thinking is not None:
        valid_thinking = get_thinking_levels()
        if thinking not in valid_thinking:
            return jsonify({"error": f"thinking must be one of: {', '.join(valid_thinking)}"}), 400
    if model is not None:
        valid_models = get_model_ids()
        if valid_models and model not in valid_models:
            return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400

    api_endpoints = data.get("api_endpoints")
    if api_endpoints is not None:
        if not isinstance(api_endpoints, list):
            return jsonify({"error": "api_endpoints must be a list of endpoint keys or null"}), 400
        invalid = [k for k in api_endpoints if k not in _REGISTRY_MAP]
        if invalid:
            return jsonify({"error": f"Unknown endpoint keys: {', '.join(invalid)}"}), 400
        api_endpoints_json = json.dumps(api_endpoints)
    else:
        api_endpoints_json = None

    try:
        cur = run_db(
            "INSERT INTO agents (name, description, workflow_id, model, thinking, "
            "api_endpoints) VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, workflow_id, model, thinking, api_endpoints_json),
        )
        agent_id = cur.lastrowid
        skill_names = data.get("skill_names")
        if skill_names is not None and isinstance(skill_names, list):
            set_agent_skill_names(agent_id, skill_names)
        excluded_skill_names = data.get("excluded_skill_names")
        if excluded_skill_names is not None and isinstance(excluded_skill_names, list):
            set_agent_excluded_skill_names(agent_id, excluded_skill_names)
        return jsonify({"id": agent_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Agent name already exists"}), 409


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["GET"])
def api_get_agent(agent_id):
    agent = get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    agent = dict(agent)
    agent["skill_names"] = get_agent_skill_names(agent_id)
    agent["excluded_skill_names"] = get_agent_excluded_skill_names(agent_id)
    return jsonify(agent)


def _build_agent_updates(data):
    """Validate and build SQL updates for agent fields."""
    updates = []
    args = []
    name = data.get("name")
    description = data.get("description")
    model = data.get("model")
    thinking = data.get("thinking")

    if name is not None:
        updates.append("name = ?")
        args.append(name.strip())
    if description is not None:
        updates.append("description = ?")
        args.append(description.strip())
    if model is not None:
        updates.append("model = ?")
        args.append(model if model else None)
        if model:
            valid_models = get_model_ids()
            if valid_models and model not in valid_models:
                return None, None, (jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400)
    if thinking is not None:
        valid_thinking = get_thinking_levels()
        if thinking and thinking not in valid_thinking:
            return None, None, (jsonify({"error": f"thinking must be one of: {', '.join(valid_thinking)}"}), 400)
        updates.append("thinking = ?")
        args.append(thinking if thinking else None)
    if "api_endpoints" in data:
        api_endpoints = data.get("api_endpoints")
        if api_endpoints is not None:
            if not isinstance(api_endpoints, list):
                return None, None, (jsonify({"error": "api_endpoints must be a list of endpoint keys or null"}), 400)
            invalid = [k for k in api_endpoints if k not in _REGISTRY_MAP]
            if invalid:
                return None, None, (jsonify({"error": f"Unknown endpoint keys: {', '.join(invalid)}"}), 400)
            updates.append("api_endpoints = ?")
            args.append(json.dumps(api_endpoints))
        else:
            updates.append("api_endpoints = ?")
            args.append(None)
    if "excluded_skill_names" in data:
        excluded_skill_names = data.get("excluded_skill_names")
        if excluded_skill_names is not None:
            if not isinstance(excluded_skill_names, list):
                return None, None, (jsonify({"error": "excluded_skill_names must be a list of strings or null"}), 400)
            updates.append("excluded_skill_names = ?")
            args.append(json.dumps([str(n).strip() for n in excluded_skill_names if str(n).strip()]))
        else:
            updates.append("excluded_skill_names = ?")
            args.append(None)
    return updates, args, None


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["PUT"])
def api_update_agent(agent_id):
    agent = get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    data = request.get_json() or {}
    updates, args, error = _build_agent_updates(data)
    if error:
        return error
    if not updates:
        skill_names = data.get("skill_names")
        if skill_names is not None and isinstance(skill_names, list):
            set_agent_skill_names(agent_id, skill_names)
        excluded_skill_names = data.get("excluded_skill_names")
        if excluded_skill_names is not None and isinstance(excluded_skill_names, list):
            set_agent_excluded_skill_names(agent_id, excluded_skill_names)
            return jsonify({"success": True})
        return jsonify({"error": "No fields to update"}), 400
    args.append(agent_id)
    try:
        run_db(f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    except sqlite3.IntegrityError:
        return jsonify({"error": "Agent name already exists"}), 409
    skill_names = data.get("skill_names")
    if skill_names is not None and isinstance(skill_names, list):
        set_agent_skill_names(agent_id, skill_names)
    excluded_skill_names = data.get("excluded_skill_names")
    if excluded_skill_names is not None and isinstance(excluded_skill_names, list):
        set_agent_excluded_skill_names(agent_id, excluded_skill_names)
    return jsonify({"success": True})


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
def api_delete_agent(agent_id):
    in_use = query_db("SELECT 1 FROM statuses WHERE agent_id = ? LIMIT 1", (agent_id,), one=True)
    if in_use:
        return jsonify({"error": "Cannot delete agent assigned to a status"}), 409
    run_db("DELETE FROM agents WHERE id = ?", (agent_id,))
    return jsonify({"success": True})
