"""Tests for Ticket #84: agent_runs status_name exposure."""

import json
from unittest.mock import patch, MagicMock


def test_ticket_agent_runs_includes_status_name(client, default_workflow, default_board):
    """GET /api/tickets/{id}/agent_runs returns status_name alongside run data."""
    agent = client.post('/api/agents', json={
        'name': 'StatusNameAgent',
        'description': 'You are a test agent.',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'StatusNameStage',
        'sort_order': 99,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(s1.data)['id']

    ticket = client.post('/api/tickets', json={
        'title': 'Status Name Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(ticket.data)['id']

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    runs_res = client.get(f'/api/tickets/{tid}/agent_runs')
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    assert 'status_name' in run
    assert run['status_name'] == 'StatusNameStage'
    # Also ensure it doesn't break agent_name
    assert run['agent_name'] == 'StatusNameAgent'


def test_ticket_agent_runs_null_status_id_graceful(client, default_workflow, default_board):
    """Runs with NULL status_id still return a response; status_name is null."""
    agent = client.post('/api/agents', json={
        'name': 'NullStatusAgent',
        'description': 'You are a test agent.',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'NullStatusStage',
        'sort_order': 99,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(s1.data)['id']

    ticket = client.post('/api/tickets', json={
        'title': 'Null Status Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(ticket.data)['id']

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    # Simulate an old row by NULLing status_id
    import app as app_module
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status_id = NULL WHERE ticket_id = ?",
            (tid,)
        )

    runs_res = client.get(f'/api/tickets/{tid}/agent_runs')
    assert runs_res.status_code == 200
    runs = json.loads(runs_res.data)
    assert len(runs) == 1
    run = runs[0]
    # status_name should be null (or missing), not crash the endpoint
    assert run.get('status_name') is None
    assert run['agent_name'] == 'NullStatusAgent'
