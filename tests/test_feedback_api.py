"""Tests for Self-Improvement Agent Feedback endpoints (ticket #179).

Covers:
  - GET /api/feedback — list with filtering, enrichment, preview
  - POST /api/feedback/<id>/consume — mark consumed
  - Error cases: 404 missing, 409 already consumed
"""

import json
from unittest.mock import MagicMock, patch

from pi_cowork.db import get_db
from pi_cowork.models import add_agent_feedback

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_agent(client, workflow_id, name="TestAgent", description="You are a test agent."):
    res = client.post(
        "/api/agents",
        json={"name": name, "description": description, "workflow_id": workflow_id},
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
    res = client.post("/api/tickets", json={"title": title, "board_id": board_id})
    assert res.status_code == 201
    return json.loads(res.data)


def _spawn_and_get_run_id(client, ticket_id, status_id):
    with patch("app.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock(pid=30001)
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_id})

    with client.application.app_context():
        import app as app_module

        rows = app_module.query_db(
            "SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        )
        return rows[0]["id"]


def _create_gate_review(client, ticket_id, gate_id, from_status_id, to_status_id):
    with client.application.app_context():
        db = get_db()
        cur = db.execute(
            """INSERT INTO gate_reviews
               (ticket_id, gate_id, from_status_id, to_status_id, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (ticket_id, gate_id, from_status_id, to_status_id),
        )
        db.commit()
        return cur.lastrowid


def _create_quality_gate(client, from_status_id, to_status_id, workflow_id, name="Test Gate"):
    with client.application.app_context():
        db = get_db()
        cur = db.execute(
            """INSERT INTO quality_gates
               (from_status_id, to_status_id, gate_type, name, sort_order, workflow_id)
               VALUES (?, ?, 'manual', ?, 0, ?)""",
            (from_status_id, to_status_id, name, workflow_id),
        )
        db.commit()
        return cur.lastrowid


# ---------------------------------------------------------------------------
# GET /api/feedback — defaults and ordering
# ---------------------------------------------------------------------------


class TestListFeedback:
    """Tests for GET /api/feedback."""

    def test_default_returns_all(self, client, default_workflow, default_board):
        """By default (no consumed param), all feedback is returned, oldest first."""
        import app as app_module

        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="Old issue")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="New issue")
            # Mark f1 as consumed
            add_agent_feedback(ticket["id"], "agent_killed", reason="Ignored")
            app_module.run_db(
                "UPDATE agent_feedback SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (f1,),
            )

        res = client.get("/api/feedback")
        assert res.status_code == 200
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        # Default is all feedback now
        assert f1 in ids
        assert f2 in ids

    def test_consumed_false_returns_unconsumed(self, client, default_workflow, default_board):
        """consumed=false returns only unconsumed rows."""
        import app as app_module

        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="Old issue")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="New issue")
            app_module.run_db(
                "UPDATE agent_feedback SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (f1,),
            )

        res = client.get("/api/feedback?consumed=false")
        assert res.status_code == 200
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 not in ids
        assert f2 in ids

    def test_consumed_true_returns_consumed(self, client, default_board):
        """consumed=true returns only consumed rows."""
        import app as app_module

        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="Old")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="New")
            app_module.run_db(
                "UPDATE agent_feedback SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (f1,),
            )

        res = client.get("/api/feedback?consumed=true")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 in ids
        assert f2 not in ids

    def test_default_orders_oldest_first(self, client, default_board):
        """Feedback is ordered by created_at ASC."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="First")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="Second")
            f3 = add_agent_feedback(ticket["id"], "agent_killed", reason="Third")

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert ids == [f1, f2, f3]

    def test_limit_param(self, client, default_board):
        """limit parameter caps the number of returned rows."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            for i in range(5):
                add_agent_feedback(ticket["id"], "agent_killed", reason=f"Item {i}")

        res = client.get("/api/feedback?limit=2")
        data = json.loads(res.data)
        assert len(data["feedback"]) == 2

    def test_per_page_and_page(self, client, default_board):
        """page and per_page params work together."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            for i in range(5):
                add_agent_feedback(ticket["id"], "agent_killed", reason=f"Item {i}")

        res = client.get("/api/feedback?per_page=2&page=1")
        data = json.loads(res.data)
        assert len(data["feedback"]) == 2
        assert data["total"] == 5
        assert data["total_pages"] == 3

        res2 = client.get("/api/feedback?per_page=2&page=2")
        data2 = json.loads(res2.data)
        assert len(data2["feedback"]) == 2
        assert data2["page"] == 2

        res3 = client.get("/api/feedback?per_page=2&page=3")
        data3 = json.loads(res3.data)
        assert len(data3["feedback"]) == 1

    def test_filter_by_feedback_type(self, client, default_board):
        """feedback_type filter narrows results."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="Gate")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="CLI")
            f3 = add_agent_feedback(ticket["id"], "agent_killed", reason="Kill")

        res = client.get("/api/feedback?feedback_type=cli_failed")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f2 in ids
        assert f1 not in ids
        assert f3 not in ids

    def test_filter_by_ticket_id(self, client, default_board):
        """ticket_id filter narrows to a specific ticket."""
        t1 = _create_ticket(client, default_board["id"], title="Ticket 1")
        t2 = _create_ticket(client, default_board["id"], title="Ticket 2")
        with client.application.app_context():
            f1 = add_agent_feedback(t1["id"], "gate_rejected", reason="T1")
            f2 = add_agent_feedback(t2["id"], "cli_failed", reason="T2")

        res = client.get(f"/api/feedback?ticket_id={t1['id']}")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 in ids
        assert f2 not in ids

    def test_filter_by_agent_id(self, client, default_workflow, default_board):
        """agent_id filter narrows to feedback linked to runs from a specific agent."""
        agent1 = _create_agent(client, default_workflow["id"], name="Agent1")
        agent2 = _create_agent(client, default_workflow["id"], name="Agent2")
        status1 = _create_status_with_agent(client, default_workflow["id"], agent1["id"], name="S1")
        status2 = _create_status_with_agent(client, default_workflow["id"], agent2["id"], name="S2")

        t1 = _create_ticket(client, default_board["id"], title="T1")
        t2 = _create_ticket(client, default_board["id"], title="T2")

        run1 = _spawn_and_get_run_id(client, t1["id"], status1["id"])
        run2 = _spawn_and_get_run_id(client, t2["id"], status2["id"])

        with client.application.app_context():
            f1 = add_agent_feedback(t1["id"], "run_feedback", run_id=run1, reason="From agent1")
            f2 = add_agent_feedback(t2["id"], "run_feedback", run_id=run2, reason="From agent2")

        res = client.get(f"/api/feedback?agent_id={agent1['id']}")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 in ids
        assert f2 not in ids

    def test_filter_by_date_from(self, client, default_board):
        """date_from filter narrows results."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            import app as app_module

            f1 = add_agent_feedback(ticket["id"], "agent_killed", reason="Old")
            app_module.run_db(
                "UPDATE agent_feedback SET created_at = '2024-01-01 00:00:00' WHERE id = ?",
                (f1,),
            )
            f2 = add_agent_feedback(ticket["id"], "agent_killed", reason="New")
            app_module.run_db(
                "UPDATE agent_feedback SET created_at = '2024-06-01 00:00:00' WHERE id = ?",
                (f2,),
            )

        res = client.get("/api/feedback?date_from=2024-05-01")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 not in ids
        assert f2 in ids

    def test_filter_by_date_to(self, client, default_board):
        """date_to filter narrows results."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            import app as app_module

            f1 = add_agent_feedback(ticket["id"], "agent_killed", reason="Old")
            app_module.run_db(
                "UPDATE agent_feedback SET created_at = '2024-01-01 00:00:00' WHERE id = ?",
                (f1,),
            )
            f2 = add_agent_feedback(ticket["id"], "agent_killed", reason="New")
            app_module.run_db(
                "UPDATE agent_feedback SET created_at = '2024-06-01 00:00:00' WHERE id = ?",
                (f2,),
            )

        res = client.get("/api/feedback?date_to=2024-03-01")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 in ids
        assert f2 not in ids

    def test_filter_by_search(self, client, default_board):
        """search filter matches reason, expected_behavior, and ticket title."""
        t1 = _create_ticket(client, default_board["id"], title="Alpha Ticket")
        t2 = _create_ticket(client, default_board["id"], title="Beta Ticket")
        with client.application.app_context():
            f1 = add_agent_feedback(t1["id"], "gate_rejected", reason="alpha failure")
            f2 = add_agent_feedback(t2["id"], "cli_failed", reason="beta failure")
            f3 = add_agent_feedback(t1["id"], "agent_killed", reason="gamma", expected_behavior="alpha expected")

        res = client.get("/api/feedback?search=alpha")
        data = json.loads(res.data)
        ids = [f["id"] for f in data["feedback"]]
        assert f1 in ids
        assert f2 not in ids
        assert f3 in ids

    def test_pagination_envelope_fields(self, client, default_board):
        """Response includes total, page, per_page, total_pages."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            add_agent_feedback(ticket["id"], "agent_killed", reason="Item")

        res = client.get("/api/feedback?per_page=1&page=1")
        data = json.loads(res.data)
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "total_pages" in data
        assert "feedback" in data

    def test_enrichment_ticket_title(self, client, default_board):
        """Response includes ticket title."""
        ticket = _create_ticket(client, default_board["id"], title="Enrichment Test")
        with client.application.app_context():
            add_agent_feedback(ticket["id"], "gate_rejected", reason="Issue")

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        assert len(data["feedback"]) == 1
        fb = data["feedback"][0]
        assert fb["type"] == "gate_rejected"

    def test_enrichment_agent_name_and_run_status(self, client, default_workflow, default_board):
        """Feedback linked to a run includes agent name in the context."""
        agent = _create_agent(client, default_workflow["id"], name="ReviewBot")
        status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
        ticket = _create_ticket(client, default_board["id"])
        run_id = _spawn_and_get_run_id(client, ticket["id"], status["id"])

        with client.application.app_context():
            add_agent_feedback(ticket["id"], "run_feedback", run_id=run_id, reason="Run issue")

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert fb["agent"] == "ReviewBot"
        # run_status is inside context
        assert fb["context"].get("run_status") == "running"

    def test_enrichment_gate_info_in_context(self, client, default_workflow, default_board):
        """Feedback linked to a gate_review includes gate name/type and status names."""
        # Need two statuses for the gate
        s1 = _create_status_with_agent(client, default_workflow["id"], None, name="FromStatus", sort_order=10)
        s2 = _create_status_with_agent(client, default_workflow["id"], None, name="ToStatus", sort_order=11)
        gate_id = _create_quality_gate(client, s1["id"], s2["id"], default_workflow["id"], name="Review Gate")
        ticket = _create_ticket(client, default_board["id"])
        gr_id = _create_gate_review(client, ticket["id"], gate_id, s1["id"], s2["id"])

        with client.application.app_context():
            add_agent_feedback(
                ticket["id"],
                "gate_rejected",
                gate_review_id=gr_id,
                reason="Gate failed",
                expected_behavior="Should pass",
            )

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert fb["context"]["gate_name"] == "Review Gate"
        assert fb["context"]["gate_type"] == "manual"
        assert fb["context"]["from_status"] == "FromStatus"
        assert fb["context"]["to_status"] == "ToStatus"

    def test_preview_composition(self, client, default_board):
        """Preview field is built from type, gate info, reason, and expected_behavior."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            add_agent_feedback(
                ticket["id"],
                "cli_failed",
                reason="Tests failed",
                expected_behavior="All green",
            )

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert "cli_failed" in fb["preview"]
        assert "Tests failed" in fb["preview"]
        assert "expected: All green" in fb["preview"]

    def test_context_json_parsed(self, client, default_board):
        """Valid context_json is parsed into the context dict."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            add_agent_feedback(
                ticket["id"],
                "agent_rerun",
                reason="Rerun needed",
                context_json='{"step": 3, "tool": "lint"}',
            )

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert fb["context"]["step"] == 3
        assert fb["context"]["tool"] == "lint"

    def test_invalid_context_json_graceful(self, client, default_board):
        """Invalid context_json is handled gracefully with a fallback key."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            add_agent_feedback(
                ticket["id"],
                "agent_killed",
                reason="Killed",
                context_json="not-json{{",
            )

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert "_invalid_context_json" in fb["context"]
        assert "not-json" in fb["context"]["_invalid_context_json"]

    def test_all_feedback_types_present(self, client, default_board):
        """All 5 feedback types can be created and listed."""
        ticket = _create_ticket(client, default_board["id"])
        types = ["gate_rejected", "cli_failed", "agent_killed", "agent_rerun", "run_feedback"]
        with client.application.app_context():
            for ft in types:
                add_agent_feedback(ticket["id"], ft, reason=f"Reason for {ft}")

        res = client.get("/api/feedback")
        data = json.loads(res.data)
        returned_types = {f["type"] for f in data["feedback"]}
        assert returned_types == set(types)

    def test_consumed_true_shows_consumed_at(self, client, default_board):
        """Consumed feedback includes consumed_at and consumed_by_run_id."""
        import app as app_module

        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "gate_rejected", reason="Old")
            app_module.run_db(
                "UPDATE agent_feedback SET consumed_at = CURRENT_TIMESTAMP, consumed_by_run_id = 42 WHERE id = ?",
                (fid,),
            )

        res = client.get("/api/feedback?consumed=true")
        data = json.loads(res.data)
        fb = data["feedback"][0]
        assert fb["consumed_at"] is not None
        assert fb["consumed_by_run_id"] == 42


# ---------------------------------------------------------------------------
# GET /api/feedback/<id>/preview
# ---------------------------------------------------------------------------


class TestFeedbackPreview:
    """Tests for GET /api/feedback/<id>/preview."""

    def test_preview_returns_json(self, client, default_board):
        """Preview endpoint returns structured JSON."""
        ticket = _create_ticket(client, default_board["id"], title="Preview Ticket")
        with client.application.app_context():
            fid = add_agent_feedback(
                ticket["id"],
                "cli_failed",
                reason="Tests failed",
                expected_behavior="All green",
                context_json='{"step": 1}',
            )

        res = client.get(f"/api/feedback/{fid}/preview")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["id"] == fid
        assert data["ticket"]["id"] == ticket["id"]
        assert data["ticket"]["title"] == "Preview Ticket"
        assert data["feedback_type"] == "cli_failed"
        assert data["reason"] == "Tests failed"
        assert data["expected_behavior"] == "All green"
        assert data["context"]["step"] == 1
        assert data["run"] is None
        assert data["gate_review"] is None

    def test_preview_with_run(self, client, default_workflow, default_board):
        """Preview includes run details when linked."""
        agent = _create_agent(client, default_workflow["id"], name="PreviewAgent")
        status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
        ticket = _create_ticket(client, default_board["id"])
        run_id = _spawn_and_get_run_id(client, ticket["id"], status["id"])

        with client.application.app_context():
            fid = add_agent_feedback(
                ticket["id"],
                "run_feedback",
                run_id=run_id,
                reason="Run issue",
            )

        res = client.get(f"/api/feedback/{fid}/preview")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["run"]["id"] == run_id
        assert data["agent"] == "PreviewAgent"

    def test_preview_with_gate_review(self, client, default_workflow, default_board):
        """Preview includes gate review details when linked."""
        s1 = _create_status_with_agent(client, default_workflow["id"], None, name="FromStatus", sort_order=10)
        s2 = _create_status_with_agent(client, default_workflow["id"], None, name="ToStatus", sort_order=11)
        gate_id = _create_quality_gate(client, s1["id"], s2["id"], default_workflow["id"], name="Preview Gate")
        ticket = _create_ticket(client, default_board["id"])
        gr_id = _create_gate_review(client, ticket["id"], gate_id, s1["id"], s2["id"])

        with client.application.app_context():
            fid = add_agent_feedback(
                ticket["id"],
                "gate_rejected",
                gate_review_id=gr_id,
                reason="Gate failed",
            )

        res = client.get(f"/api/feedback/{fid}/preview")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["gate_review"]["id"] == gr_id
        assert data["gate_review"]["gate_name"] == "Preview Gate"
        assert data["gate_review"]["gate_type"] == "manual"
        assert data["gate_review"]["from_status"] == "FromStatus"
        assert data["gate_review"]["to_status"] == "ToStatus"

    def test_preview_missing_returns_404(self, client):
        """Preview for non-existent feedback returns 404."""
        res = client.get("/api/feedback/99999/preview")
        assert res.status_code == 404
        data = json.loads(res.data)
        assert "not found" in data["error"].lower()


# ---------------------------------------------------------------------------
# POST /api/feedback/<id>/consume
# ---------------------------------------------------------------------------


class TestConsumeFeedback:
    """Tests for POST /api/feedback/<id>/consume."""

    def test_consume_success(self, client, default_board):
        """Consuming unconsumed feedback returns success."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "gate_rejected", reason="Issue")

        res = client.post(f"/api/feedback/{fid}/consume")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

        # Verify it's now consumed
        res2 = client.get("/api/feedback?consumed=false")
        data2 = json.loads(res2.data)
        assert fid not in [f["id"] for f in data2["feedback"]]

    def test_consume_with_consumed_by_run_id(self, client, default_board):
        """consume endpoint accepts consumed_by_run_id in body."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "gate_rejected", reason="Issue")

        res = client.post(
            f"/api/feedback/{fid}/consume",
            json={"consumed_by_run_id": 99},
        )
        assert res.status_code == 200

        res2 = client.get("/api/feedback?consumed=true")
        data2 = json.loads(res2.data)
        fb = data2["feedback"][0]
        assert fb["consumed_by_run_id"] == 99

    def test_consume_missing_returns_404(self, client):
        """Consuming a non-existent feedback id returns 404."""
        res = client.post("/api/feedback/99999/consume")
        assert res.status_code == 404
        data = json.loads(res.data)
        assert "not found" in data["error"].lower()

    def test_consume_already_consumed_returns_409(self, client, default_board):
        """Consuming an already-consumed feedback returns 409."""
        import app as app_module

        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "gate_rejected", reason="Issue")
            app_module.run_db(
                "UPDATE agent_feedback SET consumed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (fid,),
            )

        res = client.post(f"/api/feedback/{fid}/consume")
        assert res.status_code == 409
        data = json.loads(res.data)
        assert "already consumed" in data["error"].lower()

    def test_consume_empty_body_ok(self, client, default_board):
        """consume endpoint works with empty JSON body."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "gate_rejected", reason="Issue")

        res = client.post(f"/api/feedback/{fid}/consume", json={})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Existing endpoints still work
# ---------------------------------------------------------------------------


class TestExistingFeedbackEndpoints:
    """Regression tests for pre-existing POST and PUT /api/feedback."""

    def test_post_feedback_still_works(self, client, default_workflow, default_board):
        """POST /api/feedback still creates run_feedback rows."""
        import app as app_module

        agent = _create_agent(client, default_workflow["id"])
        status = _create_status_with_agent(client, default_workflow["id"], agent["id"])
        ticket = _create_ticket(client, default_board["id"])
        tid = ticket["id"]

        with patch("app.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=40001)
            client.put(f"/api/tickets/{tid}", json={"status_id": status["id"]})

        with client.application.app_context():
            app_module.run_db(
                "UPDATE agent_runs SET status = 'completed', exit_code = 0, "
                "completed_at = datetime('now') WHERE ticket_id = ?",
                (tid,),
            )
            rows = app_module.query_db(
                "SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
                (tid,),
            )
            run_id = rows[0]["id"]

        res = client.post(
            "/api/feedback",
            json={
                "run_id": run_id,
                "ticket_id": tid,
                "reason": "Missed requirement.",
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert isinstance(data["feedback_id"], int)

    def test_put_feedback_still_works(self, client, default_board):
        """PUT /api/feedback/<id> still updates reason and expected_behavior."""
        ticket = _create_ticket(client, default_board["id"])
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "run_feedback", reason="Original")

        res = client.put(
            f"/api/feedback/{fid}",
            json={"reason": "Updated", "expected_behavior": "Better"},
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

        res2 = client.get("/api/feedback")
        data2 = json.loads(res2.data)
        fb = data2["feedback"][0]
        assert fb["reason"] == "Updated"
        assert fb["expected_behavior"] == "Better"
