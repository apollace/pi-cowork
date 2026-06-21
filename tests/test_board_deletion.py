"""Tests for full destructive board deletion (Ticket #190)."""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import app as app_module


def _create_agent_status(client, workflow_id, name="DestroyAgent"):
    """Create an agent and a status that triggers it."""
    agent_res = client.post(
        "/api/agents",
        json={"name": name, "description": "You test destruction.", "workflow_id": workflow_id},
    )
    agent_id = json.loads(agent_res.data)["id"]
    status_res = client.post(
        "/api/statuses",
        json={
            "name": f"{name}Stage",
            "sort_order": 100,
            "agent_id": agent_id,
            "workflow_id": workflow_id,
        },
    )
    status_id = json.loads(status_res.data)["id"]
    return agent_id, status_id


def _spawn_running_agent(client, board_id, workflow_id, working_dir=None, pid=99999, agent_name="DestroyAgent"):
    """Create a ticket on the board, move it to an agent status, and return (ticket_id, run_id)."""
    agent_id, status_id = _create_agent_status(client, workflow_id, agent_name)
    ticket_res = client.post("/api/tickets", json={"title": f"Ticket for {agent_name}", "board_id": board_id})
    ticket_id = json.loads(ticket_res.data)["id"]

    with patch("app.subprocess.Popen", return_value=MagicMock(pid=pid)), patch("app.os.kill", return_value=None):
        move_res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_id})
    assert move_res.status_code == 200

    runs_res = client.get(f"/api/tickets/{ticket_id}/agent_runs")
    runs = json.loads(runs_res.data)
    assert len(runs) >= 1
    run = [r for r in runs if r["status"] == "running"][0]
    return ticket_id, run["id"], run["agent_id"]


def test_delete_board_destroys_tickets(client, default_workflow):
    """Deleting a board removes all its tickets."""
    board_res = client.post(
        "/api/boards",
        json={"name": "Destroyable", "workflow_id": default_workflow["id"]},
    )
    board_id = json.loads(board_res.data)["id"]
    client.post("/api/tickets", json={"title": "Ticket 1", "board_id": board_id})
    client.post("/api/tickets", json={"title": "Ticket 2", "board_id": board_id})

    del_res = client.delete(f"/api/boards/{board_id}")
    assert del_res.status_code == 200

    list_res = client.get(f"/api/tickets?board_id={board_id}")
    assert json.loads(list_res.data) == []


def test_delete_board_cleans_up_gate_reviews(client):
    """Gate reviews for the board's tickets are deleted with the board."""
    wf_res = client.post("/api/workflows", json={"name": "Gate Cleanup WF"})
    wf_id = json.loads(wf_res.data)["id"]

    s1_res = client.post(
        "/api/statuses",
        json={"name": "From", "sort_order": 1, "is_default": 1, "workflow_id": wf_id},
    )
    from_status_id = json.loads(s1_res.data)["id"]
    s2_res = client.post(
        "/api/statuses",
        json={"name": "To", "sort_order": 2, "workflow_id": wf_id},
    )
    to_status_id = json.loads(s2_res.data)["id"]

    board_res = client.post(
        "/api/boards",
        json={"name": "Gated", "workflow_id": wf_id},
    )
    board_id = json.loads(board_res.data)["id"]
    ticket_res = client.post(
        "/api/tickets",
        json={"title": "Gated Ticket", "board_id": board_id, "status_id": from_status_id},
    )
    ticket_id = json.loads(ticket_res.data)["id"]

    gate_res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": from_status_id,
            "to_status_id": to_status_id,
            "gate_type": "manual",
            "name": "Human Gate",
            "workflow_id": wf_id,
        },
    )
    gate_id = json.loads(gate_res.data)["id"]

    # Trigger a gate review by attempting the transition.
    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": to_status_id})
    reviews_before = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews_before) == 1
    assert reviews_before[0]["gate_id"] == gate_id

    del_res = client.delete(f"/api/boards/{board_id}")
    assert del_res.status_code == 200

    reviews_after = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert reviews_after == []


def test_delete_board_kills_running_agents(client, default_workflow):
    """Deleting a board terminates running agents before their rows are removed."""
    board_res = client.post(
        "/api/boards",
        json={"name": "Running", "workflow_id": default_workflow["id"]},
    )
    board_id = json.loads(board_res.data)["id"]
    ticket_id, run_id, _agent_id = _spawn_running_agent(client, board_id, default_workflow["id"], pid=12345)

    killpg_mock = MagicMock()
    with (
        patch("pi_cowork.board_cleanup.os.killpg", killpg_mock),
        patch("pi_cowork.agents._is_our_process", side_effect=[True, False]),
    ):
        del_res = client.delete(f"/api/boards/{board_id}")

    assert del_res.status_code == 200

    # SIGTERM was sent to the running process.
    killpg_mock.assert_called_once_with(12345, app_module.signal.SIGTERM)

    # Agent run and ticket rows are gone.
    with client.application.app_context():
        runs = app_module.query_db("SELECT * FROM agent_runs WHERE id = ?", (run_id,), one=True)
        tickets = app_module.query_db("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
    assert runs is None
    assert tickets is None


def test_delete_board_removes_pi_logs_and_sessions(client, default_workflow):
    """Board deletion removes on-disk .pi-logs and .pi-sessions directories."""
    tmpdir = tempfile.mkdtemp(prefix="pi-cowork-board-cleanup-")
    try:
        board_res = client.post(
            "/api/boards",
            json={"name": "Files", "workflow_id": default_workflow["id"], "working_directory": tmpdir},
        )
        board_id = json.loads(board_res.data)["id"]
        ticket_id, _run_id, agent_id = _spawn_running_agent(
            client, board_id, default_workflow["id"], working_dir=tmpdir, pid=12346, agent_name="FilesAgent"
        )

        board_dir = Path(tmpdir).resolve()
        logs_dir = board_dir / ".pi-logs" / f"ticket-{ticket_id}"
        session_dir = board_dir / ".pi-sessions" / str(agent_id) / f"ticket-{ticket_id}"
        assistant_session = board_dir / ".pi-sessions" / f"assistant-board-{board_id}"

        # Pre-create the directories so the test can verify deletion.
        logs_dir.mkdir(parents=True, exist_ok=True)
        session_dir.mkdir(parents=True, exist_ok=True)
        assistant_session.mkdir(parents=True, exist_ok=True)
        assert logs_dir.exists()
        assert session_dir.exists()
        assert assistant_session.exists()

        with (
            patch("pi_cowork.board_cleanup.os.killpg", MagicMock()),
            patch("pi_cowork.agents._is_our_process", return_value=False),
        ):
            del_res = client.delete(f"/api/boards/{board_id}")
        assert del_res.status_code == 200

        assert not logs_dir.exists()
        assert not session_dir.exists()
        assert not assistant_session.exists()
        # Parent workspace directories are intentionally preserved.
        assert (board_dir / ".pi-logs").exists()
        assert (board_dir / ".pi-sessions").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_delete_board_removes_notification_dismissals(client, default_workflow):
    """Notification dismissals for the board's tickets are removed."""
    board_res = client.post(
        "/api/boards",
        json={"name": "Dismissals", "workflow_id": default_workflow["id"]},
    )
    board_id = json.loads(board_res.data)["id"]
    ticket_res = client.post("/api/tickets", json={"title": "Dismissal Ticket", "board_id": board_id})
    ticket_id = json.loads(ticket_res.data)["id"]

    with client.application.app_context():
        app_module.run_db(
            "INSERT INTO notification_dismissals "
            "(ticket_id, notification_type, dismissed_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (ticket_id, "question"),
        )
        before = app_module.query_db(
            "SELECT * FROM notification_dismissals WHERE ticket_id = ?", (ticket_id,), one=True
        )
        assert before is not None

    del_res = client.delete(f"/api/boards/{board_id}")
    assert del_res.status_code == 200

    with client.application.app_context():
        after = app_module.query_db("SELECT * FROM notification_dismissals WHERE ticket_id = ?", (ticket_id,), one=True)
    assert after is None


def test_delete_board_does_not_affect_other_boards(client, default_workflow):
    """Deleting one board leaves another board's tickets, runs, and files intact."""
    tmpdir = tempfile.mkdtemp(prefix="pi-cowork-board-isolation-")
    try:
        b1_res = client.post(
            "/api/boards",
            json={"name": "Keep", "workflow_id": default_workflow["id"], "working_directory": tmpdir},
        )
        b1_id = json.loads(b1_res.data)["id"]
        b2_res = client.post(
            "/api/boards",
            json={"name": "Destroy", "workflow_id": default_workflow["id"], "working_directory": tmpdir},
        )
        b2_id = json.loads(b2_res.data)["id"]

        keep_ticket_id, _run_id, keep_agent_id = _spawn_running_agent(
            client, b1_id, default_workflow["id"], working_dir=tmpdir, pid=22345, agent_name="KeepAgent"
        )
        destroy_ticket_id, _run_id2, _destroy_agent_id = _spawn_running_agent(
            client, b2_id, default_workflow["id"], working_dir=tmpdir, pid=22346, agent_name="DestroyAgent"
        )

        board_dir = Path(tmpdir).resolve()
        keep_logs = board_dir / ".pi-logs" / f"ticket-{keep_ticket_id}"
        keep_session = board_dir / ".pi-sessions" / str(keep_agent_id) / f"ticket-{keep_ticket_id}"
        keep_logs.mkdir(parents=True, exist_ok=True)
        keep_session.mkdir(parents=True, exist_ok=True)

        with (
            patch("pi_cowork.board_cleanup.os.killpg", MagicMock()),
            patch("pi_cowork.agents._is_our_process", return_value=False),
        ):
            del_res = client.delete(f"/api/boards/{b2_id}")
        assert del_res.status_code == 200

        # b1 ticket still exists.
        t1_res = client.get(f"/api/tickets?board_id={b1_id}")
        t1 = json.loads(t1_res.data)
        assert len(t1) == 1
        assert t1[0]["id"] == keep_ticket_id

        # b2 ticket is gone.
        t2_res = client.get(f"/api/tickets?board_id={b2_id}")
        assert json.loads(t2_res.data) == []

        # Files for b1 are preserved.
        assert keep_logs.exists()
        assert keep_session.exists()
        # Files for b2 are gone.
        assert not (board_dir / ".pi-logs" / f"ticket-{destroy_ticket_id}").exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_delete_board_is_idempotent_for_missing_files(client, default_workflow):
    """Deleting a board whose working directory is already gone still succeeds."""
    tmpdir = tempfile.mkdtemp(prefix="pi-cowork-board-missing-")
    try:
        board_res = client.post(
            "/api/boards",
            json={"name": "MissingFiles", "workflow_id": default_workflow["id"], "working_directory": tmpdir},
        )
        board_id = json.loads(board_res.data)["id"]
        ticket_res = client.post("/api/tickets", json={"title": "Orphan Ticket", "board_id": board_id})
        assert ticket_res.status_code == 201

        # Remove working directory before deleting the board.
        shutil.rmtree(tmpdir)

        del_res = client.delete(f"/api/boards/{board_id}")
        assert del_res.status_code == 200

        list_res = client.get(f"/api/tickets?board_id={board_id}")
        assert json.loads(list_res.data) == []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
