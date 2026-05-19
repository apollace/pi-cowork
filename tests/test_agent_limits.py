from pi_cowork import config
import json
from unittest.mock import patch, MagicMock
import os

import app as app_module
from pi_cowork.config import get_config
from pi_cowork.models import set_setting


def _set_limits(client, max_parallel=None, max_per_hour=None):
    """Set agent limits via DB settings (and env var fallback)."""
    if max_parallel is not None:
        with client.application.app_context():
            set_setting('max_parallel', str(max_parallel))
        config.PI_MAX_PARALLEL = max_parallel
        os.environ['PI_MAX_PARALLEL'] = str(max_parallel)
    if max_per_hour is not None:
        with client.application.app_context():
            set_setting('max_per_hour', str(max_per_hour))
        config.PI_MAX_PER_HOUR = max_per_hour
        os.environ['PI_MAX_PER_HOUR'] = str(max_per_hour)


def test_parallel_limit_queues(client, default_workflow, default_board):
    """When running agents >= max_parallel, new triggers get queued."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'LimitAgent',
        'description': 'd',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'Stage1',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'T1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'T2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First spawn goes through (keep fake PID alive)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})
            assert mock_popen.call_count == 1

    # Second spawn should be queued
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            res = client.put(f'/api/tickets/{tid2}', json={'status_id': id1})
            assert res.status_code == 200
            assert mock_popen.call_count == 0

    # Queue row created
    q = client.get(f'/api/tickets/{tid2}')
    qdata = json.loads(q.data)
    assert qdata['queued'] is True
    assert qdata['queue_reason'] == 'parallel'

    # Comment should mention queuing
    assert any('Queued' in c['body'] for c in qdata['comments'])


def test_hourly_limit_queues(client, default_workflow, default_board):
    """When hourly runs >= max_per_hour, new triggers get queued."""
    _set_limits(client, max_parallel=10, max_per_hour=1)

    agent = client.post('/api/agents', json={
        'name': 'RateAgent',
        'description': 'd',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'RateStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'R1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'R2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # First spawn goes through
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Second spawn queued for rate limit
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})
            assert mock_popen.call_count == 0

    q = client.get(f'/api/tickets/{tid2}')
    qdata = json.loads(q.data)
    assert qdata['queued'] is True
    assert qdata['queue_reason'] == 'rate'


def test_cleanup_frees_slot(client, default_workflow, default_board):
    """When a running agent finishes, cleanup_runs marks it and drain_queue starts the queued one.
    Queue row is deleted after successful spawn (Issue #18)."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'DrainAgent',
        'description': 'd',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'DrainStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'D1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'D2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # Spawn first; queue second
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})
            assert mock_popen.call_count == 1

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Verify queue exists
    q = client.get(f'/api/tickets/{tid2}')
    assert json.loads(q.data)['queued'] is True

    # Simulate the first agent finishing: _is_our_process returns False (PID gone or recycled)
    with patch('pi_cowork.agents._is_our_process', return_value=False):
        with client.application.app_context():
            app_module.cleanup_runs()

    # drain_queue should start the next one and delete the queue row
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            with client.application.app_context():
                app_module.drain_queue()
            assert mock_popen.call_count == 1

    # Queue should be gone (row deleted, not just started_at set)
    q = client.get(f'/api/tickets/{tid2}')
    assert json.loads(q.data)['queued'] is False


def test_auto_cancel_on_status_change(client, default_workflow, default_board):
    """If a queued ticket is moved out of its expected status, drain_queue drops it."""
    _set_limits(client, max_parallel=1, max_per_hour=10)

    agent = client.post('/api/agents', json={
        'name': 'CancelAgent',
        'description': 'd',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'StageA',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    s2 = client.post('/api/statuses', json={
        'name': 'StageB',
        'sort_order': 2,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']
    id2 = json.loads(s2.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'C1', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'C2', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid2}', json={'status_id': id1})

    # Queue exists
    q = client.get(f'/api/tickets/{tid2}')
    assert json.loads(q.data)['queued'] is True

    # Move ticket2 to StageB (no agent)
    client.put(f'/api/tickets/{tid2}', json={'status_id': id2})

    # drain_queue should auto-cancel
    with client.application.app_context():
        app_module.drain_queue()

    q = client.get(f'/api/tickets/{tid2}')
    assert json.loads(q.data)['queued'] is False


def test_hour_rollover_resets_limit(client, default_workflow, default_board):
    """An agent run from the previous hour should not count toward this hour's limit."""
    _set_limits(client, max_parallel=10, max_per_hour=1)

    agent = client.post('/api/agents', json={
        'name': 'RollAgent',
        'description': 'd',

        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(agent.data)['id']

    s1 = client.post('/api/statuses', json={
        'name': 'RollStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    id1 = json.loads(s1.data)['id']

    ticket1 = client.post('/api/tickets', json={'title': 'Old', 'board_id': default_board['id']})
    tid1 = json.loads(ticket1.data)['id']
    ticket2 = client.post('/api/tickets', json={'title': 'New', 'board_id': default_board['id']})
    tid2 = json.loads(ticket2.data)['id']

    # Spawn first agent
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)):
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            client.put(f'/api/tickets/{tid1}', json={'status_id': id1})

    # Roll back its start time by 2 hours
    from pi_cowork.db import get_db
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE agent_runs SET started_at = datetime('now', '-2 hours') WHERE ticket_id = ?",
            (tid1,)
        )
        db.commit()

    # Second agent should now go through (hourly limit reset)
    with patch('app.subprocess.Popen', return_value=MagicMock(pid=9999)) as mock_popen:
        with patch('pi_cowork.agents._is_our_process', return_value=True):
            res = client.put(f'/api/tickets/{tid2}', json={'status_id': id1})
            assert res.status_code == 200
            assert mock_popen.call_count == 1
