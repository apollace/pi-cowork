"""Agent spawning, limits, queue management, and watcher threads."""

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from pi_cowork import config
from pi_cowork.api_docs import build_api_docs
from pi_cowork.config import get_config
from pi_cowork.db import get_db, query_db, row_to_dict, run_db
from pi_cowork.events import AGENT_COMPLETED, AGENT_FAILED, AGENT_SPAWNED, bus
from pi_cowork.models import (
    _add_question_wait_comment,
    add_comment,
    count_unanswered_questions,
    get_agent,
    get_board,
    get_comments,
    get_quality_gates,
    get_status,
    get_transitions_from,
    has_pending_gate_reviews,
)

try:
    from pi_cowork.git_helpers import ensure_ticket_branch
except ImportError:
    ensure_ticket_branch = None

logger = logging.getLogger(__name__)

_spawn_lock = threading.Lock()
_drain_app = None  # Flask app reference for event-driven drain handler


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def _is_our_process(pid):
    """Check if a PID still belongs to a pi agent process (guards against PID recycling)."""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
        return "pi" in cmdline
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _read_log(pipe, log_f):
    """Drain agent stdout pipe line-by-line into the log file, flushing every line."""
    try:
        for line in iter(pipe.readline, b""):
            if not line:
                break
            log_f.write(line.decode("utf-8", errors="replace"))
            log_f.flush()
    finally:
        pipe.close()
        log_f.close()


def _start_log_reader(pipe, log_f):
    """Start a daemon thread to read agent stdout into the log file in real time."""
    reader = threading.Thread(
        target=_read_log,
        args=(pipe, log_f),
        daemon=True,
    )
    reader.start()


def _start_watcher(proc, run_id, ticket_id, agent_name, log_f):
    """Start a watcher thread for the given agent process."""
    watcher = threading.Thread(
        target=_watch_agent,
        args=(proc, run_id, ticket_id, agent_name, log_f),
        daemon=True,
    )
    watcher.start()


def _get_db_for_watcher():
    """Get a standalone DB connection for watcher threads (outside Flask request context).

    Uses the stored ``_drain_app`` reference to read the DATABASE config rather
    than ``current_app`` (which requires an active request context and is
    unavailable in daemon threads). Falls back to ``config.DATABASE``.
    """
    path = _drain_app.config["DATABASE"] if _drain_app else config.DATABASE
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _watch_agent(proc, run_id, ticket_id, agent_name, log_f):
    """Watcher thread: waits for the agent subprocess to finish and updates the DB.

    Runs in a daemon thread with no Flask application context. We push one
    using the stored ``_drain_app`` reference so that ``bus.publish()``
    (which triggers ``_audit_subscriber`` → ``get_db()``) works correctly.
    """
    if _drain_app is None:
        logger.error("Watcher thread cannot run: _drain_app is not set")
        return

    with _drain_app.app_context():
        conn = None
        try:
            exit_code = proc.wait()
            now = datetime.now(UTC).isoformat()
            status = "completed" if exit_code == 0 else "failed"
            conn = _get_db_for_watcher()
            conn.execute(
                "UPDATE agent_runs SET status = ?, completed_at = ?, exit_code = ? WHERE id = ?",
                (status, now, exit_code, run_id),
            )
            conn.commit()
            if exit_code != 0:
                conn.execute(
                    "INSERT INTO comments (ticket_id, body) VALUES (?, ?)",
                    (ticket_id, f"⚠️ Agent '{agent_name}' exited with code {exit_code}."),
                )
                conn.commit()
                bus.publish(AGENT_FAILED, ticket_id=ticket_id, agent_name=agent_name, exit_code=exit_code)
            else:
                bus.publish(AGENT_COMPLETED, ticket_id=ticket_id, agent_name=agent_name, run_id=run_id)
        except Exception as e:
            logger.error("Watcher thread error for run %d: %s", run_id, e)
            now = datetime.now(UTC).isoformat()
            try:
                if conn is None:
                    conn = _get_db_for_watcher()
                conn.execute("UPDATE agent_runs SET status = 'failed', completed_at = ? WHERE id = ?", (now, run_id))
                conn.commit()
            except Exception:
                logger.error("Watcher thread failed to update DB for run %d", run_id)
        finally:
            if conn:
                conn.close()


# ---------------------------------------------------------------------------
# Run cleanup
# ---------------------------------------------------------------------------


def cleanup_runs():
    """Safety net for orphaned runs. Checks PIDs and marks stale runs completed.

    Also cleans up stale queue entries (Bug 5 safety net):
    - Removes queue entries where the ticket already has a running agent
    - Removes queue entries older than 2 hours that have not been started
    - Removes queue entries where the same agent already completed/failed
      for the ticket after the queue entry was created (prevents re-spawn
      of a completed agent from a stale queue entry)
    """
    now = datetime.now(UTC)
    rows = query_db("SELECT id, pid, started_at FROM agent_runs WHERE status = 'running'")
    for row in rows:
        started = row["started_at"]
        if started:
            if isinstance(started, str):
                started = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
            if (now - started).total_seconds() > get_config("run_max_age"):
                run_db(
                    "UPDATE agent_runs SET status = 'completed', completed_at = ? WHERE id = ?",
                    (now.isoformat(), row["id"]),
                )
                continue

        pid = row["pid"]
        if pid is None:
            run_db(
                "UPDATE agent_runs SET status = 'failed', completed_at = ? WHERE id = ?", (now.isoformat(), row["id"])
            )
            continue

        if not _is_our_process(pid):
            run_db(
                "UPDATE agent_runs SET status = 'completed', completed_at = ?, exit_code = ? WHERE id = ?",
                (now.isoformat(), -1, row["id"]),
            )

    # Stale queue cleanup (Bug 5 safety net)
    # Remove queue entries where the ticket already has a running agent
    run_db(
        """DELETE FROM agent_queue WHERE started_at IS NULL AND ticket_id IN (
            SELECT DISTINCT ar.ticket_id FROM agent_runs ar
            WHERE ar.status = 'running'
        )"""
    )
    # Remove queue entries older than 2 hours that have not been started
    run_db("DELETE FROM agent_queue WHERE started_at IS NULL AND queued_at < datetime('now', '-2 hours')")
    # Remove queue entries where the same agent already completed/failed for
    # the ticket after the queue entry was created
    run_db(
        """DELETE FROM agent_queue WHERE started_at IS NULL AND EXISTS (
            SELECT 1 FROM agent_runs ar
            WHERE ar.ticket_id = agent_queue.ticket_id
            AND ar.agent_id = agent_queue.agent_id
            AND ar.status IN ('completed', 'failed')
            AND ar.started_at >= agent_queue.queued_at
        )"""
    )


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


def count_running():
    row = query_db("SELECT COUNT(*) AS c FROM agent_runs WHERE status = 'running'", one=True)
    return row["c"] if row else 0


def count_hourly():
    row = query_db("SELECT COUNT(*) AS c FROM agent_runs WHERE started_at > datetime('now', '-1 hour')", one=True)
    return row["c"] if row else 0


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


def queue_agent(ticket, status, agent, reason, old_status_id=None):
    # Bug 3 fix: Remove any existing un-started queue entries for this ticket
    # to prevent duplicates from stacking up on repeated calls.
    run_db("DELETE FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL", (ticket["id"],))
    # Bug B fix: Store old_status_id so the drained agent gets transition context.
    run_db(
        "INSERT INTO agent_queue (ticket_id, status_id, agent_id, reason, old_status_id) VALUES (?, ?, ?, ?, ?)",
        (ticket["id"], status["id"], agent["id"], reason, old_status_id),
    )
    add_comment(ticket["id"], f"⏳ Queued — {reason} limit reached. Waiting for an agent slot.")


def drain_queue():
    """Process queued agents in FIFO order as limits allow."""
    pending = query_db("SELECT * FROM agent_queue WHERE started_at IS NULL ORDER BY queued_at")
    for q in pending:
        # Bug A fix: Use a 3-table JOIN to get full ticket context (board_name,
        # workflow_name, workflow_id) so the spawned agent has the same context
        # as every other spawn path.
        ticket = query_db(
            """
            SELECT t.*, b.name AS board_name, w.name AS workflow_name, b.workflow_id, w.git_enabled
            FROM tickets t
            JOIN boards b ON t.board_id = b.id
            JOIN workflows w ON b.workflow_id = w.id
            WHERE t.id = ?
        """,
            (q["ticket_id"],),
            one=True,
        )
        if not ticket or ticket["status_id"] != q["status_id"]:
            run_db("DELETE FROM agent_queue WHERE id = ?", (q["id"],))
            continue
        # Skip queued agents that are blocked by a pending gate review —
        # these require human approval and should not be spawned.
        if has_pending_gate_reviews(q["ticket_id"]):
            logger.debug("Drain queue: skipping ticket %d — pending gate review", q["ticket_id"])
            continue
        # Bug 4: Pre-check blocking conditions before deleting queue entry
        question_count = count_unanswered_questions(q["ticket_id"])
        if question_count > 0:
            logger.debug("Drain queue: skipping ticket %d — %d unanswered question(s)", q["ticket_id"], question_count)
            continue
        # Bug 2: Acquire _spawn_lock to prevent race with try_spawn_or_queue
        with _spawn_lock:
            if count_running() >= get_config("max_parallel"):
                break
            if count_hourly() >= get_config("max_per_hour"):
                break
            status = get_status(q["status_id"])
            agent = get_agent(q["agent_id"])
            if status and agent:
                # Bug B fix: Pass old_status_id from queue entry so the
                # spawned agent gets transition context ("Moved from X to Y").
                old_status_id = q["old_status_id"]
                # Bug 1 fix: Use the boolean return value of spawn_agent()
                # instead of checking if an agent_run with status='running'
                # exists — that check is racy because the watcher thread
                # can mark the run completed between spawn_agent() returning
                # and the SELECT executing.
                try:
                    spawned = spawn_agent(row_to_dict(ticket), status, agent, old_status_id=old_status_id)
                except Exception:
                    logger.exception("drain_queue: spawn_agent failed for ticket %d", q["ticket_id"])
                    continue
                if spawned:
                    run_db("DELETE FROM agent_queue WHERE id = ?", (q["id"],))
                # If spawn_agent early-returned (spawned=False), keep the queue entry
            else:
                run_db("DELETE FROM agent_queue WHERE id = ?", (q["id"],))


# ---------------------------------------------------------------------------
# Spawn logic
# ---------------------------------------------------------------------------


def spawn_agent_for_ticket(ticket_id, status_id):
    """Spawn an agent for a newly-created ticket if its status has one.

    Encapsulates the common pattern: get status → check agent_id → get agent →
    query full ticket (with board/workflow joins) → try_spawn_or_queue.
    Used after ticket creation and recurring-task triggers.
    """
    status = get_status(status_id)
    if status and status.get("agent_id"):
        agent = get_agent(status["agent_id"])
        if agent:
            full_ticket = query_db(
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
            if full_ticket:
                try_spawn_or_queue(row_to_dict(full_ticket), status, agent)


def try_spawn_or_queue(ticket, status, agent, old_status_id=None):
    # Bug 2 fix: Clean up any stale queue entries for this ticket before
    # attempting a direct spawn. Without this, an agent spawned directly
    # would leave behind a "Queued" label that persists forever.
    run_db("DELETE FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL", (ticket["id"],))
    # Block agent spawn while gate reviews are pending
    if has_pending_gate_reviews(ticket["id"]):
        logger.info("Skipping agent spawn for ticket %d — pending gate reviews exist", ticket["id"])
        return
    # Block agent spawn while unanswered questions exist
    question_count = count_unanswered_questions(ticket["id"])
    if question_count > 0:
        _add_question_wait_comment(ticket["id"], question_count)
        return
    cleanup_runs()
    with _spawn_lock:
        if count_running() >= get_config("max_parallel"):
            queue_agent(ticket, status, agent, "parallel", old_status_id=old_status_id)
        elif count_hourly() >= get_config("max_per_hour"):
            queue_agent(ticket, status, agent, "rate", old_status_id=old_status_id)
        else:
            spawn_agent(ticket, status, agent, old_status_id=old_status_id)


def spawn_agent(ticket, status, agent, old_status_id=None):
    """Fire-and-forget subprocess running pi CLI for this ticket + status.

    Returns True if an agent_run was created, False if the spawn was skipped
    (e.g. due to unanswered questions).
    """
    ticket_id = ticket["id"]
    # Block spawn if unanswered questions exist
    question_count = count_unanswered_questions(ticket_id)
    if question_count > 0:
        _add_question_wait_comment(ticket_id, question_count)
        return False

    now = datetime.now(UTC)
    board_id = ticket.get("board_id")
    workflow_id = ticket.get("workflow_id")
    board = get_board(board_id) if board_id else None
    board_dir = board["working_directory"] if board else "workspace"
    session_dir = os.path.join(board_dir, ".pi-sessions", str(agent["id"]), f"ticket-{ticket_id}")
    log_dir = os.path.join(board_dir, ".pi-logs", f"ticket-{ticket_id}")

    # ── Git integration ──
    # Look up git_enabled from the workflow and set up a branch if enabled.
    git_enabled = False
    git_info = ""  # injected into agent context when git is enabled
    if ensure_ticket_branch is not None:
        wf_row = query_db("SELECT git_enabled FROM workflows WHERE id = ?", (workflow_id,), one=True)
        if wf_row and wf_row["git_enabled"]:
            git_enabled = True
            branch = ensure_ticket_branch(board_dir, ticket_id, ticket["title"], existing_branch=ticket.get("branch"))
            if branch:
                git_info = f"\nGit: working on branch {branch} in {board_dir}."
                # Protected branch guard — warn the agent
                git_info += (
                    "\nDo NOT push to or modify the default branch (main/master). Commit only on your feature branch."
                )
            else:
                git_info = "\nGit: enabled but no branch could be created (not a git repo or no remote)."
    # Refresh ticket to pick up any branch update from ensure_ticket_branch
    if git_enabled:
        refreshed = query_db("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
        if refreshed:
            ticket = row_to_dict(refreshed)

    Path(session_dir).mkdir(parents=True, exist_ok=True)
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    last_spawned = ticket.get("agent_last_spawned_at")
    is_warm = False
    if os.path.isdir(session_dir) and last_spawned is not None:
        if isinstance(last_spawned, str):
            last_spawned = datetime.fromisoformat(last_spawned.replace("Z", "+00:00"))
            if last_spawned.tzinfo is None:
                last_spawned = last_spawned.replace(tzinfo=UTC)
        elapsed = (now - last_spawned).total_seconds()
        is_warm = elapsed < get_config("warm_spawn_threshold")

    transitions = get_transitions_from(status["id"])
    transition_parts = []
    has_gates = False
    for tr in transitions:
        instr = (tr.get("instructions") or "").strip()
        part = f'→ status_id={tr["to_status_id"]} "{tr["to_status_name"]}"'
        if instr:
            part += f" — {instr}"
        dest_gates = get_quality_gates(status["id"], tr["to_status_id"])
        if dest_gates:
            has_gates = True
            part += " ⚠️ Gate required; stop if blocked."
        transition_parts.append(part)
    transitions_line = (
        "Next status you MUST set (pick exactly one):\n" + "\n".join(transition_parts) if transition_parts else ""
    )

    status_goal = (status.get("goal") or "").strip()
    goal_line = f"{status['name']} — {status_goal}" if status_goal else status["name"]

    status_changed = old_status_id is not None and old_status_id != status["id"]

    comments = get_comments(ticket_id)
    all_comments_lines = []
    for c in comments:
        all_comments_lines.append(f"- [{c['created_at']}] {c['body']}")
    all_comments_block = "\n".join(all_comments_lines) if all_comments_lines else "(no comments yet)"

    board_ctx = f"Board: {ticket.get('board_name', 'Unknown')} (board_id={board_id})" if board_id else ""

    # Resolve the agent's selected API endpoints (NULL → default 3)
    endpoint_keys_raw = agent.get("api_endpoints")
    if endpoint_keys_raw:
        try:
            selected_keys = json.loads(endpoint_keys_raw)
        except (ValueError, TypeError):
            selected_keys = None
    else:
        selected_keys = None
    api_docs = build_api_docs(
        selected_keys,
        ticket_id,
        base_url=get_config("pi_cowork_url"),
        has_gates=has_gates,
        board_id=board_id,
        workflow_id=workflow_id,
    )

    # ── Knowledge context injection ──
    # Inject auto_context entries relevant to this board into the agent prompt.
    from pi_cowork.models import get_auto_context_entries

    knowledge_entries = get_auto_context_entries(board_id=board_id)
    knowledge_block = ""
    if knowledge_entries:
        lines = ["Knowledge entries (use GET /api/knowledge/{id} for full content):"]
        for ke in knowledge_entries:
            scope = f"Board: {ke['board_name']}" if ke.get("board_id") else "Global"
            preview = (ke["content"] or "")[:150].replace("\n", " ")
            if len(ke.get("content") or "") > 150:
                preview += "..."
            lines.append(f"- [{ke['id']}] {ke['title']} ({scope}): {preview}")
        knowledge_block = "\n".join(lines)

    if transitions_line:
        done_instruction = "When done: first add a comment to the ticket summarizing what you did, then update the ticket status to exactly one of the statuses listed above (or leave it where it is if you asked questions via the questions endpoint)."
    else:
        done_instruction = "When done: add a comment to the ticket summarizing what you did, then you're finished."

    if is_warm:
        new_comment_lines = []
        if last_spawned is not None:
            for c in comments:
                c_time = c.get("created_at")
                if c_time and isinstance(c_time, str):
                    c_time_dt = datetime.fromisoformat(c_time.replace("Z", "+00:00"))
                    if c_time_dt.tzinfo is None:
                        c_time_dt = c_time_dt.replace(tzinfo=UTC)
                else:
                    c_time_dt = None
                if c_time_dt is None or c_time_dt > last_spawned:
                    new_comment_lines.append(f"- [{c['created_at']}] {c['body']}")
        new_comments_block = "\n".join(new_comment_lines) if new_comment_lines else "(none)"

        if status_changed:
            old_status = query_db("SELECT name FROM statuses WHERE id = ?", (old_status_id,), one=True)
            change_line = f'Moved from "{old_status["name"]}" to "{status["name"]}".'
            goal_instruction = (
                f"This is a new prompt, forget the goals you had from previous prompts.\nYour goal: {goal_line}"
            )
        else:
            change_line = f'Still in "{status["name"]}".'
            goal_instruction = f"Continue your goal: {goal_line}"

        context_msg = f"""[Update] Ticket #{ticket_id}: {ticket["title"]}
{board_ctx}{git_info}
{change_line}

New comments since last update:
{new_comments_block}

API:
{api_docs}
{knowledge_block}
{goal_instruction}
{transitions_line}
{done_instruction}"""
    else:
        # Cold spawn: first time agent sees this ticket (or session expired).
        # If old_status_id is provided (e.g. from queue), include transition context
        # even though this is a fresh prompt — the agent needs to know what happened.
        change_note = ""
        if status_changed and old_status_id is not None:
            old_status = query_db("SELECT name FROM statuses WHERE id = ?", (old_status_id,), one=True)
            if old_status:
                change_note = f'\nNote: This ticket was moved from "{old_status["name"]}" to "{status["name"]}" before you were spawned.\n'
        context_msg = f"""Ticket #{ticket_id}: {ticket["title"]}
{board_ctx}{git_info}{change_note}\nDescription:
{ticket["body"] or "(no description)"}\nComments:
{all_comments_block}\nAPI:
{api_docs}\n{knowledge_block}\nThis is a new prompt, forget the goals you had from previous prompts.
Your goal: {goal_line}
{transitions_line}
{done_instruction}"""

    system_prompt = f"""{agent["description"]}

Your task and allowed actions change with each prompt. Always follow the instructions at the end of the prompt, not your general expertise.
After completing your task, write a comment on the ticket summarizing what you did."""

    # Inject board long-term vision if present
    if board and board.get("long_term_vision"):
        system_prompt += f"\n\nBoard Long-Term Vision: {board['long_term_vision']}"

    # Resolve effective model/thinking with precedence: ticket override > status > agent > default
    from pi_cowork.models import get_ticket_status_override

    ticket_override = get_ticket_status_override(ticket_id, status["id"])
    if ticket_override and ticket_override.get("model") and ticket_override["model"].strip():
        effective_model = ticket_override["model"].strip()
    elif status.get("model") and status["model"].strip():
        effective_model = status["model"].strip()
    else:
        effective_model = agent.get("model")

    if ticket_override and ticket_override.get("thinking") and ticket_override["thinking"].strip():
        effective_thinking = ticket_override["thinking"].strip()
    elif status.get("thinking") and status["thinking"].strip():
        effective_thinking = status["thinking"].strip()
    else:
        effective_thinking = agent.get("thinking")

    cmd = [
        "pi",
        "--system-prompt",
        system_prompt,
        "--print",
        "--session-dir",
        session_dir,
    ]
    if effective_thinking:
        cmd += ["--thinking", effective_thinking]
    if effective_model:
        cmd += ["--model", effective_model]
    cmd += [context_msg]

    db = get_db()
    cur = db.execute(
        "INSERT INTO agent_runs (ticket_id, agent_id, status_id, started_at, status) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, agent["id"], status["id"], now.isoformat(), "running"),
    )
    db.commit()
    run_id = cur.lastrowid
    log_path = os.path.join(log_dir, f"run-{run_id}.log")
    db.execute("UPDATE agent_runs SET log_path = ? WHERE id = ?", (log_path, run_id))
    db.commit()

    log_f = open(log_path, "w")
    log_f.write(f"=== SYSTEM PROMPT ===\n{system_prompt}\n\n")
    log_f.write(f"=== CONTEXT MESSAGE ===\n{context_msg}\n\n")
    log_f.write("=== AGENT OUTPUT ===\n")
    log_f.flush()

    try:
        proc = subprocess.Popen(
            cmd, cwd=board_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True
        )
        db.execute("UPDATE agent_runs SET pid = ? WHERE id = ?", (proc.pid, run_id))
        db.commit()
        run_db("UPDATE tickets SET agent_last_spawned_at = ? WHERE id = ?", (now.isoformat(), ticket_id))
        add_comment(
            ticket_id,
            f"🤖 Agent '{agent['name']}' {'resumed' if is_warm else 'started'} for status '{status['name']}'.",
        )
        _start_log_reader(proc.stdout, log_f)
        _start_watcher(proc, run_id, ticket_id, agent["name"], log_f)
        bus.publish(AGENT_SPAWNED, ticket_id=ticket_id, agent_name=agent["name"], run_id=run_id)
        return True
    except Exception as e:
        error_text = f"⚠️ Failed to spawn agent '{agent['name']}': {e}\n"
        try:
            log_f.write(error_text)
            log_f.close()
        except (ValueError, OSError):
            pass
        db.execute("UPDATE agent_runs SET status = 'failed', pid = NULL WHERE id = ?", (run_id,))
        db.commit()
        add_comment(ticket_id, f"⚠️ Failed to spawn agent '{agent['name']}': {e}")
        # Agent run record exists (status=failed), so from the caller's perspective
        # the spawn did create a record. Return True so the queue entry is consumed.
        return True


# ---------------------------------------------------------------------------
# Background queue drain
# ---------------------------------------------------------------------------


def _drain_loop(app):
    """Background loop: periodically clean up runs and drain the queue."""
    _last_log_cleanup = time.time()
    _last_event_log_cleanup = time.time()
    _last_dismissal_cleanup = time.time()
    _last_recurring_check = 0  # track 60s interval for recurring tasks
    while True:
        try:
            with app.app_context():
                cleanup_runs()
                drain_queue()
                # Recurring tasks: check every 60 seconds
                if time.time() - _last_recurring_check >= 60:
                    from pi_cowork.models import process_recurring_tasks

                    process_recurring_tasks()
                    _last_recurring_check = time.time()
                # Log rotation: run once per day (86400 seconds)
                if time.time() - _last_log_cleanup >= 86400:
                    from pi_cowork.system_logs import cleanup_old_logs

                    cleanup_old_logs()
                    _last_log_cleanup = time.time()
                # Event log rotation: run once per day (86400 seconds)
                if time.time() - _last_event_log_cleanup >= 86400:
                    from pi_cowork.event_log import cleanup_old_event_logs

                    cleanup_old_event_logs()
                    _last_event_log_cleanup = time.time()
                # Notification dismissals cleanup: run once per day (86400 seconds)
                if time.time() - _last_dismissal_cleanup >= 86400:
                    from pi_cowork.models import cleanup_old_notification_dismissals

                    cleanup_old_notification_dismissals()
                    _last_dismissal_cleanup = time.time()
        except Exception:
            logger.exception("Error in drain loop, will retry")
        time.sleep(10)


def register_background_tasks(app):
    """Register the before-request hook that starts the background drain loop."""
    global _drain_app
    _drain_app = app
    started = getattr(app, "_drain_started", False) or app.config.get("TESTING")
    if not started:
        app._drain_started = True
        t = threading.Thread(target=_drain_loop, args=(app,), daemon=True)
        t.start()


def _event_drain_handler(event_name=None, **kwargs):
    """Event handler: trigger drain_queue on agent completion/failure for near-instant processing."""
    if _drain_app is None:
        return
    try:
        with _drain_app.app_context():
            drain_queue()
    except Exception:
        logger.exception("Error in event-driven drain handler")


bus.subscribe(AGENT_COMPLETED, _event_drain_handler)
bus.subscribe(AGENT_FAILED, _event_drain_handler)
