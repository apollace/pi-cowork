"""API: Agent Feedback — create, update, list, and consume feedback rows."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db
from pi_cowork.models import add_agent_feedback, get_unconsumed_feedback_enriched, mark_feedback_consumed

feedback_bp = Blueprint("feedback", __name__)


@feedback_bp.route("/api/feedback", methods=["GET"])
def api_list_feedback():
    """List feedback rows with optional filtering and enrichment."""
    consumed_raw = request.args.get("consumed")
    consumed = False if consumed_raw is None else consumed_raw.lower() in ("1", "true", "yes")

    feedback_type = request.args.get("feedback_type")
    ticket_id = request.args.get("ticket_id", type=int)
    agent_id = request.args.get("agent_id", type=int)
    limit = request.args.get("limit", 50, type=int)

    rows = get_unconsumed_feedback_enriched(
        consumed=consumed,
        feedback_type=feedback_type,
        ticket_id=ticket_id,
        agent_id=agent_id,
        limit=limit,
    )

    # Map DB rows to the public shape expected by consumers
    feedback = []
    for row in rows:
        feedback.append(
            {
                "id": row["id"],
                "type": row["feedback_type"],
                "ticket_id": row["ticket_id"],
                "run_id": row["run_id"],
                "agent": row.get("agent_name"),
                "reason": row.get("reason"),
                "expected_behavior": row.get("expected_behavior"),
                "context": row.get("context", {}),
                "preview": row.get("preview", ""),
                "created_at": row["created_at"],
                "consumed_at": row.get("consumed_at"),
                "consumed_by_run_id": row.get("consumed_by_run_id"),
            }
        )

    return jsonify({"feedback": feedback})


@feedback_bp.route("/api/feedback/<int:feedback_id>/consume", methods=["POST"])
def api_consume_feedback(feedback_id):
    """Mark a feedback row as consumed."""
    row = query_db(
        "SELECT consumed_at FROM agent_feedback WHERE id = ?",
        (feedback_id,),
        one=True,
    )
    if not row:
        return jsonify({"error": "Feedback not found"}), 404

    if row["consumed_at"] is not None:
        return jsonify({"error": "Feedback already consumed"}), 409

    data = request.get_json(silent=True) or {}
    consumed_by_run_id = data.get("consumed_by_run_id")

    mark_feedback_consumed(feedback_id, consumed_by_run_id)
    return jsonify({"success": True})


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
