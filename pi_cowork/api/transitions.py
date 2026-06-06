"""API: Transitions CRUD."""

import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import get_workflow
from pi_cowork.system_logs import add_log

transitions_bp = Blueprint("transitions", __name__)


@transitions_bp.route("/api/transitions", methods=["GET"])
def api_transitions():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    rows = query_db(
        """
        SELECT t.*, fs.name AS from_status_name, ts.name AS to_status_name
        FROM transitions t
        JOIN statuses fs ON t.from_status_id = fs.id
        JOIN statuses ts ON t.to_status_id = ts.id
        WHERE t.workflow_id = ?
        ORDER BY t.from_status_id, t.to_status_id
    """,
        (workflow_id,),
    )
    return jsonify([row_to_dict(r) for r in rows])


@transitions_bp.route("/api/transitions", methods=["POST"])
def api_create_transition():
    data = request.get_json() or {}
    from_id = data.get("from_status_id")
    to_id = data.get("to_status_id")
    instructions = (data.get("instructions") or "").strip() or None
    workflow_id = data.get("workflow_id")
    if from_id is None or to_id is None:
        return jsonify({"error": "from_status_id and to_status_id are required"}), 400
    if from_id == to_id:
        return jsonify({"error": "from and to must be different"}), 400
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    try:
        cur = run_db(
            "INSERT INTO transitions (from_status_id, to_status_id, instructions, workflow_id) VALUES (?, ?, ?, ?)",
            (from_id, to_id, instructions, workflow_id),
        )
        add_log(
            "INFO",
            "db_change",
            f"INSERT transitions/{cur.lastrowid}",
            details={"operation": "INSERT", "table": "transitions", "record_id": cur.lastrowid},
        )
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Transition already exists"}), 409


@transitions_bp.route("/api/transitions/<int:transition_id>", methods=["GET"])
def api_get_transition(transition_id):
    row = query_db(
        """
        SELECT t.*, fs.name AS from_status_name, ts.name AS to_status_name
        FROM transitions t
        JOIN statuses fs ON t.from_status_id = fs.id
        JOIN statuses ts ON t.to_status_id = ts.id
        WHERE t.id = ?
    """,
        (transition_id,),
        one=True,
    )
    if not row:
        return jsonify({"error": "Transition not found"}), 404
    return jsonify(row_to_dict(row))


@transitions_bp.route("/api/transitions/<int:transition_id>", methods=["PUT"])
def api_update_transition(transition_id):
    transition = query_db("SELECT * FROM transitions WHERE id = ?", (transition_id,), one=True)
    if not transition:
        return jsonify({"error": "Transition not found"}), 404
    data = request.get_json() or {}
    instructions = data.get("instructions")
    if instructions is None:
        return jsonify({"error": "instructions is required"}), 400
    run_db(
        "UPDATE transitions SET instructions = ? WHERE id = ?", ((instructions or "").strip() or None, transition_id)
    )
    add_log(
        "INFO",
        "db_change",
        f"UPDATE transitions/{transition_id}",
        details={"operation": "UPDATE", "table": "transitions", "record_id": transition_id},
    )
    return jsonify({"success": True})


@transitions_bp.route("/api/transitions/<int:transition_id>", methods=["DELETE"])
def api_delete_transition(transition_id):
    run_db("DELETE FROM transitions WHERE id = ?", (transition_id,))
    add_log(
        "INFO",
        "db_change",
        f"DELETE transitions/{transition_id}",
        details={"operation": "DELETE", "table": "transitions", "record_id": transition_id},
    )
    return jsonify({"success": True})
