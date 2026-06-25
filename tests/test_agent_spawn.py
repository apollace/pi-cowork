import json
import os
from unittest.mock import MagicMock, patch


def _create_dummy_session(aid, tid):
    """Create a dummy .jsonl session file so warm-spawn detection works in tests.

    Real pi runs create .jsonl files in the session dir. Mocked Popen doesn't,
    so we create a placeholder to simulate a previous session for this agent.
    """
    session_dir = os.path.join("workspace", ".pi-sessions", str(aid), f"ticket-{tid}")
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "session.jsonl"), "w") as f:
        f.write('{"type":"message"}\n')


def test_cold_spawn_uses_full_context(client, default_workflow, default_board):
    """No session dir -> full context message, lean system prompt."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ColdSpawnAgent",
            "description": "You are a cold agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ColdStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Cold Ticket",
            "body": "Do cold things",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
        assert res.status_code == 200

    assert captured_cmd
    context_msg = captured_cmd[-1]

    # Full context markers
    assert "Cold Ticket" in context_msg
    assert "Do cold things" in context_msg
    assert "API:" in context_msg
    assert "Board:" in context_msg
    assert f"board_id={default_board['id']}" in context_msg
    # Cold spawn should include "forget the goals" directive
    assert "forget the goals you had from previous prompts" in context_msg
    # Questions endpoint should be documented
    assert f"/api/tickets/{tid}/questions" in context_msg
    assert "ask questions" in context_msg
    assert "paused until a human answers" in context_msg

    # System prompt should be lean: identity + directives only
    assert "--system-prompt" in captured_cmd
    idx = captured_cmd.index("--system-prompt")
    system_prompt = captured_cmd[idx + 1]
    assert "You are a cold agent." in system_prompt
    # Should NOT have CURRENT STATUS MANDATE anymore
    assert "CURRENT STATUS MANDATE" not in system_prompt
    # Should NOT have ABSOLUTE RULES anymore
    assert "ABSOLUTE RULES" not in system_prompt
    # Should NOT duplicate status info in system prompt
    assert "Status:" not in system_prompt
    assert "ColdStage" not in system_prompt

    # --session-dir should point to ticket-specific dir using agent ID under board dir
    assert "--session-dir" in captured_cmd
    idx = captured_cmd.index("--session-dir")
    assert captured_cmd[idx + 1] == f"workspace/.pi-sessions/{aid}/ticket-{tid}"

    # Cold spawn should NOT include --continue flag
    assert "--continue" not in captured_cmd

    # Should record spawn time
    ticket_row = client.get(f"/api/tickets/{tid}")
    ticket_data = json.loads(ticket_row.data)
    assert ticket_data["agent_last_spawned_at"] is not None


def test_warm_spawn_uses_full_context(client, default_workflow, default_board):
    """Session dir exists, last_spawned_at recent -> warm spawn with deltas."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "WarmSpawnAgent",
            "description": "You are a warm agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "WarmStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "WarmStage2",
            "sort_order": 2,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Warm Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold) - move to id1
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add a new comment after first spawn
    client.post(f"/api/tickets/{tid}/comments", json={"body": "New instruction from human"})

    # Ensure the comment is strictly newer than agent_last_spawned_at
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm) - move to id2 (same agent, so session dir exists)
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id2})
        assert res.status_code == 200

    context_msg = captured_cmd[-1]

    # Should be an update message (warm spawn)
    assert "[Update]" in context_msg
    assert "Moved from" in context_msg  # status changed from id1 to id2
    assert "New comments since last update:" in context_msg
    assert "New instruction from human" in context_msg

    # Warm spawn on status change should use "forget" directive
    assert "forget the goals you had from previous prompts" in context_msg
    assert "Your goal:" in context_msg

    # Warm spawn with --continue omits static API docs block; check continuity note instead
    assert "Previous API docs and skills are available from your session context." in context_msg
    assert "API:" not in context_msg  # API docs omitted on warm spawn

    # Warm spawn should include --continue flag in the command
    assert "--continue" in captured_cmd

    # Should include done instruction at the end
    assert "add a comment to the ticket" in context_msg


def test_warm_spawn_status_change_says_moved(client, default_workflow, default_board):
    """Warm spawn on status change should say 'Moved from X to Y'."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "MoveAgent",
            "description": "You are a move agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    # Both statuses have the same agent
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "MoveStage1",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "MoveStage2",
            "sort_order": 2,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Move Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold) - move to id1
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add comment to trigger new comments
    client.post(f"/api/tickets/{tid}/comments", json={"body": "New stuff"})

    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm) - move to id2 (status change with same agent)
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id2})
        assert res.status_code == 200

    context_msg = captured_cmd[-1]
    assert 'Moved from "MoveStage1" to "MoveStage2"' in context_msg
    assert "Still in" not in context_msg


def test_warm_spawn_same_status_says_still(client, default_workflow, default_board):
    """Warm spawn on same status should say 'Still in'."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "StillAgent",
            "description": "You are a still agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "StillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Still Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add a new comment
    client.post(f"/api/tickets/{tid}/comments", json={"body": "Follow-up"})

    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm, same status)
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        # Re-trigger spawn on same status (e.g. new comment)
        from pi_cowork.agents import try_spawn_or_queue
        from pi_cowork.db import get_db as _get_db

        with client.application.app_context():
            db = _get_db()
            ticket_row = db.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
            status_row = db.execute("SELECT * FROM statuses WHERE id = ?", (id1,)).fetchone()
            agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (aid,)).fetchone()
            try_spawn_or_queue(dict(ticket_row), dict(status_row), dict(agent_row))

    context_msg = captured_cmd[-1]
    assert 'Still in "StillStage"' in context_msg


def test_stale_spawn_uses_full_context(client, default_workflow, default_board):
    """Session dir exists but last_spawned_at > 1 hour ago -> full context fallback."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "StaleSpawnAgent",
            "description": "You are a stale agent.",
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
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "StaleStage2",
            "sort_order": 2,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Stale Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Move to id1 first (cold spawn)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file so the warm-spawn check reaches the
    # staleness test (without .jsonl files, it would be cold for a different reason)
    _create_dummy_session(aid, tid)

    # Set an old last_spawned_at
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE tickets SET agent_last_spawned_at = datetime('now', '-2 hours') WHERE id = ?", (tid,))
        db.commit()

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id2})
        assert res.status_code == 200

    context_msg = captured_cmd[-1]
    # Should be full context (cold spawn), not delta/update
    assert "API:" in context_msg
    assert "[Update]" not in context_msg
    assert "Description:" in context_msg
    # Stale spawn is cold — should NOT include --continue
    assert "--continue" not in captured_cmd


def test_terminal_status_deletes_session(client, default_workflow, default_board):
    """Moving to terminal status deletes ALL agent session dirs and nulls agent_last_spawned_at."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "TerminalAgent",
            "description": "You are terminal.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "Working",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "Done",
            "sort_order": 2,
            "is_terminal": True,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Terminal Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Move to working status (spawns agent)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Now move to terminal status - should clean up session dir using agent ID
    with patch("app.shutil.rmtree") as mock_rmtree:
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id2})
        assert res.status_code == 200

        # Should have tried to delete session dir for this agent
        expected_dir = f"workspace/.pi-sessions/{aid}/ticket-{tid}"
        mock_rmtree.assert_any_call(expected_dir)

    # agent_last_spawned_at should be nulled
    ticket_row = client.get(f"/api/tickets/{tid}")
    ticket_data = json.loads(ticket_row.data)
    assert ticket_data["agent_last_spawned_at"] is None


def test_agent_prompt_includes_transitions(client, default_workflow, default_board):
    """Transitions appear in context with inline format."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "PromptTester",
            "description": "You are a test agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "Stage1",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "Stage2",
            "sort_order": 2,
            "workflow_id": default_workflow["id"],
        },
    )
    s3 = client.post(
        "/api/statuses",
        json={
            "name": "Stage3",
            "sort_order": 3,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]
    id3 = json.loads(s3.data)["id"]

    client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "Move to Stage2 when ready",
            "workflow_id": default_workflow["id"],
        },
    )
    client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id3,
            "instructions": "",  # empty -> should still be shown (Issue #6)
            "workflow_id": default_workflow["id"],
        },
    )

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Prompt Ticket",
            "body": "Do it",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
        assert res.status_code == 200

    assert captured_cmd
    context_msg = captured_cmd[-1]

    # Should mention ticket details
    assert "Prompt Ticket" in context_msg
    assert "Do it" in context_msg

    # Should include transition options
    assert "Next status you MUST set" in context_msg
    assert "status_id=" in context_msg
    assert "Move to Stage2 when ready" in context_msg

    # Issue #6: Should mention Stage3 even though instructions were empty
    assert '"Stage3"' in context_msg

    # Should include API section (now just 'API:')
    assert "API:" in context_msg
    assert "PUT" in context_msg
    assert "POST" in context_msg
    assert "/api/tickets/" in context_msg

    # Should include done instruction at the end
    assert "add a comment to the ticket" in context_msg

    # Should NOT have redundant "call PUT" in transitions
    assert "call PUT" not in context_msg

    # System prompt should be lean: identity + directives, no status/mandate info
    assert "--system-prompt" in captured_cmd
    idx = captured_cmd.index("--system-prompt")
    system_prompt = captured_cmd[idx + 1]
    assert "You are a test agent." in system_prompt
    assert "CURRENT STATUS MANDATE" not in system_prompt
    assert "ABSOLUTE RULES" not in system_prompt
    assert "Stage1" not in system_prompt

    # Should include working directory in --session-dir
    assert "--session-dir" in captured_cmd


def test_agent_prompt_no_transitions(client, default_workflow, default_board):
    agent = client.post(
        "/api/agents",
        json={
            "name": "NoTransAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "Lonely",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    context_msg = captured_cmd[-1]
    # Should NOT have transitions block since there are none
    assert "Next status you MUST set" not in context_msg


def test_status_goal_included_in_cold_spawn(client, default_workflow, default_board):
    """Issue #4: status goal should appear in the 'Your goal' directive at the end."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "GoalAgent",
            "description": "You are a goal agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "GoalStage",
            "sort_order": 1,
            "agent_id": aid,
            "goal": "Investigate and recommend next steps",
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Goal Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    context_msg = captured_cmd[-1]
    # Goal should appear in the 'Your goal:' directive
    assert "Your goal: GoalStage — Investigate and recommend next steps" in context_msg


def test_status_no_goal_shows_name_only(client, default_workflow, default_board):
    """When status has no goal, just show name in the 'Your goal' directive."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "NoGoalAgent",
            "description": "You are a no-goal agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "NoGoalStage",
            "sort_order": 1,
            "agent_id": aid,
            "goal": "",
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "NoGoal Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    context_msg = captured_cmd[-1]
    # Should show just status name in the goal directive
    assert "Your goal: NoGoalStage" in context_msg
    # Should NOT show a dash with empty goal
    assert "NoGoalStage —" not in context_msg


def test_cold_spawn_prompt_structure(client, default_workflow, default_board):
    """Verify the lean prompt structure: ticket, description, comments, API, goal, transitions, done."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "StructureAgent",
            "description": "You are a structure tester.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "StructStage",
            "sort_order": 1,
            "agent_id": aid,
            "goal": "Do structural things",
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Struct Ticket",
            "body": "Struct body",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    context_msg = captured_cmd[-1]

    # Check lean structure ordering: ticket, description, comments, API, then goal directive
    ticket_pos = context_msg.find("Ticket #")
    desc_pos = context_msg.find("Description:")
    comments_pos = context_msg.find("Comments:")
    api_pos = context_msg.find("API:")
    goal_pos = context_msg.find("Your goal:")

    assert ticket_pos >= 0
    assert desc_pos > ticket_pos
    assert comments_pos > desc_pos
    assert api_pos > comments_pos
    assert goal_pos > api_pos

    # Goal should be at the end, with status name + goal merged
    assert "Your goal: StructStage — Do structural things" in context_msg

    # Should NOT have old-style "Status:" line in context message
    # (it's now in the "Your goal:" directive, not a separate block)
    # The word 'Status' should only appear in the goal directive line, not as a standalone label
    assert "Status: StructStage" not in context_msg

    # Should NOT have redundant "assigned to status"
    assert "assigned to status" not in context_msg

    # Should NOT have "call PUT" in transitions
    assert "call PUT" not in context_msg

    # Should NOT have "Base URL:" (removed, redundant)
    assert "Base URL:" not in context_msg

    # Should NOT have "API endpoints:" (now just "API:")
    assert "API endpoints:" not in context_msg

    # Should have the forget directive for cold spawn
    assert "forget the goals you had from previous prompts" in context_msg

    # Should document the questions endpoint
    assert "/questions" in context_msg
    assert "ask clarifying questions" in context_msg

    # Should have the done instruction at the very end (no transitions available)
    assert "When done: add a comment to the ticket summarizing what you did, then you're finished." in context_msg


def test_warm_spawn_prompt_structure(client, default_workflow, default_board):
    """Verify warm spawn is concise: no full description, no all-comments repeat."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "WarmStructAgent",
            "description": "You are a warm structure tester.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "WarmStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "WarmStage2",
            "sort_order": 2,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Warm Struct Ticket",
            "body": "Warm body",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add comment after first spawn
    client.post(f"/api/tickets/{tid}/comments", json={"body": "New comment"})
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm, status changed)
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        client.put(f"/api/tickets/{tid}", json={"status_id": id2})

    context_msg = captured_cmd[-1]

    # Warm spawn should NOT repeat full description or all comments
    assert "Description:" not in context_msg
    assert "All comments:" not in context_msg

    # Warm spawn should have deltas
    assert "[Update]" in context_msg
    assert "New comments since last update:" in context_msg

    # Warm spawn on status change should use "forget" directive
    assert "forget the goals you had from previous prompts" in context_msg
    assert "Your goal:" in context_msg

    # Warm spawn with --continue omits static API docs and skills blocks
    assert "/questions" not in context_msg
    assert "API:" not in context_msg
    assert "Skills available" not in context_msg
    assert "Previous API docs and skills are available from your session context." in context_msg

    # Warm spawn should NOT have redundant "You have been re-activated"
    assert "re-activated" not in context_msg
    assert "Agent:" not in context_msg

    # Should NOT have "What would you like to do?" (removed)
    assert "What would you like to do?" not in context_msg

    # Should have the done instruction when there are no transitions
    assert "When done: add a comment to the ticket summarizing what you did, then you're finished." in context_msg


# ---------------------------------------------------------------------------
# Status model/thinking override precedence (Ticket #69)
# ---------------------------------------------------------------------------


def test_spawn_agent_status_override_beats_agent_override(client, default_workflow, default_board):
    """Status model/thinking should take precedence over agent model/thinking."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "AgentOverride",
            "description": "You are an agent with overrides.",
            "workflow_id": default_workflow["id"],
            "model": "agent-model",
            "thinking": "low",
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "StatusOverride",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
            "model": "status-model",
            "thinking": "xhigh",
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Override Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    assert "--model" in captured_cmd
    idx = captured_cmd.index("--model")
    assert captured_cmd[idx + 1] == "status-model"

    assert "--thinking" in captured_cmd
    idx = captured_cmd.index("--thinking")
    assert captured_cmd[idx + 1] == "xhigh"


def test_spawn_agent_status_partial_override(client, default_workflow, default_board):
    """Status thinking only should fall back to agent for model."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "PartialAgent",
            "description": "You are a partial agent.",
            "workflow_id": default_workflow["id"],
            "model": "agent-model",
            "thinking": "low",
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "PartialOverride",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
            "thinking": "high",
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Partial Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    assert "--model" in captured_cmd
    idx = captured_cmd.index("--model")
    assert captured_cmd[idx + 1] == "agent-model"

    assert "--thinking" in captured_cmd
    idx = captured_cmd.index("--thinking")
    assert captured_cmd[idx + 1] == "high"


def test_spawn_agent_no_status_override_uses_agent(client, default_workflow, default_board):
    """When status has no overrides, agent overrides should still be used."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "NoStatusOverride",
            "description": "You are a no-status-override agent.",
            "workflow_id": default_workflow["id"],
            "model": "agent-model",
            "thinking": "medium",
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "NoOverride",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "NoOverride Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    assert "--model" in captured_cmd
    idx = captured_cmd.index("--model")
    assert captured_cmd[idx + 1] == "agent-model"

    assert "--thinking" in captured_cmd
    idx = captured_cmd.index("--thinking")
    assert captured_cmd[idx + 1] == "medium"


# ---------------------------------------------------------------------------
# Built-in skills default-enable (Ticket #151)
# ---------------------------------------------------------------------------


def test_spawn_agent_includes_built_in_skills_by_default(client, default_workflow, default_board, temp_skills_folder):
    """Agents should receive built-in skills automatically unless excluded."""
    from pi_cowork.skill_packages import get_built_in_skills_folder

    folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(folder, "auto-skill"), exist_ok=True)
    with open(os.path.join(folder, "auto-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: auto-skill\ndescription: Auto skill\n---\n\nContent.")

    agent = client.post(
        "/api/agents",
        json={
            "name": "AutoSkillAgent",
            "description": "You are an auto-skill agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "AutoSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Auto Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    assert "--skill" in captured_cmd
    idx = captured_cmd.index("--skill")
    assert "auto-skill" in captured_cmd[idx + 1]
    context_msg = captured_cmd[-1]
    assert "Skills available to you:" in context_msg
    assert "auto-skill" in context_msg


def test_spawn_agent_excluded_skill_not_included(client, default_workflow, default_board, temp_skills_folder):
    """Excluded built-in skills should not be passed to the agent."""
    from pi_cowork.skill_packages import get_built_in_skills_folder

    folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(folder, "excluded-skill"), exist_ok=True)
    with open(os.path.join(folder, "excluded-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: excluded-skill\ndescription: Excluded\n---\n\nContent.")
    os.makedirs(os.path.join(folder, "included-skill"), exist_ok=True)
    with open(os.path.join(folder, "included-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: included-skill\ndescription: Included\n---\n\nContent.")

    agent = client.post(
        "/api/agents",
        json={
            "name": "ExcludedSkillAgent",
            "description": "You are an excluded-skill agent.",
            "workflow_id": default_workflow["id"],
            "excluded_skill_names": ["excluded-skill"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ExcludedSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Excluded Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    context_msg = captured_cmd[-1]
    # included-skill should be present
    assert "included-skill" in context_msg
    # excluded-skill should NOT be in context or cmd
    assert "excluded-skill" not in context_msg
    # Verify only included-skill --skill arg is present
    skill_args = [captured_cmd[i + 1] for i in range(len(captured_cmd) - 1) if captured_cmd[i] == "--skill"]
    assert any("included-skill" in s for s in skill_args)
    assert not any("excluded-skill" in s for s in skill_args)


def test_spawn_agent_includes_global_skills_by_default(client, default_workflow, default_board, temp_skills_folder):
    """Global skills should be passed to the agent automatically."""
    global_dir = os.path.join(temp_skills_folder, "global", "global-auto-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-auto-skill\ndescription: Global auto skill\n---\n\nContent.")

    agent = client.post(
        "/api/agents",
        json={
            "name": "GlobalAutoSkillAgent",
            "description": "You are a global auto-skill agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "GlobalAutoSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Global Auto Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    assert "--skill" in captured_cmd
    idx = captured_cmd.index("--skill")
    assert "global-auto-skill" in captured_cmd[idx + 1]
    context_msg = captured_cmd[-1]
    assert "Skills available to you:" in context_msg
    assert "global-auto-skill" in context_msg


def test_spawn_agent_excludes_workflow_skill(client, default_workflow, default_board, temp_skills_folder):
    """Workflow-scoped skills can be excluded via excluded_skill_names."""
    wf_dir = os.path.join(temp_skills_folder, str(default_workflow["id"]), "wf-excluded")
    os.makedirs(wf_dir, exist_ok=True)
    with open(os.path.join(wf_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: wf-excluded\ndescription: WF excluded\n---\n\nContent.")

    agent = client.post(
        "/api/agents",
        json={
            "name": "ExcludeWorkflowSkillAgent",
            "description": "You exclude a workflow skill.",
            "workflow_id": default_workflow["id"],
            "excluded_skill_names": ["wf-excluded"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ExcludeWorkflowSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Exclude Workflow Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    context_msg = captured_cmd[-1]
    assert "wf-excluded" not in context_msg
    skill_args = [captured_cmd[i + 1] for i in range(len(captured_cmd) - 1) if captured_cmd[i] == "--skill"]
    assert not any("wf-excluded" in s for s in skill_args)


def test_spawn_agent_excludes_global_skill(client, default_workflow, default_board, temp_skills_folder):
    """Global skills can be excluded via excluded_skill_names."""
    global_dir = os.path.join(temp_skills_folder, "global", "global-excluded")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-excluded\ndescription: Global excluded\n---\n\nContent.")

    agent = client.post(
        "/api/agents",
        json={
            "name": "ExcludeGlobalSkillAgent",
            "description": "You exclude a global skill.",
            "workflow_id": default_workflow["id"],
            "excluded_skill_names": ["global-excluded"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ExcludeGlobalSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Exclude Global Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    context_msg = captured_cmd[-1]
    assert "global-excluded" not in context_msg
    skill_args = [captured_cmd[i + 1] for i in range(len(captured_cmd) - 1) if captured_cmd[i] == "--skill"]
    assert not any("global-excluded" in s for s in skill_args)


# ---------------------------------------------------------------------------
# Session management: --continue flag and context trimming (Ticket #198)
# ---------------------------------------------------------------------------


def test_warm_spawn_uses_continue_flag(client, default_workflow, default_board):
    """Warm spawn should include --continue in the pi CLI command."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ContinueAgent",
            "description": "You are a continue agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={"name": "ContStage1", "sort_order": 1, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    s2 = client.post(
        "/api/statuses",
        json={"name": "ContStage2", "sort_order": 2, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Continue Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add comment to make it warm
    client.post(f"/api/tickets/{tid}/comments", json={"body": "Follow up"})
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm)
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen), patch("app.os.path.isdir", return_value=True):
        client.put(f"/api/tickets/{tid}", json={"status_id": id2})

    # --continue should be present in warm spawn
    assert "--continue" in captured_cmd


def test_cold_spawn_no_continue(client, default_workflow, default_board):
    """Cold spawn should NOT include --continue in the pi CLI command."""
    agent = client.post(
        "/api/agents",
        json={"name": "NoContAgent", "description": "You are a no-cont agent.", "workflow_id": default_workflow["id"]},
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={"name": "NoContStage", "sort_order": 1, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post("/api/tickets", json={"title": "NoCont Ticket", "board_id": default_board["id"]})
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # --continue should NOT be present in cold spawn
    assert "--continue" not in captured_cmd


def test_warm_spawn_omits_api_docs(client, default_workflow, default_board):
    """Warm spawn with --continue should omit the API docs block from context message."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "OmitApiAgent",
            "description": "You are an omit-api agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={"name": "OmitStage1", "sort_order": 1, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    s2 = client.post(
        "/api/statuses",
        json={"name": "OmitStage2", "sort_order": 2, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]

    ticket = client.post("/api/tickets", json={"title": "OmitApi Ticket", "board_id": default_board["id"]})
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold) — should have API docs
    cold_cmd = []

    def cold_capture(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        cold_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=cold_capture):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    cold_context = cold_cmd[-1]
    assert "API:" in cold_context  # Cold spawn includes API docs

    # Simulate a real pi session file for warm-spawn detection
    _create_dummy_session(aid, tid)

    # Add comment to make it warm
    client.post(f"/api/tickets/{tid}/comments", json={"body": "New info"})
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?", (tid,))
        db.commit()

    # Second spawn (warm) — should omit API docs
    warm_cmd = []

    def warm_capture(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        warm_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=warm_capture), patch("app.os.path.isdir", return_value=True):
        client.put(f"/api/tickets/{tid}", json={"status_id": id2})

    warm_context = warm_cmd[-1]
    # Warm spawn omits API docs and skills metadata blocks
    assert "API:" not in warm_context
    assert "Skills available" not in warm_context
    # But should have the continuity note
    assert "Previous API docs and skills are available from your session context." in warm_context


def test_cold_spawn_cleans_old_session_files(client, default_workflow, default_board):
    """Cold spawn should clean up old .jsonl session files in the session directory."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "CleanupAgent",
            "description": "You are a cleanup agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={"name": "CleanupStage", "sort_order": 1, "agent_id": aid, "workflow_id": default_workflow["id"]},
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post("/api/tickets", json={"title": "Cleanup Ticket", "board_id": default_board["id"]})
    tid = json.loads(ticket.data)["id"]

    # First spawn (cold)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    # Simulate old session files
    session_dir = os.path.join("workspace", ".pi-sessions", str(aid), f"ticket-{tid}")
    old_file1 = os.path.join(session_dir, "old-session.jsonl")
    old_file2 = os.path.join(session_dir, "another-old.jsonl")
    keep_dir = os.path.join(session_dir, "skills", "some-skill")
    os.makedirs(keep_dir, exist_ok=True)
    with open(old_file1, "w") as f:
        f.write("{}")
    with open(old_file2, "w") as f:
        f.write("{}")
    assert os.path.exists(old_file1)
    assert os.path.exists(old_file2)

    # Make last_spawned_at stale so next spawn is cold
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE tickets SET agent_last_spawned_at = datetime('now', '-2 hours') WHERE id = ?", (tid,))
        db.commit()

    # Second spawn (cold because stale) — should clean old .jsonl files
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)), patch("app.os.path.isdir", return_value=True):
        from pi_cowork.agents import try_spawn_or_queue

        with client.application.app_context():
            db = get_db()
            ticket_row = db.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
            status_row = db.execute("SELECT * FROM statuses WHERE id = ?", (id1,)).fetchone()
            agent_row = db.execute("SELECT * FROM agents WHERE id = ?", (aid,)).fetchone()
            try_spawn_or_queue(dict(ticket_row), dict(status_row), dict(agent_row))

    # Old .jsonl files should be removed
    assert not os.path.exists(old_file1)
    assert not os.path.exists(old_file2)
    # Non-jsonl dirs (like skills) should be untouched
    assert os.path.isdir(keep_dir)

    # Cleanup
    import shutil

    shutil.rmtree(session_dir, ignore_errors=True)


def test_different_agent_first_spawn_is_cold(client, default_workflow, default_board):
    """First spawn of agent B on a ticket where agent A was previously spawned.

    Regression test for a bug where agent_last_spawned_at is ticket-level
    (shared across agents) and the session dir was created by mkdir before
    the warm/cold check. This caused agent B's first spawn to be incorrectly
    classified as warm, omitting API docs from the context message even though
    agent B had no previous session to pull them from.
    """
    # Agent A (e.g. Developer)
    agent_a = client.post(
        "/api/agents",
        json={
            "name": "AgentA",
            "description": "You are agent A.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid_a = json.loads(agent_a.data)["id"]

    # Agent B (e.g. Reviewer) — different agent, same ticket
    agent_b = client.post(
        "/api/agents",
        json={
            "name": "AgentB",
            "description": "You are agent B.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid_b = json.loads(agent_b.data)["id"]

    s_a = client.post(
        "/api/statuses",
        json={"name": "StageA", "sort_order": 1, "agent_id": aid_a, "workflow_id": default_workflow["id"]},
    )
    s_b = client.post(
        "/api/statuses",
        json={"name": "StageB", "sort_order": 2, "agent_id": aid_b, "workflow_id": default_workflow["id"]},
    )
    id_a = json.loads(s_a.data)["id"]
    id_b = json.loads(s_b.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Multi-Agent Ticket", "body": "Test body", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    # Spawn agent A (cold spawn)
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id_a})

    # Agent A's session dir now has a .jsonl file (simulated)
    _create_dummy_session(aid_a, tid)

    # Now move to agent B's status — this is agent B's FIRST spawn for this ticket.
    # agent_last_spawned_at is set from agent A's recent spawn, but agent B has
    # no .jsonl session files. This should be a COLD spawn with full API docs.
    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{tid}", json={"status_id": id_b})

    context_msg = captured_cmd[-1]

    # Cold spawn: should include full context with API docs
    assert "API:" in context_msg, "Agent B's first spawn should include API docs (cold spawn)"
    assert "Description:" in context_msg, "Cold spawn should include ticket description"
    assert "[Update]" not in context_msg, "Agent B's first spawn should not be a warm spawn update"
    assert "Previous API docs and skills are available from your session context." not in context_msg, (
        "Agent B has no previous session — should not claim API docs are available"
    )

    # Should NOT include --continue (no previous session for agent B)
    assert "--continue" not in captured_cmd
