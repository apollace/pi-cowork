"""Tests for agent_feedback model helpers and schema."""

import json
import sqlite3

import pytest

from pi_cowork.db import get_db
from pi_cowork.models import (
    add_agent_feedback,
    get_feedback_for_ticket,
    get_unconsumed_feedback,
    mark_feedback_consumed,
)


class TestAgentFeedback:
    """Comprehensive tests for the agent_feedback table and model helpers."""

    @pytest.fixture
    def ticket(self, client, default_board):
        """Create a ticket for feedback tests."""
        res = client.post(
            "/api/tickets",
            json={"title": "Feedback Test", "body": "Test body", "board_id": default_board["id"]},
        )
        assert res.status_code == 201
        return json.loads(res.data)

    def test_insert_all_feedback_types(self, client, ticket):
        """Insert one of each feedback_type and verify they exist."""
        types = ["gate_rejected", "cli_failed", "agent_killed", "agent_rerun", "run_feedback"]
        with client.application.app_context():
            for i, ft in enumerate(types):
                fid = add_agent_feedback(
                    ticket_id=ticket["id"],
                    feedback_type=ft,
                    reason=f"Reason {i}",
                    expected_behavior=f"Expected {i}",
                    context_json=json.dumps({"step": i}),
                    source_event=f"event_{i}",
                    created_by="test",
                )
                assert fid is not None
                assert isinstance(fid, int)

            # Verify all 5 rows exist
            db = get_db()
            cur = db.execute("SELECT COUNT(*) AS c FROM agent_feedback WHERE ticket_id = ?", (ticket["id"],))
            assert cur.fetchone()["c"] == 5

    def test_invalid_feedback_type_rejected(self, client, ticket):
        """SQLite CHECK constraint should reject invalid feedback_type values."""
        with client.application.app_context():
            db = get_db()
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO agent_feedback (ticket_id, feedback_type) VALUES (?, ?)",
                    (ticket["id"], "invalid_type"),
                )
                db.commit()

    def test_feedback_with_run_id_and_gate_review_id(self, client, ticket):
        """Insert feedback with optional run_id and gate_review_id."""
        with client.application.app_context():
            db = get_db()
            # Seed a quality gate so we can create a gate_review
            db.execute(
                """INSERT INTO quality_gates
                   (from_status_id, to_status_id, gate_type, name, sort_order, workflow_id)
                   VALUES (?, ?, 'manual', 'Test Gate', 0, ?)""",
                (1, 2, 1),
            )
            db.commit()
            gate_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            cur = db.execute(
                """INSERT INTO gate_reviews
                   (ticket_id, gate_id, from_status_id, to_status_id, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (ticket["id"], gate_id, 1, 2),
            )
            db.commit()
            gr_id = cur.lastrowid

            # Seed an agent_run
            run_cur = db.execute(
                """INSERT INTO agent_runs
                   (ticket_id, agent_id, status_id, started_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (ticket["id"], 1, 1),
            )
            db.commit()
            run_id = run_cur.lastrowid

            fid = add_agent_feedback(
                ticket_id=ticket["id"],
                feedback_type="run_feedback",
                run_id=run_id,
                gate_review_id=gr_id,
                reason="Run failed unexpectedly",
                expected_behavior="Should have completed",
            )
            row = db.execute("SELECT * FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row["ticket_id"] == ticket["id"]
            assert row["run_id"] == run_id
            assert row["gate_review_id"] == gr_id
            assert row["feedback_type"] == "run_feedback"
            assert row["reason"] == "Run failed unexpectedly"
            assert row["expected_behavior"] == "Should have completed"
            assert row["consumed_at"] is None
            assert row["consumed_by_run_id"] is None

    def test_get_feedback_for_ticket_ordering(self, client, ticket):
        """get_feedback_for_ticket returns newest first."""
        # Create another ticket first
        res2 = client.post(
            "/api/tickets",
            json={
                "title": "Other Ticket",
                "body": "Other body",
                "board_id": ticket["board_id"],
            },
        )
        other = json.loads(res2.data)

        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected", reason="First")
            f2 = add_agent_feedback(ticket["id"], "cli_failed", reason="Second")
            f3 = add_agent_feedback(ticket["id"], "agent_killed", reason="Third")
            f4 = add_agent_feedback(other["id"], "agent_rerun", reason="Other ticket")

            feedback = get_feedback_for_ticket(ticket["id"])
            ids = [f["id"] for f in feedback]
            assert ids == [f3, f2, f1]
            assert all(f["ticket_id"] == ticket["id"] for f in feedback)
            assert f4 not in ids

    def test_get_unconsumed_feedback_filtering(self, client, ticket):
        """get_unconsumed_feedback only returns rows with consumed_at IS NULL."""
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected")
            f2 = add_agent_feedback(ticket["id"], "cli_failed")
            f3 = add_agent_feedback(ticket["id"], "agent_killed")

            # Mark f2 as consumed
            mark_feedback_consumed(f2, 999)

            unconsumed = get_unconsumed_feedback()
            unconsumed_ids = [f["id"] for f in unconsumed]
            assert f1 in unconsumed_ids
            assert f3 in unconsumed_ids
            assert f2 not in unconsumed_ids

    def test_mark_feedback_consumed_update(self, client, ticket):
        """mark_feedback_consumed sets consumed_at and consumed_by_run_id."""
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "run_feedback")
            mark_feedback_consumed(fid, 42)

            db = get_db()
            row = db.execute("SELECT * FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row["consumed_at"] is not None
            assert row["consumed_by_run_id"] == 42

    def test_get_unconsumed_feedback_ordering(self, client, ticket):
        """get_unconsumed_feedback returns oldest first."""
        with client.application.app_context():
            f1 = add_agent_feedback(ticket["id"], "gate_rejected")
            f2 = add_agent_feedback(ticket["id"], "cli_failed")
            f3 = add_agent_feedback(ticket["id"], "agent_killed")

            unconsumed = get_unconsumed_feedback()
            ids = [f["id"] for f in unconsumed if f["ticket_id"] == ticket["id"]]
            assert ids == [f1, f2, f3]

    def test_on_delete_cascade_ticket(self, client, ticket):
        """Deleting a ticket cascades to agent_feedback rows."""
        with client.application.app_context():
            add_agent_feedback(ticket["id"], "gate_rejected")
            add_agent_feedback(ticket["id"], "cli_failed")

            db = get_db()
            before = db.execute(
                "SELECT COUNT(*) AS c FROM agent_feedback WHERE ticket_id = ?", (ticket["id"],)
            ).fetchone()["c"]
            assert before == 2

            # Delete the ticket
            db.execute("DELETE FROM tickets WHERE id = ?", (ticket["id"],))
            db.commit()

            after = db.execute(
                "SELECT COUNT(*) AS c FROM agent_feedback WHERE ticket_id = ?", (ticket["id"],)
            ).fetchone()["c"]
            assert after == 0

    def test_on_delete_set_null_run_id(self, client, ticket):
        """Deleting an agent_run sets run_id to NULL (ON DELETE SET NULL)."""
        with client.application.app_context():
            db = get_db()
            # Insert a fake agent_run
            cur = db.execute(
                """INSERT INTO agent_runs
                   (ticket_id, agent_id, status_id, started_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (ticket["id"], 1, 1),
            )
            db.commit()
            run_id = cur.lastrowid

            fid = add_agent_feedback(ticket["id"], "run_feedback", run_id=run_id)
            row_before = db.execute("SELECT run_id FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row_before["run_id"] == run_id

            db.execute("DELETE FROM agent_runs WHERE id = ?", (run_id,))
            db.commit()

            row_after = db.execute("SELECT run_id FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row_after["run_id"] is None

    def test_on_delete_set_null_gate_review_id(self, client, ticket):
        """Deleting a gate_review sets gate_review_id to NULL (ON DELETE SET NULL)."""
        with client.application.app_context():
            db = get_db()
            # Seed a quality gate for the default workflow so we can create a gate_review
            db.execute(
                """INSERT INTO quality_gates
                   (from_status_id, to_status_id, gate_type, name, sort_order, workflow_id)
                   VALUES (?, ?, 'manual', 'Test Gate', 0, ?)""",
                (1, 2, 1),
            )
            db.commit()
            gate_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert a fake gate_review
            cur = db.execute(
                """INSERT INTO gate_reviews
                   (ticket_id, gate_id, from_status_id, to_status_id, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (ticket["id"], gate_id, 1, 2),
            )
            db.commit()
            gr_id = cur.lastrowid

            fid = add_agent_feedback(ticket["id"], "gate_rejected", gate_review_id=gr_id)
            row_before = db.execute("SELECT gate_review_id FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row_before["gate_review_id"] == gr_id

            db.execute("DELETE FROM gate_reviews WHERE id = ?", (gr_id,))
            db.commit()

            row_after = db.execute("SELECT gate_review_id FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row_after["gate_review_id"] is None

    def test_feedback_columns_exist(self, client):
        """Verify all expected columns exist on agent_feedback."""
        with client.application.app_context():
            db = get_db()
            cols = db.execute("PRAGMA table_info(agent_feedback)").fetchall()
            col_names = [c["name"] for c in cols]
            expected = [
                "id",
                "ticket_id",
                "run_id",
                "gate_review_id",
                "feedback_type",
                "reason",
                "expected_behavior",
                "context_json",
                "created_at",
                "consumed_at",
                "consumed_by_run_id",
                "source_event",
                "created_by",
            ]
            for name in expected:
                assert name in col_names, f"Missing column: {name}"

    def test_indexes_exist(self, client):
        """Verify the 4 expected indexes on agent_feedback."""
        with client.application.app_context():
            db = get_db()
            rows = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agent_feedback'"
            ).fetchall()
            names = {r["name"] for r in rows}
            assert "idx_agent_feedback_ticket_id" in names
            assert "idx_agent_feedback_run_id" in names
            assert "idx_agent_feedback_type" in names
            assert "idx_agent_feedback_consumed_at" in names

    def test_add_agent_feedback_return_type(self, client, ticket):
        """add_agent_feedback returns an integer lastrowid."""
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "run_feedback")
            assert isinstance(fid, int)
            assert fid > 0

    def test_get_feedback_for_ticket_empty(self, client, ticket):
        """get_feedback_for_ticket returns empty list for ticket with no feedback."""
        with client.application.app_context():
            result = get_feedback_for_ticket(ticket["id"])
            assert result == []

    def test_get_unconsumed_feedback_empty(self, client):
        """get_unconsumed_feedback returns empty list when nothing is unconsumed."""
        with client.application.app_context():
            result = get_unconsumed_feedback()
            assert isinstance(result, list)

    def test_feedback_optional_fields_nullable(self, client, ticket):
        """Feedback can be inserted with only required fields."""
        with client.application.app_context():
            fid = add_agent_feedback(ticket["id"], "agent_rerun")
            db = get_db()
            row = db.execute("SELECT * FROM agent_feedback WHERE id = ?", (fid,)).fetchone()
            assert row["ticket_id"] == ticket["id"]
            assert row["feedback_type"] == "agent_rerun"
            assert row["run_id"] is None
            assert row["gate_review_id"] is None
            assert row["reason"] is None
            assert row["expected_behavior"] is None
            assert row["context_json"] is None
            assert row["source_event"] is None
            assert row["created_by"] is None
            assert row["consumed_at"] is None
            assert row["consumed_by_run_id"] is None
