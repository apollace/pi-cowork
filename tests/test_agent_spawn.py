import json
from unittest.mock import MagicMock, patch


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

    # Questions endpoint should be documented in warm spawn too
    assert f"/api/tickets/{tid}/questions" in context_msg
    assert "ask questions" in context_msg

    # Should include API section (now just 'API:')
    assert "API:" in context_msg

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

    # Should document the questions endpoint in warm spawn too
    assert "/questions" in context_msg

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
