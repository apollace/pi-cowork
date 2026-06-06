"""API: Comments."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db
from pi_cowork.models import add_comment, get_comments
from pi_cowork.system_logs import add_log

comments_bp = Blueprint("comments", __name__)


@comments_bp.route("/api/tickets/<int:ticket_id>/comments", methods=["GET"])
def api_comments(ticket_id):
    return jsonify(get_comments(ticket_id))


@comments_bp.route("/api/tickets/<int:ticket_id>/comments", methods=["POST"])
def api_add_comment(ticket_id):
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    data = request.get_json() or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Comment body is required"}), 400
    comment_id = add_comment(ticket_id, body)
    add_log(
        "INFO",
        "db_change",
        f"INSERT comments/{comment_id}",
        details={"operation": "INSERT", "table": "comments", "record_id": comment_id},
        ticket_id=ticket_id,
    )
    return jsonify({"id": comment_id}), 201
