"""Tests for the EventBus and audit log (Phases 2 & 4 of refactoring plan)."""

import json

from pi_cowork.events import (
    AGENT_COMPLETED,
    AGENT_FAILED,
    AGENT_SPAWNED,
    COMMENT_ADDED,
    GATE_FAILED,
    GATE_PASSED,
    GATE_PENDING,
    QUESTION_ANSWERED,
    QUESTION_ASKED,
    TICKET_CREATED,
    TICKET_STATUS_CHANGED,
    TICKET_UPDATED,
    EventBus,
    bus,
)


class TestEventBus:
    """Phase 2: EventBus unit tests."""

    def test_subscribe_and_publish(self):
        eb = EventBus()
        received = []
        eb.subscribe("test.event", lambda **kw: received.append(kw))
        eb.publish("test.event", foo="bar")
        assert len(received) == 1
        assert received[0] == {"foo": "bar", "event_name": "test.event"}

    def test_multiple_subscribers(self):
        eb = EventBus()
        results_a = []
        results_b = []
        eb.subscribe("test.event", lambda **kw: results_a.append(kw))
        eb.subscribe("test.event", lambda **kw: results_b.append(kw))
        eb.publish("test.event", x=1)
        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_no_subscribers_no_error(self):
        eb = EventBus()
        eb.publish("nonexistent.event", data=42)  # should not raise

    def test_handler_exception_does_not_crash_publisher(self):
        eb = EventBus()
        eb.subscribe("test.event", lambda **kw: 1 / 0)  # raises ZeroDivisionError
        eb.subscribe("test.event", lambda **kw: None)  # should still be called
        eb.publish("test.event")
        # No exception propagated

    def test_handler_exception_does_not_block_other_handlers(self):
        eb = EventBus()
        good_results = []
        eb.subscribe("test.event", lambda **kw: 1 / 0)
        eb.subscribe("test.event", lambda **kw: good_results.append("good"))
        eb.publish("test.event")
        assert "good" in good_results

    def test_unsubscribe(self):
        eb = EventBus()
        results = []
        handler = lambda **kw: results.append(1)
        eb.subscribe("test.event", handler)
        eb.publish("test.event")
        assert len(results) == 1
        eb.unsubscribe("test.event", handler)
        eb.publish("test.event")
        assert len(results) == 1  # not called again

    def test_subscribers_method(self):
        eb = EventBus()
        handler = lambda **kw: None
        eb.subscribe("test.event", handler)
        subs = eb.subscribers("test.event")
        assert handler in subs

    def test_event_name_constants_exist(self):
        """All planned event names are defined as constants."""
        assert isinstance(TICKET_CREATED, str)
        assert isinstance(TICKET_STATUS_CHANGED, str)
        assert isinstance(TICKET_UPDATED, str)
        assert isinstance(COMMENT_ADDED, str)
        assert isinstance(QUESTION_ASKED, str)
        assert isinstance(QUESTION_ANSWERED, str)
        assert isinstance(AGENT_SPAWNED, str)
        assert isinstance(AGENT_COMPLETED, str)
        assert isinstance(AGENT_FAILED, str)
        assert isinstance(GATE_PENDING, str)
        assert isinstance(GATE_PASSED, str)
        assert isinstance(GATE_FAILED, str)

    def test_global_bus_singleton(self):
        """The module-level bus is a singleton EventBus."""
        assert isinstance(bus, EventBus)

    def test_event_name_passed_as_kwarg(self):
        """Handlers receive event_name as a keyword argument."""
        eb = EventBus()
        names = []
        eb.subscribe("my.event", lambda event_name, **kw: names.append(event_name))
        eb.publish("my.event")
        assert names == ["my.event"]


class TestAuditLog:
    """Phase 4: Persistent audit log — verify events are written to DB."""

    def test_ticket_created_event_logged(self, client):
        """When a ticket is created, a ticket.created event should be logged."""
        boards = json.loads(client.get("/api/boards").data)
        board = boards[0]

        res = client.post(
            "/api/tickets",
            json={
                "title": "Audit Test Ticket",
                "body": "Testing audit log",
                "board_id": board["id"],
            },
        )
        assert res.status_code == 201

        with client.application.app_context():
            from pi_cowork.db import query_db

            rows = query_db("SELECT * FROM event_log WHERE event_name = ? ORDER BY id DESC LIMIT 1", (TICKET_CREATED,))
            assert len(rows) > 0
            event = dict(rows[0])
            assert event["event_name"] == TICKET_CREATED
            payload = json.loads(event["payload"])
            assert "ticket_id" in payload

    def test_comment_added_event_logged(self, client):
        """When a comment is posted, a comment.added event should be logged."""
        boards = json.loads(client.get("/api/boards").data)
        board = boards[0]

        res = client.post(
            "/api/tickets",
            json={
                "title": "Comment Audit Test",
                "board_id": board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        res = client.post(f"/api/tickets/{tid}/comments", json={"body": "Audit test comment"})
        assert res.status_code == 201

        with client.application.app_context():
            from pi_cowork.db import query_db

            rows = query_db("SELECT * FROM event_log WHERE event_name = ? ORDER BY id DESC LIMIT 1", (COMMENT_ADDED,))
            assert len(rows) > 0
            payload = json.loads(rows[-1]["payload"])
            assert payload.get("ticket_id") == tid

    def test_event_log_table_exists(self, client):
        """The event_log table should exist in the database."""
        with client.application.app_context():
            from pi_cowork.db import query_db

            rows = query_db("SELECT name FROM sqlite_master WHERE type='table' AND name='event_log'")
            assert len(rows) == 1

    def test_event_log_migration_idempotent(self, client):
        """Running migrations twice should not fail."""
        with client.application.app_context():
            from pi_cowork.db import _migrate, get_db

            db = get_db()
            _migrate(db)  # Should succeed without error (idempotent)
