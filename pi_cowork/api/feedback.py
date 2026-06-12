"""API: Agent Feedback — create and update feedback rows."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db
from pi_cowork.models import add_agent_feedback

feedback_bp = Blueprint("feedback", __name__)


@feedback_bp.route("/api/feedback", methods=["POST"])
def api_create_feedback():
    data = request.get_json() or {}
    run_id = data.get("run_id")
    ticket_id = data.get("ticket_id")
    reason = (data.get("reason") or "").strip()
    expected_behavior = data.get("expected_behavior")

    if not run_id:
        return jsonify({"error": "run_id is required"}), 400
    if not ticket_id:
        return jsonify({"error": "ticket_id is required"}), 400
    if not reason:
        return jsonify({"error": "reason is required"}), 400

    run = query_db(
        "SELECT * FROM agent_runs WHERE id = ? AND ticket_id = ?",
        (run_id, ticket_id),
        one=True,
    )
    if not run:
        return jsonify({"error": "Agent run not found for this ticket"}), 404

    feedback_id = add_agent_feedback(
        ticket_id=ticket_id,
        feedback_type="run_feedback",
        run_id=run_id,
        reason=reason,
        expected_behavior=expected_behavior,
        source_event="MANUAL_RUN_FEEDBACK",
        created_by="human",
    )
    return jsonify({"feedback_id": feedback_id}), 201


@feedback_bp.route("/api/feedback/<int:feedback_id>", methods=["PUT"])
def api_update_feedback(feedback_id):
    row = query_db("SELECT * FROM agent_feedback WHERE id = ?", (feedback_id,), one=True)
    if not row:
        return jsonify({"error": "Feedback not found"}), 404

    data = request.get_json() or {}
    updates = []
    args = []

    if "reason" in data:
        updates.append("reason = ?")
        args.append(data["reason"])
    if "expected_behavior" in data:
        updates.append("expected_behavior = ?")
        args.append(data["expected_behavior"])

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    args.append(feedback_id)
    run_db(f"UPDATE agent_feedback SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    return jsonify({"success": True})
