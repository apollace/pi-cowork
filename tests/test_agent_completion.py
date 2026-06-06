"""Tests for the improved agent completion mechanism:
- Watcher thread updates DB on process exit
- _is_our_process guards against PID recycling
- cleanup_runs uses cmdline verification
- exit_code is recorded
- Stale runs are still completed as fallback
"""

import json
import threading
from unittest.mock import MagicMock, patch


def test_watcher_thread_updates_db_on_success(client, default_workflow, default_board):
    """When the watcher thread sees exit code 0, it marks the run completed."""
    import app as app_module

    agent = client.post(
        "/api/agents",
        json={
            "name": "WatcherAgent",
            "description": "You are a watcher test agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "WatcherStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Watcher Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Create a real-ish fake proc that wait() returns 0
    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.return_value = 0

    watched_event = threading.Event()

    _ = app_module._start_watcher

    def tracking_watcher(proc, run_id, ticket_id, agent_name, log_f):
        # Run the real _watch_agent synchronously for test determinism
        app_module._watch_agent(proc, run_id, ticket_id, agent_name, log_f)
        watched_event.set()

    with (
        patch("app.subprocess.Popen", return_value=fake_proc),
        patch("pi_cowork.agents._start_watcher", side_effect=tracking_watcher),
    ):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Wait for the watcher to finish
    assert watched_event.wait(timeout=5)

    # Verify the run is marked completed with exit_code 0
    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        run = db.execute("SELECT status, exit_code FROM agent_runs WHERE ticket_id = ?", (tid,)).fetchone()
        assert dict(run)["status"] == "completed"
        assert dict(run)["exit_code"] == 0


def test_watcher_thread_marks_failed_on_nonzero_exit(client, default_workflow, default_board):
    """When the watcher thread sees a non-zero exit code, it marks the run failed."""
    import app as app_module

    agent = client.post(
        "/api/agents",
        json={
            "name": "FailAgent",
            "description": "You are a fail test agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "FailStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Fail Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    fake_proc = MagicMock(pid=12345)
    fake_proc.wait.return_value = 1

    watched_event = threading.Event()

    def tracking_watcher(proc, run_id, ticket_id, agent_name, log_f):
        app_module._watch_agent(proc, run_id, ticket_id, agent_name, log_f)
        watched_event.set()

    with (
        patch("app.subprocess.Popen", return_value=fake_proc),
        patch("pi_cowork.agents._start_watcher", side_effect=tracking_watcher),
    ):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    assert watched_event.wait(timeout=5)

    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        run = db.execute("SELECT status, exit_code FROM agent_runs WHERE ticket_id = ?", (tid,)).fetchone()
        row = dict(run)
        assert row["status"] == "failed"
        assert row["exit_code"] == 1

    # Should also have a comment about the failure
    comments = client.get(f"/api/tickets/{tid}/comments")
    comment_data = json.loads(comments.data)
    assert any("exited with code 1" in c["body"] for c in comment_data)


def test_is_our_process_detects_recycled_pid(client):
    """_is_our_process returns False when PID exists but isn't a pi process."""
    # Use current process PID — it's not a pi process
    import os

    from pi_cowork.agents import _is_our_process

    current_pid = os.getpid()
    assert _is_our_process(current_pid) is False


def test_is_our_process_returns_false_for_nonexistent_pid(client):
    """_is_our_process returns False when PID doesn't exist."""
    from pi_cowork.agents import _is_our_process

    # Very high PID that almost certainly doesn't exist
    assert _is_our_process(9999999) is False


def test_cleanup_uses_is_our_process(client, default_workflow, default_board):
    """cleanup_runs uses _is_our_process instead of just os.kill to avoid PID recycling."""
    import app as app_module

    agent = client.post(
        "/api/agents",
        json={
            "name": "CleanupAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "CleanupStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Cleanup Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Spawn agent with fake PID
    with (
        patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
        patch("pi_cowork.agents._is_our_process", return_value=True),
    ):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # PID exists but is NOT our process -> should mark completed
    with patch("pi_cowork.agents._is_our_process", return_value=False), client.application.app_context():
        app_module.cleanup_runs()

    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        run = db.execute("SELECT status, exit_code FROM agent_runs WHERE ticket_id = ?", (tid,)).fetchone()
        row = dict(run)
        assert row["status"] == "completed"
        assert row["exit_code"] == -1  # sentinel for "PID recycled or gone"


def test_cleanup_marks_null_pid_as_failed(client, default_workflow, default_board):
    """cleanup_runs marks runs with no PID as failed (process never started)."""
    import app as app_module

    agent = client.post(
        "/api/agents",
        json={
            "name": "NullPidAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "NullPidStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    _ = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "NullPid Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Manually insert a running run with no PID
    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        db.execute(
            (
                "INSERT INTO agent_runs (ticket_id, agent_id, pid, started_at, status) "
                "VALUES (?, ?, NULL, datetime('now'), 'running')"
            ),
            (tid, aid),
        )
        db.commit()

    with client.application.app_context():
        app_module.cleanup_runs()

    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        run = db.execute("SELECT status FROM agent_runs WHERE ticket_id = ? AND pid IS NULL", (tid,)).fetchone()
        assert dict(run)["status"] == "failed"


def test_cleanup_stale_run(client, default_workflow, default_board):
    """cleanup_runs marks runs older than RUN_MAX_AGE_SECONDS as completed."""

    import app as app_module

    agent = client.post(
        "/api/agents",
        json={
            "name": "StaleAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "StaleStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Stale Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Spawn agent with fake PID
    with (
        patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
        patch("pi_cowork.agents._is_our_process", return_value=True),
    ):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Set started_at to 3 hours ago (beyond RUN_MAX_AGE_SECONDS = 7200s)
    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        db.execute("UPDATE agent_runs SET started_at = datetime('now', '-3 hours') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Even though _is_our_process says True, stale check should complete it
    with patch("pi_cowork.agents._is_our_process", return_value=True), client.application.app_context():
        app_module.cleanup_runs()

    with client.application.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        run = db.execute("SELECT status FROM agent_runs WHERE ticket_id = ?", (tid,)).fetchone()
        assert dict(run)["status"] == "completed"
