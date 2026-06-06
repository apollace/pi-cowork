"""Tests for ticket updated_at change detection (Ticket #113).

Verifies that:
1. updated_at is bumped when comments are added
2. updated_at is bumped when labels are changed
3. updated_at is bumped when questions are asked
4. updated_at is bumped when questions are answered
5. updated_at is bumped when questions are batch-answered
6. updated_at is included in SSE event payloads for ticket-related events
7. updated_at is returned in ticket list and detail responses
8. The run_db calls to bump updated_at happen correctly
"""

import json
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helper: set ticket updated_at to a known past value
# ---------------------------------------------------------------------------


def _set_past_updated_at(client, ticket_id, past_value="2020-01-01 00:00:00"):
    """Directly set a ticket's updated_at to a known past value via DB."""
    from pi_cowork.db import run_db

    run_db("UPDATE tickets SET updated_at = ? WHERE id = ?", (past_value, ticket_id))


def _set_past_updated_at_api(client, ticket_id, past_value="2020-01-01 00:00:00"):
    """Set updated_at to a past value within app context, then return the new value."""
    with client.application.app_context():
        from pi_cowork.db import run_db

        run_db("UPDATE tickets SET updated_at = ? WHERE id = ?", (past_value, ticket_id))


# ---------------------------------------------------------------------------
# Test: updated_at is bumped when comments are added
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_comment(client, default_board):
    """Adding a comment should bump the ticket's updated_at."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Comment Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    # Set a known past value so the change is detectable regardless of second precision
    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    ticket_before = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket_before["updated_at"] == "2020-01-01 00:00:00"

    # Add a comment
    client.post(f"/api/tickets/{tid}/comments", json={"body": "Test comment"})

    ticket_after = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket_after["updated_at"] > "2020-01-01 00:00:00"


# ---------------------------------------------------------------------------
# Test: updated_at is bumped when labels are changed via PUT
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_labels(client, default_board):
    """Changing labels via ticket PUT should bump updated_at."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Label Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    # Create a label
    label_res = client.post(
        "/api/labels",
        json={
            "name": "bug",
            "color": "#ff0000",
            "workflow_id": default_board["workflow_id"],
        },
    )
    label_id = json.loads(label_res.data)["id"]

    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    client.put(f"/api/tickets/{tid}", json={"labels": [label_id]})

    ticket = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket["updated_at"] > "2020-01-01 00:00:00"


# ---------------------------------------------------------------------------
# Test: updated_at is bumped when questions are asked
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_question_asked(client, default_board):
    """Asking a question should bump the ticket's updated_at."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Question Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    client.post(
        f"/api/tickets/{tid}/questions", json={"questions": [{"body": "What is the answer?", "options": ["Yes", "No"]}]}
    )

    ticket = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket["updated_at"] > "2020-01-01 00:00:00"


# ---------------------------------------------------------------------------
# Test: updated_at is bumped when a question is answered
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_question_answered(client, default_board):
    """Answering a question should bump updated_at."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Answer Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    # Ask a question first
    q_res = client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "What is the answer?"}]})
    qid = json.loads(q_res.data)["ids"][0]

    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    # Answer the question
    with patch("app.subprocess.Popen"):
        client.put(f"/api/questions/{qid}/answer", json={"answer": "42"})

    ticket = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket["updated_at"] > "2020-01-01 00:00:00"


# ---------------------------------------------------------------------------
# Test: updated_at is bumped when questions are batch-answered
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_batch_answer(client, default_board):
    """Batch-answering questions should bump updated_at."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Batch Answer Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    # Ask questions
    q_res = client.post(
        f"/api/tickets/{tid}/questions",
        json={
            "questions": [
                {"body": "Question 1?"},
                {"body": "Question 2?"},
            ]
        },
    )
    qids = json.loads(q_res.data)["ids"]

    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    # Batch answer
    with patch("app.subprocess.Popen"):
        client.post(
            f"/api/tickets/{tid}/answers",
            json={
                "answers": [
                    {"question_id": qids[0], "answer": "Answer 1"},
                    {"question_id": qids[1], "answer": "Answer 2"},
                ]
            },
        )

    ticket = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket["updated_at"] > "2020-01-01 00:00:00"


# ---------------------------------------------------------------------------
# Test: updated_at is included in ticket list response
# ---------------------------------------------------------------------------


def test_updated_at_in_ticket_list(client, default_board):
    """Ticket list endpoint should include updated_at field."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "List Test",
            "board_id": default_board["id"],
        },
    )

    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    tickets = json.loads(res.data)
    assert len(tickets) >= 1
    ticket = tickets[0]
    assert "updated_at" in ticket
    assert ticket["updated_at"] is not None


# ---------------------------------------------------------------------------
# Test: updated_at is included in ticket detail response
# ---------------------------------------------------------------------------


def test_updated_at_in_ticket_detail(client, default_board):
    """Ticket detail endpoint should include updated_at field."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Detail Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    detail = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert "updated_at" in detail
    assert detail["updated_at"] is not None


# ---------------------------------------------------------------------------
# Test: _get_ticket_updated_at helper
# ---------------------------------------------------------------------------


class TestGetTicketUpdatedAt:
    """Test the _get_ticket_updated_at helper function."""

    def test_returns_updated_at(self, client, default_board):
        """Should return the updated_at for a known ticket."""
        from pi_cowork.api.events import _get_ticket_updated_at

        res = client.post(
            "/api/tickets",
            json={
                "title": "Helper Test",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        with client.application.app_context():
            updated_at = _get_ticket_updated_at(tid)
            assert updated_at is not None

    def test_returns_none_for_nonexistent(self):
        """Should return None for nonexistent ticket."""
        from pi_cowork.api.events import _get_ticket_updated_at

        result = _get_ticket_updated_at(999999)
        assert result is None

    def test_returns_none_without_app_context(self):
        """Should gracefully handle missing app context."""
        from pi_cowork.api.events import _get_ticket_updated_at

        # No app context — should return None without crashing
        result = _get_ticket_updated_at(999999)
        assert result is None


# ---------------------------------------------------------------------------
# Test: SSE events include updated_at for ticket-related events
# ---------------------------------------------------------------------------


class TestSSEUpdatedAt:
    """Test that SSE events include updated_at in their payloads."""

    def test_sse_event_includes_updated_at_with_app_context(self, client, default_board):
        """SSE generator should include updated_at when app context is available."""
        import threading

        from pi_cowork.api.events import _event_generator
        from pi_cowork.events import TICKET_CREATED, bus

        res = client.post(
            "/api/tickets",
            json={
                "title": "SSE Updated At Test",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        events = []
        ready = threading.Event()

        def run():
            # The generator needs a Flask app context for DB queries
            with client.application.app_context():
                gen = _event_generator(board_id=default_board["id"])
                ready.set()
                for i, frame in enumerate(gen):
                    if i == 0:
                        continue  # skip ": ready" comment
                    events.append(frame)
                    if len(events) >= 1:
                        gen.close()
                        break

        t = threading.Thread(target=run, daemon=True)
        t.start()
        ready.wait()

        bus.publish(TICKET_CREATED, ticket_id=tid, title="Test", board_id=default_board["id"], status_id=1)

        t.join(timeout=3)

        assert len(events) >= 1
        frame = events[0]
        lines = frame.split("\n")
        data_line = [l for l in lines if l.startswith("data: ")]
        assert len(data_line) == 1
        data = json.loads(data_line[0][6:])
        assert "updated_at" in data
        assert data["updated_at"] is not None

    def test_sse_event_updated_at_reflects_changes(self, client, default_board):
        """SSE events should include the latest updated_at after ticket modifications."""
        import threading

        from pi_cowork.api.events import _event_generator
        from pi_cowork.events import COMMENT_ADDED, bus

        res = client.post(
            "/api/tickets",
            json={
                "title": "SSE Change Detection",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        # Set a past updated_at to make the change detectable
        _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

        # Add a comment to bump updated_at (this also publishes COMMENT_ADDED)
        client.post(f"/api/tickets/{tid}/comments", json={"body": "Change detection test"})

        event_data = []
        ready = threading.Event()

        def run():
            with client.application.app_context():
                gen = _event_generator(board_id=default_board["id"])
                ready.set()
                for i, frame in enumerate(gen):
                    if i == 0:
                        continue
                    event_data.append(frame)
                    if len(event_data) >= 1:
                        gen.close()
                        break

        t = threading.Thread(target=run, daemon=True)
        t.start()
        ready.wait()

        bus.publish(COMMENT_ADDED, ticket_id=tid, body="Test")

        t.join(timeout=3)

        assert len(event_data) >= 1
        frame = event_data[0]
        lines = frame.split("\n")
        data_line = [l for l in lines if l.startswith("data: ")]
        data = json.loads(data_line[0][6:])
        assert "updated_at" in data
        assert data["updated_at"] > "2020-01-01 00:00:00"

    def test_sse_event_no_updated_at_when_ticket_id_missing(self):
        """Events without ticket_id should not include updated_at."""
        import threading

        from pi_cowork.api.events import _event_generator
        from pi_cowork.events import bus

        events = []
        ready = threading.Event()

        def run():
            gen = _event_generator(board_id=None)
            ready.set()
            for i, frame in enumerate(gen):
                if i == 0:
                    continue
                events.append(frame)
                if len(events) >= 1:
                    gen.close()
                    break

        t = threading.Thread(target=run, daemon=True)
        t.start()
        ready.wait()

        # Publish an event without ticket_id
        bus.publish("recurring.triggered", recurring_task_id=1)

        t.join(timeout=3)

        if events:
            frame = events[0]
            lines = frame.split("\n")
            data_line = [l for l in lines if l.startswith("data: ")]
            if data_line:
                data = json.loads(data_line[0][6:])
                # Should not have updated_at since there's no ticket_id
                assert "updated_at" not in data


# ---------------------------------------------------------------------------
# Test: updated_at is bumped on ticket update (regression)
# ---------------------------------------------------------------------------


def test_updated_at_bumped_on_ticket_update(client, default_board):
    """Updating ticket fields should bump updated_at (baseline regression test)."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Update Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    _set_past_updated_at_api(client, tid, "2020-01-01 00:00:00")

    client.put(f"/api/tickets/{tid}", json={"title": "Updated Title"})

    ticket = json.loads(client.get(f"/api/tickets/{tid}").data)
    assert ticket["updated_at"] > "2020-01-01 00:00:00"
    assert ticket["title"] == "Updated Title"
