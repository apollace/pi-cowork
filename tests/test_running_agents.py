import json
from datetime import UTC
from unittest.mock import MagicMock, patch

import app as app_module


def test_running_agent_runs_requires_board_id(client):
    """GET /api/running_agent_runs without board_id returns 400."""
    res = client.get("/api/running_agent_runs")
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "board_id is required" in data["error"]


def test_running_agent_runs_empty_when_no_running(client, default_workflow, default_board):
    """GET /api/running_agent_runs returns empty list when no agents are running."""
    res = client.get(f"/api/running_agent_runs?board_id={default_board['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data == []


def test_running_agent_runs_returns_running_only(client, default_workflow, default_board):
    """GET /api/running_agent_runs returns only runs with status=running."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "RunWatcher",
            "description": "You watch.",
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
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Watcher Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Spawn an agent run but keep it "running" by mocking os.kill to succeed
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)), patch("app.os.kill", return_value=None):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": sid})
        assert res.status_code == 200

    # Should appear in running list
    runs_res = client.get(f"/api/running_agent_runs?board_id={default_board['id']}")
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert run["agent_name"] == "RunWatcher"
    assert run["ticket_id"] == tid
    assert run["ticket_title"] == "Watcher Ticket"
    assert run["status_name"] == "WatcherStage"
    assert "started_at" in run


def test_running_agent_runs_excludes_completed(client, default_workflow, default_board):
    """GET /api/running_agent_runs does not include completed/failed runs."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ShortAgent",
            "description": "You are short.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ShortStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Short Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    # Spawn then immediately mock the PID as dead so cleanup marks it completed
    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9998)), patch("app.os.kill", return_value=None):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    # Now mock cleanup to see the process as dead
    with patch("app.os.kill", side_effect=ProcessLookupError):
        import app as app_module

        with client.application.app_context():
            app_module.cleanup_runs()

    runs_res = client.get(f"/api/running_agent_runs?board_id={default_board['id']}")
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 0


def test_live_log_page_renders(client, default_workflow, default_board):
    """GET /agent_run/{id}/live renders the live log template."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "LiveAgent",
            "description": "You are live.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "LiveStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Live Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9997)), patch("app.os.kill", return_value=None):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    # Get the run id
    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    run = json.loads(runs_res.data)[0]

    page_res = client.get(f"/agent_run/{run['id']}/live")
    assert page_res.status_code == 200
    html = page_res.data.decode("utf-8")
    assert "Live Log" in html
    assert "LiveAgent" in html
    assert "Live Ticket" in html
    assert "LiveStage" in html
    # The JS builds the URL dynamically, so just assert the endpoint path fragment appears
    assert "/api/agent_runs/" in html
    assert "/log" in html


def test_live_log_page_404_for_missing_run(client):
    """GET /agent_run/99999/live returns 404."""
    res = client.get("/agent_run/99999/live")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Kill Agent Run Endpoint Tests
# ---------------------------------------------------------------------------


def _spawn_running_agent(client, default_workflow, default_board, pid=12345, agent_name="KillTestAgent"):
    """Helper: create a ticket + status, spawn an agent, and return the run dict."""
    agent = client.post(
        "/api/agents",
        json={
            "name": agent_name,
            "description": "You are a test agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": f"KillStage_{agent_name}",
            "sort_order": 10,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": f"Kill Ticket_{agent_name}",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=pid)), patch("app.os.kill", return_value=None):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    runs = json.loads(runs_res.data)
    assert len(runs) >= 1
    return runs[0]


def test_kill_agent_run_404(client):
    """POST /api/agent_runs/99999/kill returns 404 for nonexistent run."""
    res = client.post("/api/agent_runs/99999/kill")
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "not found" in data["error"].lower()


def test_kill_agent_run_409_not_running(client, default_workflow, default_board):
    """POST /api/agent_runs/<id>/kill returns 409 if run is not in 'running' status."""
    run = _spawn_running_agent(client, default_workflow, default_board)
    run_id = run["id"]
    run["ticket_id"]

    # Mark the run as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', completed_at = ? WHERE id = ?",
            (app_module.datetime.now(UTC).isoformat(), run_id),
        )

    res = client.post(f"/api/agent_runs/{run_id}/kill")
    assert res.status_code == 409
    data = json.loads(res.data)
    assert "not running" in data["error"].lower()


def test_kill_agent_run_400_no_pid(client, default_workflow, default_board):
    """POST /api/agent_runs/<id>/kill returns 400 if run has no PID."""
    run = _spawn_running_agent(client, default_workflow, default_board)
    run_id = run["id"]

    # Set PID to NULL (simulating a process that never started properly)
    with client.application.app_context():
        app_module.run_db("UPDATE agent_runs SET pid = NULL WHERE id = ?", (run_id,))

    res = client.post(f"/api/agent_runs/{run_id}/kill")
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "no pid" in data["error"].lower()


def test_kill_agent_run_success(client, default_workflow, default_board):
    """POST /api/agent_runs/<id>/kill successfully kills a running agent."""
    run = _spawn_running_agent(client, default_workflow, default_board)
    run_id = run["id"]
    ticket_id = run["ticket_id"]

    killpg_mock = MagicMock()
    # _is_our_process returns False after kill (process is dead)
    with (
        patch("app.os.killpg", killpg_mock),
        patch("pi_cowork.agents._is_our_process", side_effect=[True, False]),
        patch("pi_cowork.api.agent_runs.time.sleep"),
    ):  # eliminate real sleeps
        res = client.post(f"/api/agent_runs/{run_id}/kill")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["exit_code"] == -15
    assert data["escalated"] is False

    # Verify DB was updated
    with client.application.app_context():
        db_run = app_module.query_db("SELECT * FROM agent_runs WHERE id = ?", (run_id,), one=True)
        assert db_run["status"] == "failed"
        assert db_run["exit_code"] == -15
        assert db_run["completed_at"] is not None

    # Verify comment was added
    comments_res = client.get(f"/api/tickets/{ticket_id}/comments")
    comments = json.loads(comments_res.data)
    kill_comments = [c for c in comments if "🛑" in c["body"] and "killed by user" in c["body"].lower()]
    assert len(kill_comments) >= 1

    # Verify killpg was called with SIGTERM
    killpg_mock.assert_called_once_with(12345, app_module.signal.SIGTERM)


def test_kill_agent_run_sigkill_escalation(client, default_workflow, default_board):
    """Kill escalates to SIGKILL if process survives SIGTERM."""
    run = _spawn_running_agent(client, default_workflow, default_board, pid=12346)
    run_id = run["id"]
    ticket_id = run["ticket_id"]

    killpg_mock = MagicMock()

    # _is_our_process returns True for all 11 calls (1 initial + 10 loop polls) —
    # process survives SIGTERM, triggering SIGKILL escalation
    with (
        patch("app.os.killpg", killpg_mock),
        patch("pi_cowork.agents._is_our_process", side_effect=[True] * 11),
        patch("pi_cowork.api.agent_runs.time.sleep"),
    ):  # eliminate real 5s sleep
        res = client.post(f"/api/agent_runs/{run_id}/kill")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["exit_code"] == -9
    assert data["escalated"] is True

    # Verify comment mentions escalation
    comments_res = client.get(f"/api/tickets/{ticket_id}/comments")
    comments = json.loads(comments_res.data)
    kill_comments = [c for c in comments if "SIGKILL" in c["body"] and "escalated" in c["body"].lower()]
    assert len(kill_comments) >= 1

    # Verify SIGTERM then SIGKILL were sent (exactly 2 calls)
    assert killpg_mock.call_count == 2
    killpg_mock.assert_any_call(12346, app_module.signal.SIGTERM)
    killpg_mock.assert_any_call(12346, app_module.signal.SIGKILL)


def test_kill_agent_run_pid_already_dead(client, default_workflow, default_board):
    """Kill endpoint handles case where PID is already dead at kill time."""
    run = _spawn_running_agent(client, default_workflow, default_board, pid=12347)
    run_id = run["id"]
    ticket_id = run["ticket_id"]

    # _is_our_process returns False (process already dead)
    with patch("pi_cowork.agents._is_our_process", return_value=False):
        res = client.post(f"/api/agent_runs/{run_id}/kill")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["exit_code"] == -15
    assert data["escalated"] is False

    # Verify DB was updated
    with client.application.app_context():
        db_run = app_module.query_db("SELECT * FROM agent_runs WHERE id = ?", (run_id,), one=True)
        assert db_run["status"] == "failed"
        assert db_run["exit_code"] == -15

    # Verify comment
    comments_res = client.get(f"/api/tickets/{ticket_id}/comments")
    comments = json.loads(comments_res.data)
    kill_comments = [c for c in comments if "🛑" in c["body"] and "already terminated" in c["body"].lower()]
    assert len(kill_comments) >= 1
