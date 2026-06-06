"""API: Labels and Ticket-Labels."""

import contextlib
import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db
from pi_cowork.models import get_label, get_labels, get_ticket_labels, get_workflow
from pi_cowork.system_logs import add_log

labels_bp = Blueprint("labels", __name__)


# --- Workflow Labels ---


@labels_bp.route("/api/labels", methods=["GET"])
def api_labels():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    return jsonify(get_labels(workflow_id))


@labels_bp.route("/api/labels", methods=["POST"])
def api_create_label():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    color = (data.get("color") or "").strip() or "#6b7280"
    workflow_id = data.get("workflow_id")
    if not name:
        return jsonify({"error": "name is required"}), 400
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    try:
        cur = run_db("INSERT INTO labels (name, color, workflow_id) VALUES (?, ?, ?)", (name, color, workflow_id))
        add_log(
            "INFO",
            "db_change",
            f"INSERT labels/{cur.lastrowid}",
            details={"operation": "INSERT", "table": "labels", "record_id": cur.lastrowid},
        )
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Label name already exists in this workflow"}), 409


@labels_bp.route("/api/labels/<int:label_id>", methods=["GET"])
def api_get_label(label_id):
    label = get_label(label_id)
    if not label:
        return jsonify({"error": "Label not found"}), 404
    return jsonify(label)


@labels_bp.route("/api/labels/<int:label_id>", methods=["PUT"])
def api_update_label(label_id):
    label = get_label(label_id)
    if not label:
        return jsonify({"error": "Label not found"}), 404
    data = request.get_json() or {}
    updates = []
    args = []
    if "name" in data:
        updates.append("name = ?")
        args.append(data["name"].strip())
    if "color" in data:
        updates.append("color = ?")
        args.append((data["color"] or "").strip() or "#6b7280")
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(label_id)
    try:
        run_db(f"UPDATE labels SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    except sqlite3.IntegrityError:
        return jsonify({"error": "Label name already exists in this workflow"}), 409
    add_log(
        "INFO",
        "db_change",
        f"UPDATE labels/{label_id}",
        details={"operation": "UPDATE", "table": "labels", "record_id": label_id},
    )
    return jsonify({"success": True})


@labels_bp.route("/api/labels/<int:label_id>", methods=["DELETE"])
def api_delete_label(label_id):
    run_db("DELETE FROM labels WHERE id = ?", (label_id,))
    add_log(
        "INFO",
        "db_change",
        f"DELETE labels/{label_id}",
        details={"operation": "DELETE", "table": "labels", "record_id": label_id},
    )
    return jsonify({"success": True})


# --- Ticket Labels ---


@labels_bp.route("/api/tickets/<int:ticket_id>/labels", methods=["GET"])
def api_ticket_labels(ticket_id):
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify(get_ticket_labels(ticket_id))


@labels_bp.route("/api/tickets/<int:ticket_id>/labels", methods=["POST"])
def api_add_ticket_labels(ticket_id):
    ticket = query_db(
        """
        SELECT t.*, b.workflow_id
        FROM tickets t
        JOIN boards b ON t.board_id = b.id
        WHERE t.id = ?
    """,
        (ticket_id,),
        one=True,
    )
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    data = request.get_json() or {}
    label_ids = data.get("label_ids", [])
    if not isinstance(label_ids, list):
        return jsonify({"error": "label_ids must be an array"}), 400
    if not label_ids:
        return jsonify({"success": True})
    placeholders = ",".join("?" * len(label_ids))
    valid = query_db(
        f"SELECT id FROM labels WHERE workflow_id = ? AND id IN ({placeholders})",  # noqa: S608
        (ticket["workflow_id"], *label_ids),
    )
    valid_ids = {r["id"] for r in valid}
    invalid = set(label_ids) - valid_ids
    if invalid:
        return jsonify({"error": f"Invalid label IDs: {sorted(invalid)}"}), 400
    for lid in label_ids:
        with contextlib.suppress(sqlite3.IntegrityError):
            run_db("INSERT INTO ticket_labels (ticket_id, label_id) VALUES (?, ?)", (ticket_id, lid))
    return jsonify({"success": True}), 201


@labels_bp.route("/api/tickets/<int:ticket_id>/labels", methods=["DELETE"])
def api_remove_ticket_label(ticket_id):
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    label_id = request.args.get("label_id", type=int)
    if label_id is None:
        return jsonify({"error": "label_id is required"}), 400
    run_db("DELETE FROM ticket_labels WHERE ticket_id = ? AND label_id = ?", (ticket_id, label_id))
    return jsonify({"success": True})
