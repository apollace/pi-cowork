"""Tests for Manual Run Feedback UI (ticket #178).

Covers:
  - API: POST /api/feedback creates run_feedback rows
  - API: 400 on missing reason, 404 on invalid run/ticket
  - API: has_feedback in agent runs list response
  - Frontend: feedback modal HTML in ticket detail page
  - Frontend: feedback button classes in CSS
"""

import json
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _create_ticket(client, board_id, title="Feedback Ticket"):
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
# POST /api/feedback
# ---------------------------------------------------------------------------


def test_create_feedback_success(client, default_workflow, default_board):
    """Successful POST creates a run_feedback row and returns 201."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    # Spawn agent to create a run
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20001)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    # Mark run as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, "
            "completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )
        rows = app_module.query_db("SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (tid,))
        run_id = rows[0]["id"]

    res = client.post(
        "/api/feedback",
        json={
            "run_id": run_id,
            "ticket_id": tid,
            "reason": "The agent missed the key requirement.",
            "expected_behavior": "Should have asked about the database first.",
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert "feedback_id" in data
    assert isinstance(data["feedback_id"], int)

    # Verify DB row
    with client.application.app_context():
        row = app_module.query_db("SELECT * FROM agent_feedback WHERE id = ?", (data["feedback_id"],), one=True)
        assert row["feedback_type"] == "run_feedback"
        assert row["run_id"] == run_id
        assert row["ticket_id"] == tid
        assert row["reason"] == "The agent missed the key requirement."
        assert row["expected_behavior"] == "Should have asked about the database first."
        assert row["source_event"] == "MANUAL_RUN_FEEDBACK"
        assert row["created_by"] == "human"


def test_create_feedback_missing_reason(client, default_workflow, default_board):
    """POST without reason returns 400."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20002)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    with client.application.app_context():
        rows = app_module.query_db("SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (tid,))
        run_id = rows[0]["id"]

    res = client.post(
        "/api/feedback",
        json={
            "run_id": run_id,
            "ticket_id": tid,
            "reason": "",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "error" in data


def test_create_feedback_missing_run_id(client, default_board):
    """POST without run_id returns 400."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    res = client.post(
        "/api/feedback",
        json={
            "ticket_id": tid,
            "reason": "Something went wrong.",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "run_id" in data["error"].lower()


def test_create_feedback_missing_ticket_id(client, default_workflow, default_board):
    """POST without ticket_id returns 400."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20003)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    with client.application.app_context():
        rows = app_module.query_db("SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (tid,))
        run_id = rows[0]["id"]

    res = client.post(
        "/api/feedback",
        json={
            "run_id": run_id,
            "reason": "Something went wrong.",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "ticket_id" in data["error"].lower()


def test_create_feedback_run_not_found(client, default_board):
    """POST with run_id that doesn't belong to ticket returns 404."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    res = client.post(
        "/api/feedback",
        json={
            "run_id": 999999,
            "ticket_id": tid,
            "reason": "Something went wrong.",
        },
    )
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "error" in data


def test_create_feedback_run_belongs_to_other_ticket(client, default_workflow, default_board):
    """POST with a valid run_id that belongs to a different ticket returns 404."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket1 = _create_ticket(client, default_board["id"], title="Ticket 1")
    ticket2 = _create_ticket(client, default_board["id"], title="Ticket 2")

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20004)
        client.put(f"/api/tickets/{ticket1['id']}", json={"status_id": status["id"]})

    with client.application.app_context():
        rows = app_module.query_db(
            "SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket1["id"],)
        )
        run_id = rows[0]["id"]

    # Try to submit feedback for ticket2 using run_id from ticket1
    res = client.post(
        "/api/feedback",
        json={
            "run_id": run_id,
            "ticket_id": ticket2["id"],
            "reason": "Something went wrong.",
        },
    )
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "not found" in data["error"].lower()


# ---------------------------------------------------------------------------
# GET /api/tickets/<id>/agent_runs — has_feedback field
# ---------------------------------------------------------------------------


def test_agent_runs_has_feedback_false(client, default_workflow, default_board):
    """has_feedback is false when no run_feedback exists."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20010)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, "
            "completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )

    res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert res.status_code == 200
    runs = json.loads(res.data)
    assert len(runs) == 1
    assert runs[0]["has_feedback"] == 0


def test_agent_runs_has_feedback_true(client, default_workflow, default_board):
    """has_feedback is true after run_feedback is created."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20011)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, "
            "completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )
        rows = app_module.query_db("SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (tid,))
        run_id = rows[0]["id"]

    # Create feedback
    res = client.post(
        "/api/feedback",
        json={
            "run_id": run_id,
            "ticket_id": tid,
            "reason": "Missed requirement.",
        },
    )
    assert res.status_code == 201

    res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert res.status_code == 200
    runs = json.loads(res.data)
    assert len(runs) == 1
    assert runs[0]["has_feedback"] == 1


def test_agent_runs_has_feedback_only_run_feedback_counts(client, default_workflow, default_board):
    """has_feedback is false when feedback exists but is not run_feedback type."""
    import app as app_module

    agent = _create_agent(client, default_workflow["id"])
    status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]

    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=20012)
        client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, "
            "completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,),
        )
        rows = app_module.query_db("SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (tid,))
        run_id = rows[0]["id"]

        # Insert a non-run_feedback row
        app_module.run_db(
            "INSERT INTO agent_feedback (ticket_id, run_id, feedback_type, reason, created_by) "
            "VALUES (?, ?, 'agent_killed', 'Killed by user', 'human')",
            (tid, run_id),
        )

    res = client.get(f"/api/tickets/{tid}/agent_runs")
    assert res.status_code == 200
    runs = json.loads(res.data)
    assert len(runs) == 1
    assert runs[0]["has_feedback"] == 0


# ---------------------------------------------------------------------------
# Frontend: ticket detail HTML
# ---------------------------------------------------------------------------


def test_ticket_detail_includes_feedback_modal(client, default_board):
    """Ticket detail page includes the feedback modal markup."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "feedback-modal" in html, "Feedback modal should be in ticket detail HTML"
    assert "feedback-reason" in html, "Feedback reason textarea should exist"
    assert "feedback-expected" in html, "Feedback expected textarea should exist"
    assert "feedback-submit-btn" in html, "Feedback submit button should exist"
    assert "feedback-cancel-btn" in html, "Feedback cancel button should exist"
    assert "Give Feedback" in html, "Modal title should be present"


def test_ticket_detail_includes_feedback_button_in_agent_runs(client, default_workflow, default_board):
    """Ticket detail page JS includes the feedback button rendering logic."""
    ticket = _create_ticket(client, default_board["id"])
    tid = ticket["id"]
    res = client.get(f"/ticket/{tid}")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "openFeedbackModal" in html, "openFeedbackModal function should exist"
    assert "give-feedback" in html, "give-feedback CSS class should be referenced"
    assert "feedback-submitted" in html, "feedback-submitted CSS class should be referenced"


# ---------------------------------------------------------------------------
# Frontend: CSS classes
# ---------------------------------------------------------------------------


def test_css_includes_feedback_button_styles():
    """The stylesheet includes feedback button styles."""
    import os

    style_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "style.css")
    with open(style_path) as f:
        css = f.read()
    assert ".btn.give-feedback" in css, "give-feedback button styles should exist"
    assert ".btn.feedback-submitted" in css, "feedback-submitted button styles should exist"
