"""Tests for feedback settings: capture toggle, retention cleanup, and seeding."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from conftest import HUMAN_ACTION_SECRET_FOR_TESTS

HUMAN_HEADERS = {"Content-Type": "application/json", "X-Human-Action": HUMAN_ACTION_SECRET_FOR_TESTS}


def _create_workflow_with_statuses(client, n_statuses=2):
    """Helper: create a workflow with n_statuses statuses and return ids."""
    res = client.post("/api/workflows", json={"name": "Feedback Settings Test WF"})
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
    tmpdir = tempfile.mkdtemp()
    res = client.post(
        "/api/boards",
        json={
            "name": "Feedback Settings Test Board",
            "workflow_id": wf_id,
            "working_directory": tmpdir,
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


# ── 1. Schema seeds feedback settings on init ──


def test_settings_seeded_on_init(client):
    """The DB schema should seed feedback_capture_enabled and feedback_retention_days."""
    for key in ["feedback_capture_enabled", "feedback_retention_days"]:
        res = client.get(f"/api/settings/{key}")
        assert res.status_code == 200, f"Setting {key} not seeded"
        data = json.loads(res.data)
        assert data["value"] is not None


# ── 2. Global feedback capture disabled → no feedback on gate rejection ──


def test_global_feedback_disabled_skips_gate_rejection_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )
    json.loads(res.data)["id"]

    # Disable global feedback capture
    client.put("/api/settings/feedback_capture_enabled", json={"value": "0"})

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
    # feedback_id should be None when capture is disabled
    assert data.get("feedback_id") is None

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 3. Per-gate include_in_feedback=false → no feedback even when global is on ──


def test_per_gate_feedback_disabled_skips_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

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
    json.loads(res.data)["id"]

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
    assert data.get("feedback_id") is None

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 4. Global feedback disabled → no CLI failure feedback ──


def test_global_feedback_disabled_skips_cli_failure_feedback(client):
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

    # Disable global feedback capture
    client.put("/api/settings/feedback_capture_enabled", json={"value": "0"})

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "diagnostic"
        mock_result.stderr = "error"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200
    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 5. Global feedback disabled → no kill feedback ──


def test_global_feedback_disabled_skips_kill_feedback(client):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1
    res = client.post(
        "/api/agents",
        json={"name": "Worker", "description": "Does work", "workflow_id": wf_id},
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    with patch("app.subprocess.Popen") as mock_popen:
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        mock_popen.return_value = fake_proc
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    runs = json.loads(client.get(f"/api/tickets/{ticket_id}/agent_runs").data)
    assert len(runs) == 1
    run_id = runs[0]["id"]

    # Disable global feedback capture
    client.put("/api/settings/feedback_capture_enabled", json={"value": "0"})

    with (
        patch("pi_cowork.api.agent_runs._agents_mod._is_our_process", return_value=True),
        patch("os.killpg"),
        patch("pi_cowork.api.agent_runs.time.sleep"),
    ):
        res = client.post(f"/api/agent_runs/{run_id}/kill")

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("feedback_id") is None

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 6. Global feedback disabled → no rerun feedback ──


def test_global_feedback_disabled_skips_rerun_feedback(client):
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

    # Disable global feedback capture
    client.put("/api/settings/feedback_capture_enabled", json={"value": "0"})

    with patch("app.subprocess.Popen"):
        res = client.post(f"/api/tickets/{ticket_id}/spawn", json={"reason": "Re-running"})
    assert res.status_code == 200

    feedback = _get_feedback_for_ticket(client, ticket_id)
    assert len(feedback) == 0


# ── 7. Cleanup old feedback respects retention days ──


def test_cleanup_old_feedback_deletes_stale_rows(client):
    """cleanup_old_feedback should delete rows older than retention days."""
    from pi_cowork.db import get_db
    from pi_cowork.models import cleanup_old_feedback

    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    with client.application.app_context():
        db = get_db()
        # Insert an old feedback row (40 days ago)
        old_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        db.execute(
            "INSERT INTO agent_feedback (ticket_id, feedback_type, created_at) VALUES (?, ?, ?)",
            (ticket_id, "cli_failed", old_ts),
        )
        # Insert a recent feedback row (1 day ago)
        recent_ts = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO agent_feedback (ticket_id, feedback_type, created_at) VALUES (?, ?, ?)",
            (ticket_id, "cli_failed", recent_ts),
        )
        db.commit()

        # With default 30 days retention, only the old row should be deleted
        deleted = cleanup_old_feedback(max_age_days=30)
        assert deleted == 1

        # Verify remaining row
        rows = db.execute("SELECT * FROM agent_feedback WHERE ticket_id = ?", (ticket_id,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["created_at"] == recent_ts


# ── 8. Cleanup old feedback with custom retention ──


def test_cleanup_old_feedback_custom_retention(client):
    """cleanup_old_feedback should accept explicit max_age_days."""
    from pi_cowork.db import get_db
    from pi_cowork.models import cleanup_old_feedback

    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    with client.application.app_context():
        db = get_db()
        # Insert a row from 5 days ago
        ts = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        db.execute(
            "INSERT INTO agent_feedback (ticket_id, feedback_type, created_at) VALUES (?, ?, ?)",
            (ticket_id, "cli_failed", ts),
        )
        db.commit()

        deleted = cleanup_old_feedback(max_age_days=3)
        assert deleted == 1

        rows = db.execute("SELECT * FROM agent_feedback WHERE ticket_id = ?", (ticket_id,)).fetchall()
        assert len(rows) == 0


# ── 9. Settings page includes Self-Improvement category ──


def test_settings_page_has_self_improvement_category(client):
    res = client.get("/settings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert 'id="category-feedback"' in html
    assert 'id="detail-feedback"' in html
    assert "🧠 Self-Improvement" in html
    assert "cfg-feedback-capture-enabled" in html
    assert "cfg-feedback-retention-days" in html
