"""Tests for ticket #41: Remove the re-run button from inside agent runs.

Verifies that:
  1. The per-card "🔄 Re-run" button is NOT rendered in agent run cards
  2. The `rerunAgent()` JS function is NOT present in the ticket detail page
  3. The header "Re-run Agent" button (rerun-agent-btn) IS still present
  4. The API/backend re-run functionality is unaffected
"""

import json
from unittest.mock import MagicMock, patch


def _create_agent(client, workflow_id, name="TestAgent", description="You are a test agent."):
    res = client.post(
        "/api/agents",
        json={
            "name": name,
            "description": description,
            "workflow_id": workflow_id,
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)


def _create_status_with_agent(client, workflow_id, agent_id, name="SpawnStage", sort_order=99, is_terminal=False):
    res = client.post(
        "/api/statuses",
        json={
            "name": name,
            "sort_order": sort_order,
            "agent_id": agent_id,
            "is_terminal": is_terminal,
            "workflow_id": workflow_id,
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)


def _create_ticket(client, board_id, title="NoPerRunRerun Ticket"):
    res = client.post(
        "/api/tickets",
        json={
            "title": title,
            "board_id": board_id,
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)


# ---------------------------------------------------------------------------
# Frontend: per-card re-run button is removed
# ---------------------------------------------------------------------------


def test_per_card_rerun_button_removed_from_html(client, default_board):
    """The ticket detail page should NOT contain per-agent-run re-run buttons
    (onclick='rerunAgent()') inside agent run cards."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # The per-card button used onclick="rerunAgent()" — must NOT be present
    assert 'onclick="rerunAgent()"' not in html, (
        "Per-card re-run button (onclick='rerunAgent()') should be removed from agent run cards"
    )


def test_rerunAgent_function_removed_from_js(client, default_board):
    """The `rerunAgent()` JavaScript function should not exist in the page."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "async function rerunAgent()" not in html, (
        "The rerunAgent() function should be removed (dead code after per-card button removal)"
    )


def test_header_rerun_button_still_present(client, default_board):
    """The header 'Re-run Agent' button (rerun-agent-btn) must remain in the page."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "rerun-agent-btn" in html, "The header re-run agent button should still be present"


def test_no_rerun_text_inside_agent_run_cards(client, default_workflow, default_board):
    """With agent runs present, the agent run cards should not contain '🔄 Re-run' text."""
    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    # Spawn agent
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20001)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    # Mark agent as completed
    import app as app_module

    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )

    # Fetch the page and verify no per-card re-run button in the HTML
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # The header button says "🔄 Re-run Agent" with ID rerun-agent-btn — that's fine.
    # The per-card button said "🔄 Re-run" (without "Agent") — that must be gone.
    # We check that within the agent-runs-section div, there's no re-run button.
    agent_runs_start = html.find('id="agent-runs-section"')
    agent_runs_end = html.find("</section>", agent_runs_start) if agent_runs_start != -1 else -1
    if agent_runs_start != -1 and agent_runs_end != -1:
        agent_runs_html = html[agent_runs_start:agent_runs_end]
        assert "🔄 Re-run" not in agent_runs_html, (
            "Per-card '🔄 Re-run' button should not appear inside the Agent Runs section"
        )


def test_log_button_still_present_in_completed_runs(client, default_workflow, default_board):
    """After removing re-run, the '📋 Log' button should still be in completed run cards."""
    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    # Spawn agent
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20002)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    # Mark agent as completed
    import app as app_module

    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )

    # The "📋 Log" toggle button should still be dynamically rendered via JS.
    # We verify the toggleRunLog function still exists in the page source.
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "toggleRunLog" in html, "The toggleRunLog function should still exist for the Log button"


# ---------------------------------------------------------------------------
# Backend: re-run API still works (header button uses it)
# ---------------------------------------------------------------------------


def test_rerun_via_spawn_api_still_works(client, default_workflow, default_board):
    """Re-running via the /spawn API (used by header button) should still work."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    # First spawn
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20010)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    # Mark as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )

    # Re-run via spawn endpoint (same endpoint the header button calls)
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20011)
        res = client.post(f"/api/tickets/{tid}/spawn")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

    # Should have 2 runs now
    res = client.get(f"/api/tickets/{tid}/agent_runs")
    runs = json.loads(res.data)
    assert len(runs) == 2
