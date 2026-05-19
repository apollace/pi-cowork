import json
import pytest

from conftest import HUMAN_ACTION_SECRET_FOR_TESTS

HUMAN_HEADERS = {'Content-Type': 'application/json', 'X-Human-Action': HUMAN_ACTION_SECRET_FOR_TESTS}


def _create_workflow(client):
    res = client.post('/api/workflows', json={'name': 'Notify WF', 'description': 'test'})
    return json.loads(res.data)['id']


def _create_board(client, workflow_id, name='Notify Board'):
    res = client.post('/api/boards', json={'name': name, 'workflow_id': workflow_id})
    return json.loads(res.data)['id']


def _create_status(client, workflow_id, name, sort_order, agent_id=None):
    res = client.post('/api/statuses', json={
        'name': name, 'sort_order': sort_order, 'workflow_id': workflow_id,
        'agent_id': agent_id
    })
    return json.loads(res.data)['id']


def _create_ticket(client, board_id, title, status_id):
    res = client.post('/api/tickets', json={
        'title': title, 'body': 'test', 'board_id': board_id, 'status_id': status_id
    })
    return json.loads(res.data)['id']


def _create_agent(client, workflow_id, name='Agent'):
    res = client.post('/api/agents', json={
        'name': name, 'description': 'test', 'workflow_id': workflow_id
    })
    return json.loads(res.data)['id']


def _create_gate(client, from_status_id, to_status_id, name='Gate', workflow_id=1):
    res = client.post('/api/quality_gates', json={
        'from_status_id': from_status_id, 'to_status_id': to_status_id, 'gate_type': 'manual', 'name': name,
        'workflow_id': workflow_id
    })
    return json.loads(res.data)['id']


def _create_review(client, ticket_id, gate_id, from_status_id, to_status_id):
    from pi_cowork.db import get_db, run_db
    with client.application.app_context():
        cur = run_db(
            "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', datetime('now'))",
            (ticket_id, gate_id, from_status_id, to_status_id)
        )
        return cur.lastrowid


def _create_question(client, ticket_id, body='Q?'):
    from pi_cowork.db import get_db, run_db
    with client.application.app_context():
        cur = run_db(
            "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, datetime('now'))",
            (ticket_id, body)
        )
        return cur.lastrowid


def _get_notifications(client):
    res = client.get('/api/notifications')
    assert res.status_code == 200
    return json.loads(res.data)


# ── Existing tests (preserved) ──

class TestNotificationsEmpty:
    def test_empty_notifications(self, client):
        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data == []


class TestGateReviewNotifications:
    def test_gate_review_notification(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Gate', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket, gate, s1, s2)

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 1
        assert data[0]['type'] == 'gate_review'
        assert data[0]['ticket_id'] == ticket
        assert data[0]['count'] == 1
        assert 'pending gate approval' in data[0]['message']

    def test_no_notification_for_non_pending_review(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Gate', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        rid = _create_review(client, ticket, gate, s1, s2)

        # approve the review
        from pi_cowork.db import run_db
        with client.application.app_context():
            run_db("UPDATE gate_reviews SET status='approved' WHERE id=?", (rid,))

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data == []

    def test_multiple_gates_single_notification(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Gate', s1)
        g1 = _create_gate(client, s1, s2, 'Gate 1', wf)
        g2 = _create_gate(client, s1, s2, 'Gate 2', wf)
        _create_review(client, ticket, g1, s1, s2)
        _create_review(client, ticket, g2, s1, s2)

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 1
        assert data[0]['count'] == 2


class TestQuestionNotifications:
    def test_question_notification(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Question', s1)
        _create_question(client, ticket, 'What?')

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 1
        assert data[0]['type'] == 'question'
        assert data[0]['ticket_id'] == ticket
        assert data[0]['count'] == 1
        assert 'unanswered question' in data[0]['message']

    def test_multiple_questions(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Question', s1)
        _create_question(client, ticket, 'What?')
        _create_question(client, ticket, 'Why?')

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 1
        assert data[0]['count'] == 2

    def test_no_notification_after_answer(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Test Question', s1)
        qid = _create_question(client, ticket, 'What?')

        res = client.put(f'/api/questions/{qid}/answer', json={'answer': 'Yes'})
        assert res.status_code == 200

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data == []


class TestCombinedNotifications:
    def test_both_types_together(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket1 = _create_ticket(client, board, 'Gate Ticket', s1)
        ticket2 = _create_ticket(client, board, 'Question Ticket', s1)

        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket1, gate, s1, s2)
        _create_question(client, ticket2, 'What?')

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 2
        types = {d['type'] for d in data}
        assert types == {'gate_review', 'question'}

    def test_sorted_by_created_at_desc(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket1 = _create_ticket(client, board, 'Older', s1)
        ticket2 = _create_ticket(client, board, 'Newer', s1)

        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        # manually tweak created_at to ensure order
        from pi_cowork.db import run_db
        with client.application.app_context():
            rid = _create_review(client, ticket1, gate, s1, s2)
            run_db("UPDATE gate_reviews SET created_at=datetime('now', '-1 day') WHERE id=?", (rid,))
            rid2 = _create_review(client, ticket2, gate, s1, s2)
            run_db("UPDATE gate_reviews SET created_at=datetime('now') WHERE id=?", (rid2,))

        res = client.get('/api/notifications')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert len(data) == 2
        # newer should come first
        assert data[0]['ticket_id'] == ticket2
        assert data[1]['ticket_id'] == ticket1


def _create_terminal_status(client, workflow_id, name='Done', sort_order=99):
    """Create a terminal status."""
    res = client.post('/api/statuses', json={
        'name': name, 'sort_order': sort_order,
        'workflow_id': workflow_id, 'is_terminal': True
    })
    return json.loads(res.data)['id']


class TestTerminalStateNotificationClearing:
    """When a ticket transitions into a terminal status, notifications are
    eagerly cleared and the API filter excludes them."""

    def test_gate_reviews_cleared_on_terminal_transition(self, client):
        """Moving a ticket to a terminal status via PUT deletes pending gate reviews."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'In Progress', 2)
        s_terminal = _create_terminal_status(client, wf, 'Done', 3)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Term Gate', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket, gate, s1, s2)

        # Verify notification appears before transition
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        gate_notifs = [n for n in data if n['type'] == 'gate_review']
        assert len(gate_notifs) == 1

        # Move ticket to terminal status via PUT
        res = client.put(f'/api/tickets/{ticket}', json={'status_id': s_terminal})
        assert res.status_code == 200

        # Notifications should no longer include the gate review
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        gate_notifs = [n for n in data if n['type'] == 'gate_review']
        assert len(gate_notifs) == 0

        # Gate reviews should be deleted from the DB
        from pi_cowork.db import query_db
        with client.application.app_context():
            rows = query_db("SELECT * FROM gate_reviews WHERE ticket_id = ? AND status = 'pending'", (ticket,))
            assert len(rows) == 0

    def test_questions_cleared_on_terminal_transition(self, client):
        """Moving a ticket to a terminal status via PUT deletes unanswered questions."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s_terminal = _create_terminal_status(client, wf, 'Done', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Term Q', s1)
        _create_question(client, ticket, 'Unanswered?')

        # Verify question notification exists
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        q_notifs = [n for n in data if n['type'] == 'question']
        assert len(q_notifs) == 1

        # Move ticket to terminal status
        res = client.put(f'/api/tickets/{ticket}', json={'status_id': s_terminal})
        assert res.status_code == 200

        # Notifications should no longer include the question
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        q_notifs = [n for n in data if n['type'] == 'question']
        assert len(q_notifs) == 0

        # Questions should be deleted from the DB
        from pi_cowork.db import query_db
        with client.application.app_context():
            rows = query_db("SELECT * FROM questions WHERE ticket_id = ?", (ticket,))
            assert len(rows) == 0

    def test_notifications_filtered_for_terminal_tickets(self, client):
        """Even if orphaned notification data remains in the DB for a terminal ticket,
        the /api/notifications endpoint should filter them out."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'In Progress', 2)
        s_terminal = _create_terminal_status(client, wf, 'Done', 3)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Terminal Filter', s_terminal)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)

        # Manually insert pending gate_review and question (bypassing the eager clearing)
        from pi_cowork.db import run_db
        with client.application.app_context():
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', datetime('now'))",
                (ticket, gate, s1, s2)
            )
            run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, datetime('now'))",
                (ticket, 'Stale Q?')
            )

        # API should return empty because the ticket is in a terminal status
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        assert data == []

    def test_gate_approval_to_terminal_clears_questions(self, client):
        """When a gate approval moves a ticket into a terminal status,
        remaining questions should be cleared."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s_terminal = _create_terminal_status(client, wf, 'Done', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Gate to Terminal', s1)

        # Create a manual gate on the terminal status transition
        gate = _create_gate(client, s1, s_terminal, 'Final Gate', wf)
        rid = _create_review(client, ticket, gate, s1, s_terminal)

        # Add a question to the ticket
        _create_question(client, ticket, 'Will this be cleared?')

        # Verify question notification exists
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        q_notifs = [n for n in data if n['type'] == 'question']
        assert len(q_notifs) == 1

        # Approve the gate, which moves the ticket to the terminal status
        res = client.put(f'/api/gate_reviews/{rid}', json={'status': 'approved', 'comment': 'Looks good'}, headers=HUMAN_HEADERS)
        assert res.status_code == 200

        # Questions should be cleared
        from pi_cowork.db import query_db
        with client.application.app_context():
            rows = query_db("SELECT * FROM questions WHERE ticket_id = ?", (ticket,))
            assert len(rows) == 0

        # Notifications should be empty (no gate reviews pending, no questions)
        res = client.get('/api/notifications')
        data = json.loads(res.data)
        assert data == []


# ── Dismiss features (Ticket #52) ──

class TestResolveEndpointRemoved:
    """The resolve endpoint has been removed — agents should not be able to reject
    gate reviews or delete questions via the notification panel."""

    def test_resolve_endpoint_returns_404(self, client):
        res = client.put('/api/notifications/resolve', json={
            'ticket_id': 1, 'type': 'gate_review'
        })
        assert res.status_code == 404


class TestDismissSingleNotification:
    """PUT /api/notifications/dismiss — hide a single notification from the panel."""

    def test_dismiss_gate_review_notification(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Dismiss Gate', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket, gate, s1, s2)

        # Verify notification appears
        notifs = _get_notifications(client)
        assert len(notifs) == 1
        assert notifs[0]['type'] == 'gate_review'

        # Dismiss it
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'gate_review'
        })
        assert res.status_code == 200

        # Notification should no longer appear
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Gate reviews should still exist in the DB (only hidden, not deleted)
        from pi_cowork.db import query_db
        with client.application.app_context():
            rows = query_db("SELECT * FROM gate_reviews WHERE ticket_id = ? AND status = 'pending'", (ticket,))
            assert len(rows) == 1

    def test_dismiss_question_notification(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Dismiss Q', s1)
        _create_question(client, ticket, 'Q1?')

        notifs = _get_notifications(client)
        assert len(notifs) == 1

        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200

        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Questions should still exist in DB
        from pi_cowork.db import query_db
        with client.application.app_context():
            rows = query_db("SELECT * FROM questions WHERE ticket_id = ?", (ticket,))
            assert len(rows) == 1

    def test_dismiss_missing_fields(self, client):
        res = client.put('/api/notifications/dismiss', json={})
        assert res.status_code == 400

        res = client.put('/api/notifications/dismiss', json={'ticket_id': 1})
        assert res.status_code == 400

        res = client.put('/api/notifications/dismiss', json={'type': 'gate_review'})
        assert res.status_code == 400

    def test_dismiss_invalid_type(self, client):
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': 1, 'type': 'invalid'
        })
        assert res.status_code == 400

    def test_dismiss_nonexistent_ticket(self, client):
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': 99999, 'type': 'gate_review'
        })
        assert res.status_code == 404

    def test_dismiss_only_affects_one_type(self, client):
        """Dismissing gate_review doesn't hide question notification for same ticket."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Both Types', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket, gate, s1, s2)
        _create_question(client, ticket, 'Q1?')

        notifs = _get_notifications(client)
        assert len(notifs) == 2

        # Dismiss only the gate_review
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'gate_review'
        })
        assert res.status_code == 200

        notifs = _get_notifications(client)
        assert len(notifs) == 1
        assert notifs[0]['type'] == 'question'


class TestDismissAllNotifications:
    """PUT /api/notifications/dismiss-all — hide all current notifications."""

    def test_dismiss_all(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, 'Gate Ticket', s1)
        t2 = _create_ticket(client, board, 'Question Ticket', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, t1, gate, s1, s2)
        _create_question(client, t2, 'Q?')

        notifs = _get_notifications(client)
        assert len(notifs) == 2

        res = client.put('/api/notifications/dismiss-all')
        assert res.status_code == 200

        notifs = _get_notifications(client)
        assert notifs == []

    def test_dismiss_all_empty(self, client):
        """Dismiss-all when no notifications is a no-op."""
        res = client.put('/api/notifications/dismiss-all')
        assert res.status_code == 200

        notifs = _get_notifications(client)
        assert notifs == []


class TestDismissedNotificationsFiltered:
    """Verify that dismissed notifications are filtered from GET /api/notifications."""

    def test_dismissed_gate_review_not_shown(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, 'Hidden', s1)
        t2 = _create_ticket(client, board, 'Visible', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, t1, gate, s1, s2)
        _create_review(client, t2, gate, s1, s2)

        # Dismiss t1's gate review notification
        client.put('/api/notifications/dismiss', json={
            'ticket_id': t1, 'type': 'gate_review'
        })

        notifs = _get_notifications(client)
        assert len(notifs) == 1
        assert notifs[0]['ticket_id'] == t2

    def test_dismissed_question_not_shown(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, 'Hidden Q', s1)
        t2 = _create_ticket(client, board, 'Visible Q', s1)
        _create_question(client, t1, 'Q1?')
        _create_question(client, t2, 'Q2?')

        client.put('/api/notifications/dismiss', json={
            'ticket_id': t1, 'type': 'question'
        })

        notifs = _get_notifications(client)
        assert len(notifs) == 1
        assert notifs[0]['ticket_id'] == t2


class TestTimestampBasedDismissal:
    """Timestamp-based dismissal: dismissed notifications stay hidden until a
    genuinely new event (question/gate review) is created AFTER the dismissal timestamp.

    This replaces the old auto-clear mechanism (clear_notification_dismissal)
    which deleted the dismissal row entirely whenever a new event was created,
    causing notifications to always reappear even for already-seen events.

    Tests use explicit SQL timestamps to avoid timing-dependent behavior.
    """

    def test_dismissal_stays_hidden_for_existing_events(self, client):
        """After dismissal, notifications for events that existed at dismiss time
        stay hidden even if no auto-clear is triggered."""
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'No Reappear', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, ticket, gate, s1, s2)

        notifs = _get_notifications(client)
        assert len(notifs) == 1

        # Dismiss the notification
        client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'gate_review'
        })
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # The notification stays hidden — dismissed_at >= MAX(created_at)
        notifs = _get_notifications(client)
        assert len(notifs) == 0

    def test_new_gate_review_after_dismiss_reappears(self, client):
        """When a new gate review is created AFTER the dismissal timestamp,
        the notification reappears because the new event's created_at > dismissed_at."""
        from pi_cowork.db import run_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Reappear Gate', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)

        # Create initial gate review with created_at in the past
        with client.application.app_context():
            cur = run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:00')",
                (ticket, gate, s1, s2)
            )

        # Verify notification appears
        notifs = _get_notifications(client)
        assert len(notifs) == 1

        # Dismiss it
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'gate_review'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Set dismissed_at to a known time between old and new events
        with client.application.app_context():
            run_db(
                "UPDATE notification_dismissals SET dismissed_at = '2025-01-01 00:00:01' "
                "WHERE ticket_id = ? AND notification_type = 'gate_review'",
                (ticket,)
            )

        # Create a NEW gate review with created_at after dismissed_at
        with client.application.app_context():
            cur = run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:02')",
                (ticket, gate, s1, s2)
            )

        # Notification should reappear because there's a new event after the dismissal
        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 1

    def test_new_question_after_dismiss_reappears(self, client):
        """When a new question is created AFTER the dismissal timestamp,
        the notification reappears because the new event's created_at > dismissed_at."""
        from pi_cowork.db import run_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Reappear Q', s1)

        # Create initial question with created_at in the past
        with client.application.app_context():
            cur = run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, '2025-01-01 00:00:00')",
                (ticket, 'Old question?')
            )

        # Verify notification appears
        notifs = _get_notifications(client)
        assert len(notifs) == 1

        # Dismiss it
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Set dismissed_at to a known time between old and new questions
        with client.application.app_context():
            run_db(
                "UPDATE notification_dismissals SET dismissed_at = '2025-01-01 00:00:01' "
                "WHERE ticket_id = ? AND notification_type = 'question'",
                (ticket,)
            )

        # Create a NEW question with created_at after dismissed_at
        with client.application.app_context():
            cur = run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, '2025-01-01 00:00:02')",
                (ticket, 'New question after dismiss?')
            )

        # Notification should reappear
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 1

    def test_old_events_stay_hidden_after_dismiss(self, client):
        """Events created BEFORE or AT the same time as the dismissal stay hidden;
        only events created AFTER the dismissal cause the notification to reappear."""
        from pi_cowork.db import run_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Stay Hidden', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)

        # Create gate review with created_at in the past
        with client.application.app_context():
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:00')",
                (ticket, gate, s1, s2)
            )

        notifs = _get_notifications(client)
        assert len(notifs) == 1

        # Dismiss with dismissed_at after all events
        with client.application.app_context():
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', '2025-01-01 00:00:05')",
                (ticket,)
            )

        # Notification hidden
        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 0

        # Add another gate review AT the same time as the dismissal — still hidden
        with client.application.app_context():
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:05')",
                (ticket, gate, s1, s2)
            )

        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 0

        # Add a gate review created BEFORE the dismissal — still hidden
        with client.application.app_context():
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:03')",
                (ticket, gate, s1, s2)
            )

        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 0

        # Add a gate review AFTER the dismissal — notification reappears
        with client.application.app_context():
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:10')",
                (ticket, gate, s1, s2)
            )

        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 1

    def test_re_dismiss_after_reappearance(self, client):
        """After a notification reappears (due to new events), it can be dismissed again,
        and the new dismissal timestamp is used for filtering."""
        from pi_cowork.db import run_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Re-Dismiss', s1)

        # Create initial question with specific past timestamp
        with client.application.app_context():
            run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, '2025-01-01 00:00:00')",
                (ticket, 'First?')
            )

        # Verify notification appears
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 1

        # Dismiss (dismissed_at = now >> 2025-01-01 00:00:00)
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Manually set dismissed_at to a time between old and new question
        with client.application.app_context():
            run_db(
                "UPDATE notification_dismissals SET dismissed_at = '2025-01-01 00:00:01' "
                "WHERE ticket_id = ? AND notification_type = 'question'",
                (ticket,)
            )

        # Create a new question with created_at after dismissed_at
        with client.application.app_context():
            run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, '2025-01-01 00:00:02')",
                (ticket, 'New question?')
            )

        # Notification reappears
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 1

        # Dismiss again (dismissed_at = now >> 2025-01-01 00:00:02)
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 0

    def test_no_auto_clear_on_ticket_transition(self, client):
        """Moving a ticket through a quality gate no longer auto-clears dismissals.
        The notification stays hidden because dismissed_at >= MAX(created_at)
        of the existing pending gate reviews."""
        from pi_cowork.db import run_db, query_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'No Auto Clear', s1)

        # Create a manual gate on the s1→s2 transition
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)

        # Trigger gate creation via the ticket update API
        res = client.put(f'/api/tickets/{ticket}', json={'status_id': s2})

        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 1

        # Dismiss it
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'gate_review'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 0

        # Verify the notification stays hidden (no auto-clear)
        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 0

        # Create a new gate review with created_at AFTER dismissed_at to simulate
        # a genuinely new event that should make the notification reappear
        with client.application.app_context():
            # Set dismissed_at to a known past time
            run_db(
                "UPDATE notification_dismissals SET dismissed_at = '2025-01-01 00:00:00' "
                "WHERE ticket_id = ? AND notification_type = 'gate_review'",
                (ticket,)
            )
            # Add a gate review created after that time
            run_db(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', '2025-01-01 00:00:01')",
                (ticket, gate, s1, s2)
            )

        # Notification reappears because there's a new event after dismissed_at
        notifs = _get_notifications(client)
        gate_notifs = [n for n in notifs if n['type'] == 'gate_review' and n['ticket_id'] == ticket]
        assert len(gate_notifs) == 1

    def test_no_auto_clear_on_question_creation(self, client):
        """Creating a new question via the API no longer auto-clears dismissals.
        If the new question's created_at > dismissed_at, the notification
        reappears naturally through timestamp-based filtering."""
        from pi_cowork.db import run_db

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        board = _create_board(client, wf)
        ticket = _create_ticket(client, board, 'Question No Clear', s1)

        # Create a question with a specific past timestamp
        with client.application.app_context():
            run_db(
                "INSERT INTO questions (ticket_id, body, created_at) VALUES (?, ?, '2025-01-01 00:00:00')",
                (ticket, 'Old question?')
            )

        notifs = _get_notifications(client)
        assert len(notifs) == 1

        # Dismiss
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        assert len(notifs) == 0

        # Set dismissed_at to a known time between old and new questions
        with client.application.app_context():
            run_db(
                "UPDATE notification_dismissals SET dismissed_at = '2025-01-01 00:00:01' "
                "WHERE ticket_id = ? AND notification_type = 'question'",
                (ticket,)
            )

        # Create a new question via API (this used to call clear_notification_dismissal)
        # The new question has created_at = CURRENT_TIMESTAMP, which is >> 2025-01-01 00:00:01
        # So the notification should reappear via timestamp-based filtering
        res = client.post(f'/api/tickets/{ticket}/questions', json={
            'questions': [{'body': 'New question after dismiss?'}]
        })
        assert res.status_code == 201

        # The notification reappears because the new question has a later timestamp
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 1

        # Dismiss again — should stay hidden
        res = client.put('/api/notifications/dismiss', json={
            'ticket_id': ticket, 'type': 'question'
        })
        assert res.status_code == 200
        notifs = _get_notifications(client)
        q_notifs = [n for n in notifs if n['type'] == 'question' and n['ticket_id'] == ticket]
        assert len(q_notifs) == 0
class TestClearAllDismiss:
    """Clear All button flow — dismiss all current notifications at once."""

    def test_clear_all_with_mixed_types(self, client):
        wf = _create_workflow(client)
        s1 = _create_status(client, wf, 'Backlog', 1)
        s2 = _create_status(client, wf, 'Review', 2)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, 'Gate T', s1)
        t2 = _create_ticket(client, board, 'Q T', s1)
        gate = _create_gate(client, s1, s2, 'Manual Gate', wf)
        _create_review(client, t1, gate, s1, s2)
        _create_question(client, t2, 'Q?')

        notifs = _get_notifications(client)
        assert len(notifs) == 2

        # Dismiss all
        res = client.put('/api/notifications/dismiss-all')
        assert res.status_code == 200

        notifs = _get_notifications(client)
        assert notifs == []

        # Underlying data still exists
        from pi_cowork.db import query_db
        with client.application.app_context():
            gate_rows = query_db("SELECT * FROM gate_reviews WHERE ticket_id = ? AND status = 'pending'", (t1,))
            assert len(gate_rows) == 1
            q_rows = query_db("SELECT * FROM questions WHERE ticket_id = ?", (t2,))
            assert len(q_rows) == 1