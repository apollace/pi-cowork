"""Tests for Ticket #59: drain queue context bugs and recurring task agent spawn.

Bug A — drain_queue() uses incomplete ticket context (no board_name/workflow_id)
Bug B — drain_queue() drops old_status_id context
Bug C — Recurring task tickets don't spawn agents
"""

import json
from datetime import UTC
from unittest.mock import MagicMock, patch

from pi_cowork import config
from pi_cowork.models import set_setting


def _set_limits(client, max_parallel=None, max_per_hour=None):
    """Set agent limits via DB settings."""
    if max_parallel is not None:
        with client.application.app_context():
            set_setting("max_parallel", str(max_parallel))
        config.PI_MAX_PARALLEL = max_parallel
    if max_per_hour is not None:
        with client.application.app_context():
            set_setting("max_per_hour", str(max_per_hour))
        config.PI_MAX_PER_HOUR = max_per_hour


# ===================================================================
# Bug A: drain_queue() must use full ticket context (board_name, workflow_id)
# ===================================================================


class TestDrainQueueFullContext:
    """Drain-queued agents must receive the same ticket context as direct spawns."""

    def test_drain_queue_ticket_has_full_context(self, client, default_workflow, default_board):
        """Queue → drain → verify agent prompt includes board_name and workflow_id."""
        _set_limits(client, max_parallel=1, max_per_hour=10)

        agent = client.post(
            "/api/agents",
            json={
                "name": "DrainContextAgent",
                "description": "Test agent for drain context.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "DrainContextStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create TWO tickets; the first will take the slot, the second gets queued
        ticket1 = client.post("/api/tickets", json={"title": "DrainCtx1", "board_id": default_board["id"]})
        tid1 = json.loads(ticket1.data)["id"]
        ticket2 = client.post("/api/tickets", json={"title": "DrainCtx2", "board_id": default_board["id"]})
        tid2 = json.loads(ticket2.data)["id"]

        # First ticket takes the slot
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid1}", json={"status_id": sid})

        # Second ticket gets queued (limit reached)
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid2}", json={"status_id": sid})

        # Verify ticket2 is queued
        q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
        assert q_data["queued"] is True

        # Mark first as completed (free slot)
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
            db.commit()

        # Now drain the queue and capture what spawn_agent receives
        captured_args = {}

        original_spawn = None
        from pi_cowork import agents as agents_module

        original_spawn = agents_module.spawn_agent

        def capture_spawn(ticket, status, agent, old_status_id=None):
            captured_args["ticket"] = ticket
            captured_args["status"] = status
            captured_args["agent"] = agent
            captured_args["old_status_id"] = old_status_id
            return original_spawn(ticket, status, agent, old_status_id=old_status_id)

        with (
            patch("pi_cowork.agents.spawn_agent", side_effect=capture_spawn),
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9998)),
            patch("pi_cowork.agents._is_our_process", return_value=False),
            client.application.app_context(),
        ):
            agents_module.drain_queue()

        # Verify the ticket dict passed to spawn_agent has full context
        assert "board_name" in captured_args["ticket"], "Bug A: ticket dict lacks board_name"
        assert "workflow_id" in captured_args["ticket"], "Bug A: ticket dict lacks workflow_id"
        assert captured_args["ticket"]["board_name"] == default_board["name"], (
            f"Bug A: board_name should be '{default_board['name']}', got '{captured_args['ticket'].get('board_name')}'"
        )
        assert captured_args["ticket"]["workflow_id"] == default_workflow["id"], (
            f"Bug A: workflow_id should be {default_workflow['id']}, got {captured_args['ticket'].get('workflow_id')}"
        )

    def test_drain_queue_agent_prompt_includes_board_name(self, client, default_workflow, default_board):
        """Queue → drain → verify the agent's context message mentions Board with correct name."""
        _set_limits(client, max_parallel=1, max_per_hour=10)

        agent = client.post(
            "/api/agents",
            json={
                "name": "PromptCtxAgent",
                "description": "Test agent for prompt context.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "PromptCtxStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket1 = client.post("/api/tickets", json={"title": "PromptCtx1", "board_id": default_board["id"]})
        tid1 = json.loads(ticket1.data)["id"]
        ticket2 = client.post("/api/tickets", json={"title": "PromptCtx2", "board_id": default_board["id"]})
        tid2 = json.loads(ticket2.data)["id"]

        # First ticket takes the slot
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid1}", json={"status_id": sid})

        # Second ticket gets queued
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid2}", json={"status_id": sid})

        # Mark first as completed
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
            db.commit()

        # Drain and capture Popen command (context message is the last arg)
        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            captured_cmd[:] = cmd
            proc = MagicMock()
            proc.pid = 9998
            return proc

        with (
            patch("app.subprocess.Popen", side_effect=capture_popen),
            patch("pi_cowork.agents._is_our_process", return_value=False),
            client.application.app_context(),
        ):
            from pi_cowork.agents import cleanup_runs, drain_queue

            cleanup_runs()
            drain_queue()

        assert captured_cmd, "Agent should have been spawned during drain"
        context_msg = captured_cmd[-1]
        # Bug A: context must include board name, not "Unknown"
        assert default_board["name"] in context_msg, (
            f"Bug A: context message should include board name '{default_board['name']}'"
        )
        assert f"board_id={default_board['id']}" in context_msg, "Bug A: context message should include board_id"


# ===================================================================
# Bug B: drain_queue() must preserve old_status_id for transition context
# ===================================================================


class TestDrainQueueOldStatusId:
    """Drained agents must receive old_status_id so prompts say 'Moved from X to Y'."""

    def test_drain_queue_carries_old_status_id(self, client, default_workflow, default_board):
        """Queue with old_status_id → drain → verify prompt says 'Moved from X to Y'."""
        _set_limits(client, max_parallel=1, max_per_hour=10)

        agent = client.post(
            "/api/agents",
            json={
                "name": "OldStatusAgent",
                "description": "Test agent for old_status_id.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create two statuses with the same agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "FromStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        from_sid = json.loads(s1.data)["id"]

        s2 = client.post(
            "/api/statuses",
            json={
                "name": "ToStatus",
                "sort_order": 2,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        to_sid = json.loads(s2.data)["id"]

        # Create two tickets
        ticket1 = client.post("/api/tickets", json={"title": "OldStat1", "board_id": default_board["id"]})
        tid1 = json.loads(ticket1.data)["id"]
        ticket2 = client.post("/api/tickets", json={"title": "OldStat2", "board_id": default_board["id"]})
        tid2 = json.loads(ticket2.data)["id"]

        # Move ticket1 to from_status to take the slot
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid1}", json={"status_id": from_sid})

        # Move ticket2 to from_status (no agent on from_status at this point... actually there is)
        # Let's reconfigure: use a status with no agent for the initial state, then move to one with agent
        # Actually, the simplest way: move ticket2 from backlog to from_status, which should queue it
        # But we need the max_parallel limit to be hit first

        # Mark first agent run as running, then try moving ticket2 which queues
        # First let ticket1's agent be "running"
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            # Ensure ticket1's run is still 'running' for limit check
            # (already running from the spawn above)

        # Move ticket2 to from_status (this will queue because limit is 1)
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid2}", json={"status_id": from_sid})

        # Verify ticket2 is queued
        q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
        assert q_data["queued"] is True

        # Now check that the queue entry has old_status_id set
        # ticket2 originally was in Backlog (the default status), moved to FromStatus
        # Looking at the queue entry
        with client.application.app_context():
            from pi_cowork.db import query_db as qdb
            from pi_cowork.db import row_to_dict as rtd

            queue_entries = qdb("SELECT * FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL", (tid2,))
            assert len(queue_entries) == 1, f"Expected 1 queue entry, got {len(queue_entries)}"
            q_entry = rtd(queue_entries[0])
            # The transition from Backlog to FromStatus should have old_status_id set
            backlog_statuses = qdb(
                "SELECT id FROM statuses WHERE is_default = 1 AND workflow_id = ?", (default_workflow["id"],)
            )
            assert len(backlog_statuses) > 0
            backlog_id = backlog_statuses[0]["id"]
            assert q_entry["old_status_id"] == backlog_id, (
                f"Bug B: queue entry should have old_status_id={backlog_id}, got {q_entry.get('old_status_id')}"
            )

        # Mark first as completed (free slot)
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
            db.commit()

        # Drain and capture spawn arguments
        captured_args = {}
        from pi_cowork import agents as agents_module

        original_spawn = agents_module.spawn_agent

        def capture_spawn(ticket, status, agent, old_status_id=None):
            captured_args["ticket"] = ticket
            captured_args["status"] = status
            captured_args["agent"] = agent
            captured_args["old_status_id"] = old_status_id
            return original_spawn(ticket, status, agent, old_status_id=old_status_id)

        with (
            patch("pi_cowork.agents.spawn_agent", side_effect=capture_spawn),
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9998)),
            patch("pi_cowork.agents._is_our_process", return_value=False),
            client.application.app_context(),
        ):
            agents_module.drain_queue()

        # Verify old_status_id was passed through to spawn_agent
        assert captured_args.get("old_status_id") is not None, (
            "Bug B: old_status_id should be passed from queue to spawn_agent"
        )
        assert captured_args["old_status_id"] == backlog_id, (
            f"Bug B: old_status_id should be {backlog_id}, got {captured_args.get('old_status_id')}"
        )

    def test_queue_agent_stores_old_status_id(self, client, default_workflow, default_board):
        """queue_agent should store old_status_id in the agent_queue table."""
        _set_limits(client, max_parallel=1, max_per_hour=10)

        agent = client.post(
            "/api/agents",
            json={
                "name": "QueueStoreAgent",
                "description": "Test agent.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "QueueStoreStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket = client.post("/api/tickets", json={"title": "QueueTest", "board_id": default_board["id"]})
        tid = json.loads(ticket.data)["id"]

        # Move to status (will queue because max_parallel is 1, but first need a running agent)
        # Create another ticket that takes the slot
        ticket2 = client.post("/api/tickets", json={"title": "FillSlot", "board_id": default_board["id"]})
        tid2 = json.loads(ticket2.data)["id"]

        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid2}", json={"status_id": sid})

        # Now move ticket1 - this should queue
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        # Check queue entry has old_status_id
        with client.application.app_context():
            from pi_cowork.db import query_db as qdb
            from pi_cowork.db import row_to_dict as rtd

            queue_entries = qdb("SELECT * FROM agent_queue WHERE ticket_id = ? AND started_at IS NULL", (tid,))
            assert len(queue_entries) == 1
            q = rtd(queue_entries[0])
            # The old status should be backlog (default)
            backlog_statuses = qdb(
                "SELECT id FROM statuses WHERE is_default = 1 AND workflow_id = ?", (default_workflow["id"],)
            )
            backlog_id = backlog_statuses[0]["id"]
            assert q["old_status_id"] == backlog_id, (
                f"Bug B: queue should store old_status_id={backlog_id}, got {q.get('old_status_id')}"
            )

    def test_drain_queue_status_transition_in_prompt(self, client, default_workflow, default_board):
        """When old_status_id is set, the drained agent's prompt should say 'Moved from X to Y'."""
        _set_limits(client, max_parallel=1, max_per_hour=10)

        agent = client.post(
            "/api/agents",
            json={
                "name": "TransitionCtxAgent",
                "description": "Test agent for transition context.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        from_res = client.post(
            "/api/statuses",
            json={
                "name": "SrcTransition",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        from_sid = json.loads(from_res.data)["id"]

        to_res = client.post(
            "/api/statuses",
            json={
                "name": "DstTransition",
                "sort_order": 2,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        to_sid = json.loads(to_res.data)["id"]

        # Create two tickets
        ticket1 = client.post("/api/tickets", json={"title": "Transition1", "board_id": default_board["id"]})
        tid1 = json.loads(ticket1.data)["id"]
        ticket2 = client.post("/api/tickets", json={"title": "Transition2", "board_id": default_board["id"]})
        tid2 = json.loads(ticket2.data)["id"]

        # Move ticket1 to "from" status to take the slot
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid1}", json={"status_id": from_sid})

        # Move ticket2 from backlog to "to" status (this will queue due to limit)
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("pi_cowork.agents._is_our_process", return_value=True),
        ):
            client.put(f"/api/tickets/{tid2}", json={"status_id": to_sid})

        # Verify ticket2 is queued
        q_data = json.loads(client.get(f"/api/tickets/{tid2}").data)
        assert q_data["queued"] is True

        # Mark ticket1 as completed to free a slot
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ?", (tid1,))
            db.commit()

        # Drain and capture the Popen command
        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            captured_cmd[:] = cmd
            proc = MagicMock()
            proc.pid = 9998
            return proc

        with (
            patch("app.subprocess.Popen", side_effect=capture_popen),
            patch("pi_cowork.agents._is_our_process", return_value=False),
            client.application.app_context(),
        ):
            from pi_cowork.agents import cleanup_runs, drain_queue

            cleanup_runs()
            drain_queue()

        assert captured_cmd, "Agent should have been spawned during drain"
        context_msg = captured_cmd[-1]
        # Bug B: the prompt should contain transition context when old_status_id is set
        # For a cold spawn (first spawn), the context includes a note about the transition
        assert "Moved from" in context_msg or "was moved from" in context_msg, (
            f"Bug B: context message should indicate a status transition, got: {context_msg[:300]}"
        )


# ===================================================================
# Bug C: Recurring task tickets should spawn agents
# ===================================================================


class TestRecurringTaskSpawnsAgent:
    """Recurring task tickets must spawn agents when the initial status has one."""

    def test_recurring_task_spawns_agent_when_status_has_agent(self, client, default_workflow, default_board):
        """process_recurring_tasks should spawn an agent if the status has one."""
        from datetime import datetime, timedelta

        from pi_cowork import models

        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "RecurringSpawnAgent",
                "description": "Agent for recurring task spawn test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with the agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "RecurSpawnStatus",
                "sort_order": 1,
                "is_default": 0,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a recurring task with status that has an agent
        now = datetime.now(UTC)
        past = (now - timedelta(minutes=30)).isoformat()
        res = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "Agent Spawn Test",
                "body": "Testing agent spawn from recurring",
                "status_id": sid,
                "cron_expression": "* * * * *",
            },
        )
        assert res.status_code == 201
        task_id = json.loads(res.data)["id"]

        # Set next_trigger_at to the past so it fires
        _run_db_in_ctx(client, "UPDATE recurring_tasks SET next_trigger_at = ? WHERE id = ?", (past, task_id))

        # Clear existing running agents so the spawn isn't rate-limited
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE status = 'running'")
            db.commit()

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9997

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen), client.application.app_context():
            models.process_recurring_tasks()

        # An agent should have been spawned
        assert captured_cmd, "Bug C: process_recurring_tasks should spawn an agent when status has one"
        context_msg = captured_cmd[-1]
        assert "Agent Spawn Test" in context_msg or "Recurring" in context_msg, (
            "Bug C: The spawned agent prompt should reference the recurring ticket"
        )

    def test_recurring_task_no_spawn_when_status_has_no_agent(self, client, default_workflow, default_board):
        """process_recurring_tasks should NOT spawn when status has no agent."""
        from datetime import datetime, timedelta

        from pi_cowork import models

        # Create a status WITHOUT an agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "NoAgentRecurStatus",
                "sort_order": 1,
                "is_default": 0,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a recurring task
        now = datetime.now(UTC)
        past = (now - timedelta(minutes=30)).isoformat()
        res = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "No Agent Recur",
                "body": "Testing no agent spawn",
                "status_id": sid,
                "cron_expression": "* * * * *",
            },
        )
        task_id = json.loads(res.data)["id"]
        _run_db_in_ctx(client, "UPDATE recurring_tasks SET next_trigger_at = ? WHERE id = ?", (past, task_id))

        with patch("app.subprocess.Popen") as mock_popen, client.application.app_context():
            models.process_recurring_tasks()

        assert not mock_popen.called, "Bug C: No agent should be spawned when status has no agent"

    def test_recurring_manual_trigger_spawns_agent(self, client, default_workflow, default_board):
        """POST /api/recurring/<id>/trigger should spawn agent when status has one."""
        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "ManualTriggerAgent",
                "description": "Agent for manual trigger spawn test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with the agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "ManualTriggerStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a recurring task
        res = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "Manual Trigger Test",
                "body": "Testing manual trigger spawn",
                "status_id": sid,
                "cron_expression": "0 9 * * 1",
            },
        )
        task_id = json.loads(res.data)["id"]

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9996

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            res = client.post(f"/api/recurring/{task_id}/trigger")

        assert res.status_code == 200
        assert captured_cmd, "Bug C: Manual trigger should spawn an agent when status has one"

    def test_recurring_manual_trigger_no_spawn_without_agent(self, client, default_workflow, default_board):
        """POST /api/recurring/<id>/trigger should NOT spawn when status has no agent."""
        # Create a status without an agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "NoAgentManualStatus",
                "sort_order": 1,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        res = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "No Agent Manual",
                "status_id": sid,
                "cron_expression": "0 9 * * 1",
            },
        )
        task_id = json.loads(res.data)["id"]

        with patch("app.subprocess.Popen") as mock_popen:
            res = client.post(f"/api/recurring/{task_id}/trigger")

        assert res.status_code == 200
        assert not mock_popen.called, "Bug C: No agent should be spawned when status has no agent"

    def test_recurring_spawn_uses_full_context(self, client, default_workflow, default_board):
        """Recurring task agent spawn should include board_name and workflow_id in context."""
        from datetime import datetime, timedelta

        from pi_cowork import models

        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "RecurCtxAgent",
                "description": "Agent for recurring context test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with the agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "RecurCtxStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a recurring task
        now = datetime.now(UTC)
        past = (now - timedelta(minutes=30)).isoformat()
        res = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "Context Test Recur",
                "body": "Testing context in recurring spawn",
                "status_id": sid,
                "cron_expression": "* * * * *",
            },
        )
        task_id = json.loads(res.data)["id"]
        _run_db_in_ctx(client, "UPDATE recurring_tasks SET next_trigger_at = ? WHERE id = ?", (past, task_id))

        # Clear existing running agents so spawn isn't rate-limited
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE status = 'running'")
            db.commit()

        captured_args = {}
        from pi_cowork import agents as agents_module

        original_spawn = agents_module.spawn_agent

        def capture_spawn(ticket, status, agent, old_status_id=None):
            captured_args["ticket"] = ticket
            captured_args["status"] = status
            captured_args["agent"] = agent
            captured_args["old_status_id"] = old_status_id
            return original_spawn(ticket, status, agent, old_status_id=old_status_id)

        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9997)),
            patch("pi_cowork.agents._is_our_process", return_value=False),
            patch("pi_cowork.agents.spawn_agent", side_effect=capture_spawn),
            client.application.app_context(),
        ):
            models.process_recurring_tasks()

        assert "ticket" in captured_args, "Spawn should have been called"
        ticket = captured_args["ticket"]
        assert "board_name" in ticket, "Bug C/A: Ticket context should include board_name"
        assert "workflow_id" in ticket, "Bug C/A: Ticket context should include workflow_id"
        assert ticket["board_name"] == default_board["name"]
        assert ticket["workflow_id"] == default_workflow["id"]


# ===================================================================
# Helper
# ===================================================================


def _run_db_in_ctx(client, query, args=()):
    """Run a DB write within app context."""
    with client.application.app_context():
        from pi_cowork.db import run_db

        return run_db(query, args)
