"""API: Statuses CRUD."""

import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.api.pi_models import get_model_ids, get_thinking_levels
from pi_cowork.db import query_db, run_db
from pi_cowork.models import get_status, get_statuses, get_workflow
from pi_cowork.system_logs import add_log

statuses_bp = Blueprint("statuses", __name__)


@statuses_bp.route("/api/statuses", methods=["GET"])
def api_statuses():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    return jsonify(get_statuses(workflow_id))


@statuses_bp.route("/api/statuses", methods=["POST"])
def api_create_status():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    sort_order = data.get("sort_order")
    is_default = 1 if data.get("is_default") else 0
    is_terminal = 1 if data.get("is_terminal") else 0
    agent_id = data.get("agent_id")
    goal = (data.get("goal") or "").strip() or None
    model = data.get("model") or None
    thinking = data.get("thinking") or None
    workflow_id = data.get("workflow_id")
    if not name or sort_order is None:
        return jsonify({"error": "name and sort_order are required"}), 400
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
    try:
        cur = run_db(
            "INSERT INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, model, thinking, workflow_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, int(sort_order), is_default, is_terminal, agent_id, goal, model, thinking, workflow_id),
        )
        add_log(
            "INFO",
            "db_change",
            f"INSERT statuses/{cur.lastrowid}",
            details={"operation": "INSERT", "table": "statuses", "record_id": cur.lastrowid},
        )
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Status name already exists"}), 409


@statuses_bp.route("/api/statuses/<int:status_id>", methods=["GET"])
def api_get_status(status_id):
    status = get_status(status_id)
    if not status:
        return jsonify({"error": "Status not found"}), 404
    return jsonify(status)


@statuses_bp.route("/api/statuses/<int:status_id>", methods=["PUT"])
def api_update_status(status_id):
    status = get_status(status_id)
    if not status:
        return jsonify({"error": "Status not found"}), 404
    data = request.get_json() or {}
    updates = []
    args = []
    if "name" in data:
        updates.append("name = ?")
        args.append(data["name"].strip())
    if "sort_order" in data:
        updates.append("sort_order = ?")
        args.append(int(data["sort_order"]))
    if "is_default" in data:
        updates.append("is_default = ?")
        args.append(1 if data["is_default"] else 0)
    if "is_terminal" in data:
        updates.append("is_terminal = ?")
        args.append(1 if data["is_terminal"] else 0)
    if "agent_id" in data:
        updates.append("agent_id = ?")
        args.append(data["agent_id"])
    if "goal" in data:
        updates.append("goal = ?")
        args.append((data["goal"] or "").strip() or None)
    if "model" in data:
        model = data["model"]
        if model:
            valid_models = get_model_ids()
            if valid_models and model not in valid_models:
                return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400
        updates.append("model = ?")
        args.append(model if model else None)
    if "thinking" in data:
        valid_thinking = get_thinking_levels()
        thinking = data["thinking"]
        if thinking and thinking not in valid_thinking:
            return jsonify({"error": f"thinking must be one of: {', '.join(valid_thinking)}"}), 400
        updates.append("thinking = ?")
        args.append(thinking if thinking else None)
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(status_id)
    try:
        run_db(f"UPDATE statuses SET {', '.join(updates)} WHERE id = ?", tuple(args))
    except sqlite3.IntegrityError:
        return jsonify({"error": "Status name already exists"}), 409
    add_log(
        "INFO",
        "db_change",
        f"UPDATE statuses/{status_id}",
        details={"operation": "UPDATE", "table": "statuses", "record_id": status_id},
    )
    return jsonify({"success": True})


@statuses_bp.route("/api/statuses/<int:status_id>", methods=["DELETE"])
def api_delete_status(status_id):
    in_use_ticket = query_db("SELECT 1 FROM tickets WHERE status_id = ? LIMIT 1", (status_id,), one=True)
    if in_use_ticket:
        return jsonify({"error": "Cannot delete status used by tickets"}), 409
    in_use_transition = query_db(
        "SELECT 1 FROM transitions WHERE from_status_id = ? OR to_status_id = ? LIMIT 1",
        (status_id, status_id),
        one=True,
    )
    if in_use_transition:
        return jsonify({"error": "Cannot delete status used by transitions"}), 409
    run_db("DELETE FROM statuses WHERE id = ?", (status_id,))
    add_log(
        "INFO",
        "db_change",
        f"DELETE statuses/{status_id}",
        details={"operation": "DELETE", "table": "statuses", "record_id": status_id},
    )
    return jsonify({"success": True})
