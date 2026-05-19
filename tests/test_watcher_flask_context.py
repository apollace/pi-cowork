"""Regression tests for ticket #40: Agent runs stuck as "running" forever.

The root cause was that ``_watch_agent()`` runs in a daemon thread with no
Flask application context.  Two problems:
1. ``_get_db_for_watcher()`` used ``current_app.config.get()`` which raises
   ``RuntimeError: Working outside of application context`` in a daemon thread.
2. ``bus.publish(AGENT_COMPLETED/AGENT_FAILED)`` triggers ``_audit_subscriber``
   which calls ``get_db()`` — also needs a Flask context.

These tests verify the fix by calling ``_watch_agent`` from a thread that
does *not* have a Flask request context, simulating the real production path.
"""
import json
import threading
from unittest.mock import patch, MagicMock

from pi_cowork import config
from pi_cowork.agents import _watch_agent, _start_watcher, _drain_app


def _setup_agent_and_ticket(client, default_workflow, default_board, name_prefix="CtxAgent"):
    """Helper: create an agent, status, and ticket; return (agent_id, status_id, ticket_id)."""
    agent = client.post('/api/agents', json={
        'name': name_prefix,
        'description': 'You are a test agent.',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': f'{name_prefix}Stage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(s1.data)['id']

    ticket = client.post('/api/tickets', json={
        'title': f'{name_prefix} Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(ticket.data)['id']
    return aid, sid, tid


def test_watcher_in_daemon_thread_without_request_context(client, default_workflow, default_board):
    """Regression: _watch_agent must work when called from a daemon thread
    (no Flask request context). This was the core bug — current_app raised
    RuntimeError inside the watcher thread."""
    # Set up agent, status, ticket, and create a running agent run
    aid, sid, tid = _setup_agent_and_ticket(client, default_workflow, default_board, "DaemonCtx")

    # Create a run entry directly in the DB
    with client.application.app_context():
        from pi_cowork.db import get_db
        from datetime import datetime, timezone
        db = get_db()
        cur = db.execute(
            "INSERT INTO agent_runs (ticket_id, agent_id, started_at, status) VALUES (?, ?, ?, ?)",
            (tid, aid, datetime.now(timezone.utc).isoformat(), 'running')
        )
        db.commit()
        run_id = cur.lastrowid

    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.return_value = 0

    # Create a fake log file for the watcher's log_f argument
    import tempfile, os
    log_fd, log_path = tempfile.mkstemp(suffix='.log')
    log_f = open(log_path, 'w')

    # Run _watch_agent in a daemon thread (simulating the real production path)
    result = {'completed': threading.Event(), 'exception': None}

    def run_watcher():
        try:
            _watch_agent(fake_proc, run_id, tid, 'DaemonCtx', log_f)
        except Exception as e:
            result['exception'] = e
        finally:
            result['completed'].set()

    t = threading.Thread(target=run_watcher, daemon=True)
    t.start()

    # Wait for watcher to finish (with timeout for safety)
    assert result['completed'].wait(timeout=10), "Watcher thread did not complete"
    assert result['exception'] is None, f"Watcher thread raised exception: {result['exception']}"

    # Verify the run is marked completed with exit_code 0
    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        run = db.execute(
            "SELECT status, exit_code FROM agent_runs WHERE id = ?",
            (run_id,)
        ).fetchone()
        row = dict(run)
        assert row['status'] == 'completed', f"Expected 'completed', got '{row['status']}'"
        assert row['exit_code'] == 0

    # Clean up temp file
    log_f.close()
    os.unlink(log_path)


def test_watcher_in_daemon_thread_marks_failed_on_nonzero_exit(client, default_workflow, default_board):
    """Regression: _watch_agent in a daemon thread must publish AGENT_FAILED
    event and mark the run as failed when exit code is non-zero."""
    aid, sid, tid = _setup_agent_and_ticket(client, default_workflow, default_board, "DaemonFail")

    with client.application.app_context():
        from pi_cowork.db import get_db
        from datetime import datetime, timezone
        db = get_db()
        cur = db.execute(
            "INSERT INTO agent_runs (ticket_id, agent_id, started_at, status) VALUES (?, ?, ?, ?)",
            (tid, aid, datetime.now(timezone.utc).isoformat(), 'running')
        )
        db.commit()
        run_id = cur.lastrowid

    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.return_value = 1

    import tempfile, os
    log_fd, log_path = tempfile.mkstemp(suffix='.log')
    log_f = open(log_path, 'w')

    result = {'completed': threading.Event(), 'exception': None}

    def run_watcher():
        try:
            _watch_agent(fake_proc, run_id, tid, 'DaemonFail', log_f)
        except Exception as e:
            result['exception'] = e
        finally:
            result['completed'].set()

    t = threading.Thread(target=run_watcher, daemon=True)
    t.start()

    assert result['completed'].wait(timeout=10), "Watcher thread did not complete"
    assert result['exception'] is None, f"Watcher thread raised exception: {result['exception']}"

    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        run = db.execute(
            "SELECT status, exit_code FROM agent_runs WHERE id = ?",
            (run_id,)
        ).fetchone()
        row = dict(run)
        assert row['status'] == 'failed'
        assert row['exit_code'] == 1

    # Verify failure comment was added
    comments = client.get(f'/api/tickets/{tid}/comments')
    comment_data = json.loads(comments.data)
    assert any('exited with code 1' in c['body'] for c in comment_data)

    # Verify audit event was logged
    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        events = db.execute(
            "SELECT event_name FROM event_log WHERE event_name = ?",
            ('agent.failed',)
        ).fetchall()
        assert len(events) > 0, "Expected agent.failed event in event_log"

    log_f.close()
    os.unlink(log_path)


def test_watcher_in_daemon_thread_publishes_completed_event(client, default_workflow, default_board):
    """Regression: _watch_agent in a daemon thread must publish AGENT_COMPLETED
    event so that audit log and event-driven drain queue processing work."""
    aid, sid, tid = _setup_agent_and_ticket(client, default_workflow, default_board, "DaemonEvt")

    with client.application.app_context():
        from pi_cowork.db import get_db
        from datetime import datetime, timezone
        db = get_db()
        cur = db.execute(
            "INSERT INTO agent_runs (ticket_id, agent_id, started_at, status) VALUES (?, ?, ?, ?)",
            (tid, aid, datetime.now(timezone.utc).isoformat(), 'running')
        )
        db.commit()
        run_id = cur.lastrowid

    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.return_value = 0

    import tempfile, os
    log_fd, log_path = tempfile.mkstemp(suffix='.log')
    log_f = open(log_path, 'w')

    result = {'completed': threading.Event(), 'exception': None}

    def run_watcher():
        try:
            _watch_agent(fake_proc, run_id, tid, 'DaemonEvt', log_f)
        except Exception as e:
            result['exception'] = e
        finally:
            result['completed'].set()

    t = threading.Thread(target=run_watcher, daemon=True)
    t.start()

    assert result['completed'].wait(timeout=10), "Watcher thread did not complete"
    assert result['exception'] is None, f"Watcher thread raised exception: {result['exception']}"

    # Verify AGENT_COMPLETED event was logged (audit subscriber works)
    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        events = db.execute(
            "SELECT event_name, payload FROM event_log WHERE event_name = ?",
            ('agent.completed',)
        ).fetchall()
        assert len(events) > 0, "Expected agent.completed event in event_log"

    log_f.close()
    os.unlink(log_path)


def test_watcher_exception_still_marks_failed_in_daemon_thread(client, default_workflow, default_board):
    """Regression: if an exception occurs in _watch_agent (e.g., proc.wait()
    raises), the watcher should still mark the run as 'failed' in the DB."""
    aid, sid, tid = _setup_agent_and_ticket(client, default_workflow, default_board, "DaemonExc")

    with client.application.app_context():
        from pi_cowork.db import get_db
        from datetime import datetime, timezone
        db = get_db()
        cur = db.execute(
            "INSERT INTO agent_runs (ticket_id, agent_id, started_at, status) VALUES (?, ?, ?, ?)",
            (tid, aid, datetime.now(timezone.utc).isoformat(), 'running')
        )
        db.commit()
        run_id = cur.lastrowid

    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.side_effect = OSError("Process vanished")

    import tempfile, os
    log_fd, log_path = tempfile.mkstemp(suffix='.log')
    log_f = open(log_path, 'w')

    result = {'completed': threading.Event(), 'exception': None}

    def run_watcher():
        try:
            _watch_agent(fake_proc, run_id, tid, 'DaemonExc', log_f)
        except Exception as e:
            result['exception'] = e
        finally:
            result['completed'].set()

    t = threading.Thread(target=run_watcher, daemon=True)
    t.start()

    assert result['completed'].wait(timeout=10), "Watcher thread did not complete"
    # The exception is caught internally, shouldn't propagate
    assert result['exception'] is None, f"Watcher thread should have caught exception, got: {result['exception']}"

    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        run = db.execute(
            "SELECT status FROM agent_runs WHERE id = ?",
            (run_id,)
        ).fetchone()
        assert dict(run)['status'] == 'failed'

    log_f.close()
    os.unlink(log_path)