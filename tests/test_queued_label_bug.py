"""Tests for ticket #58: Fix "Queued" label persisting after agent starts.

Bug 1: Race condition in drain_queue queue entry deletion — the SELECT COUNT(*)
       WHERE status='running' check is racy because the watcher thread can mark
       the run completed between spawn_agent() returning and the query executing.
       Fix: spawn_agent() now returns bool; drain_queue uses the return value.

Bug 2: Stale queue entries never cleaned when agent spawns directly —
       try_spawn_or_queue() spawns directly but doesn't delete pre-existing
       queue entries. The "Queued" label persists forever.
       Fix: try_spawn_or_queue() now cleans up stale queue entries before spawning.

Bug 3: Duplicate queue entries can accumulate — queue_agent() always inserts
       without checking for existing entries, so multiple calls stack up
       duplicates. Only one is processed by drain_queue, others persist forever.
       Fix: queue_agent() now deletes existing un-started entries before inserting.

Bug 4: (pre-existing) Unanswered questions block spawn in drain_queue.
       Already handled by a pre-check, but with Bug 1's fix (return value),
       spawn_agent() also returns False to keep the queue entry.

Bug 5: Stale queue cleanup safety net — cleanup_runs() now periodically removes
       queue entries where the ticket already has a running agent, or entries
       older than 2 hours.
"""

import json
from unittest.mock import patch, MagicMock

from pi_cowork import config
from pi_cowork.models import set_setting


def _set_limits(client, max_parallel=None, max_per_hour=None):
    """Set agent limits via DB settings (and module-level constants for compat)."""
    if max_parallel is not None:
        with client.application.app_context():
            set_setting('max_parallel', str(max_parallel))
        config.PI_MAX_PARALLEL = max_parallel
    if max_per_hour is not None:
        with client.application.app_context():
            set_setting('max_per_hour', str(max_per_hour))
        config.PI_MAX_PER_HOUR = max_per_hour


# ---------------------------------------------------------------------------
# Bug 1: Race condition in drain_queue — use spawn_agent return value
# ---------------------------------------------------------------------------

def test_drain_queue_deletes_entry_on_spawn_true(client, default_workflow, default_board):
    """Bug 1: drain_queue should delete the queue entry when spawn_agent returns True."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'Bug1Agent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'Bug1Stage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Bug1-1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'Bug1-2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First ticket takes the slot
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second ticket gets queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Verify queued
    q_data = json.loads(client.get(f'/api/tickets/{tid2}').data)
    assert q_data['queued'] is True

    # Free slot: complete first agent run
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Drain — spawn_agent returns True, so queue entry should be deleted
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9998)):
        with patch('pi_cowork.agents._is_our_process', return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue
                drain_queue()

    q_data = json.loads(client.get(f'/api/tickets/{tid2}').data)
    assert q_data['queued'] is False, "Queue entry should be deleted when spawn_agent returns True"


def test_drain_queue_keeps_entry_on_spawn_false(client, default_workflow, default_board):
    """Bug 1: drain_queue should keep the queue entry when spawn_agent returns False (early return)."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'Bug1FalseAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'Bug1FalseStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Bug1F-1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'Bug1F-2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First ticket takes the slot
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second ticket gets queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Free slot
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Add unanswered question so spawn_agent will return False
    client.post(f'/api/tickets/{tid2}/questions', json={
        'questions': [{'body': 'Blocked?', 'options': ['yes', 'no']}]
    })

    # Drain — spawn_agent should return False, keeping queue entry
    with client.application.app_context():
        from pi_cowork.agents import drain_queue
        drain_queue()

    q_data = json.loads(client.get(f'/api/tickets/{tid2}').data)
    assert q_data['queued'] is True, "Queue entry should be kept when spawn_agent returns False"


def test_drain_queue_racey_completion_still_deletes_entry(client, default_workflow, default_board):
    """Bug 1 (core scenario): Even if the agent completes extremely fast (by the time
    drain_queue checks), the queue entry should still be deleted because
    spawn_agent returned True."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'FastAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'FastStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Fast1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'Fast2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First ticket takes the slot
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second ticket gets queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Free slot
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Drain — spawn_agent will return True (it did create a run), but the run
    # may already be marked completed by watcher. Old code checked status='running'
    # which would fail. New code uses return value, so queue entry is deleted.
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9998)):
        with patch('pi_cowork.agents._is_our_process', return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue
                drain_queue()

    # After drain, the queue entry should be gone (bug 1 fixed)
    q_data = json.loads(client.get(f'/api/tickets/{tid2}').data)
    assert q_data['queued'] is False, "Queue entry should be deleted even if agent completed fast"


# ---------------------------------------------------------------------------
# Bug 2: Stale queue entries cleaned when agent spawns directly
# ---------------------------------------------------------------------------

def test_direct_spawn_cleans_stale_queue_entry(client, default_workflow, default_board):
    """Bug 2: try_spawn_or_queue should delete stale queue entries when spawning directly."""
    _set_limits(client, max_parallel=2, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'DirectSpawnAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'DirectSpawnStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Direct1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']

    # First, queue the ticket by filling up the parallel limit to 0
    _set_limits(client, max_parallel=0, max_per_hour=10)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Verify it was queued
    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is True, "Ticket should be queued when limits are hit"

    # Now increase the limit so try_spawn_or_queue can spawn directly on re-run
    _set_limits(client, max_parallel=2, max_per_hour=10)

    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("DELETE FROM agent_runs WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Trigger another spawn via the re-run endpoint (/api/tickets/<id>/spawn)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9998)):
        with patch('pi_cowork.agents._is_our_process', return_value=False):
            client.post(f'/api/tickets/{tid1}/spawn')

    # After direct spawn, the ticket should NOT be queued anymore
    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is False, "Stale queue entry should be cleaned up by try_spawn_or_queue"


# ---------------------------------------------------------------------------
# Bug 3: Duplicate queue entries prevented
# ---------------------------------------------------------------------------

def test_no_duplicate_queue_entries(client, default_workflow, default_board):
    """Bug 3: queue_agent should not create duplicate entries for the same ticket."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'DupAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'DupStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Dup1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'Dup2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # Fill up the parallel limit
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Queue ticket2 multiple times (simulating repeated status changes)
    _set_limits(client, max_parallel=0, max_per_hour=10)
    for _ in range(3):
        with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
            with patch('pi_cowork.agents._is_our_process', return_value=True):
                client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Should have exactly ONE queue entry for ticket2 (not 3)
    from pi_cowork.db import query_db
    with client.application.app_context():
        entries = query_db(
            "SELECT COUNT(*) AS c FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL",
            (tid2,), one=True
        )
        assert entries['c'] == 1, f"Expected exactly 1 queue entry for ticket2, got {entries['c']}"


def test_queue_entry_replaced_on_requeue(client, default_workflow, default_board):
    """Bug 3: Re-queuing the same ticket should replace the old queue entry, not stack."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'RequeueAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'RequeueStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Req1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'Req2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # Fill up the parallel limit
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Queue ticket2 with 'rate' reason (set max_per_hour=0)
    _set_limits(client, max_parallel=1, max_per_hour=0)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    from pi_cowork.db import query_db
    with client.application.app_context():
        entries_before = query_db(
            "SELECT * FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL",
            (tid2,), one=True
        )
        assert entries_before is not None
        reason_before = entries_before['reason']

    # Queue again (different reason: parallel, set max_parallel=0)
    _set_limits(client, max_parallel=0, max_per_hour=10)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    with client.application.app_context():
        entries_after = query_db(
            "SELECT COUNT(*) AS c FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL",
            (tid2,), one=True
        )
        assert entries_after['c'] == 1, "Should have exactly 1 queue entry after re-queue"


# ---------------------------------------------------------------------------
# Bug 5: Stale queue cleanup in cleanup_runs
# ---------------------------------------------------------------------------

def test_cleanup_runs_removes_queue_entries_with_running_agent(client, default_workflow, default_board):
    """Bug 5: cleanup_runs should remove queue entries where the ticket already
    has a running agent (stale entries from Bug 1/2)."""
    _set_limits(client, max_parallel=2, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'CleanupAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'CleanupStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Cleanup1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']

    # Spawn a running agent for the ticket
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Verify there's a running agent
    data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert data['running_agents'] >= 1

    # Manually insert a stale queue entry (simulating Bug 1/2 leftover)
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO agent_queue (ticket_id, status_id, agent_id, reason) VALUES (?, ?, ?, 'parallel')",
            (tid1, id1, aid)
        )
        db.commit()

    # Verify the stale queue entry exists AND the ticket shows as queued
    data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert data['queued'] is True, "Stale queue entry should exist before cleanup"

    # Run cleanup_runs — should remove the stale entry since ticket has running agent
    with patch('pi_cowork.agents._is_our_process', return_value=True):
        with client.application.app_context():
            from pi_cowork.agents import cleanup_runs
            cleanup_runs()

    # Stale queue entry should be gone
    data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert data['queued'] is False, "Stale queue entry should be removed by cleanup_runs"


def test_cleanup_runs_removes_old_queue_entries(client, default_workflow, default_board):
    """Bug 5: cleanup_runs should remove queue entries older than 2 hours."""
    _set_limits(client, max_parallel=2, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'OldQueueAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'OldQueueStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'OldQueue1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']

    # Insert an old queue entry (queued 3 hours ago)
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO agent_queue (ticket_id, status_id, agent_id, reason, queued_at) VALUES (?, ?, ?, 'parallel', datetime('now', '-3 hours'))",
            (tid1, id1, aid)
        )
        db.commit()

    # Verify queue entry exists
    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is True

    # Run cleanup_runs — should remove the old entry
    with client.application.app_context():
        from pi_cowork.agents import cleanup_runs
        cleanup_runs()

    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is False, "Old queue entry (>2 hours) should be removed"


def test_cleanup_runs_preserves_recent_queue_entries(client, default_workflow, default_board):
    """Bug 5: cleanup_runs should NOT remove recent queue entries (<2 hours) for tickets
    that don't have running agents."""
    _set_limits(client, max_parallel=2, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'FreshQueueAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'FreshQueueStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'FreshQueue1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']

    # Insert a recent queue entry (queued now)
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO agent_queue (ticket_id, status_id, agent_id, reason) VALUES (?, ?, ?, 'parallel')",
            (tid1, id1, aid)
        )
        db.commit()

    # Verify queue entry exists
    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is True

    # Run cleanup_runs — should NOT remove the fresh entry
    with client.application.app_context():
        from pi_cowork.agents import cleanup_runs
        cleanup_runs()

    q_data = json.loads(client.get(f'/api/tickets/{tid1}').data)
    assert q_data['queued'] is True, "Recent queue entry (<2 hours) should be preserved"


# ---------------------------------------------------------------------------
# Integration: spawn_agent returns booleans correctly
# ---------------------------------------------------------------------------

def test_spawn_agent_returns_true_on_success(client, default_workflow, default_board):
    """spawn_agent should return True when an agent run is created successfully."""
    from pi_cowork.agents import spawn_agent
    from pi_cowork.db import query_db, row_to_dict
    from pi_cowork.models import get_status, get_agent

    agent = client.post('/api/agents', json={
        'name': 'ReturnTrueAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'ReturnTrueStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(s1.data)['id']

    ticket = client.post('/api/tickets', json={'title': 'ReturnTrue', 'board_id': default_board['id']})
    tid = json.loads(ticket.data)['id']

    with client.application.app_context():
        status = get_status(sid)
        agent_obj = get_agent(aid)
        ticket_row = query_db("SELECT * FROM tickets WHERE id = ?", (tid,), one=True)

        with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
            result = spawn_agent(row_to_dict(ticket_row), status, agent_obj)

    assert result is True, f"spawn_agent should return True on success, got {result}"


def test_spawn_agent_returns_false_on_unanswered_questions(client, default_workflow, default_board):
    """spawn_agent should return False when blocked by unanswered questions."""
    from pi_cowork.agents import spawn_agent
    from pi_cowork.db import query_db, row_to_dict
    from pi_cowork.models import get_status, get_agent

    agent = client.post('/api/agents', json={
        'name': 'ReturnFalseAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'ReturnFalseStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(s1.data)['id']

    ticket = client.post('/api/tickets', json={'title': 'ReturnFalse', 'board_id': default_board['id']})
    tid = json.loads(ticket.data)['id']

    # Add an unanswered question
    client.post(f'/api/tickets/{tid}/questions', json={
        'questions': [{'body': 'Blocking question?', 'options': ['A', 'B']}]
    })

    with client.application.app_context():
        status = get_status(sid)
        agent_obj = get_agent(aid)
        ticket_row = query_db("SELECT * FROM tickets WHERE id = ?", (tid,), one=True)

        result = spawn_agent(row_to_dict(ticket_row), status, agent_obj)

    assert result is False, f"spawn_agent should return False when blocked by questions, got {result}"


# ---------------------------------------------------------------------------
# End-to-end: Queued label properly removed after agent finishes
# ---------------------------------------------------------------------------

def test_queued_label_removed_after_drain(client, default_workflow, default_board):
    """End-to-end: After drain processes a queued ticket, the queued label is gone."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'E2EAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'E2EStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'E2E1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'E2E2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First ticket takes the slot
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second ticket gets queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    assert json.loads(client.get(f'/api/tickets/{tid2}').data)['queued'] is True

    # Complete first agent and drain queue
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9998)):
        with patch('pi_cowork.agents._is_our_process', return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue
                drain_queue()

    # The second ticket should no longer show as queued
    assert json.loads(client.get(f'/api/tickets/{tid2}').data)['queued'] is False


def test_bug1_race_condition_no_stale_queued_label(client, default_workflow, default_board):
    """Full regression test for Bug 1: Agent completes instantly but
    queue entry is still properly cleaned up because spawn_agent returns True."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'InstantAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'InstantStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    t1 = client.post('/api/tickets', json={'title': 'Instant1', 'board_id': default_board['id']})
    tid1 = json.loads(t1.data)['id']
    t2 = client.post('/api/tickets', json={'title': 'Instant2', 'board_id': default_board['id']})
    tid2 = json.loads(t2.data)['id']

    # First ticket takes the slot
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second ticket gets queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    assert json.loads(client.get(f'/api/tickets/{tid2}').data)['queued'] is True

    # Free the slot
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
        db.commit()

    # Spawn, then immediately mark the new agent run as completed (simulates instant completion)
    # The old code would SELECT COUNT(*) WHERE status='running' and find 0, not deleting the queue entry.
    # The new code uses the spawn_agent() return value instead.
    spawned_return = None
    from pi_cowork import agents as agents_module
    original_spawn = agents_module.spawn_agent

    def spawn_and_complete(ticket, status, agent, old_status_id=None):
        result = original_spawn(ticket, status, agent, old_status_id=old_status_id)
        nonlocal spawned_return
        spawned_return = result
        # Immediately mark the run as completed to simulate instant agent finish
        if result:
            with client.application.app_context():
                d = get_db()
                d.execute(
                    "UPDATE agent_runs SET status = 'completed', completed_at = datetime('now') WHERE ticket_id = ? AND status = 'running'",
                    (ticket['id'],)
                )
                d.commit()
        return result

    with patch('pi_cowork.agents.spawn_agent', side_effect=spawn_and_complete):
        with patch('pi_cowork.agents._is_our_process', return_value=False):
            with client.application.app_context():
                from pi_cowork.agents import drain_queue
                drain_queue()

    # The queue entry should be deleted even though the agent completed instantly
    assert spawned_return is True, f"spawn_agent should return True, got {spawned_return}"
    assert json.loads(client.get(f'/api/tickets/{tid2}').data)['queued'] is False, \
        "Queue entry should be deleted after drain even when agent completes instantly"