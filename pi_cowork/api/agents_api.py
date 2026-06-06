"""API: Agents CRUD."""

import json
import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.api.pi_models import get_model_ids, get_thinking_levels
from pi_cowork.api_docs import _REGISTRY_MAP
from pi_cowork.db import query_db, run_db
from pi_cowork.models import get_agent, get_agents, get_workflow

agents_api_bp = Blueprint("agents_api", __name__)


@agents_api_bp.route("/api/agents", methods=["GET"])
def api_agents():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    return jsonify(get_agents(workflow_id))


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
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Agent name already exists"}), 409


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["GET"])
def api_get_agent(agent_id):
    agent = get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    return jsonify(agent)


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["PUT"])
def api_update_agent(agent_id):
    agent = get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description")
    model = data.get("model")
    thinking = data.get("thinking")
    updates = []
    args = []
    if name is not None:
        updates.append("name = ?")
        args.append(name.strip())
    if description is not None:
        updates.append("description = ?")
        args.append(description.strip())
    if model is not None:
        updates.append("model = ?")
        # Empty string or null clears the override (sets DB value to NULL)
        args.append(model if model else None)
        if model:
            valid_models = get_model_ids()
            if valid_models and model not in valid_models:
                return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400
    if thinking is not None:
        valid_thinking = get_thinking_levels()
        if thinking and thinking not in valid_thinking:
            return jsonify({"error": f"thinking must be one of: {', '.join(valid_thinking)}"}), 400
        updates.append("thinking = ?")
        # Empty string or null clears the override (sets DB value to NULL)
        args.append(thinking if thinking else None)
    # api_endpoints: list of keys → JSON string; null/None → NULL (use defaults)
    if "api_endpoints" in data:
        api_endpoints = data.get("api_endpoints")
        if api_endpoints is not None:
            if not isinstance(api_endpoints, list):
                return jsonify({"error": "api_endpoints must be a list of endpoint keys or null"}), 400
            invalid = [k for k in api_endpoints if k not in _REGISTRY_MAP]
            if invalid:
                return jsonify({"error": f"Unknown endpoint keys: {', '.join(invalid)}"}), 400
            updates.append("api_endpoints = ?")
            args.append(json.dumps(api_endpoints))
        else:
            # Explicitly set to null → use defaults
            updates.append("api_endpoints = ?")
            args.append(None)
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(agent_id)
    try:
        run_db(f"UPDATE agents SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    except sqlite3.IntegrityError:
        return jsonify({"error": "Agent name already exists"}), 409
    return jsonify({"success": True})


@agents_api_bp.route("/api/agents/<int:agent_id>", methods=["DELETE"])
def api_delete_agent(agent_id):
    in_use = query_db("SELECT 1 FROM statuses WHERE agent_id = ? LIMIT 1", (agent_id,), one=True)
    if in_use:
        return jsonify({"error": "Cannot delete agent assigned to a status"}), 409
    run_db("DELETE FROM agents WHERE id = ?", (agent_id,))
    return jsonify({"success": True})
