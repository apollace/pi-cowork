"""Tests for auto-captured feedback on gates, kills, and re-runs."""

import json
from unittest.mock import MagicMock, patch

from conftest import HUMAN_ACTION_SECRET_FOR_TESTS

HUMAN_HEADERS = {"Content-Type": "application/json", "X-Human-Action": HUMAN_ACTION_SECRET_FOR_TESTS}


def _create_workflow_with_statuses(client, n_statuses=2):
    """Helper: create a workflow with n_statuses statuses and return ids."""
    res = client.post("/api/workflows", json={"name": "Feedback Test WF"})
    wf = json.loads(res.data)
    wf_id = wf["id"]
    status_ids = []
    for i in range(n_statuses):
        res = client.post(
            "/api/statuses",
            json={
                "name": f"Status {i}",
                "sort_order": i,
                "is_default": 1 if i == 0 else 0,
                "is_terminal": 1 if i == n_statuses - 1 else 0,
                "workflow_id": wf_id,
            },
        )
        status_ids.append(json.loads(res.data)["id"])
    return wf_id, status_ids


def _create_board_with_ticket(client, wf_id, status_id):
    """Helper: create a board and a ticket, return board_id, ticket_id."""
    res = client.post(
        "/api/boards",
        json={
            "name": "Feedback Test Board",
            "workflow_id": wf_id,
            "working_directory": "/tmp",  # noqa: S108
        },
    )
    board_id = json.loads(res.data)["id"]
    res = client.post(
        "/api/tickets",
        json={
            "title": "Test Ticket",
            "board_id": board_id,
        },
    )
    ticket_id = json.loads(res.data)["id"]
    return board_id, ticket_id


def _get_feedback_for_ticket(client, ticket_id):
    """Helper: query agent_feedback rows via model helper (inside app context)."""
    from pi_cowork.models import get_feedback_for_ticket

    with client.application.app_context():
        return get_feedback_for_ticket(ticket_id)


# ── 1. Gate rejection → feedback row ──


def test_gate_rejection_creates_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id = reviews[0]["id"]

    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id}",
            json={"status": "rejected", "comment": "Needs more work"},
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "feedback_id" in data

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 1
    assert feedback[0]["feedback_type"] == "gate_rejected"
    # gate_review_id becomes NULL because gate_reviews are deleted on rejection (ON DELETE SET NULL)
    # The important fields are feedback_type and reason
    assert feedback[0]["reason"] == "Needs more work"
    assert feedback[0]["source_event"] == "GATE_REVIEW_REJECTED"


# ── 2. CLI failure with notify_on_failure=true → feedback row ──


def test_cli_failure_with_notify_creates_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Test Suite",
            "config": json.dumps({"command": "false"}),
            "workflow_id": wf_id,
            "notify_on_failure": True,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "diagnostic"
        mock_result.stderr = "error"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200
    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 1
    assert feedback[0]["feedback_type"] == "cli_failed"
    assert "diagnostic" in feedback[0]["reason"]
    assert feedback[0]["source_event"] == "GATE_FAILED"


# ── 3. CLI failure with notify_on_failure=false → no feedback row ──


def test_cli_failure_without_notify_skips_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "false"}),
            "workflow_id": wf_id,
            "notify_on_failure": False,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "lint error"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200
    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 4. Kill → feedback row; kill reason update works via PUT ──


def test_kill_creates_feedback_and_update_reason(client):
    """Kill an agent run creates feedback; PUT /api/feedback/{id} updates reason."""
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1
    res = client.post(
        "/api/agents",
        json={"name": "Worker", "description": "Does work", "workflow_id": wf_id},
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    # Move ticket to status 1 so agent spawns
    with patch("app.subprocess.Popen") as mock_popen:
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        mock_popen.return_value = fake_proc
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Verify a running agent exists
    runs = json.loads(client.get(f"/api/tickets/{ticket_id}/agent_runs").data)
    assert len(runs) == 1
    run_id = runs[0]["id"]
    assert runs[0]["status"] == "running"

    # Kill the run — we need to mock _is_our_process so it goes down the live-kill path
    with (
        patch("pi_cowork.api.agent_runs._agents_mod._is_our_process", return_value=True),
        patch("os.killpg"),
        patch("pi_cowork.api.agent_runs.time.sleep"),
    ):
        res = client.post(f"/api/agent_runs/{run_id}/kill")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert "feedback_id" in data
    feedback_id = data["feedback_id"]

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 1
    assert feedback[0]["feedback_type"] == "agent_killed"
    assert feedback[0]["run_id"] == run_id
    assert "🛑 Agent killed by user" in feedback[0]["reason"]

    # Update the kill reason
    res = client.put(
        f"/api/feedback/{feedback_id}",
        json={"reason": "It was stuck in a loop", "expected_behavior": "Should have completed"},
    )
    assert res.status_code == 200

    feedback_after = _get_feedback_for_ticket(client, ticket_id)
    assert feedback_after[0]["reason"] == "It was stuck in a loop"
    assert feedback_after[0]["expected_behavior"] == "Should have completed"


# ── 5. Re-run with/without reason → feedback row ──


def test_rerun_without_reason_creates_feedback(client, default_board):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1
    res = client.post(
        "/api/agents",
        json={"name": "Worker", "description": "Does work", "workflow_id": wf_id},
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    # Move ticket to status 1 so agent spawns
    with patch("app.subprocess.Popen") as mock_popen:
        fake_proc = MagicMock()
        fake_proc.pid = 9999
        mock_popen.return_value = fake_proc
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Wait for the run to be marked completed in the test (watcher is mocked)
    # Actually with mock_watcher the run stays running, so let's just call spawn endpoint directly
    res = client.post(f"/api/tickets/{ticket_id}/spawn", json={})
    assert res.status_code == 409  # already running

    # Manually mark the run as completed so we can re-run
    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE agent_runs SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
            (ticket_id,),
        )
        db.commit()

    # Now re-run without reason
    with patch("app.subprocess.Popen"):
        res = client.post(f"/api/tickets/{ticket_id}/spawn", json={})
    assert res.status_code == 200

    feedback = _get_feedback_for_ticket(client, ticket_id)
    rerun_feedback = [f for f in feedback if f["feedback_type"] == "agent_rerun"]
    assert len(rerun_feedback) == 1
    assert rerun_feedback[0]["reason"] is None


def test_rerun_with_reason_creates_feedback(client, default_board):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    res = client.post(
        "/api/agents",
        json={"name": "Worker", "description": "Does work", "workflow_id": wf_id},
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    with patch("app.subprocess.Popen") as mock_popen:
        fake_proc = MagicMock()
        fake_proc.pid = 9999
        mock_popen.return_value = fake_proc
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    from pi_cowork.db import get_db

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE agent_runs SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
            (ticket_id,),
        )
        db.commit()

    with patch("app.subprocess.Popen"):
        res = client.post(
            f"/api/tickets/{ticket_id}/spawn",
            json={"reason": "Previous run produced incomplete output"},
        )
    assert res.status_code == 200

    feedback = _get_feedback_for_ticket(client, ticket_id)
    rerun_feedback = [f for f in feedback if f["feedback_type"] == "agent_rerun"]
    assert len(rerun_feedback) == 1
    assert rerun_feedback[0]["reason"] == "Previous run produced incomplete output"


# ── 6. Quality gates CRUD exposes notify_on_failure ──


def test_quality_gate_crud_exposes_notify_on_failure(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)

    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
            "notify_on_failure": False,
        },
    )
    assert res.status_code == 201
    gate_id = json.loads(res.data)["id"]

    # GET single gate
    res = client.get(f"/api/quality_gates/{gate_id}")
    assert res.status_code == 200
    gate = json.loads(res.data)
    assert gate["notify_on_failure"] == 0 or gate["notify_on_failure"] is False

    # GET list by workflow
    res = client.get(f"/api/quality_gates?workflow_id={wf_id}")
    assert res.status_code == 200
    gates = json.loads(res.data)
    assert any(g["id"] == gate_id and (g["notify_on_failure"] == 0 or g["notify_on_failure"] is False) for g in gates)

    # PUT to toggle
    res = client.put(
        f"/api/quality_gates/{gate_id}",
        json={"notify_on_failure": True},
    )
    assert res.status_code == 200

    res = client.get(f"/api/quality_gates/{gate_id}")
    gate = json.loads(res.data)
    assert gate["notify_on_failure"] == 1 or gate["notify_on_failure"] is True


# ── 7. Export/import preserves notify_on_failure ──


def test_export_import_preserves_notify_on_failure(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "flake8"}),
            "workflow_id": wf_id,
            "sort_order": 0,
            "notify_on_failure": False,
        },
    )

    res = client.get(f"/api/workflows/{wf_id}/export")
    export_data = json.loads(res.data)
    assert "quality_gates" in export_data
    assert len(export_data["quality_gates"]) == 1
    gate = export_data["quality_gates"][0]
    assert gate["notify_on_failure"] == 0 or gate["notify_on_failure"] is False

    res = client.post("/api/workflows/import", json=export_data)
    assert res.status_code == 200
    import_data = json.loads(res.data)
    new_wf_id = import_data["workflow_id"]

    new_gates = json.loads(client.get(f"/api/quality_gates?workflow_id={new_wf_id}").data)
    assert len(new_gates) == 1
    assert new_gates[0]["notify_on_failure"] == 0 or new_gates[0]["notify_on_failure"] is False


# ── 8. Per-gate include_in_feedback is exposed in CRUD ──


def test_quality_gate_crud_exposes_include_in_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)

    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
            "include_in_feedback": False,
        },
    )
    assert res.status_code == 201
    gate_id = json.loads(res.data)["id"]

    res = client.get(f"/api/quality_gates/{gate_id}")
    assert res.status_code == 200
    gate = json.loads(res.data)
    assert gate["include_in_feedback"] == 0 or gate["include_in_feedback"] is False

    res = client.put(
        f"/api/quality_gates/{gate_id}",
        json={"include_in_feedback": True},
    )
    assert res.status_code == 200

    res = client.get(f"/api/quality_gates/{gate_id}")
    gate = json.loads(res.data)
    assert gate["include_in_feedback"] == 1 or gate["include_in_feedback"] is True


# ── 9. Export/import preserves include_in_feedback ──


def test_export_import_preserves_include_in_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "flake8"}),
            "workflow_id": wf_id,
            "sort_order": 0,
            "include_in_feedback": False,
        },
    )

    res = client.get(f"/api/workflows/{wf_id}/export")
    export_data = json.loads(res.data)
    assert "quality_gates" in export_data
    assert len(export_data["quality_gates"]) == 1
    gate = export_data["quality_gates"][0]
    assert gate["include_in_feedback"] == 0 or gate["include_in_feedback"] is False

    res = client.post("/api/workflows/import", json=export_data)
    assert res.status_code == 200
    import_data = json.loads(res.data)
    new_wf_id = import_data["workflow_id"]

    new_gates = json.loads(client.get(f"/api/quality_gates?workflow_id={new_wf_id}").data)
    assert len(new_gates) == 1
    assert new_gates[0]["include_in_feedback"] == 0 or new_gates[0]["include_in_feedback"] is False
