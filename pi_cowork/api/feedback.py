"""API: Agent Feedback — create, update, list, and consume feedback rows."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db
from pi_cowork.models import (
    add_agent_feedback,
    get_feedback_count,
    get_unconsumed_feedback_enriched,
    mark_feedback_consumed,
)

feedback_bp = Blueprint("feedback", __name__)


def _parse_consumed(value):
    """Parse consumed query param into tristate bool.

    Returns True/False for explicit values, None when absent or empty.
    """
    if value is None or value == "":
        return None
    v = value.lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return None


@feedback_bp.route("/api/feedback", methods=["GET"])
def api_list_feedback():
    """List feedback rows with optional filtering, enrichment, and pagination."""
    consumed = _parse_consumed(request.args.get("consumed"))
    feedback_type = request.args.get("feedback_type")
    ticket_id = request.args.get("ticket_id", type=int)
    agent_id = request.args.get("agent_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    limit = request.args.get("limit", type=int)

    # Backward compat: limit overrides per_page when explicit
    if limit is not None:
        per_page = limit
        page = 1

    limit = max(1, min(per_page, 200))
    offset = max(0, (page - 1) * limit)

    total = get_feedback_count(
        consumed=consumed,
        feedback_type=feedback_type,
        ticket_id=ticket_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    rows = get_unconsumed_feedback_enriched(
        consumed=consumed,
        feedback_type=feedback_type,
        ticket_id=ticket_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
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

    total_pages = (total + limit - 1) // limit if total > 0 else 1
    return jsonify(
        {
            "feedback": feedback,
            "total": total,
            "page": page,
            "per_page": limit,
            "total_pages": total_pages,
        }
    )


@feedback_bp.route("/api/feedback/<int:feedback_id>/preview", methods=["GET"])
def api_feedback_preview(feedback_id):
    """Return canonical structured JSON payload for a self-improvement agent."""
    row = query_db(
        """
        SELECT
            af.id,
            af.ticket_id,
            af.run_id,
            af.gate_review_id,
            af.feedback_type,
            af.reason,
            af.expected_behavior,
            af.context_json,
            af.created_at,
            af.consumed_at,
            af.consumed_by_run_id,
            af.source_event,
            af.created_by,
            t.title AS ticket_title,
            a.name AS agent_name,
            ar.status AS run_status,
            ar.log_path AS run_log_path,
            qg.name AS gate_name,
            qg.gate_type AS gate_type,
            fs.name AS from_status,
            ts.name AS to_status
        FROM agent_feedback af
        LEFT JOIN tickets t ON t.id = af.ticket_id
        LEFT JOIN agent_runs ar ON ar.id = af.run_id
        LEFT JOIN agents a ON a.id = ar.agent_id
        LEFT JOIN gate_reviews gr ON gr.id = af.gate_review_id
        LEFT JOIN quality_gates qg ON qg.id = gr.gate_id
        LEFT JOIN statuses fs ON fs.id = gr.from_status_id
        LEFT JOIN statuses ts ON ts.id = gr.to_status_id
        WHERE af.id = ?
    """,
        (feedback_id,),
        one=True,
    )
    if not row:
        return jsonify({"error": "Feedback not found"}), 404

    import json

    context = {}
    if row["context_json"]:
        try:
            context = json.loads(row["context_json"])
        except json.JSONDecodeError:
            context = {"_invalid_context_json": row["context_json"]}

    runtime = {}
    for key in ("run_status", "gate_name", "gate_type", "from_status", "to_status"):
        if row[key]:
            runtime[key] = row[key]
    if runtime:
        context.update(runtime)

    payload = {
        "id": row["id"],
        "ticket": {
            "id": row["ticket_id"],
            "title": row["ticket_title"],
        },
        "agent": row["agent_name"],
        "run": {
            "id": row["run_id"],
            "status": row["run_status"],
            "log_path": row["run_log_path"],
        }
        if row["run_id"]
        else None,
        "gate_review": {
            "id": row["gate_review_id"],
            "gate_name": row["gate_name"],
            "gate_type": row["gate_type"],
            "from_status": row["from_status"],
            "to_status": row["to_status"],
        }
        if row["gate_review_id"]
        else None,
        "feedback_type": row["feedback_type"],
        "reason": row["reason"],
        "expected_behavior": row["expected_behavior"],
        "context": context,
        "created_at": row["created_at"],
        "consumed_at": row["consumed_at"],
        "consumed_by_run_id": row["consumed_by_run_id"],
        "source_event": row["source_event"],
        "created_by": row["created_by"],
    }

    return jsonify(payload)


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
