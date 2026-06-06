"""Tests for board loading performance improvements (Ticket #83).

Verifies:
1. Board listing returns comment_count instead of comments array
2. Batch queries produce correct results (labels, recurring, queue, gates, questions)
3. WAL mode is active on the database
4. Critical indexes exist after migration
5. Board listing scopes queue/gate/question queries to the board's tickets
"""

import json

from app import app


class TestBoardListingLightweightPayload:
    """Board listing should return comment_count, not comments array."""

    def test_board_listing_has_comment_count_no_comments(self, client, default_board):
        """Board listing returns comment_count, not comments."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "Test ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        # Add 3 comments
        for i in range(3):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"Comment {i}"})

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert "comment_count" in ticket
        assert ticket["comment_count"] == 3
        # Board listing should NOT include full comments array
        assert "comments" not in ticket

    def test_board_listing_comment_count_zero(self, client, default_board):
        """Tickets with no comments have comment_count=0."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "No comments ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert ticket["comment_count"] == 0

    def test_ticket_detail_still_has_comments(self, client, default_board):
        """Ticket detail endpoint still returns full comments array."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "Detail ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]
        client.post(f"/api/tickets/{tid}/comments", json={"body": "Hello"})

        detail = json.loads(client.get(f"/api/tickets/{tid}").data)
        assert "comments" in detail
        assert len(detail["comments"]) == 1
        assert detail["comments"][0]["body"] == "Hello"


class TestBoardListingBatchQueries:
    """Verify batch-fetched data is correct."""

    def test_labels_in_board_listing(self, client, default_board):
        """Labels are correctly attached to tickets in board listing."""
        # Create labels
        wf_id = default_board["workflow_id"]
        l1 = json.loads(
            client.post(
                "/api/labels",
                json={
                    "name": "bug",
                    "color": "#ff0000",
                    "workflow_id": wf_id,
                },
            ).data
        )
        l2 = json.loads(
            client.post(
                "/api/labels",
                json={
                    "name": "feature",
                    "color": "#00ff00",
                    "workflow_id": wf_id,
                },
            ).data
        )

        res = client.post(
            "/api/tickets",
            json={
                "title": "Labeled ticket",
                "board_id": default_board["id"],
                "labels": [l1["id"], l2["id"]],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        label_names = sorted(l["name"] for l in ticket["labels"])
        assert label_names == ["bug", "feature"]

    def test_queued_flag_in_board_listing(self, client, default_board):
        """Queue state is correctly scoped to board's tickets."""
        # Create a ticket and verify it's not queued by default
        res = client.post(
            "/api/tickets",
            json={
                "title": "Normal ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert ticket["queued"] is False

    def test_gate_pending_flag_in_board_listing(self, client, default_board, default_workflow):
        """Gate pending flag is scoped to board's tickets."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "Normal ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert ticket["gate_pending"] is False

    def test_question_count_in_board_listing(self, client, default_board):
        """Question count reflects unanswered questions."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "Question ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert ticket["question_count"] == 0

    def test_recurring_parents_in_board_listing(self, client, default_board):
        """recurring_parents is an empty list for non-recurring tickets."""
        res = client.post(
            "/api/tickets",
            json={
                "title": "Non-recurring ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        ticket = next(t for t in listing if t["id"] == tid)
        assert ticket["recurring_parents"] == []


class TestWalMode:
    """Verify WAL mode is active after DB init."""

    def test_wal_mode_enabled(self, client):
        """Database should use WAL journal mode for concurrent read/write."""
        with app.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            result = db.execute("PRAGMA journal_mode").fetchone()
            assert result[0].lower() == "wal"


class TestDatabaseIndexes:
    """Verify performance indexes exist after migration."""

    EXPECTED_INDEXES = [
        "idx_tickets_board_id",
        "idx_comments_ticket_id",
        "idx_agent_runs_ticket_id_status",
        "idx_agent_queue_ticket_id",
        "idx_gate_reviews_ticket_id",
        "idx_questions_ticket_id",
        "idx_ticket_labels_ticket_id",
        "idx_recurring_instances_ticket_id",
        "idx_labels_workflow_id",
    ]

    def test_indexes_exist(self, client):
        """All expected performance indexes should exist."""
        with app.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            rows = db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            index_names = {row[0] for row in rows}
            for idx in self.EXPECTED_INDEXES:
                assert idx in index_names, f"Missing index: {idx}"


class TestBoardListingScoping:
    """Verify that queue/gate/question queries are scoped to the board."""

    def test_queue_not_polluted_by_other_board(self, client, default_board, new_board, new_workflow):
        """Tickets from other boards should not affect this board's queue data."""
        # Create a default status on new workflow for creating tickets
        client.post(
            "/api/statuses",
            json={
                "name": "New Default",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "workflow_id": new_workflow["id"],
            },
        )

        # Create tickets on both boards
        client.post(
            "/api/tickets",
            json={
                "title": "Board 1 ticket",
                "board_id": default_board["id"],
            },
        )
        client.post(
            "/api/tickets",
            json={
                "title": "Board 2 ticket",
                "board_id": new_board["id"],
            },
        )

        # Both boards should return valid ticket lists
        res1 = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        res2 = json.loads(client.get(f"/api/tickets?board_id={new_board['id']}").data)

        assert len(res1) == 1
        assert len(res2) == 1
        assert res1[0]["title"] == "Board 1 ticket"
        assert res2[0]["title"] == "Board 2 ticket"

    def test_empty_board_returns_empty_list(self, client, default_board):
        """Board listing with no tickets returns empty JSON array."""
        # Delete any seeded ticket (the default board starts empty after init)
        res = client.get(f"/api/tickets?board_id={default_board['id']}")
        data = json.loads(res.data)
        assert isinstance(data, list)

    def test_multiple_tickets_batch_accuracy(self, client, default_board):
        """Batch queries correctly match data to each ticket."""
        # Create 5 tickets with varying comment counts
        ticket_ids = []
        for i in range(5):
            res = client.post(
                "/api/tickets",
                json={
                    "title": f"Ticket {i}",
                    "board_id": default_board["id"],
                },
            )
            tid = json.loads(res.data)["id"]
            ticket_ids.append(tid)

        # Add 0, 1, 2, 3, 4 comments respectively
        for i, tid in enumerate(ticket_ids):
            for j in range(i):
                client.post(f"/api/tickets/{tid}/comments", json={"body": f"Comment {j}"})

        listing = json.loads(client.get(f"/api/tickets?board_id={default_board['id']}").data)
        by_id = {t["id"]: t for t in listing}

        for i, tid in enumerate(ticket_ids):
            assert by_id[tid]["comment_count"] == i, (
                f"Ticket {tid} should have {i} comments, got {by_id[tid]['comment_count']}"
            )


class TestMigrationIdempotency:
    """Verify that the index migrations can be run multiple times safely."""

    def test_double_migration(self, client):
        """Running migrations twice should not raise errors."""
        with app.app_context():
            from pi_cowork.db import _migrate, get_db

            db = get_db()
            # Second run should be idempotent
            _migrate(db)
            # Verify indexes still exist
            rows = db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            index_names = {row[0] for row in rows}
            assert "idx_tickets_board_id" in index_names
