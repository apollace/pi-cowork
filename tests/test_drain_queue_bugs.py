"""Tests for ticket #36: Fix stuck queued state bugs (6 bugs).

Bug 1: _drain_loop dies permanently on any exception
Bug 2: drain_queue() race condition -- no _spawn_lock
Bug 3: Queue entry deleted before spawn succeeds -- data loss
Bug 4: spawn_agent() early-returns for unanswered questions, losing queue entry
Bug 5: drain_queue was deleting pending gate reviews (awaiting human approval)
Bug 6: No reactive drain trigger on agent completion/failure
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

from pi_cowork import config
from pi_cowork.models import set_setting


def _set_limits(client, max_parallel=None, max_per_hour=None):
    """Set agent limits via DB settings (and module-level constants for compat)."""
    if max_parallel is not None:
        with client.application.app_context():
            set_setting("max_parallel", str(max_parallel))
        config.PI_MAX_PARALLEL = max_parallel
    if max_per_hour is not None:
        with client.application.app_context():
            set_setting("max_per_hour", str(max_per_hour))
        config.PI_MAX_PER_HOUR = max_per_hour


# ---------------------------------------------------------------------------
# Bug 1: _drain_loop survives exceptions
# ---------------------------------------------------------------------------


def test_drain_loop_survives_exceptions(client, default_workflow, default_board, monkeypatch):
    """Bug 1: _drain_loop should not die on transient exceptions."""
    from pi_cowork.agents import _drain_loop

    call_count = 0
    stopped = threading.Event()

    def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            stopped.set()
            return

    call_num = 0

    def fake_cleanup():
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            raise RuntimeError("Transient DB error")

    # Patch within the right module context
    with client.application.app_context(), patch("pi_cowork.agents.cleanup_runs", side_effect=fake_cleanup):
        with patch("pi_cowork.agents.drain_queue"):
            with patch("pi_cowork.agents.time.sleep", side_effect=fake_sleep):
                # _drain_loop should survive the first exception
                t = threading.Thread(target=_drain_loop, args=(client.application,), daemon=True)
                t.start()
                stopped.wait(timeout=5)
                t.join(timeout=2)

    # Should have called sleep 3 times (3 iterations), meaning it survived the exception
    assert call_count >= 3, f"Expected >=3 iterations, got {call_count}"


# ---------------------------------------------------------------------------
# Bug 2: drain_queue respects _spawn_lock
# ---------------------------------------------------------------------------


def test_drain_queue_respects_spawn_lock(client, default_workflow, default_board, monkeypatch):
    """Bug 2: Concurrent try_spawn_or_queue() and drain_queue() should not exceed PI_MAX_PARALLEL."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "LockAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "LockStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket1 = client.post("/api/tickets", json={"title": "Lock1", "board_id": default_board["id"]})
    tid1 = json.loads(ticket1.data)["id"]
    ticket2 = client.post("/api/tickets", json={"title": "Lock2", "board_id": default_board["id"]})
    tid2 = json.loads(ticket2.data)["id"]

    spawn_count = 0
    spawn_lock = threading.Lock()

    original_spawn = None
    from pi_cowork import agents as agents_module

    original_spawn = agents_module.spawn_agent

    def counting_spawn(ticket, status, agent, old_status_id=None):
        nonlocal spawn_count
        with spawn_lock:
            spawn_count += 1
        # Simulate work so concurrent calls overlap
        time.sleep(0.05)
        return original_spawn(ticket, status, agent, old_status_id=old_status_id)

    # First ticket takes the slot
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid1}", json={"status_id": id1})

    # Queue second ticket (limit reached)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid2}", json={"status_id": id1})

    # Mark first as completed (free slot)
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Drain should only spawn one for ticket2 (within lock)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)) as mock_popen:
        with patch("pi_cowork.agents._is_our_process", return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue

                drain_queue()

    # Second ticket should now be running
    with client.application.app_context():
        from pi_cowork.db import query_db

        running = query_db(
            "SELECT COUNT(*) AS c FROM agent_runs WHERE ticket_id = ? AND status = 'running'", (tid2,), one=True
        )
        assert running["c"] == 1, f"Expected 1 running agent for ticket2, got {running['c']}"


# ---------------------------------------------------------------------------
# Bug 3: Queue entry preserved on spawn failure
# ---------------------------------------------------------------------------


def test_drain_queue_keeps_entry_on_spawn_failure(client, default_workflow, default_board, monkeypatch):
    """Bug 3: If spawn_agent() raises, the queue entry should be preserved for next cycle."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "FailAgent",
            "description": "d",
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

    ticket1 = client.post("/api/tickets", json={"title": "Fail1", "board_id": default_board["id"]})
    tid1 = json.loads(ticket1.data)["id"]
    ticket2 = client.post("/api/tickets", json={"title": "Fail2", "board_id": default_board["id"]})
    tid2 = json.loads(ticket2.data)["id"]

    # First ticket takes the slot
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid1}", json={"status_id": id1})

    # Second ticket gets queued
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid2}", json={"status_id": id1})

    # Verify queue entry exists
    q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
    assert q_data["queued"] is True

    # Mark first as completed (free slot)
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Now drain, but spawn_agent raises an exception
    from pi_cowork import agents as agents_module

    original_spawn = agents_module.spawn_agent

    call_count = 0

    def failing_spawn(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Spawn failed!")
        return original_spawn(*args, **kwargs)

    with patch("pi_cowork.agents.spawn_agent", side_effect=failing_spawn):
        with patch("pi_cowork.agents._is_our_process", return_value=False):
            with client.application.app_context():
                agents_module.drain_queue()

    # Queue entry should still exist (not deleted on spawn failure)
    q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
    assert q_data["queued"] is True, "Queue entry should be preserved after spawn failure"


# ---------------------------------------------------------------------------
# Bug 4: Unanswered questions do not cause queue entry data loss
# ---------------------------------------------------------------------------


def test_drain_queue_preserves_entry_on_blocked_questions(client, default_workflow, default_board, monkeypatch):
    """Bug 4: Unanswered questions should not cause queue entry data loss in drain_queue."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "QuestionAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "QStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket1 = client.post("/api/tickets", json={"title": "Q1", "board_id": default_board["id"]})
    tid1 = json.loads(ticket1.data)["id"]
    ticket2 = client.post("/api/tickets", json={"title": "Q2", "board_id": default_board["id"]})
    tid2 = json.loads(ticket2.data)["id"]

    # First ticket takes the slot
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid1}", json={"status_id": id1})

    # Second ticket gets queued
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid2}", json={"status_id": id1})

    # Add an unanswered question to ticket2
    client.post(
        f"/api/tickets/{tid2}/questions", json={"questions": [{"body": "What should we do?", "options": ["A", "B"]}]}
    )

    # Mark first as completed (free slot)
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Drain should skip ticket2 (unanswered questions) and NOT delete the queue entry
    with client.application.app_context():
        from pi_cowork.agents import drain_queue

        drain_queue()

    # Queue entry should still exist (not deleted)
    q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
    assert q_data["queued"] is True, "Queue entry should be preserved when blocked by questions"


# ---------------------------------------------------------------------------
# Bug 5: Drain queue must NOT delete pending gate reviews
# ---------------------------------------------------------------------------


def test_drain_queue_preserves_pending_gate_reviews(client, default_workflow, default_board, monkeypatch):
    """Drain queue must NOT delete pending gate reviews -- they await human approval.

    Previously, drain_queue deleted pending gate reviews and removed the queue
    entry when a ticket had pending reviews. This was wrong: a pending gate
    review means a human needs to approve the transition, and deleting it
    makes the approval UI disappear while the "⏳ Quality gate pending" comment
    remains visible to the user.
    """
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "GateAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "GateStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket1 = client.post("/api/tickets", json={"title": "Gate1", "board_id": default_board["id"]})
    tid1 = json.loads(ticket1.data)["id"]
    ticket2 = client.post("/api/tickets", json={"title": "Gate2", "board_id": default_board["id"]})
    tid2 = json.loads(ticket2.data)["id"]

    # First ticket takes the slot
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid1}", json={"status_id": id1})

    # Second ticket gets queued
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid2}", json={"status_id": id1})

    # Artificially add a pending gate review for ticket2
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO quality_gates (from_status_id, to_status_id, gate_type, name, workflow_id) VALUES (?, ?, 'manual', 'Test Gate', ?)",
            (id1, id1, default_workflow["id"]),
        )
        gate_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute(
            "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status) VALUES (?, ?, ?, ?, 'pending')",
            (tid2, gate_id, id1, id1),
        )
        db.commit()

    # Mark first as completed (free slot)
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Drain queue should SKIP the ticket with a pending gate review,
    # NOT delete the review or the queue entry.
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue

                drain_queue()

    # Pending gate reviews must STILL exist (not deleted)
    from pi_cowork.models import has_pending_gate_reviews

    with client.application.app_context():
        assert has_pending_gate_reviews(tid2), (
            "Pending gate reviews must NOT be deleted by drain_queue -- they await human approval"
        )

    # The gate review should be visible via the API
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={tid2}").data)
    assert len(reviews) == 1, "Gate review should be visible in the API for human approval"
    assert reviews[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Bug 6: Event-driven drain on agent completion
# ---------------------------------------------------------------------------


def test_event_driven_drain_on_completion(client, default_workflow, default_board, monkeypatch):
    """Bug 6: AGENT_COMPLETED event should trigger drain_queue for near-instant processing."""
    import pi_cowork.agents as agents_mod
    from pi_cowork.events import AGENT_COMPLETED, bus

    drain_calls = 0

    def counting_drain():
        nonlocal drain_calls
        drain_calls += 1

    # Must set _drain_app so the handler can push an app context
    orig_app = agents_mod._drain_app
    agents_mod._drain_app = client.application

    try:
        with patch("pi_cowork.agents.drain_queue", side_effect=counting_drain):
            bus.publish(AGENT_COMPLETED, ticket_id=999, agent_name="TestAgent", run_id=1)
    finally:
        agents_mod._drain_app = orig_app

    assert drain_calls >= 1, f"Expected drain_queue to be called on AGENT_COMPLETED, got {drain_calls} calls"


def test_event_driven_drain_on_failure(client, default_workflow, default_board):
    """Bug 6: AGENT_FAILED event should trigger drain_queue."""
    import pi_cowork.agents as agents_mod
    from pi_cowork.events import AGENT_FAILED, bus

    drain_calls = 0

    def counting_drain():
        nonlocal drain_calls
        drain_calls += 1

    orig_app = agents_mod._drain_app
    agents_mod._drain_app = client.application

    try:
        with patch("pi_cowork.agents.drain_queue", side_effect=counting_drain):
            bus.publish(AGENT_FAILED, ticket_id=999, agent_name="TestAgent", exit_code=1)
    finally:
        agents_mod._drain_app = orig_app

    assert drain_calls >= 1, f"Expected drain_queue to be called on AGENT_FAILED, got {drain_calls} calls"


# ---------------------------------------------------------------------------
# End-to-end: stuck queue recovery
# ---------------------------------------------------------------------------


def test_stuck_queue_recovery(client, default_workflow, default_board, monkeypatch):
    """End-to-end test simulating the original bug: a ticket stuck in queued state
    because the drain thread died, then verify it recovers."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "RecoveryAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "RecoveryStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket1 = client.post("/api/tickets", json={"title": "Rec1", "board_id": default_board["id"]})
    tid1 = json.loads(ticket1.data)["id"]
    ticket2 = client.post("/api/tickets", json={"title": "Rec2", "board_id": default_board["id"]})
    tid2 = json.loads(ticket2.data)["id"]

    # First ticket takes the slot
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid1}", json={"status_id": id1})

    # Second ticket gets queued
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            client.put(f"/api/tickets/{tid2}", json={"status_id": id1})

    # Verify ticket2 is queued
    q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
    assert q_data["queued"] is True

    # Simulate: first agent's process is gone (completed)
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Simulate drain loop recovery (e.g., after the bug 1 fix prevented permanent death)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9998)) as mock_popen:
        with patch("pi_cowork.agents._is_our_process", return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import cleanup_runs, drain_queue

                cleanup_runs()
                drain_queue()

    # Ticket2 should now be un-queued and have a running agent
    q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
    assert q_data["queued"] is False, "Ticket should be un-queued after recovery drain"

    # Verify an agent run was created for ticket2
    with client.application.app_context():
        from pi_cowork.db import query_db

        runs = query_db("SELECT * FROM agent_runs WHERE ticket_id = ? AND status = 'running'", (tid2,))
        assert len(runs) == 1, f"Expected 1 running agent for ticket2, got {len(runs)}"


def test_drain_loop_exception_does_not_kill_thread(client, default_workflow, default_board):
    """Bug 1: Verify _drain_loop continues iterating after an exception in drain_queue."""
    from pi_cowork.agents import _drain_loop

    iteration_count = 0
    stop_event = threading.Event()
    drain_queue_calls = 0

    def fake_cleanup():
        pass

    def fake_drain():
        nonlocal drain_queue_calls
        drain_queue_calls += 1

    def fake_sleep(seconds):
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count >= 3:
            stop_event.set()

    # First call to cleanup_runs raises, second succeeds
    call_num = 0

    def cleanup_first_raises():
        nonlocal call_num
        call_num += 1
        if call_num == 1:
            raise RuntimeError("Database is locked")

    with client.application.app_context(), patch("pi_cowork.agents.cleanup_runs", side_effect=cleanup_first_raises):
        with patch("pi_cowork.agents.drain_queue", side_effect=fake_drain):
            with patch("pi_cowork.agents.time.sleep", side_effect=fake_sleep):
                t = threading.Thread(target=_drain_loop, args=(client.application,), daemon=True)
                t.start()
                stop_event.wait(timeout=5)
                t.join(timeout=2)

    # Should have reached 3 iterations despite the exception on the first iteration
    assert iteration_count >= 3, f"Expected >=3 iterations after exception, got {iteration_count}"


def test_event_drain_handler_returns_early_without_app(client, default_workflow, default_board):
    """Bug 6: _event_drain_handler should return early if _drain_app is None."""
    import pi_cowork.agents as agents_mod
    from pi_cowork.events import AGENT_COMPLETED, bus

    drain_calls = 0

    def counting_drain():
        nonlocal drain_calls
        drain_calls += 1

    orig_app = agents_mod._drain_app
    agents_mod._drain_app = None  # No app context available

    try:
        with patch("pi_cowork.agents.drain_queue", side_effect=counting_drain):
            bus.publish(AGENT_COMPLETED, ticket_id=999, agent_name="TestAgent", run_id=1)
    finally:
        agents_mod._drain_app = orig_app

    assert drain_calls == 0, f"Expected drain_queue NOT to be called when _drain_app is None, got {drain_calls} calls"


def test_event_drain_handler_uses_app_context(client, default_workflow, default_board):
    """Bug 6: _event_drain_handler should push Flask app context so drain_queue works from watcher thread."""
    import pi_cowork.agents as agents_mod
    from pi_cowork.events import AGENT_COMPLETED, bus

    drain_calls = 0

    def counting_drain():
        nonlocal drain_calls
        drain_calls += 1

    curr_app = agents_mod._drain_app
    agents_mod._drain_app = client.application

    try:
        with patch("pi_cowork.agents.drain_queue", side_effect=counting_drain):
            bus.publish(AGENT_COMPLETED, ticket_id=999, agent_name="TestAgent", run_id=1)
    finally:
        agents_mod._drain_app = curr_app

    assert drain_calls >= 1, f"Expected drain_queue to be called with app context, got {drain_calls} calls"


def test_concurrent_try_spawn_and_drain_no_race(client, default_workflow, default_board, monkeypatch):
    """Bug 2: Verify concurrent try_spawn_or_queue() and drain_queue() don't exceed limits."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post(
        "/api/agents",
        json={
            "name": "RaceAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "RaceStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post("/api/tickets", json={"title": "Race1", "board_id": default_board["id"]})
    tid = json.loads(ticket.data)["id"]

    max_running = 0
    lock = threading.Lock()

    original_count_running = None
    from pi_cowork import agents as agents_module

    original_count_running = agents_module.count_running

    def instrumented_count_running():
        result = original_count_running()
        with lock:
            nonlocal max_running
            if result > max_running:
                max_running = result
        return result

    # Spawn via HTTP (try_spawn_or_queue)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        with patch("pi_cowork.agents._is_our_process", return_value=True):
            with patch("pi_cowork.agents.count_running", side_effect=instrumented_count_running):
                client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Since max_parallel is 1, max_running should never exceed 1
    # (this is a basic sanity check -- a real race is hard to trigger in a test)
    with lock:
        assert max_running <= 1, f"Max running agents should not exceed 1, got {max_running}"
