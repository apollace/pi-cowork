"""API: Tickets — create, read, update (including status changes, quality gates)."""

import json
import os
import shutil
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.models import (
    add_comment, count_unanswered_questions, get_board, get_board_with_workflow,
    get_comments, get_quality_gates, get_status, get_ticket_labels,
    get_transitions_from, has_pending_gate_reviews, run_cli_gate,
    set_ticket_labels, get_recurring_parents,
    get_comment_counts, get_ticket_labels_batch, get_recurring_parents_batch,
)
from pi_cowork.agents import try_spawn_or_queue, cleanup_runs, spawn_agent
from pi_cowork.models import get_agents, get_agent
from pi_cowork.events import bus, TICKET_CREATED, TICKET_STATUS_CHANGED, TICKET_UPDATED, GATE_PENDING
from pi_cowork.system_logs import add_log

tickets_bp = Blueprint('tickets', __name__)


@tickets_bp.route('/api/tickets', methods=['GET'])
def api_tickets():
    board_id = request.args.get('board_id', type=int)
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    if board_id is None:
        return jsonify({"error": "board_id is required"}), 400

    # Look up git_enabled for this board's workflow
    board_row = query_db("SELECT workflow_id FROM boards WHERE id = ?", (board_id,), one=True)
    workflow_git_enabled = False
    if board_row:
        wf_row = query_db("SELECT git_enabled FROM workflows WHERE id = ?", (board_row['workflow_id'],), one=True)
        if wf_row:
            workflow_git_enabled = bool(wf_row['git_enabled'])

    rows = query_db("""
        SELECT t.*, s.name AS status_name, a.name AS agent_name, b.name AS board_name, b.workflow_id, w.git_enabled
        FROM tickets t
        JOIN statuses s ON t.status_id = s.id
        LEFT JOIN agents a ON s.agent_id = a.id
        JOIN boards b ON t.board_id = b.id
        JOIN workflows w ON b.workflow_id = w.id
        WHERE t.board_id = ?
        ORDER BY
          CASE t.priority
            WHEN 'Critical' THEN 4
            WHEN 'High' THEN 3
            WHEN 'Medium' THEN 2
            WHEN 'Low' THEN 1
            ELSE 2
          END DESC,
          t.created_at DESC
        LIMIT ? OFFSET ?
    """, (board_id, limit, offset))

    if not rows:
        return jsonify([])

    tickets = []
    ticket_ids = []
    for r in rows:
        d = row_to_dict(r)
        # Hide branch when git is disabled for this workflow
        if not workflow_git_enabled:
            d.pop('branch', None)
        d.pop('git_enabled', None)
        tickets.append(d)
        ticket_ids.append(d['id'])

    # --- Batch queries instead of N+1 ---
    comment_counts = get_comment_counts(ticket_ids)
    labels_map = get_ticket_labels_batch(ticket_ids)
    parents_map = get_recurring_parents_batch(ticket_ids)

    # Scoped queue lookups: only unstarted entries for this board's tickets
    placeholders = ','.join('?' * len(ticket_ids))
    queue_rows = query_db(
        f"SELECT ticket_id, reason FROM agent_queue WHERE started_at IS NULL AND ticket_id IN ({placeholders})",
        tuple(ticket_ids)
    )
    queue_map = {row['ticket_id']: row['reason'] for row in queue_rows}

    # Scoped gate_pending lookups: only pending reviews for this board's tickets
    gate_pending_rows = query_db(
        f"SELECT DISTINCT ticket_id FROM gate_reviews WHERE status = 'pending' AND ticket_id IN ({placeholders})",
        tuple(ticket_ids)
    )
    gate_pending_set = {row['ticket_id'] for row in gate_pending_rows}

    # Scoped question counts for this board's tickets
    qrows = query_db(
        f"SELECT ticket_id, COUNT(*) AS c FROM questions WHERE ticket_id IN ({placeholders}) GROUP BY ticket_id",
        tuple(ticket_ids)
    )
    question_counts = {r['ticket_id']: r['c'] for r in qrows}

    for t in tickets:
        # Board view: comment count only (lightweight payload)
        t['comment_count'] = comment_counts.get(t['id'], 0)
        t['labels'] = labels_map.get(t['id'], [])
        t['queued'] = t['id'] in queue_map
        t['queue_reason'] = queue_map.get(t['id'])
        t['gate_pending'] = t['id'] in gate_pending_set
        t['question_count'] = question_counts.get(t['id'], 0)
        t['recurring_parents'] = parents_map.get(t['id'], [])

    return jsonify(tickets)


@tickets_bp.route('/api/tickets/<int:ticket_id>', methods=['GET'])
def api_ticket(ticket_id):
    row = query_db("""
        SELECT t.*, s.name AS status_name, s.is_terminal AS is_terminal, s.agent_id AS status_agent_id, a.name AS agent_name, b.name AS board_name, b.workflow_id, w.git_enabled
        FROM tickets t
        JOIN statuses s ON t.status_id = s.id
        LEFT JOIN agents a ON s.agent_id = a.id
        JOIN boards b ON t.board_id = b.id
        JOIN workflows w ON b.workflow_id = w.id
        WHERE t.id = ?
    """, (ticket_id,), one=True)
    if not row:
        return jsonify({"error": "Ticket not found"}), 404
    d = row_to_dict(row)
    # Hide branch when git is disabled for this workflow
    if not d.get('git_enabled'):
        d.pop('branch', None)
    d.pop('git_enabled', None)
    d['comments'] = get_comments(d['id'])
    d['labels'] = get_ticket_labels(ticket_id)

    q = query_db(
        "SELECT reason FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL",
        (ticket_id,), one=True
    )
    d['queued'] = q is not None
    d['queue_reason'] = q['reason'] if q else None

    d['gate_pending'] = has_pending_gate_reviews(ticket_id)
    d['question_count'] = count_unanswered_questions(ticket_id)
    d['recurring_parents'] = get_recurring_parents(ticket_id)

    # Agent run stats — combined into a single query to reduce DB round-trips
    counts_row = query_db(
        """SELECT
               COUNT(*) AS total_count,
               COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running_count
           FROM agent_runs WHERE ticket_id = ?""",
        (ticket_id,), one=True
    )
    d['running_agents'] = counts_row['running_count'] if counts_row else 0
    d['agent_run_count'] = counts_row['total_count'] if counts_row else 0

    # Last agent run info (for re-run button display)
    if d['agent_run_count'] > 0:
        last_run = query_db(
            """SELECT ar.status, ar.exit_code, ar.started_at, ar.completed_at, a.name AS agent_name
               FROM agent_runs ar
               JOIN agents a ON ar.agent_id = a.id
               WHERE ar.ticket_id = ?
               ORDER BY ar.started_at DESC, ar.id DESC
               LIMIT 1""",
            (ticket_id,), one=True
        )
        d['last_agent_run'] = row_to_dict(last_run) if last_run else None
    else:
        d['last_agent_run'] = None

    return jsonify(d)



@tickets_bp.route('/api/tickets', methods=['POST'])
def api_create_ticket():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    board_id = data.get('board_id')
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if board_id is None:
        return jsonify({"error": "board_id is required"}), 400

    board = get_board_with_workflow(board_id)
    if not board:
        return jsonify({"error": "Board not found"}), 404

    status_id = data.get('status_id')
    if status_id is not None:
        status_id = int(status_id)
    else:
        default = query_db(
            "SELECT id FROM statuses WHERE is_default = 1 AND workflow_id = ? LIMIT 1",
            (board['workflow_id'],), one=True
        )
        status_id = default['id'] if default else None
        if status_id is None:
            return jsonify({"error": "No default status found for this board's workflow"}), 400

    priority = (data.get('priority') or 'Medium').strip()
    valid_priorities = ['Low', 'Medium', 'High', 'Critical']
    if priority not in valid_priorities:
        return jsonify({"error": f"priority must be one of {valid_priorities}"}), 400

    cur = run_db("INSERT INTO tickets (title, body, status_id, board_id, priority) VALUES (?, ?, ?, ?, ?)", (title, body, status_id, board_id, priority))
    ticket_id = cur.lastrowid
    bus.publish(TICKET_CREATED, ticket_id=ticket_id, title=title, board_id=board_id, status_id=status_id)
    add_log('INFO', 'db_change', f'INSERT tickets/{ticket_id}', details={'operation': 'INSERT', 'table': 'tickets', 'record_id': ticket_id}, ticket_id=ticket_id)

    label_ids = data.get('labels')
    if isinstance(label_ids, list):
        set_ticket_labels(ticket_id, board['workflow_id'], label_ids)

    # If the initial status has an agent, spawn it (mirrors api_update_ticket logic)
    status = get_status(status_id)
    if status and status.get('agent_id'):
        agent = get_agent(status['agent_id'])
        if agent:
            full_ticket = query_db("""
                SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
                FROM tickets t
                JOIN boards b ON t.board_id = b.id
                JOIN workflows w ON b.workflow_id = w.id
                WHERE t.id = ?
            """, (ticket_id,), one=True)
            if full_ticket:
                try_spawn_or_queue(row_to_dict(full_ticket), status, agent)

    return jsonify({"id": ticket_id, "status_id": status_id, "board_id": board_id, "labels": get_ticket_labels(ticket_id)}), 201


@tickets_bp.route('/api/tickets/<int:ticket_id>', methods=['PUT'])
def api_update_ticket(ticket_id):
    ticket = query_db("""
        SELECT t.*, b.workflow_id, b.name AS board_name, w.name AS workflow_name, b.working_directory, w.git_enabled
        FROM tickets t
        JOIN boards b ON t.board_id = b.id
        JOIN workflows w ON b.workflow_id = w.id
        WHERE t.id = ?
    """, (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    data = request.get_json() or {}
    title = data.get('title')
    body = data.get('body')
    status_id = data.get('status_id')

    # Guard: block branch updates when git is not enabled for this workflow
    if 'branch' in data and not ticket['git_enabled']:
        return jsonify({"error": "Cannot set branch: git is not enabled for this workflow"}), 400

    # Handle label replacement if provided
    labels_provided = False
    if 'labels' in data:
        label_ids = data['labels']
        if not isinstance(label_ids, list):
            return jsonify({"error": "labels must be an array"}), 400
        set_ticket_labels(ticket_id, ticket['workflow_id'], label_ids)
        labels_provided = True

    updates = []
    args = []
    if title is not None:
        updates.append("title = ?")
        args.append(title.strip())
    if body is not None:
        updates.append("body = ?")
        args.append(body.strip())

    priority = data.get('priority')
    if priority is not None:
        priority = str(priority).strip()
        valid_priorities = ['Low', 'Medium', 'High', 'Critical']
        if priority not in valid_priorities:
            return jsonify({"error": f"priority must be one of {valid_priorities}"}), 400
        updates.append("priority = ?")
        args.append(priority)

    # Branch can only be set when git is enabled (guard is above)
    if 'branch' in data and ticket['git_enabled']:
        updates.append("branch = ?")
        args.append((data['branch'] or '').strip() or None)

    new_status_id = status_id if status_id is not None else ticket['status_id']
    old_status_id = ticket['status_id']

    response_data = {"success": True}

    # Quality gate logic
    if new_status_id != old_status_id:
        dest_status = get_status(new_status_id)
        gates = get_quality_gates(old_status_id, new_status_id) if dest_status else []

        if gates:
            run_db(
                "DELETE FROM gate_reviews WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?",
                (ticket_id, old_status_id, new_status_id)
            )
            now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            for gate in gates:
                run_db(
                    "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                    (ticket_id, gate['id'], old_status_id, new_status_id, now)
                )


            any_failed = False
            all_resolved = True
            board_dir = ticket['working_directory'] if ticket['working_directory'] else 'workspace'

            for gate in gates:
                if gate['gate_type'] == 'cli':
                    config_json = json.loads(gate['config'] or '{}')
                    command = config_json.get('command', '')
                    passed, output = run_cli_gate(command, board_dir)
                    review = query_db(
                        "SELECT id FROM gate_reviews WHERE ticket_id = ? AND gate_id = ? AND status = 'pending' LIMIT 1",
                        (ticket_id, gate['id']), one=True
                    )
                    if review:
                        review_status = 'passed' if passed else 'failed'
                        completed_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                        run_db(
                            "UPDATE gate_reviews SET status = ?, output = ?, completed_at = ? WHERE id = ?",
                            (review_status, output, completed_at, review['id'])
                        )
                        if passed:
                            add_comment(ticket_id, f"✅ Gate '{gate['name']}' (CLI) passed.\n{output}")
                        else:
                            add_comment(ticket_id, f"❌ Gate '{gate['name']}' (CLI) failed.\n{output}")
                            any_failed = True
                elif gate['gate_type'] == 'manual':
                    all_resolved = False

            if any_failed:
                run_db(
                    "DELETE FROM gate_reviews WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ?",
                    (ticket_id, old_status_id, new_status_id)
                )
                add_comment(ticket_id, f"🚫 Transition to '{dest_status['name']}' rejected — quality gate(s) failed.")
                response_data['gate_pending'] = False
                if labels_provided:
                    response_data['labels'] = get_ticket_labels(ticket_id)
                return jsonify(response_data)

            if not all_resolved:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                args.append(ticket_id)
                if updates:
                    run_db(f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?", tuple(args))
                    add_log('INFO', 'db_change', f'UPDATE tickets/{ticket_id}', details={'operation': 'UPDATE', 'table': 'tickets', 'record_id': ticket_id}, ticket_id=ticket_id)
                add_comment(ticket_id, f"⏳ Quality gate pending — transition to '{dest_status['name']}' awaits manual approval.")
                bus.publish(GATE_PENDING, ticket_id=ticket_id, from_status_id=old_status_id, to_status_id=new_status_id)
                response_data['gate_pending'] = True
                if labels_provided:
                    response_data['labels'] = get_ticket_labels(ticket_id)
                return jsonify(response_data)

            # All gates passed (all were CLI and passed)
            run_db("DELETE FROM gate_reviews WHERE ticket_id = ?", (ticket_id,))

    updates.append("status_id = ?")
    args.append(new_status_id)
    updates.append("updated_at = CURRENT_TIMESTAMP")
    args.append(ticket_id)

    if new_status_id != old_status_id:
        run_db(
            "DELETE FROM gate_reviews WHERE ticket_id = ? AND status = 'pending' AND (from_status_id != ? OR to_status_id != ?)",
            (ticket_id, old_status_id, new_status_id)
        )
        run_db(
            "DELETE FROM gate_reviews WHERE ticket_id = ? AND from_status_id = ? AND to_status_id = ? AND status = 'pending'",
            (ticket_id, old_status_id, new_status_id)
        )

    run_db(f"UPDATE tickets SET {', '.join(updates)} WHERE id = ?", tuple(args))
    add_log('INFO', 'db_change', f'UPDATE tickets/{ticket_id}', details={'operation': 'UPDATE', 'table': 'tickets', 'record_id': ticket_id}, ticket_id=ticket_id)

    if new_status_id != old_status_id:
        bus.publish(TICKET_STATUS_CHANGED, ticket_id=ticket_id, old_status_id=old_status_id, new_status_id=new_status_id)
        status = get_status(new_status_id)
        if status:
            if status.get('is_terminal'):
                from pi_cowork.models import get_agents
                all_agents = get_agents(ticket['workflow_id'])
                board = get_board(ticket['board_id']) if ticket['board_id'] else None
                board_dir = board['working_directory'] if board else 'workspace'
                for ag in all_agents:
                    session_dir = os.path.join(board_dir, '.pi-sessions', str(ag['id']), f'ticket-{ticket_id}')
                    if os.path.isdir(session_dir):
                        shutil.rmtree(session_dir)
                run_db("UPDATE tickets SET agent_last_spawned_at = NULL WHERE id = ?", (ticket_id,))
                run_db("DELETE FROM gate_reviews WHERE ticket_id = ? AND status = 'pending'", (ticket_id,))
                run_db("DELETE FROM questions WHERE ticket_id = ?", (ticket_id,))
                add_comment(ticket_id, "🔔 All pending notifications (gate reviews and questions) cleared — ticket is now in a terminal state.")

            if status.get('agent_id'):
                agent = get_agent(status['agent_id'])
                if agent:
                    updated_ticket = query_db("""
                        SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id
                        FROM tickets t
                        JOIN boards b ON t.board_id = b.id
                        JOIN workflows w ON b.workflow_id = w.id
                        WHERE t.id = ?
                    """, (ticket_id,), one=True)
                    try_spawn_or_queue(row_to_dict(updated_ticket), status, agent, old_status_id=old_status_id)
    else:
        bus.publish(TICKET_UPDATED, ticket_id=ticket_id)

    if labels_provided:
        response_data['labels'] = get_ticket_labels(ticket_id)
    return jsonify(response_data)


@tickets_bp.route('/api/tickets/<int:ticket_id>/spawn', methods=['POST'])
def api_spawn_agent(ticket_id):
    """Manually trigger an agent run for a ticket (re-run button)."""
    ticket = query_db("""
        SELECT t.*, b.workflow_id, b.name AS board_name, w.name AS workflow_name, b.working_directory
        FROM tickets t
        JOIN boards b ON t.board_id = b.id
        JOIN workflows w ON b.workflow_id = w.id
        WHERE t.id = ?
    """, (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    status = get_status(ticket['status_id'])
    if not status:
        return jsonify({"error": "Current status not found"}), 409

    # Guard: terminal status
    if status.get('is_terminal'):
        return jsonify({"error": "Cannot spawn agent: ticket is in a terminal status"}), 409

    # Guard: no agent assigned to current status
    agent_id = status.get('agent_id')
    if not agent_id:
        return jsonify({"error": "Cannot spawn agent: current status has no agent assigned"}), 409

    agent = get_agent(agent_id)
    if not agent:
        return jsonify({"error": "Cannot spawn agent: agent not found"}), 409

    # Guard: agent already running on this ticket
    running_row = query_db(
        "SELECT COUNT(*) AS c FROM agent_runs WHERE ticket_id = ? AND status = 'running'",
        (ticket_id,), one=True
    )
    if running_row and running_row['c'] > 0:
        return jsonify({"error": "Cannot spawn agent: an agent is already running on this ticket"}), 409

    try_spawn_or_queue(row_to_dict(ticket), status, agent)

    # Check whether the agent was actually spawned or blocked (e.g. by gates/questions)
    running_after = query_db(
        "SELECT COUNT(*) AS c FROM agent_runs WHERE ticket_id = ? AND status = 'running'",
        (ticket_id,), one=True
    )
    queued_after = query_db(
        "SELECT COUNT(*) AS c FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL",
        (ticket_id,), one=True
    )

    return jsonify({
        "success": True,
        "agent": {"id": agent['id'], "name": agent['name']},
        "spawned": (running_after['c'] if running_after else 0) > 0,
        "queued": (queued_after['c'] if queued_after else 0) > 0,
    })