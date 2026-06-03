"""Tests for GET /api/tickets include_terminal parameter and removal of limit/offset.

Verifies:
1. Default request (no include_terminal) excludes terminal tickets
2. include_terminal=true includes all tickets (terminal + non-terminal)
3. More than 100 non-terminal tickets are all returned (no limit)
4. limit/offset parameters are ignored (backwards compatible, no error)
"""

import json


def _create_ticket(client, board_id, title='Ticket', priority='Medium'):
    """Helper to create a ticket and return its id."""
    res = client.post('/api/tickets', json={
        'title': title,
        'board_id': board_id,
        'priority': priority,
    })
    assert res.status_code == 201
    return json.loads(res.data)['id']


def _get_status_id(client, workflow_id, status_name):
    """Helper to find a status id by name in a workflow."""
    res = client.get(f'/api/statuses?workflow_id={workflow_id}')
    statuses = json.loads(res.data)
    for s in statuses:
        if s['name'] == status_name:
            return s['id']
    return None


def _get_terminal_status_id(client, workflow_id):
    """Helper to find a terminal status id (Closed or Dropped)."""
    res = client.get(f'/api/statuses?workflow_id={workflow_id}')
    statuses = json.loads(res.data)
    for s in statuses:
        if s.get('is_terminal'):
            return s['id']
    return None


def test_default_excludes_terminal(client, default_board):
    """By default, GET /api/tickets excludes terminal tickets."""
    wf_id = default_board['workflow_id']
    terminal_id = _get_terminal_status_id(client, wf_id)
    assert terminal_id is not None, "Workflow must have a terminal status"

    # Create a non-terminal ticket
    _create_ticket(client, default_board['id'], 'Active ticket')

    # Create a terminal ticket by moving it to Closed
    tid = _create_ticket(client, default_board['id'], 'Closed ticket')
    client.put(f'/api/tickets/{tid}', json={'status_id': terminal_id})

    # Default request should only return 1 ticket (the non-terminal one)
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]['title'] == 'Active ticket'


def test_include_terminal_true_returns_all(client, default_board):
    """include_terminal=true returns both terminal and non-terminal tickets."""
    wf_id = default_board['workflow_id']
    terminal_id = _get_terminal_status_id(client, wf_id)
    assert terminal_id is not None

    _create_ticket(client, default_board['id'], 'Active ticket')
    tid = _create_ticket(client, default_board['id'], 'Closed ticket')
    client.put(f'/api/tickets/{tid}', json={'status_id': terminal_id})

    res = client.get(f'/api/tickets?board_id={default_board["id"]}&include_terminal=true')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 2
    titles = sorted(t['title'] for t in data)
    assert titles == ['Active ticket', 'Closed ticket']


def test_include_terminal_false_explicit(client, default_board):
    """include_terminal=false explicitly excludes terminal tickets, matching the default."""
    wf_id = default_board['workflow_id']
    terminal_id = _get_terminal_status_id(client, wf_id)
    assert terminal_id is not None

    _create_ticket(client, default_board['id'], 'Active ticket')
    tid = _create_ticket(client, default_board['id'], 'Closed ticket')
    client.put(f'/api/tickets/{tid}', json={'status_id': terminal_id})

    res = client.get(f'/api/tickets?board_id={default_board["id"]}&include_terminal=false')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]['title'] == 'Active ticket'


def test_no_limit_on_100_plus_tickets(client, default_board):
    """When >100 non-terminal tickets exist, all are returned (no LIMIT)."""
    for i in range(110):
        _create_ticket(client, default_board['id'], f'Ticket {i}')

    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 110


def test_include_terminal_true_with_100_plus_tickets(client, default_board):
    """include_terminal=true also returns all >100 tickets without limit."""
    wf_id = default_board['workflow_id']
    terminal_id = _get_terminal_status_id(client, wf_id)
    assert terminal_id is not None

    # Create 105 non-terminal + 5 terminal = 110 total
    for i in range(105):
        _create_ticket(client, default_board['id'], f'Active {i}')

    for i in range(5):
        tid = _create_ticket(client, default_board['id'], f'Closed {i}')
        client.put(f'/api/tickets/{tid}', json={'status_id': terminal_id})

    # With include_terminal=true, all 110 should be returned
    res = client.get(f'/api/tickets?board_id={default_board["id"]}&include_terminal=true')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 110

    # Without include_terminal, only 105 non-terminal should be returned
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 105


def test_limit_and_offset_parameters_ignored(client, default_board):
    """limit and offset parameters no longer have any effect (backwards compatible)."""
    _create_ticket(client, default_board['id'], 'Ticket A')
    _create_ticket(client, default_board['id'], 'Ticket B')
    _create_ticket(client, default_board['id'], 'Ticket C')

    # With old-style limit=1, should still return all 3 tickets
    res = client.get(f'/api/tickets?board_id={default_board["id"]}&limit=1')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 3

    # With old-style offset, should still return all 3 tickets
    res = client.get(f'/api/tickets?board_id={default_board["id"]}&offset=2')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 3


def test_empty_board_returns_empty(client, default_board):
    """An empty board returns an empty list regardless of include_terminal."""
    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data == []

    res = client.get(f'/api/tickets?board_id={default_board["id"]}&include_terminal=true')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data == []


def test_all_terminal_tickets_default_returns_empty(client, default_board):
    """If all tickets are terminal, default returns empty list."""
    wf_id = default_board['workflow_id']
    terminal_id = _get_terminal_status_id(client, wf_id)

    tid = _create_ticket(client, default_board['id'], 'Only closed')
    client.put(f'/api/tickets/{tid}', json={'status_id': terminal_id})

    res = client.get(f'/api/tickets?board_id={default_board["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 0

    # But include_terminal=true should show it
    res = client.get(f'/api/tickets?board_id={default_board["id"]}&include_terminal=true')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1


def test_board_filtering_still_works_with_include_terminal(client, default_board, new_board, new_workflow):
    """Board filtering is independent of include_terminal."""
    # Create a non-default status on the new workflow
    client.post('/api/statuses', json={
        'name': 'New Default',
        'sort_order': 1,
        'is_default': True,
        'is_terminal': False,
        'workflow_id': new_workflow['id'],
    })

    _create_ticket(client, default_board['id'], 'Board 1 ticket')
    _create_ticket(client, new_board['id'], 'Board 2 ticket')

    default_res = json.loads(client.get(f'/api/tickets?board_id={default_board["id"]}').data)
    new_res = json.loads(client.get(f'/api/tickets?board_id={new_board["id"]}').data)

    assert len(default_res) == 1
    assert default_res[0]['title'] == 'Board 1 ticket'
    assert len(new_res) == 1
    assert new_res[0]['title'] == 'Board 2 ticket'