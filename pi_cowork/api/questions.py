"""API: Questions — ask, answer, batch answer."""

import json

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db
from pi_cowork.models import add_comment, count_unanswered_questions, get_questions
from pi_cowork.models import get_status, get_agent, get_board
from pi_cowork.agents import try_spawn_or_queue
from pi_cowork.events import bus, QUESTION_ASKED, QUESTION_ANSWERED
from pi_cowork.system_logs import add_log


def _bump_ticket_updated_at(ticket_id):
    """Touch the ticket's updated_at timestamp for change detection."""
    run_db("UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ticket_id,))

questions_bp = Blueprint('questions', __name__)


@questions_bp.route('/api/tickets/<int:ticket_id>/questions', methods=['GET'])
def api_list_questions(ticket_id):
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    return jsonify(get_questions(ticket_id))


@questions_bp.route('/api/tickets/<int:ticket_id>/questions', methods=['POST'])
def api_create_questions(ticket_id):
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    data = request.get_json() or {}
    questions = data.get('questions')
    if not isinstance(questions, list) or not questions:
        return jsonify({"error": "questions array is required"}), 400

    ids = []
    for q in questions:
        body = (q.get('body') or '').strip()
        if not body:
            return jsonify({"error": "Each question must have a body"}), 400
        options = q.get('options')
        options_str = json.dumps(options) if isinstance(options, list) else None
        cur = run_db(
            "INSERT INTO questions (ticket_id, body, options) VALUES (?, ?, ?)",
            (ticket_id, body, options_str)
        )
        ids.append(cur.lastrowid)
    bus.publish(QUESTION_ASKED, ticket_id=ticket_id, count=len(ids))
    _bump_ticket_updated_at(ticket_id)
    for qid in ids:
        add_log('INFO', 'db_change', f'INSERT questions/{qid}', details={'operation': 'INSERT', 'table': 'questions', 'record_id': qid}, ticket_id=ticket_id)
    return jsonify({"ids": ids}), 201


@questions_bp.route('/api/questions/<int:question_id>/answer', methods=['PUT'])
def api_answer_question(question_id):
    from pi_cowork.db import row_to_dict
    question = query_db("SELECT * FROM questions WHERE id = ?", (question_id,), one=True)
    if not question:
        return jsonify({"error": "Question not found"}), 404
    data = request.get_json() or {}
    answer = (data.get('answer') or '').strip()
    if not answer:
        return jsonify({"error": "answer is required"}), 400

    ticket_id = question['ticket_id']
    comment_body = f"**Q:** {question['body']}\n**A:** {answer}"
    add_comment(ticket_id, comment_body)
    run_db("DELETE FROM questions WHERE id = ?", (question_id,))
    add_log('INFO', 'db_change', f'DELETE questions/{question_id}', details={'operation': 'DELETE', 'table': 'questions', 'record_id': question_id}, ticket_id=ticket_id)
    bus.publish(QUESTION_ANSWERED, ticket_id=ticket_id, question_id=question_id)
    _bump_ticket_updated_at(ticket_id)

    # If no more questions remain, attempt to spawn an agent for the current status
    remaining = count_unanswered_questions(ticket_id)
    if remaining == 0:
        ticket = query_db("""
            SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
            FROM tickets t
            JOIN boards b ON t.board_id = b.id
            JOIN workflows w ON b.workflow_id = w.id
            WHERE t.id = ?
        """, (ticket_id,), one=True)
        if ticket:
            status = get_status(ticket['status_id'])
            if status and status.get('agent_id'):
                agent = get_agent(status['agent_id'])
                if agent:
                    try_spawn_or_queue(row_to_dict(ticket), status, agent, old_status_id=None)

    return jsonify({"success": True})


@questions_bp.route('/api/tickets/<int:ticket_id>/answers', methods=['POST'])
def api_batch_answer(ticket_id):
    from pi_cowork.db import row_to_dict
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404
    data = request.get_json() or {}
    answers = data.get('answers')
    if not isinstance(answers, list) or not answers:
        return jsonify({"error": "answers array is required"}), 400

    qa_pairs = []
    answered_ids = []
    for item in answers:
        qid = item.get('question_id')
        answer = (item.get('answer') or '').strip()
        if not qid or not answer:
            return jsonify({"error": "Each answer must have question_id and answer"}), 400
        question = query_db(
            "SELECT * FROM questions WHERE id = ? AND ticket_id = ?",
            (qid, ticket_id), one=True,
        )
        if not question:
            return jsonify({"error": f"Question {qid} not found for this ticket"}), 404
        qa_pairs.append((question['body'], answer))
        answered_ids.append(qid)

    if not qa_pairs:
        return jsonify({"error": "No valid answers provided"}), 400

    comment_lines = []
    for q_body, answer in qa_pairs:
        comment_lines.append(f"**Q:** {q_body}\n**A:** {answer}")
    comment_body = "\n\n".join(comment_lines)
    add_comment(ticket_id, comment_body)

    for qid in answered_ids:
        run_db("DELETE FROM questions WHERE id = ?", (qid,))
        add_log('INFO', 'db_change', f'DELETE questions/{qid}', details={'operation': 'DELETE', 'table': 'questions', 'record_id': qid}, ticket_id=ticket_id)
        bus.publish(QUESTION_ANSWERED, ticket_id=ticket_id, question_id=qid)

    _bump_ticket_updated_at(ticket_id)

    remaining = count_unanswered_questions(ticket_id)
    if remaining == 0:
        ticket_row = query_db("""
            SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
            FROM tickets t
            JOIN boards b ON t.board_id = b.id
            JOIN workflows w ON b.workflow_id = w.id
            WHERE t.id = ?
        """, (ticket_id,), one=True)
        if ticket_row:
            status = get_status(ticket_row['status_id'])
            if status and status.get('agent_id'):
                agent = get_agent(status['agent_id'])
                if agent:
                    try_spawn_or_queue(row_to_dict(ticket_row), status, agent, old_status_id=None)

    return jsonify({"success": True, "answered": len(answered_ids)}), 200