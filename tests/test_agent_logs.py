import io
import json
import os
from unittest.mock import MagicMock, patch

from pi_cowork.agents import _read_log


def test_spawn_creates_log_file(client, default_workflow, default_board):
    """Moving a ticket to an agent-backed status creates a log file."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "LogAgent",
            "description": "You are a log agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "LogStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Log Ticket",
            "body": "Test body",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
        assert res.status_code == 200

    # Fetch runs via API
    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "running"
    assert run["log_path"] is not None
    assert os.path.isfile(run["log_path"])


def test_log_contains_preamble_and_prompts(client, default_workflow, default_board):
    """Log file starts with system prompt and context message headers."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "PromptLogAgent",
            "description": "You are a prompt log agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "PromptStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Prompt Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    run = json.loads(runs_res.data)[0]

    with open(run["log_path"]) as f:
        content = f.read()

    assert "=== SYSTEM PROMPT ===" in content
    assert "You are a prompt log agent." in content
    assert "=== CONTEXT MESSAGE ===" in content
    assert "Prompt Ticket" in content
    assert "=== AGENT OUTPUT ===" in content


def test_log_contains_agent_output(client, default_workflow, default_board):
    """Mock agent writes to stdout (the log file); verify it appears after preamble."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "OutputAgent",
            "description": "You are an output agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "OutputStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Output Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    def fake_popen(cmd, **kwargs):
        proc = MagicMock(pid=9999)
        proc.stdout = io.BytesIO(b"FAKE_AGENT_OUTPUT_LINE\n")
        return proc

    with patch("app.subprocess.Popen", side_effect=fake_popen):
        with patch("pi_cowork.agents._start_log_reader", lambda pipe, log_f: _read_log(pipe, log_f)):
            client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    run = json.loads(runs_res.data)[0]

    with open(run["log_path"]) as f:
        content = f.read()

    assert "FAKE_AGENT_OUTPUT_LINE" in content
    # It should come after the agent output header
    agent_output_pos = content.index("=== AGENT OUTPUT ===")
    fake_pos = content.index("FAKE_AGENT_OUTPUT_LINE")
    assert fake_pos > agent_output_pos


def test_failed_spawn_creates_log_with_error(client, default_workflow, default_board):
    """If pi fails to launch, a run row is created with status='failed' and the error in the log."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "FailAgent",
            "description": "You are a fail agent.",
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

    with patch("app.subprocess.Popen", side_effect=FileNotFoundError("pi not found")):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
        assert res.status_code == 200

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "failed"
    assert run["pid"] is None
    assert run["log_path"] is not None
    assert os.path.isfile(run["log_path"])

    with open(run["log_path"]) as f:
        content = f.read()
    assert "Failed to spawn agent" in content
    assert "pi not found" in content

    # A comment should also have been added
    comments_res = client.get(f"/api/tickets/{tid}/comments")
    comments = json.loads(comments_res.data)
    assert any("Failed to spawn" in c["body"] for c in comments)


def test_api_agent_run_log(client, default_workflow, default_board):
    """GET /api/agent_runs/{id}/log returns the log content."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ApiLogAgent",
            "description": "You are an api log agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "ApiStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "API Log Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": id1})

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    run = json.loads(runs_res.data)[0]

    log_res = client.get(f"/api/agent_runs/{run['id']}/log")
    assert log_res.status_code == 200
    assert b"=== SYSTEM PROMPT ===" in log_res.data

    # Non-existent run
    assert client.get("/api/agent_runs/99999/log").status_code == 404


def test_agent_run_sse_stream(client, default_workflow, default_board):
    """GET /api/agent_runs/{id}/stream returns SSE events while run is active,
    and 410 Gone when the run is already completed."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "StreamAgent",
            "description": "You are a stream agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "StreamStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Stream Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    def fake_popen(cmd, **kwargs):
        proc = MagicMock(pid=9999)
        proc.stdout = io.BytesIO(b"STREAM_LINE_1\nSTREAM_LINE_2\n")
        return proc

    with patch("app.subprocess.Popen", side_effect=fake_popen):
        with patch("pi_cowork.agents._start_log_reader", lambda pipe, log_f: _read_log(pipe, log_f)):
            res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
            assert res.status_code == 200

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    run = json.loads(runs_res.data)[0]

    # ── Case 1: run is completed → stream returns 410 Gone immediately
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'completed' WHERE id = ?", (run["id"],))
        db.commit()

    completed_res = client.get(f"/api/agent_runs/{run['id']}/stream")
    assert completed_res.status_code == 410
    body = json.loads(completed_res.data)
    assert body["status"] == "completed"

    # ── Case 2: re-mark as running, open stream, then complete in background
    #    The stream should yield available data then terminate with a done event.
    import threading
    import time as _time

    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE agent_runs SET status = 'running' WHERE id = ?", (run["id"],))
        db.commit()

    def _complete_run_after_delay():
        _time.sleep(0.5)
        with client.application.app_context():
            db = get_db()
            db.execute("UPDATE agent_runs SET status = 'completed' WHERE id = ?", (run["id"],))
            db.commit()

    completer = threading.Thread(target=_complete_run_after_delay, daemon=True)
    completer.start()

    stream_res = client.get(f"/api/agent_runs/{run['id']}/stream")
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.content_type
    content = stream_res.data.decode("utf-8")
    # Should contain data lines from the log
    assert (
        "data: === SYSTEM PROMPT ===" in content
        or "data: STREAM_LINE_1" in content
        or "data: === AGENT OUTPUT ===" in content
    )
    # Should emit done event since run is completed
    assert "event: done" in content

    completer.join(timeout=5)

    # ── Case 3: non-existent run → 404
    res = client.get("/api/agent_runs/99999/stream")
    assert res.status_code == 404
