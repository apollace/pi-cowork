"""API: Recurring Tasks — CRUD, toggle, manual trigger, preview."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.models import (
    add_comment, get_board,
    get_recurring_tasks, get_recurring_task, create_recurring_task,
    update_recurring_task, delete_recurring_task, toggle_recurring_task,
    get_recurring_parents, compute_next_trigger, cron_human_readable,
    _parse_dt,
)
from pi_cowork.events import bus, TICKET_CREATED

recurring_bp = Blueprint('recurring', __name__)


@recurring_bp.route('/api/recurring', methods=['GET'])
def api_list_recurring():
    board_id = request.args.get('board_id', type=int)
    if board_id is None:
        return jsonify({"error": "board_id is required"}), 400
    tasks = get_recurring_tasks(board_id)
    for t in tasks:
        t['human_readable'] = cron_human_readable(t.get('cron_expression', ''))
    return jsonify(tasks)


@recurring_bp.route('/api/recurring', methods=['POST'])
def api_create_recurring():
    data = request.get_json() or {}
    board_id = data.get('board_id')
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '')
    status_id = data.get('status_id')
    cron_expression = (data.get('cron_expression') or '').strip()
    start_at = data.get('start_at')
    end_at = data.get('end_at')

    if not board_id:
        return jsonify({"error": "board_id is required"}), 400
    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not status_id:
        return jsonify({"error": "status_id is required"}), 400
    if not cron_expression:
        return jsonify({"error": "cron_expression is required"}), 400

    task, error = create_recurring_task(
        board_id=board_id, title=title, body=body, status_id=status_id,
        cron_expression=cron_expression, start_at=start_at, end_at=end_at
    )
    if error:
        return jsonify({"error": error}), 400

    task['human_readable'] = cron_human_readable(task.get('cron_expression', ''))
    return jsonify(task), 201


@recurring_bp.route('/api/recurring/<int:task_id>', methods=['GET'])
def api_get_recurring(task_id):
    task = get_recurring_task(task_id)
    if not task:
        return jsonify({"error": "Not found"}), 404
    task['human_readable'] = cron_human_readable(task.get('cron_expression', ''))
    return jsonify(task)


@recurring_bp.route('/api/recurring/<int:task_id>', methods=['PUT'])
def api_update_recurring(task_id):
    data = request.get_json() or {}
    title = data.get('title')
    body = data.get('body')
    status_id = data.get('status_id')
    cron_expression = data.get('cron_expression')
    start_at = data.get('start_at')
    end_at = data.get('end_at')

    # If title is explicitly provided as empty, reject
    if title is not None and not title.strip():
        return jsonify({"error": "Title cannot be empty"}), 400

    task, error = update_recurring_task(
        task_id=task_id, title=title, body=body, status_id=status_id,
        cron_expression=cron_expression, start_at=start_at, end_at=end_at
    )
    if error:
        return jsonify({"error": error}), 400

    task['human_readable'] = cron_human_readable(task.get('cron_expression', ''))
    return jsonify(task)


@recurring_bp.route('/api/recurring/<int:task_id>', methods=['DELETE'])
def api_delete_recurring(task_id):
    result, error = delete_recurring_task(task_id)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(result)


@recurring_bp.route('/api/recurring/<int:task_id>/toggle', methods=['POST'])
def api_toggle_recurring(task_id):
    task, error = toggle_recurring_task(task_id)
    if error:
        return jsonify({"error": error}), 404
    task['human_readable'] = cron_human_readable(task.get('cron_expression', ''))
    return jsonify(task)


@recurring_bp.route('/api/recurring/<int:task_id>/trigger', methods=['POST'])
def api_trigger_recurring(task_id):
    """Manually trigger a recurring task now."""
    task = get_recurring_task(task_id)
    if not task:
        return jsonify({"error": "Not found"}), 404

    now = datetime.now(timezone.utc)
    human_dt = now.strftime('%Y-%m-%d %H:%M UTC')
    ticket_title = f"[Recurring {human_dt}] {task['title']}"
    ticket_body = task.get('body') or ''

    cur = run_db(
        "INSERT INTO tickets (title, body, status_id, board_id, priority) VALUES (?, ?, ?, ?, ?)",
        (ticket_title, ticket_body, task['status_id'], task['board_id'], 'Medium')
    )
    ticket_id = cur.lastrowid

    run_db(
        "INSERT INTO recurring_instances (recurring_task_id, ticket_id, triggered_at) VALUES (?, ?, ?)",
        (task_id, ticket_id, now.isoformat())
    )

    next_trigger = compute_next_trigger(task['cron_expression'], after=now)
    run_db(
        "UPDATE recurring_tasks SET last_triggered_at = ?, next_trigger_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (now.isoformat(), next_trigger, task_id)
    )

    add_comment(ticket_id,
        f"🔄 Ticket manually triggered from recurring task **{task['title']}** "
        f"(schedule: `{task['cron_expression']}`)")

    bus.publish('recurring.triggered', recurring_task_id=task_id, ticket_id=ticket_id, board_id=task['board_id'])
    bus.publish(TICKET_CREATED, ticket_id=ticket_id, title=ticket_title, board_id=task['board_id'], status_id=task['status_id'])

    # Bug C fix: If the initial status has an agent, spawn it (mirrors api_create_ticket)
    from pi_cowork.agents import spawn_agent_for_ticket
    spawn_agent_for_ticket(ticket_id, task['status_id'])

    return jsonify({"success": True, "ticket_id": ticket_id})


@recurring_bp.route('/api/recurring/preview', methods=['GET'])
def api_preview_cron():
    cron_expr = request.args.get('cron', '').strip()
    if not cron_expr:
        return jsonify({"error": "cron parameter is required"}), 400

    from croniter import croniter
    try:
        now = datetime.now(timezone.utc)
        it = croniter(cron_expr, now)
        times = []
        for _ in range(5):
            times.append(it.get_next(datetime).isoformat())
    except (ValueError, KeyError):
        return jsonify({"error": "Invalid cron expression"}), 400

    return jsonify({"times": times, "human_readable": cron_human_readable(cron_expr)})


@recurring_bp.route('/api/tickets/<int:ticket_id>/recurring', methods=['GET'])
def api_ticket_recurring_parents(ticket_id):
    """Get parent recurring tasks for a ticket."""
    parents = get_recurring_parents(ticket_id)
    for p in parents:
        p['human_readable'] = cron_human_readable(p.get('cron_expression', ''))
    return jsonify(parents)
