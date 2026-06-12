"""API: Agent Feedback — update feedback rows."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db

feedback_bp = Blueprint("feedback", __name__)


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
