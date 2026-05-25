import json
from unittest.mock import patch


def test_create_ticket(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'Hello',
        'body': 'World',
        'board_id': default_board['id'],
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['id']
    assert data['status_id']
    assert data['board_id'] == default_board['id']

    # Verify default priority is Medium
    detail = client.get(f'/api/tickets/{data["id"]}')
    ticket = json.loads(detail.data)
    assert ticket['priority'] == 'Medium'


def test_create_ticket_with_priority(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'High Priority',
        'board_id': default_board['id'],
        'priority': 'High',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    detail = client.get(f'/api/tickets/{data["id"]}')
    ticket = json.loads(detail.data)
    assert ticket['priority'] == 'High'


def test_create_ticket_invalid_priority(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'Bad Priority',
        'board_id': default_board['id'],
        'priority': 'Urgent',
    })
    assert res.status_code == 400
    assert b'priority must be one of' in res.data


def test_update_ticket_priority(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'T',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    res = client.put(f'/api/tickets/{tid}', json={'priority': 'Critical'})
    assert res.status_code == 200
    detail = client.get(f'/api/tickets/{tid}')
    ticket = json.loads(detail.data)
    assert ticket['priority'] == 'Critical'


def test_update_ticket_invalid_priority(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'T',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    res = client.put(f'/api/tickets/{tid}', json={'priority': 'SuperUrgent'})
    assert res.status_code == 400
    assert b'priority must be one of' in res.data


def test_list_tickets_sort_by_priority(client, default_board):
    # Create tickets with different priorities
    t1 = client.post('/api/tickets', json={
        'title': 'Low Ticket',
        'board_id': default_board['id'],
        'priority': 'Low',
    })
    t2 = client.post('/api/tickets', json={
        'title': 'Critical Ticket',
        'board_id': default_board['id'],
        'priority': 'Critical',
    })
    t3 = client.post('/api/tickets', json={
        'title': 'High Ticket',
        'board_id': default_board['id'],
        'priority': 'High',
    })
    t4 = client.post('/api/tickets', json={
        'title': 'Medium Ticket',
        'board_id': default_board['id'],
        'priority': 'Medium',
    })

    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    data = json.loads(res.data)
    priorities = [t['priority'] for t in data]
    # API returns Critical > High > Medium > Low within same created_at ordering (newest first)
    # All created sequentially, so reverse chronological = last created first
    # But priority DESC takes precedence over created_at DESC.
    # Critical (4) > High (3) > Medium (2) > Low (1)
    assert priorities == ['Critical', 'High', 'Medium', 'Low']


def test_create_ticket_no_board(client):
    res = client.post('/api/tickets', json={'title': 'Hello'})
    assert res.status_code == 400
    assert b'board_id' in res.data


def test_list_tickets_by_board(client, default_board, new_board, new_workflow):
    # Add a default status to the new workflow so tickets can be created
    client.post('/api/statuses', json={
        'name': 'New Default',
        'sort_order': 1,
        'is_default': True,
        'is_terminal': False,
        'workflow_id': new_workflow['id'],
    })
    # Create tickets on different boards
    client.post('/api/tickets', json={
        'title': 'Default Board Ticket',
        'board_id': default_board['id'],
    })
    client.post('/api/tickets', json={
        'title': 'New Board Ticket',
        'board_id': new_board['id'],
    })
    
    # Check default board only
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]['title'] == 'Default Board Ticket'
    
    # Check new board only
    res = client.get(f'/api/tickets?board_id={new_board["id"]}')
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]['title'] == 'New Board Ticket'


def test_update_ticket_status(client, default_workflow, default_board):
    # Create an agent and a status with that agent in the default workflow
    agent = client.post('/api/agents', json={
        'name': 'Dev',
        'description': 'dev agent',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']
    status = client.post('/api/statuses', json={
        'name': 'Coding',
        'sort_order': 5,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(status.data)['id']

    # Create ticket on default board
    res = client.post('/api/tickets', json={
        'title': 'T',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    with patch('app.subprocess.Popen') as mock_popen:
        res = client.put(f'/api/tickets/{tid}', json={'status_id': sid})
        assert res.status_code == 200
        assert mock_popen.called


def test_update_ticket_no_agent(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'T',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    
    # Get Backlog status id (seeded, no agent)
    statuses = json.loads(client.get('/api/statuses?workflow_id=1').data)
    backlog_id = next(s['id'] for s in statuses if s['name'] == 'Backlog')

    with patch('app.subprocess.Popen') as mock_popen:
        res = client.put(f'/api/tickets/{tid}', json={'status_id': backlog_id})
        assert res.status_code == 200
        assert not mock_popen.called


def test_add_comment(client, default_board):
    res = client.post('/api/tickets', json={
        'title': 'T',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']
    res = client.post(f'/api/tickets/{tid}/comments', json={'body': 'nice'})
    assert res.status_code == 201
    comments = json.loads(client.get(f'/api/tickets/{tid}/comments').data)
    assert len(comments) == 1
    assert comments[0]['body'] == 'nice'


def test_comments_order_with_identical_timestamps(client, default_board):
    """Comments with the same created_at must still be ordered by id."""
    import sqlite3
    from app import app

    res = client.post('/api/tickets', json={
        'title': 'Ordering',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    # Insert two comments with the exact same created_at directly
    with app.app_context():
        db = sqlite3.connect(app.config['DATABASE'])
        db.execute(
            "INSERT INTO comments (ticket_id, body, created_at) VALUES (?, ?, ?)",
            (tid, 'first', '2024-01-01 12:00:00')
        )
        db.execute(
            "INSERT INTO comments (ticket_id, body, created_at) VALUES (?, ?, ?)",
            (tid, 'second', '2024-01-01 12:00:00')
        )
        db.commit()
        db.close()

    comments = json.loads(client.get(f'/api/tickets/{tid}/comments').data)
    assert len(comments) == 2
    assert comments[0]['body'] == 'first'
    assert comments[1]['body'] == 'second'


# ── Git-enabled tests ──

def test_branch_hidden_when_git_disabled(client, default_workflow, default_board):
    """Branch field should not appear in ticket list when git_enabled is off."""
    # Default workflow should have git_enabled = 0
    wf = json.loads(client.get(f'/api/workflows/{default_workflow["id"]}').data)
    assert wf.get('git_enabled') in (0, False, None)

    res = client.post('/api/tickets', json={
        'title': 'No git ticket',
        'board_id': default_board['id'],
    })
    assert res.status_code == 201
    tid = json.loads(res.data)['id']

    # Directly update the ticket's branch (DB-level bypass, simulating prior data)
    from pi_cowork.db import run_db
    with client.application.app_context():
        run_db("UPDATE tickets SET branch = ? WHERE id = ?", ('ticket-1-test', tid))

    # List tickets — branch should be excluded
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    tickets = json.loads(res.data)
    ticket = next(t for t in tickets if t['id'] == tid)
    assert 'branch' not in ticket

    # Single ticket — branch should be excluded
    res = client.get(f'/api/tickets/{tid}')
    ticket = json.loads(res.data)
    assert 'branch' not in ticket


def test_branch_visible_when_git_enabled(client, default_workflow, default_board):
    """Branch field should appear in ticket when git_enabled is on."""
    # Enable git on workflow
    res = client.put(f'/api/workflows/{default_workflow["id"]}', json={'git_enabled': True})
    assert res.status_code == 200

    res = client.post('/api/tickets', json={
        'title': 'Git ticket',
        'board_id': default_board['id'],
    })
    assert res.status_code == 201
    tid = json.loads(res.data)['id']

    # Set branch directly
    from pi_cowork.db import run_db
    with client.application.app_context():
        run_db("UPDATE tickets SET branch = ? WHERE id = ?", ('ticket-99-git-ticket', tid))

    # List tickets — branch should be present
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    tickets = json.loads(res.data)
    ticket = next(t for t in tickets if t['id'] == tid)
    assert ticket.get('branch') == 'ticket-99-git-ticket'

    # Single ticket — branch should be present
    res = client.get(f'/api/tickets/{tid}')
    ticket = json.loads(res.data)
    assert ticket.get('branch') == 'ticket-99-git-ticket'


def test_branch_update_blocked_when_git_disabled(client, default_workflow, default_board):
    """PUT with branch field should return 400 when git not enabled."""
    res = client.post('/api/tickets', json={
        'title': 'Blocked',
        'board_id': default_board['id'],
    })
    assert res.status_code == 201
    tid = json.loads(res.data)['id']

    res = client.put(f'/api/tickets/{tid}', json={'branch': 'ticket-1-test'})
    assert res.status_code == 400
    assert b'git' in res.data.lower()


def test_branch_update_allowed_when_git_enabled(client, default_workflow, default_board):
    """PUT with branch field should succeed when git is enabled."""
    # Enable git on workflow
    client.put(f'/api/workflows/{default_workflow["id"]}', json={'git_enabled': True})

    res = client.post('/api/tickets', json={
        'title': 'Allowed',
        'board_id': default_board['id'],
    })
    assert res.status_code == 201
    tid = json.loads(res.data)['id']

    res = client.put(f'/api/tickets/{tid}', json={'branch': 'ticket-1-allowed'})
    assert res.status_code == 200

    # Verify branch was set
    ticket = json.loads(client.get(f'/api/tickets/{tid}').data)
    assert ticket['branch'] == 'ticket-1-allowed'


def test_create_ticket_ignores_branch_field(client, default_board):
    """POST ticket should ignore branch field — branch is auto-managed."""
    res = client.post('/api/tickets', json={
        'title': 'Ignored branch',
        'board_id': default_board['id'],
        'branch': 'should-be-ignored',
    })
    assert res.status_code == 201
    # branch should not be set
    tid = json.loads(res.data)['id']
    from pi_cowork.db import query_db
    with client.application.app_context():
        row = query_db('SELECT branch FROM tickets WHERE id = ?', (tid,), one=True)
    assert row['branch'] is None
