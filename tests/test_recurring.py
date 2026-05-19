"""Tests for recurring tasks (Ticket #47)."""

import json
from datetime import datetime, timezone, timedelta

import pytest


# ── Helpers ──

def _make_recurring(client, board_id, status_id, cron='0 9 * * 1', **overrides):
    payload = {
        'board_id': board_id,
        'title': 'Weekly recap',
        'body': 'Generate weekly status summary',
        'status_id': status_id,
        'cron_expression': cron,
        **overrides,
    }
    res = client.post('/api/recurring', json=payload)
    return res


def _status_for_board(client, board_id):
    board = client.get(f'/api/boards/{board_id}')
    bd = json.loads(board.data)
    statuses = client.get(f'/api/statuses?workflow_id={bd['workflow_id']}')
    return json.loads(statuses.data)[0]


def _run_db_in_ctx(client, query, args=()):
    """Run a DB write within app context."""
    with client.application.app_context():
        from pi_cowork.db import run_db
        return run_db(query, args)


# ── CRUD ──


def test_create_recurring_task(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    res = _make_recurring(client, board_id, status['id'])
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['title'] == 'Weekly recap'
    assert data['cron_expression'] == '0 9 * * 1'
    assert data['enabled'] == 1
    assert data['next_trigger_at'] is not None
    assert data['human_readable'] is not None


def test_create_recurring_with_invalid_cron(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    res = _make_recurring(client, board_id, status['id'], cron='invalid cron')
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'Invalid cron' in data['error']


def test_create_recurring_no_title(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    res = client.post('/api/recurring', json={
        'board_id': board_id,
        'status_id': status['id'],
        'cron_expression': '0 9 * * 1',
    })
    assert res.status_code == 400


def test_create_recurring_no_board_id(client):
    res = client.post('/api/recurring', json={
        'title': 'Test',
        'status_id': 1,
        'cron_expression': '0 9 * * 1',
    })
    assert res.status_code == 400


def test_list_recurring_tasks(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    _make_recurring(client, board_id, status['id'])
    _make_recurring(client, board_id, status['id'], title='Daily standup', cron='0 9 * * *')
    res = client.get(f'/api/recurring?board_id={board_id}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 2
    for t in data:
        assert 'human_readable' in t


def test_get_single_recurring(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.get(f'/api/recurring/{task_id}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['id'] == task_id
    assert 'human_readable' in data


def test_get_nonexistent_recurring(client):
    res = client.get('/api/recurring/99999')
    assert res.status_code == 404


def test_update_recurring(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.put(f'/api/recurring/{task_id}', json={'title': 'Updated recap'})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['title'] == 'Updated recap'


def test_update_recurring_cron_recomputes_next_trigger(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.put(f'/api/recurring/{task_id}', json={'cron_expression': '0 17 * * 5'})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['next_trigger_at'] is not None
    assert data['cron_expression'] == '0 17 * * 5'


def test_update_recurring_invalid_cron(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.put(f'/api/recurring/{task_id}', json={'cron_expression': 'bad'})
    assert res.status_code == 400


def test_delete_recurring_no_instances(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.delete(f'/api/recurring/{task_id}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get('deleted') is True
    res2 = client.get(f'/api/recurring/{task_id}')
    assert res2.status_code == 404


def test_toggle_recurring_disables(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    res = client.post(f'/api/recurring/{task_id}/toggle')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['enabled'] == 0
    assert data['next_trigger_at'] is None


def test_toggle_recurring_re_enables(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']
    client.post(f'/api/recurring/{task_id}/toggle')
    res = client.post(f'/api/recurring/{task_id}/toggle')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['enabled'] == 1
    assert data['next_trigger_at'] is not None


# ── Cron Preview ──


def test_cron_preview_valid(client):
    res = client.get('/api/recurring/preview?cron=0+9+*+*+1')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data['times']) == 5
    assert data['human_readable'] is not None


def test_cron_preview_invalid(client):
    res = client.get('/api/recurring/preview?cron=invalid')
    assert res.status_code == 400


def test_cron_preview_missing(client):
    res = client.get('/api/recurring/preview')
    assert res.status_code == 400


# ── Manual Trigger ──


def test_manual_trigger_creates_ticket(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    res = client.post(f'/api/recurring/{task_id}/trigger')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is True
    ticket_id = data['ticket_id']

    ticket = client.get(f'/api/tickets/{ticket_id}')
    assert ticket.status_code == 200
    td = json.loads(ticket.data)
    assert '[Recurring' in td['title']
    assert td['status_id'] == status['id']

    parents = client.get(f'/api/tickets/{ticket_id}/recurring')
    assert parents.status_code == 200
    pd = json.loads(parents.data)
    assert len(pd) == 1
    assert pd[0]['id'] == task_id


def test_manual_trigger_updates_timestamps(client, default_board):
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    client.post(f'/api/recurring/{task_id}/trigger')
    updated = client.get(f'/api/recurring/{task_id}')
    ud = json.loads(updated.data)
    assert ud['last_triggered_at'] is not None
    assert ud['next_trigger_at'] is not None


def test_ticket_recurring_parents_empty(client, default_board):
    """A normal ticket (not from recurring) has empty recurring_parents."""
    res = client.post('/api/tickets', json={
        'board_id': default_board['id'],
        'title': 'Normal ticket',
    })
    ticket_id = json.loads(res.data)['id']
    parents = client.get(f'/api/tickets/{ticket_id}/recurring')
    assert parents.status_code == 200
    assert json.loads(parents.data) == []


# ── Scheduler (process_recurring_tasks) ──


def test_scheduler_creates_ticket_when_due(client, default_board):
    """process_recurring_tasks should create tickets for due tasks."""
    from pi_cowork import models

    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=30)).isoformat()

    create = _make_recurring(client, board_id, status['id'], cron='* * * * *')
    task_id = json.loads(create.data)['id']

    _run_db_in_ctx(client,
        "UPDATE recurring_tasks SET next_trigger_at = ? WHERE id = ?",
        (past, task_id))

    with client.application.app_context():
        models.process_recurring_tasks()

    tickets = client.get(f'/api/tickets?board_id={board_id}')
    data = json.loads(tickets.data)
    due_tickets = [t for t in data if 'Weekly recap' in t['title']]
    assert len(due_tickets) >= 1

    ticket_id = due_tickets[0]['id']
    parents = client.get(f'/api/tickets/{ticket_id}/recurring')
    pd = json.loads(parents.data)
    assert len(pd) >= 1
    assert any(p['id'] == task_id for p in pd)

    assert any(p for p in due_tickets[0].get('recurring_parents', [])
               if p['id'] == task_id)


def test_scheduler_updates_next_trigger_after_fire(client, default_board):
    """After process_recurring_tasks fires, next_trigger_at should be updated."""
    from pi_cowork import models
    from pi_cowork.db import query_db, row_to_dict

    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=30)).isoformat()

    create = _make_recurring(client, board_id, status['id'], cron='* * * * *')
    task_id = json.loads(create.data)['id']

    _run_db_in_ctx(client,
        "UPDATE recurring_tasks SET next_trigger_at = ? WHERE id = ?",
        (past, task_id))

    old = None
    with client.application.app_context():
        old = query_db("SELECT next_trigger_at FROM recurring_tasks WHERE id = ?",
                       (task_id,), one=True)
        models.process_recurring_tasks()

    with client.application.app_context():
        new_task = query_db("SELECT * FROM recurring_tasks WHERE id = ?",
                            (task_id,), one=True)
        newd = row_to_dict(new_task)
        assert newd['last_triggered_at'] is not None
        assert newd['next_trigger_at'] is not None
        assert newd['next_trigger_at'] != old['next_trigger_at']


def test_disabled_task_not_triggered(client, default_board):
    """A disabled task should not create tickets even if next_trigger_at is in the past."""
    from pi_cowork import models

    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=30)).isoformat()

    create = _make_recurring(client, board_id, status['id'], cron='* * * * *')
    task_id = json.loads(create.data)['id']

    _run_db_in_ctx(client,
        "UPDATE recurring_tasks SET next_trigger_at = ?, enabled = 0 WHERE id = ?",
        (past, task_id))

    before = client.get(f'/api/tickets?board_id={board_id}')
    before_count = len(json.loads(before.data))

    with client.application.app_context():
        models.process_recurring_tasks()

    after = client.get(f'/api/tickets?board_id={board_id}')
    after_count = len(json.loads(after.data))

    assert after_count == before_count


def test_end_at_past_disables_task(client, default_board):
    """A task with end_at in the past should be auto-disabled."""
    from pi_cowork import models
    from pi_cowork.db import query_db, row_to_dict

    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    now = datetime.now(timezone.utc)
    past = (now - timedelta(minutes=30)).isoformat()
    end_past = (now - timedelta(minutes=10)).isoformat()

    create = _make_recurring(client, board_id, status['id'], cron='* * * * *')
    task_id = json.loads(create.data)['id']

    _run_db_in_ctx(client,
        "UPDATE recurring_tasks SET next_trigger_at = ?, end_at = ? WHERE id = ?",
        (past, end_past, task_id))

    with client.application.app_context():
        models.process_recurring_tasks()

    with client.application.app_context():
        task = query_db(
            "SELECT enabled, next_trigger_at FROM recurring_tasks WHERE id = ?",
            (task_id,), one=True)
        td = row_to_dict(task)
        assert td['enabled'] == 0
        assert td['next_trigger_at'] is None


def test_board_delete_cascades_recurring(client, default_board, default_workflow):
    """Deleting a board should delete its recurring tasks and instances."""
    # Create a new board under the default workflow (which has statuses)
    res = client.post('/api/boards', json={
        'name': 'Recurring Test Board',
        'workflow_id': default_workflow['id'],
    })
    board_id = json.loads(res.data)['id']
    status = _status_for_board(client, board_id)

    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    trigger = client.post(f'/api/recurring/{task_id}/trigger')
    ticket_id = json.loads(trigger.data)['ticket_id']

    res = client.delete(f'/api/boards/{board_id}')
    assert res.status_code == 200

    res = client.get(f'/api/recurring/{task_id}')
    assert res.status_code == 404

    res = client.get(f'/api/tickets/{ticket_id}')
    assert res.status_code == 404


# ── Edge cases ──


def test_start_at_in_future(client, default_board):
    """Task with start_at in the future should have next_trigger_at set after start_at."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    res = _make_recurring(client, board_id, status['id'],
                          cron='0 9 * * 1', start_at=future)
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['next_trigger_at'] is not None
    nt = datetime.fromisoformat(data['next_trigger_at'].replace('Z', '+00:00'))
    ft = datetime.fromisoformat(future.replace('Z', '+00:00'))
    assert nt >= ft


def test_every_minute_cron(client, default_board):
    """'* * * * *' cron should be valid and compute next trigger."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)

    res = _make_recurring(client, board_id, status['id'], cron='* * * * *')
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['next_trigger_at'] is not None
    assert data['human_readable'] is not None


def test_human_readable_mappings(client):
    """Test human-readable cron conversions."""
    res = client.get('/api/recurring/preview?cron=*+*+*+*+*')
    assert json.loads(res.data)['human_readable'] == 'Every minute'

    res = client.get('/api/recurring/preview?cron=0+*+*+*+*')
    assert json.loads(res.data)['human_readable'] == 'Every hour'

    res = client.get('/api/recurring/preview?cron=0+9+*+*+*')
    assert json.loads(res.data)['human_readable'] == 'Daily at 9:00 AM'

    res = client.get('/api/recurring/preview?cron=0+9+*+*+1')
    assert json.loads(res.data)['human_readable'] == 'Every Monday at 9:00 AM'

    res = client.get('/api/recurring/preview?cron=0+9+1+*+*')
    assert json.loads(res.data)['human_readable'] == '1st of every month at 9:00 AM'


def test_recurring_info_in_ticket_response(client, default_board):
    """Ticket detail should include recurring_parents."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    trigger = client.post(f'/api/recurring/{task_id}/trigger')
    ticket_id = json.loads(trigger.data)['ticket_id']

    ticket = client.get(f'/api/tickets/{ticket_id}')
    td = json.loads(ticket.data)
    assert 'recurring_parents' in td
    assert len(td['recurring_parents']) == 1
    assert td['recurring_parents'][0]['id'] == task_id


def test_recurring_parents_in_ticket_list(client, default_board):
    """Ticket list should include recurring_parents."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    trigger = client.post(f'/api/recurring/{task_id}/trigger')
    ticket_id = json.loads(trigger.data)['ticket_id']

    tickets = client.get(f'/api/tickets?board_id={board_id}')
    tlist = json.loads(tickets.data)
    found = [t for t in tlist if t['id'] == ticket_id]
    assert len(found) == 1
    assert len(found[0]['recurring_parents']) == 1


def test_end_at_in_past_rejected_on_create(client, default_board):
    """Creating a task with end_at in the past should fail."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    res = _make_recurring(client, board_id, status['id'], end_at=past)
    assert res.status_code == 400


def test_recurring_badge_in_ticket_list(client, default_board):
    """Tickets created from recurring tasks should have recurring_parents in list response."""
    board_id = default_board['id']
    status = _status_for_board(client, board_id)
    create = _make_recurring(client, board_id, status['id'])
    task_id = json.loads(create.data)['id']

    trigger = client.post(f'/api/recurring/{task_id}/trigger')
    ticket_id = json.loads(trigger.data)['ticket_id']

    tickets = client.get(f'/api/tickets?board_id={board_id}')
    tlist = json.loads(tickets.data)
    found = [t for t in tlist if t['id'] == ticket_id]
    assert len(found) == 1
    assert len(found[0]['recurring_parents']) == 1
    assert found[0]['recurring_parents'][0]['title'] == 'Weekly recap'
