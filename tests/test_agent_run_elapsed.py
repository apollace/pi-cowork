"""Tests for Ticket #197: elapsed time in agent runs."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from pi_cowork.models import compute_agent_run_elapsed


def test_compute_agent_run_elapsed_completed():
    """Elapsed for completed run = completed_at - started_at."""
    started = datetime(2026, 6, 23, 6, 0, 0, tzinfo=UTC)
    completed = started + timedelta(seconds=125)
    run = {
        "status": "completed",
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
    }
    assert compute_agent_run_elapsed(run) == 125


def test_compute_agent_run_elapsed_running_uses_now():
    """Running run without completed_at uses current time."""
    started = datetime.now(UTC) - timedelta(seconds=30)
    run = {
        "status": "running",
        "started_at": started.isoformat(),
        "completed_at": None,
    }
    elapsed = compute_agent_run_elapsed(run)
    assert 29 <= elapsed <= 35


def test_compute_agent_run_elapsed_failed_without_completed_at():
    """Failed run without completed_at still uses current time."""
    started = datetime.now(UTC) - timedelta(seconds=10)
    run = {
        "status": "failed",
        "started_at": started.isoformat(),
        "completed_at": None,
    }
    elapsed = compute_agent_run_elapsed(run)
    assert 8 <= elapsed <= 15


def test_compute_agent_run_elapsed_missing_started_at():
    """Missing started_at returns 0."""
    assert compute_agent_run_elapsed({"status": "running", "started_at": None}) == 0
    assert compute_agent_run_elapsed({"status": "completed"}) == 0


def test_compute_agent_run_elapsed_bad_timestamps():
    """Malformed timestamps return 0."""
    run = {
        "status": "completed",
        "started_at": "not-a-date",
        "completed_at": "also-bad",
    }
    assert compute_agent_run_elapsed(run) == 0


def test_ticket_agent_runs_includes_elapsed_seconds_for_running(client, default_workflow, default_board):
    """GET /api/tickets/{id}/agent_runs returns elapsed_seconds for a running run."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ElapsedRunningAgent",
            "description": "You are a running elapsed agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "ElapsedRunningStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Elapsed Running Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": sid})
        assert res.status_code == 200

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert "elapsed_seconds" in run
    assert run["elapsed_seconds"] >= 0
    assert run["status"] == "running"


def test_ticket_agent_runs_includes_elapsed_seconds_for_completed(client, default_workflow, default_board):
    """GET /api/tickets/{id}/agent_runs returns elapsed_seconds for a completed run."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ElapsedCompletedAgent",
            "description": "You are a completed elapsed agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "ElapsedCompletedStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Elapsed Completed Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    started = datetime(2026, 6, 23, 6, 0, 0, tzinfo=UTC)
    completed = started + timedelta(seconds=42)

    import app as app_module

    with client.application.app_context():
        app_module.run_db(
            """
            UPDATE agent_runs
            SET started_at = ?, completed_at = ?, status = 'completed', exit_code = 0
            WHERE ticket_id = ?
            """,
            (started.isoformat(), completed.isoformat(), tid),
        )

    runs_res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "completed"
    assert run["elapsed_seconds"] == 42


def test_running_agent_runs_includes_elapsed_seconds(client, default_workflow, default_board):
    """GET /api/running_agent_runs also includes elapsed_seconds."""
    agent = client.post(
        "/api/agents",
        json={
            "name": "ElapsedRunningPanelAgent",
            "description": "You are a running panel agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    status = client.post(
        "/api/statuses",
        json={
            "name": "ElapsedRunningPanelStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(status.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Elapsed Running Panel Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
        client.put(f"/api/tickets/{tid}", json={"status_id": sid})

    res = client.get(f"/api/running_agent_runs?board_id={default_board['id']}")
    assert res.status_code == 200
    runs = json.loads(res.data)
    assert len(runs) == 1
    assert "elapsed_seconds" in runs[0]
    assert runs[0]["elapsed_seconds"] >= 0
