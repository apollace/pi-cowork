"""API: Gate Reviews — approve/reject manual gates, view reviews.

Security note: Gate review approvals (`PUT /api/gate_reviews/<id>` with
status='approved') MUST originate from a human, not from an AI agent.
A random secret is generated at app startup and stored in the Flask config
as ``HUMAN_ACTION_SECRET``.  The web UI includes this secret in the
``X-Human-Action`` header on approval/rejection requests.  The endpoint
rejects any approval that lacks a valid secret, preventing agents from
bypassing manual quality gates.
"""

from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request

from pi_cowork.agents import try_spawn_or_queue
from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.events import GATE_FAILED, GATE_PASSED, GATE_REVIEW_REJECTED, TICKET_STATUS_CHANGED, bus
from pi_cowork.models import add_comment, get_agent, get_board, get_status
from pi_cowork.system_logs import add_log

gate_reviews_bp = Blueprint("gate_reviews", __name__)


@gate_reviews_bp.route("/api/gate_reviews", methods=["GET"])
def api_gate_reviews():
    ticket_id = request.args.get("ticket_id", type=int)
    if ticket_id is None:
        return jsonify({"error": "ticket_id is required"}), 400
    rows = query_db(
        """
        SELECT gr.*, qg.gate_type, qg.name AS gate_name, qg.config AS gate_config,
               fs.name AS from_status_name, ts.name AS to_status_name
        FROM gate_reviews gr
        JOIN quality_gates qg ON gr.gate_id = qg.id
        JOIN statuses fs ON gr.from_status_id = fs.id
        JOIN statuses ts ON gr.to_status_id = ts.id
        WHERE gr.ticket_id = ?
        ORDER BY gr.created_at, gr.id
    """,
        (ticket_id,),
    )
    return jsonify([row_to_dict(r) for r in rows])


@gate_reviews_bp.route("/api/gate_reviews/<int:review_id>", methods=["PUT"])
def api_update_gate_review(review_id):  # noqa: C901
    review = query_db(
        """
        SELECT gr.*, qg.gate_type, qg.name AS gate_name,
               fs.name AS from_status_name, ts.name AS to_status_name
        FROM gate_reviews gr
        JOIN quality_gates qg ON gr.gate_id = qg.id
        JOIN statuses fs ON gr.from_status_id = fs.id
        JOIN statuses ts ON gr.to_status_id = ts.id
        WHERE gr.id = ?
    """,
        (review_id,),
        one=True,
    )
    if not review:
        return jsonify({"error": "Gate review not found"}), 404
    if review["status"] != "pending":
        return jsonify({"error": "Gate review already resolved"}), 409

    # ── Human-action guard ────────────────────────────────────────────
    # Gate review approvals must come from the web UI (a human), not from
    # an AI agent.  The UI sends a random per-instance secret in the
    # X-Human-Action header; agents never receive this secret.
    secret = current_app.config.get("HUMAN_ACTION_SECRET", "")
    provided = request.headers.get("X-Human-Action", "")
    if not secret or provided != secret:
        add_log(
            "WARNING",
            "http_request",
            f"Gate review approval blocked — missing or invalid X-Human-Action header (review_id={review_id})",
        )
        return jsonify({"error": "Gate review approvals require human action. Missing or invalid authentication."}), 403
    # ─────────────────────────────────────────────────────────────────

    data = request.get_json() or {}
    new_status = data.get("status")
    if new_status not in ("approved", "rejected"):
        return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400

    comment = (data.get("comment") or "").strip()
    if new_status == "rejected" and not comment:
        return jsonify({"error": "Rejection requires a comment"}), 400

    ticket_id = review["ticket_id"]
    now = datetime.now(UTC).isoformat()

    # Update the review
    output = comment if comment else None
    run_db(
        "UPDATE gate_reviews SET status = ?, output = ?, completed_at = ? WHERE id = ?",
        (new_status, output, now, review_id),
    )
    add_log(
        "INFO",
        "db_change",
        f"UPDATE gate_reviews/{review_id}",
        details={"operation": "UPDATE", "table": "gate_reviews", "record_id": review_id},
        ticket_id=ticket_id,
    )

    if new_status == "approved":
        add_comment(ticket_id, f"✅ Gate '{review['gate_name']}' approved." + (f" {comment}" if comment else ""))
        # Verify ticket is still in the expected from status
        ticket_check = query_db("SELECT status_id FROM tickets WHERE id = ?", (ticket_id,), one=True)
        if not ticket_check or ticket_check["status_id"] != review["from_status_id"]:
            return jsonify({"success": True, "note": "Ticket status changed; approval ignored."})
        # Check if ALL gates for this transition are now resolved
        pending = query_db(
            """SELECT 1 FROM gate_reviews
               WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?
               AND status = 'pending' LIMIT 1""",
            (ticket_id, review["from_status_id"], review["to_status_id"]),
            one=True,
        )
        if not pending:
            any_rejected = query_db(
                """SELECT 1 FROM gate_reviews
                   WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?
                   AND status IN ('failed', 'rejected') LIMIT 1""",
                (ticket_id, review["from_status_id"], review["to_status_id"]),
                one=True,
            )
            if not any_rejected:
                # All passed/approved — move ticket to new status
                new_status_id = review["to_status_id"]
                old_status_id = review["from_status_id"]
                run_db(
                    "DELETE FROM gate_reviews WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?",
                    (ticket_id, review["from_status_id"], review["to_status_id"]),
                )
                run_db(
                    "UPDATE tickets SET status_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_status_id, ticket_id),
                )
                add_log(
                    "INFO",
                    "db_change",
                    f"UPDATE tickets/{ticket_id}",
                    details={"operation": "UPDATE", "table": "tickets", "record_id": ticket_id, "via": "gate_approval"},
                    ticket_id=ticket_id,
                )
                bus.publish(
                    TICKET_STATUS_CHANGED, ticket_id=ticket_id, old_status_id=old_status_id, new_status_id=new_status_id
                )
                # If the new status is terminal, clear remaining notifications
                status = get_status(new_status_id)
                if status and status.get("is_terminal"):
                    import os
                    import shutil

                    from pi_cowork.models import get_agents

                    ticket_row = query_db(
                        "SELECT t.board_id, b.workflow_id "
                        "FROM tickets t JOIN boards b ON t.board_id = b.id WHERE t.id = ?",
                        (ticket_id,),
                        one=True,
                    )
                    if ticket_row:
                        board = get_board(ticket_row["board_id"]) if ticket_row["board_id"] else None
                        board_dir = board["working_directory"] if board else "workspace"
                        all_agents = get_agents(ticket_row["workflow_id"])
                        for ag in all_agents:
                            session_dir = os.path.join(board_dir, ".pi-sessions", str(ag["id"]), f"ticket-{ticket_id}")
                            if os.path.isdir(session_dir):
                                shutil.rmtree(session_dir)
                    run_db("UPDATE tickets SET agent_last_spawned_at = NULL WHERE id = ?", (ticket_id,))
                    run_db("DELETE FROM gate_reviews WHERE ticket_id = ? AND status = 'pending'", (ticket_id,))
                    run_db("DELETE FROM questions WHERE ticket_id = ?", (ticket_id,))
                    add_comment(
                        ticket_id,
                        "🔔 All pending notifications (gate reviews and questions) cleared — "
                        "ticket is now in a terminal state.",
                    )
                # Spawn agent for new status if applicable
                if status and status.get("agent_id"):
                    agent = get_agent(status["agent_id"])
                    if agent:
                        updated_ticket = query_db(
                            """
                            SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
                            FROM tickets t
                            JOIN boards b ON t.board_id = b.id
                            JOIN workflows w ON b.workflow_id = w.id
                            WHERE t.id = ?
                        """,
                            (ticket_id,),
                            one=True,
                        )
                        try_spawn_or_queue(row_to_dict(updated_ticket), status, agent, old_status_id=old_status_id)
        bus.publish(GATE_PASSED, ticket_id=ticket_id, gate_name=review["gate_name"])

    elif new_status == "rejected":
        add_comment(ticket_id, f"❌ Gate '{review['gate_name']}' rejected: {comment}")
        # Transition is fully rejected — delete all reviews for this flow
        run_db(
            "DELETE FROM gate_reviews WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?",
            (ticket_id, review["from_status_id"], review["to_status_id"]),
        )
        bus.publish(GATE_REVIEW_REJECTED, ticket_id=ticket_id, gate_name=review["gate_name"])
        bus.publish(GATE_FAILED, ticket_id=ticket_id, gate_name=review["gate_name"])
        # Re-trigger agent for the current (old) status
        current_status = get_status(review["from_status_id"])
        if current_status and current_status.get("agent_id"):
            agent = get_agent(current_status["agent_id"])
            if agent:
                updated_ticket = query_db(
                    """
                    SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
                    FROM tickets t
                    JOIN boards b ON t.board_id = b.id
                    JOIN workflows w ON b.workflow_id = w.id
                    WHERE t.id = ?
                """,
                    (ticket_id,),
                    one=True,
                )
                try_spawn_or_queue(row_to_dict(updated_ticket), current_status, agent, old_status_id=None)

    return jsonify({"success": True})
