"""Data-access layer: get/add/set functions for all domain objects.

Every function here performs SQL via ``pi_cowork.db`` and publishes events
through ``pi_cowork.events.bus`` where appropriate.
"""

import contextlib
import json
import logging
import subprocess
from datetime import UTC

from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.events import COMMENT_ADDED, TICKET_CREATED, bus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def get_comments(ticket_id):
    rows = query_db(  # noqa: S608
        "SELECT id, body, created_at FROM comments WHERE ticket_id = ? ORDER BY created_at, id", (ticket_id,)
    )
    return [row_to_dict(r) for r in rows]


def add_comment(ticket_id, body):
    cur = run_db("INSERT INTO comments (ticket_id, body) VALUES (?, ?)", (ticket_id, body))
    run_db("UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ticket_id,))
    bus.publish(COMMENT_ADDED, ticket_id=ticket_id, body=body)
    return cur.lastrowid


def get_comment_counts(ticket_ids):
    """Get comment counts for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> count.
    """
    if not ticket_ids:
        return {}
    placeholders = ",".join("?" * len(ticket_ids))
    rows = query_db(  # noqa: S608
        f"SELECT ticket_id, COUNT(*) AS c FROM comments WHERE ticket_id IN ({placeholders}) GROUP BY ticket_id",  # noqa: S608
        tuple(ticket_ids),
    )
    return {r["ticket_id"]: r["c"] for r in rows}


def get_ticket_labels_batch(ticket_ids):
    """Get labels for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> list of label dicts.
    """
    if not ticket_ids:
        return {}
    placeholders = ",".join("?" * len(ticket_ids))
    sql = f"""SELECT tl.ticket_id, l.id, l.name, l.color
            FROM ticket_labels tl
            JOIN labels l ON tl.label_id = l.id
            WHERE tl.ticket_id IN ({placeholders})
            ORDER BY l.name"""  # noqa: S608
    rows = query_db(sql, tuple(ticket_ids))
    result = {}
    for r in rows:
        result.setdefault(r["ticket_id"], []).append({"id": r["id"], "name": r["name"], "color": r["color"]})
    return result


def get_recurring_parents_batch(ticket_ids):
    """Get recurring parent tasks for multiple tickets in a single query.

    Returns a dict mapping ticket_id -> list of recurring task dicts.
    """
    if not ticket_ids:
        return {}
    placeholders = ",".join("?" * len(ticket_ids))
    sql = f"""SELECT ri.ticket_id, rt.*, s.name AS status_name
            FROM recurring_instances ri
            JOIN recurring_tasks rt ON rt.id = ri.recurring_task_id
            JOIN statuses s ON rt.status_id = s.id
            WHERE ri.ticket_id IN ({placeholders})"""  # noqa: S608
    rows = query_db(sql, tuple(ticket_ids))
    result = {}
    for r in rows:
        d = row_to_dict(r)
        tid = d.pop("ticket_id")
        result.setdefault(tid, []).append(d)
    return result


# ---------------------------------------------------------------------------
# Ticket Status Overrides
# ---------------------------------------------------------------------------


def get_ticket_status_overrides(ticket_id):
    """Get all status overrides for a ticket."""
    rows = query_db(  # noqa: S608
        """SELECT tso.*, s.name AS status_name
           FROM ticket_status_overrides tso
           JOIN statuses s ON tso.status_id = s.id
           WHERE tso.ticket_id = ?
           ORDER BY s.sort_order""",
        (ticket_id,),
    )
    return [row_to_dict(r) for r in rows]


def get_ticket_status_override(ticket_id, status_id):
    """Get a single ticket-status override, or None."""
    row = query_db(
        "SELECT * FROM ticket_status_overrides WHERE ticket_id = ? AND status_id = ?", (ticket_id, status_id), one=True
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
        (ticket_id, status_id, model, thinking),
    )
    return get_ticket_status_override(ticket_id, status_id)


def delete_ticket_status_override(ticket_id, status_id):
    """Delete a ticket-status override."""
    run_db("DELETE FROM ticket_status_overrides WHERE ticket_id = ? AND status_id = ?", (ticket_id, status_id))


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


def get_questions(ticket_id):
    rows = query_db(  # noqa: S608
        "SELECT id, ticket_id, body, options, created_at FROM questions WHERE ticket_id = ? ORDER BY created_at, id",
        (ticket_id,),
    )
    result = []
    for r in rows:
        d = row_to_dict(r)
        if d.get("options"):
            try:
                d["options"] = json.loads(d["options"])
            except (json.JSONDecodeError, TypeError):
                d["options"] = None
        else:
            d["options"] = None
        result.append(d)
    return result


def count_unanswered_questions(ticket_id):
    row = query_db("SELECT COUNT(*) AS c FROM questions WHERE ticket_id = ?", (ticket_id,), one=True)
    return row["c"] if row else 0


def has_unanswered_questions(ticket_id):
    return count_unanswered_questions(ticket_id) > 0


def _add_question_wait_comment(ticket_id, count):
    last = query_db(
        "SELECT body FROM comments WHERE ticket_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (ticket_id,),
        one=True,
    )
    msg = f"⏳ Waiting for {count} unanswered question(s) before agent can proceed."
    if last and msg in last["body"]:
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
    row = query_db(
        """
        SELECT b.*, w.name AS workflow_name, w.git_enabled AS workflow_git_enabled
        FROM boards b
        JOIN workflows w ON b.workflow_id = w.id
        WHERE b.id = ?
    """,
        (board_id,),
        one=True,
    )
    return row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------


def get_statuses(workflow_id):
    rows = query_db(  # noqa: S608
        """
        SELECT s.*, a.name AS agent_name
        FROM statuses s
        LEFT JOIN agents a ON s.agent_id = a.id
        WHERE s.workflow_id = ?
        ORDER BY s.sort_order
    """,
        (workflow_id,),
    )
    return [row_to_dict(r) for r in rows]


def get_status(status_id):
    row = query_db(
        """
        SELECT s.*, a.name AS agent_name
        FROM statuses s
        LEFT JOIN agents a ON s.agent_id = a.id
        WHERE s.id = ?
    """,
        (status_id,),
        one=True,
    )
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
    rows = query_db(  # noqa: S608
        """SELECT t.*, s.name AS to_status_name
           FROM transitions t JOIN statuses s ON t.to_status_id = s.id
           WHERE t.from_status_id = ?""",
        (status_id,),
    )
    return [row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------


def get_quality_gates(from_status_id, to_status_id):
    rows = query_db(  # noqa: S608
        "SELECT * FROM quality_gates WHERE from_status_id = ? AND to_status_id = ? AND enabled = 1 ORDER BY sort_order",
        (from_status_id, to_status_id),
    )
    return [row_to_dict(r) for r in rows]


def get_all_quality_gates(workflow_id):
    rows = query_db(  # noqa: S608
        """SELECT qg.*, fs.name AS from_status_name, ts.name AS to_status_name
           FROM quality_gates qg
           JOIN statuses fs ON qg.from_status_id = fs.id
           JOIN statuses ts ON qg.to_status_id = ts.id
           WHERE qg.workflow_id = ?
           ORDER BY qg.sort_order""",
        (workflow_id,),
    )
    return [row_to_dict(r) for r in rows]


def get_pending_gate_reviews(ticket_id):
    rows = query_db(  # noqa: S608
        """SELECT gr.*, qg.gate_type, qg.name AS gate_name, qg.config AS gate_config,
                  fs.name AS from_status_name, ts.name AS to_status_name
           FROM gate_reviews gr
           JOIN quality_gates qg ON gr.gate_id = qg.id
           JOIN statuses fs ON gr.from_status_id = fs.id
           JOIN statuses ts ON gr.to_status_id = ts.id
           WHERE gr.ticket_id = ? AND gr.status = 'pending'
           ORDER BY gr.created_at, gr.id""",
        (ticket_id,),
    )
    return [row_to_dict(r) for r in rows]


def has_pending_gate_reviews(ticket_id):
    row = query_db(
        "SELECT 1 FROM gate_reviews WHERE ticket_id = ? AND status = 'pending' LIMIT 1", (ticket_id,), one=True
    )
    return row is not None


def _truncate(text, max_bytes=50 * 1024):
    """Truncate text to max_bytes UTF-8 length, appending a marker."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Leave room for the truncation marker
    marker = "\n... (truncated, N more bytes)"
    marker_len = len(marker.encode("utf-8")) + 6  # rough room for number
    cut = max_bytes - marker_len
    while cut > 0:
        try:
            return encoded[:cut].decode("utf-8") + f"\n... (truncated, {len(encoded) - cut} more bytes)"
        except UnicodeDecodeError:
            cut -= 1
    return encoded[:max_bytes].decode("utf-8", errors="replace") + "\n... (truncated)"


def run_cli_gate(command, working_directory):
    """Run a CLI gate command and return (passed, output)."""
    try:
        result = subprocess.run(command, shell=True, cwd=working_directory, capture_output=True, text=True, timeout=60)  # noqa: S602
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            parts = [f"Exit code: {result.returncode}"]
            if stdout:
                parts.append(f"--- stdout ---\n{stdout}")
            if stderr:
                parts.append(f"--- stderr ---\n{stderr}")
            output = _truncate("\n".join(parts))
            return False, output
        return True, _truncate(stdout)
    except subprocess.TimeoutExpired as e:
        parts = ["Command timed out after 60 seconds"]
        stderr = (e.stderr or "").strip() if hasattr(e, "stderr") else ""
        if stderr:
            parts.append(f"--- stderr ---\n{stderr}")
        output = _truncate("\n".join(parts))
        return False, output
    except Exception as exc:
        return False, f"Failed to run command: {exc}"


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def get_ticket_labels(ticket_id):
    rows = query_db(  # noqa: S608
        """
        SELECT l.id, l.name, l.color
        FROM labels l
        JOIN ticket_labels tl ON tl.label_id = l.id
        WHERE tl.ticket_id = ?
        ORDER BY l.name
    """,
        (ticket_id,),
    )
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
        placeholders = ",".join("?" * len(label_ids))
        valid = query_db(
            f"SELECT id FROM labels WHERE workflow_id = ? AND id IN ({placeholders})",  # noqa: S608
            (workflow_id, *label_ids),
        )
        valid_ids = {r["id"] for r in valid}
        for lid in valid_ids:
            with contextlib.suppress(Exception):
                run_db("INSERT INTO ticket_labels (ticket_id, label_id) VALUES (?, ?)", (ticket_id, lid))
    run_db("UPDATE tickets SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (ticket_id,))
    return True


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_setting(key, default=None):
    row = query_db("SELECT value FROM settings WHERE key = ?", (key,), one=True)
    return row["value"] if row else default


def set_setting(key, value):
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    run_db(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, now),
    )


# ---------------------------------------------------------------------------
# Recurring Tasks
# ---------------------------------------------------------------------------


def compute_next_trigger(cron_expression, after=None):
    """Compute the next firing time for a cron expression. Returns ISO string or None."""
    from datetime import datetime

    from croniter import croniter

    if after is None:
        after = datetime.now(UTC)
    elif isinstance(after, str):
        after = datetime.fromisoformat(after.replace("Z", "+00:00"))
        if after.tzinfo is None:
            after = after.replace(tzinfo=UTC)
    try:
        it = croniter(cron_expression, after)
        return it.get_next(datetime).isoformat()
    except (ValueError, KeyError):
        return None


def get_recurring_tasks(board_id):
    rows = query_db(  # noqa: S608
        """SELECT rt.*, s.name AS status_name
           FROM recurring_tasks rt
           JOIN statuses s ON rt.status_id = s.id
           WHERE rt.board_id = ?
           ORDER BY rt.created_at DESC""",
        (board_id,),
    )
    return [row_to_dict(r) for r in rows]


def get_recurring_task(task_id):
    row = query_db(
        """SELECT rt.*, s.name AS status_name, b.name AS board_name
           FROM recurring_tasks rt
           JOIN statuses s ON rt.status_id = s.id
           JOIN boards b ON rt.board_id = b.id
           WHERE rt.id = ?""",
        (task_id,),
        one=True,
    )
    return row_to_dict(row) if row else None


def create_recurring_task(board_id, title, body, status_id, cron_expression, start_at=None, end_at=None):
    """Create a recurring task. Returns (task_dict, error)."""
    from datetime import datetime

    from croniter import croniter

    # Validate cron expression
    try:
        croniter(cron_expression, datetime.now(UTC))
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
    if status["workflow_id"] != board["workflow_id"]:
        return None, "Status does not belong to the board's workflow"

    # Validate end_at not in the past
    now = datetime.now(UTC)
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
        (board_id, title.strip(), body, status_id, cron_expression.strip(), next_trigger, start_at, end_at),
    )
    return get_recurring_task(cur.lastrowid), None


def update_recurring_task(  # noqa: C901
    task_id, title=None, body=None, status_id=None, cron_expression=None, start_at=None, end_at=None
):
    """Update a recurring task. Returns (task_dict, error)."""
    from datetime import datetime

    from croniter import croniter

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
        board = get_board(task["board_id"])
        if board and status["workflow_id"] != board["workflow_id"]:
            return None, "Status does not belong to the board's workflow"
        updates.append("status_id = ?")
        args.append(status_id)

    if cron_expression is not None:
        try:
            croniter(cron_expression, datetime.now(UTC))
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
            if end_dt <= datetime.now(UTC):
                return None, "End date must be in the future"
        except (ValueError, TypeError):
            return None, "Invalid end_at format"
        updates.append("end_at = ?")
        args.append(end_at)

    # Recompute next_trigger_at if cron, start, or enabled state changed
    need_recompute = cron_expression is not None or start_at is not None
    if need_recompute and task.get("enabled"):
        new_cron = cron_expression if cron_expression is not None else task["cron_expression"]
        after = (
            _parse_dt(task.get("last_triggered_at") or start_at or task.get("start_at"))
            if not start_at
            else _parse_dt(start_at)
        )
        if after is None:
            after = datetime.now(UTC)
        next_trigger = compute_next_trigger(new_cron, after=after)
        updates.append("next_trigger_at = ?")
        args.append(next_trigger)

    if not updates:
        return task, None

    updates.append("updated_at = CURRENT_TIMESTAMP")
    args.append(task_id)
    run_db(f"UPDATE recurring_tasks SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608
    return get_recurring_task(task_id), None


def delete_recurring_task(task_id):
    """Delete a recurring task — soft-disables, or hard delete if no instances."""
    task = get_recurring_task(task_id)
    if not task:
        return None, "Recurring task not found"

    instance_count = query_db(
        "SELECT COUNT(*) AS c FROM recurring_instances WHERE recurring_task_id = ?", (task_id,), one=True
    )
    if instance_count and instance_count["c"] > 0:
        run_db("UPDATE recurring_tasks SET enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
        return {"soft_deleted": True}, None
    else:
        run_db("DELETE FROM recurring_tasks WHERE id = ?", (task_id,))
        return {"deleted": True}, None


def toggle_recurring_task(task_id):
    """Toggle enabled state. Returns (task_dict, error)."""
    from datetime import datetime

    task = get_recurring_task(task_id)
    if not task:
        return None, "Recurring task not found"

    new_enabled = not task.get("enabled")
    if new_enabled:
        # Recompute next_trigger_at from last_triggered_at or start_at
        after_src = task.get("last_triggered_at") or task.get("start_at")
        after = _parse_dt(after_src) if after_src else datetime.now(UTC)
        next_trigger = compute_next_trigger(task["cron_expression"], after=after)
        run_db(
            "UPDATE recurring_tasks SET enabled = 1, next_trigger_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (next_trigger, task_id),
        )
    else:
        run_db(
            "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
    return get_recurring_task(task_id), None


def get_recurring_parents(ticket_id):
    """Get parent recurring tasks of a ticket."""
    rows = query_db(  # noqa: S608
        """SELECT rt.*, s.name AS status_name
           FROM recurring_tasks rt
           JOIN recurring_instances ri ON rt.id = ri.recurring_task_id
           JOIN statuses s ON rt.status_id = s.id
           WHERE ri.ticket_id = ?""",
        (ticket_id,),
    )
    return [row_to_dict(r) for r in rows]


def process_recurring_tasks():
    """Create tickets for all due recurring tasks. Called periodically from drain loop."""
    from datetime import datetime

    now = datetime.now(UTC).isoformat()
    due_tasks = query_db(
        """SELECT * FROM recurring_tasks
           WHERE enabled = 1
             AND next_trigger_at IS NOT NULL
             AND next_trigger_at <= ?""",
        (now,),
    )
    for task in due_tasks:
        task = row_to_dict(task)
        board = get_board(task["board_id"])
        if not board:
            continue

        # Check if end_at has passed — disable the task
        if task.get("end_at"):
            end_dt = _parse_dt(task["end_at"])
            if end_dt and datetime.now(UTC) >= end_dt:
                run_db(
                    "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task["id"],),
                )
                continue

        # Build ticket title with datetime
        triggered_time = _parse_dt(task["next_trigger_at"])
        if triggered_time:
            human_dt = triggered_time.strftime("%Y-%m-%d %H:%M UTC")
        else:
            human_dt = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        ticket_title = f"[Recurring {human_dt}] {task['title']}"
        ticket_body = task.get("body") or ""

        # Create the ticket
        cur = run_db(
            "INSERT INTO tickets (title, body, status_id, board_id, priority) VALUES (?, ?, ?, ?, ?)",
            (ticket_title, ticket_body, task["status_id"], task["board_id"], "Medium"),
        )
        ticket_id = cur.lastrowid

        # Link to recurring task
        run_db(
            "INSERT INTO recurring_instances (recurring_task_id, ticket_id, triggered_at) VALUES (?, ?, ?)",
            (task["id"], ticket_id, now),
        )

        # Add system comment
        add_comment(
            ticket_id,
            f"🔄 Ticket auto-created by recurring task **{task['title']}** (schedule: `{task['cron_expression']}`)",
        )

        # Publish events
        bus.publish("recurring.triggered", recurring_task_id=task["id"], ticket_id=ticket_id, board_id=task["board_id"])
        bus.publish(
            TICKET_CREATED,
            ticket_id=ticket_id,
            title=ticket_title,
            board_id=task["board_id"],
            status_id=task["status_id"],
        )

        # Bug C fix: If the initial status has an agent, spawn it (mirrors api_create_ticket)
        from pi_cowork.agents import spawn_agent_for_ticket

        spawn_agent_for_ticket(ticket_id, task["status_id"])

        # Update next_trigger_at and last_triggered_at
        compute_next_trigger(task["cron_expression"], after=triggered_time if triggered_time else datetime.now(UTC))
        # Actually trigger from the just-fired time
        next_trigger = compute_next_trigger(task["cron_expression"], after=_parse_dt(task["next_trigger_at"]))
        run_db(
            "UPDATE recurring_tasks SET last_triggered_at = ?, next_trigger_at = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task["next_trigger_at"], next_trigger, task["id"]),
        )

        # Check if next_trigger is after end_at — disable
        if task.get("end_at") and next_trigger:
            end_dt = _parse_dt(task["end_at"])
            if end_dt and _parse_dt(next_trigger) and _parse_dt(next_trigger) >= end_dt:
                run_db(
                    "UPDATE recurring_tasks SET enabled = 0, next_trigger_at = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task["id"],),
                )
                add_comment(ticket_id, "🔚 Recurring task auto-disabled: end date reached.")


def _parse_dt(val):
    """Parse a datetime string or value to a timezone-aware datetime, or None."""
    from datetime import datetime

    if not val:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=UTC)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
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
        "INSERT OR REPLACE INTO notification_dismissals "
        "(ticket_id, notification_type, dismissed_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (ticket_id, notification_type),
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
        dismiss_notification(row["ticket_id"], "gate_review")

    # Get all current question notifications
    question_rows = query_db("""
        SELECT t.id AS ticket_id FROM questions q
        JOIN tickets t ON q.ticket_id = t.id
        JOIN statuses s ON t.status_id = s.id
        WHERE s.is_terminal = 0
        GROUP BY t.id
    """)
    for row in question_rows:
        dismiss_notification(row["ticket_id"], "question")


def get_dismissed_notification_set():
    """Return a set of (ticket_id, notification_type) tuples for dismissed notifications."""
    rows = query_db("SELECT ticket_id, notification_type FROM notification_dismissals")
    return {(r["ticket_id"], r["notification_type"]) for r in rows}


def cron_human_readable(cron_expression):
    """Convert a cron expression to a human-readable string."""
    from datetime import datetime

    from croniter import croniter

    try:
        croniter(cron_expression, datetime.now(UTC))
    except (ValueError, KeyError):
        return None
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return cron_expression
    minute, hour, dom, month, dow = parts
    if minute == "*" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "Every minute"
    if minute == "0" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "Every hour"
    if minute == "0" and hour == "9" and dom == "*" and month == "*" and dow == "*":
        return "Daily at 9:00 AM"
    if minute == "0" and hour == "9" and dom == "*" and month == "*" and dow == "1":
        return "Every Monday at 9:00 AM"
    if minute == "0" and hour == "9" and dom == "1" and month == "*" and dow == "*":
        return "1st of every month at 9:00 AM"
    return cron_expression


# ---------------------------------------------------------------------------
# Notification Dismissals Cleanup
# ---------------------------------------------------------------------------


def cleanup_old_notification_dismissals(max_age_days=None):
    """Delete notification_dismissals rows older than *max_age_days*.

    Called periodically from the drain loop.  Works inside and outside a
    Flask application context.

    Retention priority:
    1. Explicit max_age_days argument
    2. DB settings table (notification_dismissal_retention_days key)
    3. PI_NOTIFICATION_DISMISSAL_RETENTION_DAYS environment variable
    4. Default of 7 days

    Re-dismissing a notification replaces the row with a fresh dismissed_at
    timestamp, effectively resetting the TTL — no separate created_at column
    is needed.

    Returns the number of rows deleted.
    """
    import os
    import sqlite3
    from datetime import datetime, timedelta

    from pi_cowork.config import get_config

    if max_age_days is None:
        max_age_days = get_config("notification_dismissal_retention_days")
        if max_age_days is None:
            max_age_days = 7

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            db = get_db()
            cur = db.execute("DELETE FROM notification_dismissals WHERE dismissed_at < ?", (cutoff,))
            db.commit()
            deleted = cur.rowcount
        else:
            raise RuntimeError("No app context")
    except (ImportError, RuntimeError):
        from pi_cowork import config as _config

        path = os.environ.get("DATABASE", _config.DATABASE)
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute("DELETE FROM notification_dismissals WHERE dismissed_at < ?", (cutoff,))
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()

    if deleted:
        logger.info("Notification dismissals cleanup: deleted %d rows older than %d days", deleted, max_age_days)
    return deleted


# ---------------------------------------------------------------------------
# Knowledge Management
# ---------------------------------------------------------------------------


def get_knowledge_entries(board_id=None, search=None, category=None, auto_context=None, tags=None):
    """List knowledge entries with optional filters.

    When board_id is specified, returns both global (board_id IS NULL) and
    board-specific entries for that board.
    When board_id is None, returns only global entries.
    """
    conditions = []
    args = []

    if board_id is not None:
        conditions.append("(ke.board_id = ? OR ke.board_id IS NULL)")
        args.append(board_id)
    else:
        conditions.append("ke.board_id IS NULL")

    if search:
        conditions.append("(ke.title LIKE ? OR ke.content LIKE ?)")
        args.extend([f"%{search}%", f"%{search}%"])

    if category is not None:
        conditions.append("ke.category = ?")
        args.append(category)

    if auto_context is not None:
        conditions.append("ke.auto_context = ?")
        args.append(1 if auto_context else 0)

    if tags:
        tag_names = tags if isinstance(tags, list) else [tags]
        placeholders = ",".join("?" * len(tag_names))
        conditions.append(
            f"""ke.id IN (
            SELECT ket.entry_id FROM knowledge_entry_tags ket
            JOIN knowledge_tags kt ON ket.tag_id = kt.id
            WHERE kt.name IN ({placeholders})
        )"""  # noqa: S608
        )
        args.extend(tag_names)

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT ke.*, b.name AS board_name
           FROM knowledge_entries ke
           LEFT JOIN boards b ON ke.board_id = b.id
           WHERE {where}
           ORDER BY ke.sort_order, ke.updated_at DESC"""  # noqa: S608
    rows = query_db(sql, tuple(args))
    result = []
    for r in rows:
        entry = row_to_dict(r)
        # Load tags for entry
        tag_rows = query_db(
            """SELECT kt.id, kt.name FROM knowledge_tags kt
               JOIN knowledge_entry_tags ket ON ket.tag_id = kt.id
               WHERE ket.entry_id = ? ORDER BY kt.name""",
            (entry["id"],),
        )
        entry["tags"] = [row_to_dict(t) for t in tag_rows]
        result.append(entry)
    return result


def get_knowledge_entry(entry_id):
    """Get a single knowledge entry with tags."""
    row = query_db(
        """SELECT ke.*, b.name AS board_name
           FROM knowledge_entries ke
           LEFT JOIN boards b ON ke.board_id = b.id
           WHERE ke.id = ?""",
        (entry_id,),
        one=True,
    )
    if not row:
        return None
    entry = row_to_dict(row)
    tag_rows = query_db(
        """SELECT kt.id, kt.name FROM knowledge_tags kt
           JOIN knowledge_entry_tags ket ON ket.tag_id = kt.id
           WHERE ket.entry_id = ? ORDER BY kt.name""",
        (entry_id,),
    )
    entry["tags"] = [row_to_dict(t) for t in tag_rows]
    return entry


def search_knowledge(query, board_id=None):
    """Full-text search across title + content, filtered by board scope.
    Returns global + board-specific matches.
    """
    conditions = []
    args = []

    if board_id is not None:
        conditions.append("(ke.board_id = ? OR ke.board_id IS NULL)")
        args.append(board_id)

    if query:
        conditions.append("(ke.title LIKE ? OR ke.content LIKE ?)")
        args.extend([f"%{query}%", f"%{query}%"])

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT ke.*, b.name AS board_name
           FROM knowledge_entries ke
           LEFT JOIN boards b ON ke.board_id = b.id
           WHERE {where}
           ORDER BY ke.sort_order, ke.updated_at DESC"""  # noqa: S608
    rows = query_db(sql, tuple(args))
    result = []
    for r in rows:
        entry = row_to_dict(r)
        tag_rows = query_db(
            """SELECT kt.id, kt.name FROM knowledge_tags kt
               JOIN knowledge_entry_tags ket ON ket.tag_id = kt.id
               WHERE ket.entry_id = ? ORDER BY kt.name""",
            (entry["id"],),
        )
        entry["tags"] = [row_to_dict(t) for t in tag_rows]
        result.append(entry)
    return result


def create_knowledge_entry(
    title, content, board_id=None, category=None, auto_context=False, tags=None, sort_order=0, created_by="human"
):
    """Create a knowledge entry. Returns the new entry dict with tags."""
    auto_context_val = 1 if auto_context else 0
    cur = run_db(
        """INSERT INTO knowledge_entries (board_id, title, content, category, auto_context, sort_order)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (board_id, title.strip(), content, category, auto_context_val, sort_order),
    )
    entry_id = cur.lastrowid

    # Create version history record
    run_db(
        """INSERT INTO knowledge_versions (entry_id, title, content, category, auto_context, created_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (entry_id, title.strip(), content, category, auto_context_val, created_by),
    )

    # Handle tags
    if tags:
        _set_entry_tags(entry_id, tags)

    return get_knowledge_entry(entry_id)


def update_knowledge_entry(
    entry_id,
    title=None,
    content=None,
    board_id=None,
    category=None,
    auto_context=None,
    tags=None,
    sort_order=None,
    updated_by="human",
    clear_board_id=False,
):
    """Update a knowledge entry. Auto-creates version record.

    board_id: If provided, set to this board. None means not changed (unless
              clear_board_id is True).
    clear_board_id: If True, set board_id to NULL (global). Cannot be used
              together with board_id.
    Returns the updated entry dict or None if not found.
    """
    entry = get_knowledge_entry(entry_id)
    if not entry:
        return None

    updates = []
    args = []

    if title is not None:
        updates.append("title = ?")
        args.append(title.strip())
    if content is not None:
        updates.append("content = ?")
        args.append(content)
    # board_id: clear_board_id takes priority; then explicit board_id; else no change
    if clear_board_id:
        updates.append("board_id = ?")
        args.append(None)  # set to global
    elif board_id is not None:
        updates.append("board_id = ?")
        args.append(board_id)
    if category is not None:
        updates.append("category = ?")
        args.append(category if category else None)
    if auto_context is not None:
        updates.append("auto_context = ?")
        args.append(1 if auto_context else 0)
    if sort_order is not None:
        updates.append("sort_order = ?")
        args.append(sort_order)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        args.append(entry_id)
        run_db(f"UPDATE knowledge_entries SET {', '.join(updates)} WHERE id = ?", tuple(args))  # noqa: S608

    # Handle tags update
    if tags is not None:
        _set_entry_tags(entry_id, tags)

    # Create version history record (always record after any update)
    updated_entry = get_knowledge_entry(entry_id)
    if updated_entry:
        run_db(
            """INSERT INTO knowledge_versions (entry_id, title, content, category, auto_context, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                updated_entry["title"],
                updated_entry["content"],
                updated_entry.get("category"),
                1 if updated_entry.get("auto_context") else 0,
                updated_by,
            ),
        )

    return updated_entry


def delete_knowledge_entry(entry_id):
    """Delete a knowledge entry (cascades versions + tags)."""
    run_db("DELETE FROM knowledge_entry_tags WHERE entry_id = ?", (entry_id,))
    run_db("DELETE FROM knowledge_versions WHERE entry_id = ?", (entry_id,))
    run_db("DELETE FROM knowledge_entries WHERE id = ?", (entry_id,))


def get_knowledge_versions(entry_id):
    """Get all versions of a knowledge entry."""
    rows = query_db(  # noqa: S608
        "SELECT * FROM knowledge_versions WHERE entry_id = ? ORDER BY created_at DESC, id DESC", (entry_id,)
    )
    return [row_to_dict(r) for r in rows]


def get_knowledge_version(entry_id, version_id):
    """Get a specific version of a knowledge entry."""
    row = query_db("SELECT * FROM knowledge_versions WHERE entry_id = ? AND id = ?", (entry_id, version_id), one=True)
    return row_to_dict(row) if row else None


def restore_knowledge_version(entry_id, version_id, restored_by="human"):
    """Restore a previous version as the current entry. Returns the updated entry."""
    version = get_knowledge_version(entry_id, version_id)
    if not version:
        return None
    return update_knowledge_entry(
        entry_id,
        title=version["title"],
        content=version["content"],
        category=version.get("category"),
        auto_context=bool(version.get("auto_context", 0)),
        updated_by=restored_by,
    )


def get_auto_context_entries(board_id=None):
    """Get all auto_context entries for injection into agent prompts.
    Returns entries with board_id matching the given board OR global (board_id IS NULL)."""
    if board_id is not None:
        rows = query_db(
            """SELECT ke.id, ke.title, ke.content, ke.board_id, b.name AS board_name, ke.category
               FROM knowledge_entries ke
               LEFT JOIN boards b ON ke.board_id = b.id
               WHERE ke.auto_context = 1 AND (ke.board_id = ? OR ke.board_id IS NULL)
               ORDER BY ke.sort_order, ke.updated_at DESC""",
            (board_id,),
        )
    else:
        rows = query_db(
            """SELECT ke.id, ke.title, ke.content, ke.board_id, b.name AS board_name, ke.category
               FROM knowledge_entries ke
               LEFT JOIN boards b ON ke.board_id = b.id
               WHERE ke.auto_context = 1 AND ke.board_id IS NULL
               ORDER BY ke.sort_order, ke.updated_at DESC"""  # noqa: S608
        )
    return [row_to_dict(r) for r in rows]


def get_knowledge_categories(board_id=None):
    """Get distinct categories for knowledge entries."""
    if board_id is not None:
        rows = query_db(
            """SELECT DISTINCT ke.category FROM knowledge_entries ke
               WHERE ke.category IS NOT NULL AND (ke.board_id = ? OR ke.board_id IS NULL)
               ORDER BY ke.category""",
            (board_id,),
        )
    else:
        rows = query_db(
            """SELECT DISTINCT category FROM knowledge_entries
               WHERE category IS NOT NULL AND board_id IS NULL
               ORDER BY category"""
        )
    return [r["category"] for r in rows]


def get_knowledge_count_for_board(board_id):
    """Get count of knowledge entries relevant to a board (global + board-specific)."""
    row = query_db(
        """SELECT COUNT(*) AS c FROM knowledge_entries
           WHERE board_id = ? OR board_id IS NULL""",
        (board_id,),
        one=True,
    )
    return row["c"] if row else 0


def _set_entry_tags(entry_id, tags):
    """Set tags for a knowledge entry. tags is a list of tag name strings."""
    # Clear existing tags
    run_db("DELETE FROM knowledge_entry_tags WHERE entry_id = ?", (entry_id,))

    for tag_name in tags:
        tag_name = tag_name.strip()
        if not tag_name:
            continue
        # Find or create tag
        existing = query_db("SELECT id FROM knowledge_tags WHERE name = ?", (tag_name,), one=True)
        if existing:
            tag_id = existing["id"]
        else:
            cur = run_db("INSERT INTO knowledge_tags (name) VALUES (?)", (tag_name,))
            tag_id = cur.lastrowid
        # Link entry to tag
        with contextlib.suppress(Exception):
            run_db("INSERT INTO knowledge_entry_tags (entry_id, tag_id) VALUES (?, ?)", (entry_id, tag_id))


def get_all_tags():
    """Get all knowledge tags."""
    rows = query_db("SELECT * FROM knowledge_tags ORDER BY name")
    return [row_to_dict(r) for r in rows]
