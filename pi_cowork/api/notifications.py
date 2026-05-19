"""API: Notifications — derived notifications for pending gate reviews and unanswered questions."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict
from pi_cowork.models import (
    dismiss_notification, dismiss_all_notifications,
)

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/api/notifications', methods=['GET'])
def api_notifications():
    """Return derived notifications for pending manual gate reviews and unanswered questions,
    excluding any (ticket_id, type) pairs that have been dismissed."""
    gate_rows = query_db("""
        SELECT t.id AS ticket_id, t.title AS ticket_title,
               b.id AS board_id, b.name AS board_name,
               s.name AS status_name,
               COUNT(gr.id) AS count,
               MIN(gr.created_at) AS created_at
        FROM gate_reviews gr
        JOIN tickets t ON gr.ticket_id = t.id
        JOIN boards b ON t.board_id = b.id
        JOIN statuses s ON t.status_id = s.id
        WHERE gr.status = 'pending' AND s.is_terminal = 0
            AND NOT EXISTS (
                SELECT 1 FROM notification_dismissals nd
                WHERE nd.ticket_id = t.id AND nd.notification_type = 'gate_review'
                AND nd.dismissed_at >= (
                    SELECT MAX(gr2.created_at)
                    FROM gate_reviews gr2
                    WHERE gr2.ticket_id = t.id AND gr2.status = 'pending'
                )
            )
        GROUP BY t.id, t.title, b.id, b.name, s.name
    """)

    question_rows = query_db("""
        SELECT t.id AS ticket_id, t.title AS ticket_title,
               b.id AS board_id, b.name AS board_name,
               s.name AS status_name,
               COUNT(q.id) AS count,
               MIN(q.created_at) AS created_at
        FROM questions q
        JOIN tickets t ON q.ticket_id = t.id
        JOIN boards b ON t.board_id = b.id
        JOIN statuses s ON t.status_id = s.id
        WHERE s.is_terminal = 0
            AND NOT EXISTS (
                SELECT 1 FROM notification_dismissals nd
                WHERE nd.ticket_id = t.id AND nd.notification_type = 'question'
                AND nd.dismissed_at >= (
                    SELECT MAX(q2.created_at)
                    FROM questions q2
                    WHERE q2.ticket_id = t.id
                )
            )
        GROUP BY t.id, t.title, b.id, b.name, s.name
    """)

    notifications = []
    for row in gate_rows:
        d = row_to_dict(row)
        d['type'] = 'gate_review'
        d['message'] = f"{d['count']} pending gate approval(s)"
        notifications.append(d)

    for row in question_rows:
        d = row_to_dict(row)
        d['type'] = 'question'
        d['message'] = f"{d['count']} unanswered question(s)"
        notifications.append(d)

    notifications.sort(key=lambda x: x['created_at'] or '', reverse=True)
    return jsonify(notifications)


@notifications_bp.route('/api/notifications/dismiss', methods=['PUT'])
def api_dismiss_notification():
    """Dismiss a single notification — hide it from the panel."""
    data = request.get_json() or {}
    ticket_id = data.get('ticket_id')
    notif_type = data.get('type')
    if ticket_id is None or notif_type is None:
        return jsonify({"error": "ticket_id and type are required"}), 400
    if notif_type not in ('gate_review', 'question'):
        return jsonify({"error": "type must be 'gate_review' or 'question'"}), 400
    # Verify ticket exists
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    dismiss_notification(ticket_id, notif_type)
    return jsonify({"success": True})


@notifications_bp.route('/api/notifications/dismiss-all', methods=['PUT'])
def api_dismiss_all_notifications():
    """Dismiss all current notifications."""
    dismiss_all_notifications()
    return jsonify({"success": True})