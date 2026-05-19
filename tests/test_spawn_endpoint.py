"""Tests for the POST /api/tickets/<id>/spawn endpoint and running_agents field."""

import json
from unittest.mock import patch, MagicMock

import app as app_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_agent(client, workflow_id, name='TestAgent', description='You are a test agent.'):
    res = client.post('/api/agents', json={
        'name': name,
        'description': description,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_status_with_agent(client, workflow_id, agent_id, name='SpawnStage', sort_order=99, is_terminal=False):
    res = client.post('/api/statuses', json={
        'name': name,
        'sort_order': sort_order,
        'agent_id': agent_id,
        'is_terminal': is_terminal,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_terminal_status(client, workflow_id, name='DoneStage', sort_order=100):
    res = client.post('/api/statuses', json={
        'name': name,
        'sort_order': sort_order,
        'is_terminal': True,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_status_no_agent(client, workflow_id, name='NoAgentStage', sort_order=101):
    res = client.post('/api/statuses', json={
        'name': name,
        'sort_order': sort_order,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_ticket(client, board_id, title='Spawn Ticket'):
    res = client.post('/api/tickets', json={
        'title': title,
        'board_id': board_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


# ---------------------------------------------------------------------------
# POST /api/tickets/<id>/spawn tests
# ---------------------------------------------------------------------------

def test_spawn_success(client, default_workflow, default_board):
    """Spawn an agent via the explicit spawn endpoint."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])

    # Move ticket to the status with the agent (triggers agent spawn)
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=54321)
        move_res = client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': status['id']})
        assert move_res.status_code == 200

    # Mark the running agent as completed so we can re-spawn
    with client.application.app_context():
        app_module.run_db("UPDATE agent_runs SET status = 'completed', completed_at = datetime('now') WHERE ticket_id = ?", (ticket['id'],))

    # Re-spawn via the explicit endpoint
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=54322)
        res = client.post(f'/api/tickets/{ticket["id"]}/spawn')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True
        assert 'agent' in data
        assert data['agent']['id'] == agent['id']
        assert data['spawned'] is True


def test_spawn_terminal_status_rejected(client, default_workflow, default_board):
    """Cannot spawn agent on a ticket in a terminal status."""
    terminal_status = _create_terminal_status(client, default_workflow['id'])
    ticket = _create_ticket(client, default_board['id'])

    # Move ticket to terminal status
    client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': terminal_status['id']})

    res = client.post(f'/api/tickets/{ticket["id"]}/spawn')
    assert res.status_code == 409
    data = json.loads(res.data)
    assert 'terminal' in data['error'].lower()


def test_spawn_no_agent_rejected(client, default_workflow, default_board):
    """Cannot spawn agent when current status has no agent assigned."""
    no_agent_status = _create_status_no_agent(client, default_workflow['id'])
    ticket = _create_ticket(client, default_board['id'])

    # Move to status with no agent
    client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': no_agent_status['id']})

    res = client.post(f'/api/tickets/{ticket["id"]}/spawn')
    assert res.status_code == 409
    data = json.loads(res.data)
    assert 'no agent' in data['error'].lower()


def test_spawn_already_running_rejected(client, default_workflow, default_board):
    """Cannot spawn when an agent is already running on this ticket."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])

    # Spawn an agent that stays running
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=54323)
        client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': status['id']})

    # Try to spawn again while still running
    res = client.post(f'/api/tickets/{ticket["id"]}/spawn')
    assert res.status_code == 409
    data = json.loads(res.data)
    assert 'already running' in data['error'].lower()


def test_spawn_ticket_not_found(client):
    """Spawn endpoint returns 404 for nonexistent ticket."""
    res = client.post('/api/tickets/99999/spawn')
    assert res.status_code == 404


def test_spawn_queued_when_parallel_limit_reached(client, default_workflow, default_board):
    """When parallel limit is reached, spawn endpoint queues the agent."""
    from pi_cowork.models import set_setting

    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])

    # Ticket1: spawn agent, occupies the single parallel slot
    ticket1 = _create_ticket(client, default_board['id'], title='First ticket')
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=54324)
        client.put(f'/api/tickets/{ticket1["id"]}', json={'status_id': status['id']})

    # Ticket2: place into agent status via DB without spawning (bypass API)
    ticket2 = _create_ticket(client, default_board['id'], title='Second ticket')
    with client.application.app_context():
        app_module.run_db("UPDATE tickets SET status_id = ? WHERE id = ?", (status['id'], ticket2['id']))

    # Set parallel limit to 1 (ticket1's agent occupies it)
    # The DB is seeded with max_parallel=1, so this is the default
    # But let's be explicit and set it
    with client.application.app_context():
        set_setting('max_parallel', '1')

    # Patch _is_our_process to keep ticket1's agent alive during cleanup
    with patch('app.subprocess.Popen') as mock_popen, \
         patch('pi_cowork.agents._is_our_process', return_value=True):
        mock_popen.return_value = MagicMock(pid=54325)
        res = client.post(f'/api/tickets/{ticket2["id"]}/spawn')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True
        assert data['queued'] is True


# ---------------------------------------------------------------------------
# GET /api/tickets/<id> — running_agents field tests
# ---------------------------------------------------------------------------

def test_ticket_detail_includes_running_agents_zero(client, default_workflow, default_board):
    """Ticket detail includes running_agents=0 when no agents are running."""
    ticket = _create_ticket(client, default_board['id'])
    res = client.get(f'/api/tickets/{ticket["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert 'running_agents' in data
    assert data['running_agents'] == 0


def test_ticket_detail_includes_running_agents_count(client, default_workflow, default_board):
    """Ticket detail includes running_agents=1 when an agent is active."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])

    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=54325)
        client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': status['id']})

    res = client.get(f'/api/tickets/{ticket["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['running_agents'] >= 1


def test_ticket_detail_includes_is_terminal(client, default_workflow, default_board):
    """Ticket detail includes is_terminal field from status."""
    agent = _create_agent(client, default_workflow['id'])
    _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])

    res = client.get(f'/api/tickets/{ticket["id"]}')
    assert res.status_code == 200
    data = json.loads(res.data)
    # Default status is not terminal
    assert data.get('is_terminal') == 0

    # Move to terminal status
    terminal_status = _create_terminal_status(client, default_workflow['id'])
    client.put(f'/api/tickets/{ticket["id"]}', json={'status_id': terminal_status['id']})

    res = client.get(f'/api/tickets/{ticket["id"]}')
    data = json.loads(res.data)
    # is_terminal should be 1 for terminal status
    assert data.get('is_terminal') == 1