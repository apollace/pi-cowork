"""Data-access layer: get/add/set functions for all domain objects.

Every function here performs SQL via ``pi_cowork.db`` and publishes events
through ``pi_cowork.events.bus`` where appropriate.
"""

import json
import logging
import subprocess

from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.events import bus, COMMENT_ADDED, QUESTION_ASKED, QUESTION_ANSWERED, TICKET_CREATED, GATE_FAILED

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def get_comments(ticket_id):
    rows = query_db(
        "SELECT id, body, created_at FROM comments WHERE ticket_id = ? ORDER BY created_at, id",
        (ticket_id,)
    )
    return [row_to_dict(r) for r in rows]


def add_comment(ticket_id, body):
    cur = run_db("INSERT INTO comments (ticket_id, body) VALUES (?, ?)", (ticket_id, body))
    bus.publish(COMMENT_ADDED, ticket_id=ticket_id, body=body)
    return cur.lastrowid


def get_comment_counts(ticket_ids):
    """Get comment counts for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> count.
    """
    if not ticket_ids:
        return {}
    placeholders = ','.join('?' * len(ticket_ids))
    rows = query_db(
        f"SELECT ticket_id, COUNT(*) AS c FROM comments WHERE ticket_id IN ({placeholders}) GROUP BY ticket_id",
        tuple(ticket_ids)
    )
    return {r['ticket_id']: r['c'] for r in rows}


def get_ticket_labels_batch(ticket_ids):
    """Get labels for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> list of label dicts.
    """
    if not ticket_ids:
        return {}
    placeholders = ','.join('?' * len(ticket_ids))
    rows = query_db(
        f"""SELECT tl.ticket_id, l.id, l.name, l.color
            FROM ticket_labels tl
            JOIN labels l ON tl.label_id = l.id
            WHERE tl.ticket_id IN ({placeholders})
            ORDER BY l.name""",
        tuple(ticket_ids)
    )
    result = {}
    for r in rows:
        result.setdefault(r['ticket_id'], []).append({
            'id': r['id'], 'name': r['name'], 'color': r['color']
        })
    return result


def get_recurring_parents_batch(ticket_ids):
    """Get recurring parent tasks for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> list of recurring task dicts.
    """
    if not ticket_ids:
        return {}
    placeholders = ','.join('?' * len(ticket_ids))
    rows = query_db(
        f"""SELECT ri.ticket_id, rt.*, s.name AS status_name
            FROM recurring_instances ri
            JOIN recurring_tasks rt ON rt.id = ri.recurring_task_id
            JOIN statuses s ON rt.status_id = s.id
            WHERE ri.ticket_id IN ({placeholders})""",
        tuple(ticket_ids)
    )
    result = {}
    for r in rows:
        d = row_to_dict(r)
        tid = d.pop('ticket_id')
        result.setdefault(tid, []).append(d)
    return result


# ---------------------------------------------------------------------------
# Ticket Status Overrides
# ---------------------------------------------------------------------------

def get_ticket_status_overrides(ticket_id):
    """Get all status overrides for a ticket."""
    rows = query_db(
        """SELECT tso.*, s.name AS status_name
           FROM ticket_status_overrides tso
           JOIN statuses s ON tso.status_id = s.id
           WHERE tso.ticket_id = ?
           ORDER BY s.sort_order""",
        (ticket_id,)
    )
    return [row_to_dict(r) for r in rows]


def get_ticket_status_override(ticket_id, status_id):
    """Get a single ticket-status override, or None."""
    row = query_db(
        "SELECT * FROM ticket_status_overrides WHERE ticket_id = ? AND status_id = ?",
        (ticket_id, status_id),
        one=True
    )
    return row_to_dict(row) if row else None


def set_ticket_status_override(ticket_id, status_id, model=None, thinking=None):
    """Upsert a ticket-status override. Returns the override dict."""
    run_db(
        """INSERT INTO ticket_status_overrides (ticket_id, status_id, model, thinking)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(ticket_id, status_id) DO UPDATE SET
             model = excluded.model,
             thinking = excluded.thinking""",
        (ticket_id, status_id, model, thinking)
    )
    return get_ticket_status_override(ticket_id, status_id)


def delete_ticket_status_override(ticket_id, status_id):
    """Delete a ticket-status override."""
    run_db(
        "DELETE FROM ticket_status_overrides WHERE ticket_id = ? AND status_id = ?",
        (ticket_id, status_id)
    )


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def get_questions(ticket_id):
    rows = query_db(
        "SELECT id, ticket_id, body, options, created_at FROM questions WHERE ticket_id = ? ORDER BY created_at, id",
        (ticket_id,)
    )
    result = []
    for r in rows:
        d = row_to_dict(r)
        if d.get('options'):
            try:
                d['options'] = json.loads(d['options'])
            except (json.JSONDecodeError, TypeError):
                d['options'] = None
        else:
            d['options'] = None
        result.append(d)
    return result


def count_unanswered_questions(ticket_id):
    row = query_db(
        "SELECT COUNT(*) AS c FROM questions WHERE ticket_id = ?",
        (ticket_id,), one=True
    )
    return row['c'] if row else 0


def has_unanswered_questions(ticket_id):
    return count_unanswered_questions(ticket_id) > 0


def _add_question_wait_comment(ticket_id, count):
    last = query_db(
        "SELECT body FROM comments WHERE ticket_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (ticket_id,), one=True
    )
    msg = f"⏳ Waiting for {count} unanswered question(s) before agent can proceed."
    if last and msg in last['body']:
        return
    add_comment(ticket_id, msg)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

def get_workflow(workflow_id):
    row = query_db("SELECT * FROM workflows WHERE id = ?", (workflow_id,), one=True)
    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Boards
# ---------------------------------------------------------------------------

def get_board(board_id):
    row = query_db("SELECT * FROM boards WHERE id = ?", (board_id,), one=True)
    return row_to_dict(row) if row else None


def get_board_with_workflow(board_id):
    row = query_db("""
        SELECT b.*, w.name AS workflow_name, w.git_enabled AS workflow_git_enabled
        FROM boards b
        JOIN workflows w ON b.workflow_id = w.id
        WHERE b.id = ?
    """, (board_id,), one=True)
    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

def get_statuses(workflow_id):
    rows = query_db("""
        SELECT s.*, a.name AS agent_name
        FROM statuses s
        LEFT JOIN agents a ON s.agent_id = a.id
        WHERE s.workflow_id = ?
        ORDER BY s.sort_order
    """, (workflow_id,))
    return [row_to_dict(r) for r in rows]


def get_status(status_id):
    row = query_db("""
        SELECT s.*, a.name AS agent_name
        FROM statuses s
        LEFT JOIN agents a ON s.agent_id = a.id
        WHERE s.id = ?
    """, (status_id,), one=True)
    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def get_agents(workflow_id):
    rows = query_db("SELECT * FROM agents WHERE workflow_id = ? ORDER BY name", (workflow_id,))
    return [row_to_dict(r) for r in rows]


def get_agent(agent_id):
    row = query_db("SELECT * FROM agents WHERE id = ?", (agent_id,), one=True)
    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

def get_transitions_from(status_id):
    rows = query_db(
        """SELECT t.*, s.name AS to_status_name
           FROM transitions t JOIN statuses s ON t.to_status_id = s.id
           WHERE t.from_status_id = ?""",
        (status_id,)
    )
    return [row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

def get_quality_gates(from_status_id, to_status_id):
    rows = query_db(
        "SELECT * FROM quality_gates WHERE from_status_id = ? AND to_status_id = ? AND enabled = 1 ORDER BY sort_order",
        (from_status_id, to_status_id)
    )
    return [row_to_dict(r) for r in rows]


def get_all_quality_gates(workflow_id):
    rows = query_db(
        """SELECT qg.*, fs.name AS from_status_name, ts.name AS to_status_name
           FROM quality_gates qg
           JOIN statuses fs ON qg.from_status_id = fs.id
           JOIN statuses ts ON qg.to_status_id = ts.id
           WHERE qg.workflow_id = ?
           ORDER BY qg.sort_order""",
        (workflow_id,)
    )
    return [row_to_dict(r) for r in rows]


def get_pending_gate_reviews(ticket_id):
    rows = query_db(
        """SELECT gr.*, qg.gate_type, qg.name AS gate_name, qg.config AS gate_config,
                  fs.name AS from_status_name, ts.name AS to_status_name
           FROM gate_reviews gr
           JOIN quality_gates qg ON gr.gate_id = qg.id
           JOIN statuses fs ON gr.from_status_id = fs.id
           JOIN statuses ts ON gr.to_status_id = ts.id
           WHERE gr.ticket_id = ? AND gr.status = 'pending'
           ORDER BY gr.created_at, gr.id""",
        (ticket_id,)
    )
    return [row_to_dict(r) for r in rows]


def has_pending_gate_reviews(ticket_id):
    row = query_db(
        "SELECT 1 FROM gate_reviews WHERE ticket_id = ? AND status = 'pending' LIMIT 1",
        (ticket_id,), one=True
    )
    return row is not None


def run_cli_gate(command, working_directory):
    """Run a CLI gate command and return (passed, output)."""
    try:
        result = subprocess.run(
            command, shell=True, cwd=working_directory,
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout.strip() if result.stdout else ''
        if result.returncode != 0:
            err = result.stderr.strip() if result.stderr else ''
            output = f"Exit code: {result.returncode}\n{err}" if err else f"Exit code: {result.returncode}"
            return False, output
        return True, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out after 60 seconds"
    except Exception as e:
        return False, f"Failed to run command: {e}"


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def get_ticket_labels(ticket_id):
    rows = query_db("""
        SELECT l.id, l.name, l.color
        FROM labels l
        JOIN ticket_labels tl ON tl.label_id = l.id
        WHERE tl.ticket_id = ?
        ORDER BY l.name
    """, (ticket_id,))
    return [row_to_dict(r) for r in rows]


def get_labels(workflow_id):
    rows = query_db("SELECT * FROM labels WHERE workflow_id = ? ORDER BY name", (workflow_id,))
    return [row_to_dict(r) for r in rows]


def get_label(label_id):
    row = query_db("SELECT * FROM labels WHERE id = ?", (label_id,), one=True)
    return row_to_dict(row) if row else None


def set_ticket_labels(ticket_id, workflow_id, label_ids):
    """Replace a ticket's labels with the given list of label IDs (validated against workflow)."""
    if not isinstance(label_ids, list):
        return False
    run_db("DELETE FROM ticket_labels WHERE ticket_id = ?", (ticket_id,))
    if label_ids:
        placeholders = ','.join('?' * len(label_ids))
        valid = query_db(
            f"SELECT id FROM labels WHERE workflow_id = ? AND id IN ({placeholders})",
            (workflow_id, *label_ids)
        )
        valid_ids = {r['id'] for r in valid}
        for lid in valid_ids:
            try:
                run_db("INSERT INTO ticket_labels (ticket_id, label_id) VALUES (?, ?)", (ticket_id, lid))
            except Exception:
                pass
    return True


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key, default=None):
    row = query_db("SELECT value FROM settings WHERE key = ?", (key,), one=True)
    return row['value'] if row else default


def set_setting(key, value):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    run_db(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now)
    )


# ---------------------------------------------------------------------------
# Recurring Tasks
# ---------------------------------------------------------------------------


def compute_next_trigger(cron_expression, after=None):
    """Compute the next firing time for a cron expression. Returns ISO string or None."""
    from croniter import croniter
    from datetime import datetime, timezone
    if after is None:
        after = datetime.now(timezone.utc)
    elif isinstance(after, str):
        after = datetime.fromisoformat(after.replace('Z', '+00:00'))
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
    try:
        it = croniter(cron_expression, after)
        return it.get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None


def get_recurring_tasks(board_id):
    rows = query_db(
        """SELECT rt.*, s.name AS status_name
           FROM recurring_tasks rt
           JOIN statuses s ON rt.status_id = s.id
           WHERE rt.board_id = ?
           ORDER BY rt.created_at DESC""",
        (board_id,)
    )
    return [row_to_dict(r) for r in rows]


def get_recurring_task(task_id):
    row = query_db(
        """SELECT rt.*, s.name AS status_name, b.name AS board_name
           FROM recurring_tasks rt
           JOIN statuses s ON rt.status_id = s.id
           JOIN boards b ON rt.board_id = b.id
           WHERE rt.id = ?""",
        (task_id,), one=True
    )
    return row_to_dict(row) if row else None


def create_recurring_task(board_id, title, body, status_id, cron_expression,
                           start_at=None, end_at=None):
    """Create a recurring task. Returns (task_dict, error)."""
    from datetime import datetime, timezone
    from croniter import croniter

    # Validate cron expression
    try:
        croniter(cron_expression, datetime.now(timezone.utc))
    except (ValueError, KeyError):
        return None, "Invalid cron expression"

    # Validate board exists
    board = get_board(board_id)
    if not board:
        return None, "Board not found"

    # Validate status belongs to board's workflow
    status = get_status(status_id)
    if not status:
        return None, "Status not found"
    if status['workflow_id'] != board['workflow_id']:
        return None, "Status does not belong to the board's workflow"

    # Validate end_at not in the past
    now = datetime.now(timezone.utc)
    if end_at:
        try:
            end_dt = _parse_dt(end_at)
            if end_dt <= now:
                return None, "End date must be in the future"
        except (ValueError, TypeError):
            return None, "Invalid end_at format"

    # Compute next trigger
    after = _parse_dt(start_at) if start_at else now
    next_trigger = compute_next_trigger(cron_expression, after=after)

    cur = run_db(
        """INSERT INTO recurring_tasks (board_id, title, body, status_id, cron_expression,
           next_trigger_at, start_at, end_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (board_id, title.strip(), body, status_id, cron_expression.strip(),
         next_trigger, start_at, end_at)
    )
    return get_recurring_task(cur.lastrowid), None


def update_recurring_task(task_id, title=None, body=None, status_id=None,
                           cron_expression=None, start_at=None, end_at=None):
    """Update a recurring task. Returns (task_dict, error)."""
    from croniter import croniter
    from datetime import datetime, timezone

    task = get_recurring_task(task_id)
    if not task:
        return None, "Recurring task not found"

    updates = []
    args = []

    if title is not None:
        updates.append("title = ?")
        args.append(title.strip())

    if body is not None:
        updates.append("body = ?")
        args.append(body)

    if status_id is not None:
        status = get_status(status_id)
        if not status:
            return None, "Status not found"
        board = get_board(task['board_id'])
        if board and status['workflow_id'] != board['workflow_id']:
            return None, "Status does not belong to the board's workflow"
        updates.append("status_id = ?")
        args.append(status_id)

    if cron_expression is not None:
        try:
            croniter(cron_expression, datetime.now(timezone.utc))
        except (ValueError, KeyError):
            return None, "Invalid cron expression"
        updates.append("cron_expression = ?")
        args.append(cron_expression.strip())

    if start_at is not None:
        updates.append("start_at = ?")
        args.append(start_at)

    if end_at is not None:
        try:
            end_dt = _parse_dt(end_at)
            if end_dt <= datetime.now(timezone.utc):
                return None, "End date must be in the future"
        except (ValueError, TypeError):
            return None, "Invalid end_at format"
        updates.append("end_at = ?")
        args.append(end_at)

    # Recompute next_trigger_at if cron, start, or enabled state changed
    need_recompute = (cron_expression is not None or start_at is not None)
    if need_recompute and task.get('enabled'):
        new_cron = cron_expression if cron_expression is not None else task['cron_expression']
        after = _parse_dt(task.get('last_triggered_at') or start_at or task.get('start_at')) if not start_at else _parse_dt(start_at)
        if after is None:
            after = datetime.now(timezone.utc)
        next_trigger = compute_next_trigger(new_cron, after=after)
        updates.append("next_trigger_at = ?")
        args.append(next_trigger)

    if not updates:
        return task, None

    updates.append("updated_at = CURRENT_TIMESTAMP")
    args.append(task_id)
    run_db(f"UPDATE recurring_tasks SET {', '.join(updates)} WHERE id = ?", tuple(args))
    return get_recurring_task(task_id), None


def delete_recurring_task(task_id):
    """Delete a recurring task — soft-disables, or hard delete if no instances."""
    task = get_recurring_task(task_id)
    if not task:
        return None, "Recurring task not found"

    instance_count = query_db(
        "SELECT COUNT(*) AS c FROM recurring_instances WHERE recurring_task_id = ?",
        (task_id,), one=True
    )
    if instance_count and instance_count['c'] > 0:
        run_db("UPDATE recurring_tasks SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
        return {"soft_deleted": True}, None
    else:
        run_db("DELETE FROM recurring_tasks WHERE id = ?", (task_id,))
        return {"deleted": True}, None


def toggle_recurring_task(task_id):
    """Toggle enabled state. Returns (task_dict, error)."""
    from datetime import datetime, timezone

    task = get_recurring_task(task_id)
    if not task:
        return None, "Recurring task not found"

    new_enabled = not task.get('enabled')
    if new_enabled:
        # Recompute next_trigger_at from last_triggered_at or start_at
        after_src = task.get('last_triggered_at') or task.get('start_at')
        after = _parse_dt(after_src) if after_src else datetime.now(timezone.utc)
        next_trigger = compute_next_trigger(task['cron_expression'], after=after)
        run_db(
            "UPDATE recurring_tasks SET enabled = 1, next_trigger_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (next_trigger, task_id)
        )
    else:
        run_db(
            "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,)
        )
    return get_recurring_task(task_id), None


def get_recurring_parents(ticket_id):
    """Get parent recurring tasks of a ticket."""
    rows = query_db(
        """SELECT rt.*, s.name AS status_name
           FROM recurring_tasks rt
           JOIN recurring_instances ri ON rt.id = ri.recurring_task_id
           JOIN statuses s ON rt.status_id = s.id
           WHERE ri.ticket_id = ?""",
        (ticket_id,)
    )
    return [row_to_dict(r) for r in rows]


def process_recurring_tasks():
    """Create tickets for all due recurring tasks. Called periodically from drain loop."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    due_tasks = query_db(
        """SELECT * FROM recurring_tasks
           WHERE enabled = 1
             AND next_trigger_at IS NOT NULL
             AND next_trigger_at <= ?""",
        (now,)
    )
    for task in due_tasks:
        task = row_to_dict(task)
        board = get_board(task['board_id'])
        if not board:
            continue

        # Check if end_at has passed — disable the task
        if task.get('end_at'):
            end_dt = _parse_dt(task['end_at'])
            if end_dt and datetime.now(timezone.utc) >= end_dt:
                run_db(
                    "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task['id'],)
                )
                continue

        # Build ticket title with datetime
        triggered_time = _parse_dt(task['next_trigger_at'])
        if triggered_time:
            human_dt = triggered_time.strftime('%Y-%m-%d %H:%M UTC')
        else:
            human_dt = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

        ticket_title = f"[Recurring {human_dt}] {task['title']}"
        ticket_body = task.get('body') or ''

        # Create the ticket
        cur = run_db(
            "INSERT INTO tickets (title, body, status_id, board_id, priority) VALUES (?, ?, ?, ?, ?)",
            (ticket_title, ticket_body, task['status_id'], task['board_id'], 'Medium')
        )
        ticket_id = cur.lastrowid

        # Link to recurring task
        run_db(
            "INSERT INTO recurring_instances (recurring_task_id, ticket_id, triggered_at) VALUES (?, ?, ?)",
            (task['id'], ticket_id, now)
        )

        # Add system comment
        add_comment(ticket_id,
            f"🔄 Ticket auto-created by recurring task **{task['title']}** "
            f"(schedule: `{task['cron_expression']}`)")

        # Publish events
        bus.publish('recurring.triggered', recurring_task_id=task['id'], ticket_id=ticket_id, board_id=task['board_id'])
        bus.publish(TICKET_CREATED, ticket_id=ticket_id, title=ticket_title, board_id=task['board_id'], status_id=task['status_id'])

        # Bug C fix: If the initial status has an agent, spawn it (mirrors api_create_ticket)
        from pi_cowork.agents import try_spawn_or_queue
        status = get_status(task['status_id'])
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

        # Update next_trigger_at and last_triggered_at
        last_triggered = compute_next_trigger(task['cron_expression'], after=triggered_time if triggered_time else datetime.now(timezone.utc))
        # Actually trigger from the just-fired time
        next_trigger = compute_next_trigger(task['cron_expression'], after=_parse_dt(task['next_trigger_at']))
        run_db(
            "UPDATE recurring_tasks SET last_triggered_at = ?, next_trigger_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task['next_trigger_at'], next_trigger, task['id'])
        )

        # Check if next_trigger is after end_at — disable
        if task.get('end_at') and next_trigger:
            end_dt = _parse_dt(task['end_at'])
            if end_dt and _parse_dt(next_trigger) and _parse_dt(next_trigger) >= end_dt:
                run_db(
                    "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task['id'],)
                )
                add_comment(ticket_id, "🔚 Recurring task auto-disabled: end date reached.")


def _parse_dt(val):
    """Parse a datetime string or value to a timezone-aware datetime, or None."""
    from datetime import datetime, timezone
    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Notification Dismissals
# ---------------------------------------------------------------------------

def dismiss_notification(ticket_id, notification_type):
    """Insert or replace a dismissal row for (ticket_id, notification_type)."""
    run_db(
        "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (ticket_id, notification_type)
    )


def dismiss_all_notifications():
    """Dismiss all currently visible notifications by inserting dismissal rows for each."""
    # Get all current gate_review notifications
    gate_rows = query_db("""
        SELECT t.id AS ticket_id FROM gate_reviews gr
        JOIN tickets t ON gr.ticket_id = t.id
        JOIN statuses s ON t.status_id = s.id
        WHERE gr.status = 'pending' AND s.is_terminal = 0
        GROUP BY t.id
    """)
    for row in gate_rows:
        dismiss_notification(row['ticket_id'], 'gate_review')

    # Get all current question notifications
    question_rows = query_db("""
        SELECT t.id AS ticket_id FROM questions q
        JOIN tickets t ON q.ticket_id = t.id
        JOIN statuses s ON t.status_id = s.id
        WHERE s.is_terminal = 0
        GROUP BY t.id
    """)
    for row in question_rows:
        dismiss_notification(row['ticket_id'], 'question')


def get_dismissed_notification_set():
    """Return a set of (ticket_id, notification_type) tuples for dismissed notifications."""
    rows = query_db("SELECT ticket_id, notification_type FROM notification_dismissals")
    return {(r['ticket_id'], r['notification_type']) for r in rows}


def cron_human_readable(cron_expression):
    """Convert a cron expression to a human-readable string."""
    from croniter import croniter
    from datetime import datetime, timezone
    try:
        croniter(cron_expression, datetime.now(timezone.utc))
    except (ValueError, KeyError):
        return None
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return cron_expression
    minute, hour, dom, month, dow = parts
    if minute == '*' and hour == '*' and dom == '*' and month == '*' and dow == '*':
        return "Every minute"
    if minute == '0' and hour == '*' and dom == '*' and month == '*' and dow == '*':
        return "Every hour"
    if minute == '0' and hour == '9' and dom == '*' and month == '*' and dow == '*':
        return "Daily at 9:00 AM"
    if minute == '0' and hour == '9' and dom == '*' and month == '*' and dow == '1':
        return "Every Monday at 9:00 AM"
    if minute == '0' and hour == '9' and dom == '1' and month == '*' and dow == '*':
        return "1st of every month at 9:00 AM"
    return cron_expression