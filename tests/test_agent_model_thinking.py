import io
import json
import os
from unittest.mock import patch, MagicMock


def _make_mock_popen(ndjson='', stderr='', returncode=0):
    """Return a side-effect function that creates a mock Popen with NDJSON stdout."""
    def _fake(*args, **kwargs):
        proc = MagicMock()
        proc.stdout = io.StringIO(ndjson)
        proc.stderr = io.StringIO(stderr)
        proc.pid = 12345
        proc.poll.return_value = None
        proc.wait.return_value = returncode
        return proc
    return _fake


def test_create_agent_invalid_model(client, default_workflow):
    res = client.post('/api/agents', json={
        'name': 'BadModel',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'model': 'not-a-real-model',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'model' in data['error'].lower()


def test_update_agent_invalid_model(client, default_workflow):
    res = client.post('/api/agents', json={
        'name': 'ModelBase',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    agent_id = json.loads(res.data)['id']

    res = client.put(f'/api/agents/{agent_id}', json={
        'model': 'not-a-real-model',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'model' in data['error'].lower()


# ---------------------------------------------------------------------------
# Agent API: model/thinking fields
# ---------------------------------------------------------------------------

def test_create_agent_with_model_and_thinking(client, default_workflow):
    res = client.post('/api/agents', json={
        'name': 'ModelAgent',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'model': 'gpt-4o',
        'thinking': 'high',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    agent_id = data['id']

    # GET should return model and thinking
    res = client.get(f'/api/agents/{agent_id}')
    assert res.status_code == 200
    agent = json.loads(res.data)
    assert agent['model'] == 'gpt-4o'
    assert agent['thinking'] == 'high'


def test_create_agent_without_model_and_thinking(client, default_workflow):
    res = client.post('/api/agents', json={
        'name': 'NoOverrides',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    agent_id = data['id']

    res = client.get(f'/api/agents/{agent_id}')
    assert res.status_code == 200
    agent = json.loads(res.data)
    assert agent['model'] is None
    assert agent['thinking'] is None


def test_create_agent_with_empty_model_and_thinking(client, default_workflow):
    """Empty strings should be stored as NULL (no override)."""
    res = client.post('/api/agents', json={
        'name': 'EmptyOverrides',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'model': '',
        'thinking': '',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    agent_id = data['id']

    res = client.get(f'/api/agents/{agent_id}')
    assert res.status_code == 200
    agent = json.loads(res.data)
    assert agent['model'] is None
    assert agent['thinking'] is None


def test_create_agent_invalid_thinking(client, default_workflow):
    """Thinking must be one of: off, minimal, low, medium, high, xhigh."""
    res = client.post('/api/agents', json={
        'name': 'BadThinking',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'thinking': 'ultra',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'thinking' in data['error'].lower()


def test_create_agent_model_accepts_any_string(client, default_workflow):
    """Model is free-form text."""
    res = client.post('/api/agents', json={
        'name': 'AnyModel',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'model': 'claude-3-opus-20240229',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    agent_id = data['id']

    res = client.get(f'/api/agents/{agent_id}')
    assert res.status_code == 200
    agent = json.loads(res.data)
    assert agent['model'] == 'claude-3-opus-20240229'


def test_update_agent_model_and_thinking(client, default_workflow):
    # Create agent without overrides
    res = client.post('/api/agents', json={
        'name': 'Updatable',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    agent_id = json.loads(res.data)['id']

    # Update model and thinking
    res = client.put(f'/api/agents/{agent_id}', json={
        'model': 'gpt-4o',
        'thinking': 'xhigh',
    })
    assert res.status_code == 200

    res = client.get(f'/api/agents/{agent_id}')
    agent = json.loads(res.data)
    assert agent['model'] == 'gpt-4o'
    assert agent['thinking'] == 'xhigh'


def test_update_agent_clears_model_and_thinking(client, default_workflow):
    """Setting model/thinking to empty string clears the override (stores NULL)."""
    res = client.post('/api/agents', json={
        'name': 'Clearable',
        'description': 'd',
        'workflow_id': default_workflow['id'],
        'model': 'gpt-4o',
        'thinking': 'high',
    })
    agent_id = json.loads(res.data)['id']

    # Clear overrides by setting to empty string
    res = client.put(f'/api/agents/{agent_id}', json={
        'model': '',
        'thinking': '',
    })
    assert res.status_code == 200

    res = client.get(f'/api/agents/{agent_id}')
    agent = json.loads(res.data)
    assert agent['model'] is None
    assert agent['thinking'] is None


def test_update_agent_invalid_thinking(client, default_workflow):
    res = client.post('/api/agents', json={
        'name': 'ThinkCheck',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    agent_id = json.loads(res.data)['id']

    res = client.put(f'/api/agents/{agent_id}', json={
        'thinking': 'invalid',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'thinking' in data['error'].lower()


def test_update_agent_valid_thinking_values(client, default_workflow):
    """All valid thinking values should be accepted."""
    res = client.post('/api/agents', json={
        'name': 'ThinkVals',
        'description': 'd',
        'workflow_id': default_workflow['id'],
    })
    agent_id = json.loads(res.data)['id']

    for val in ('off', 'minimal', 'low', 'medium', 'high', 'xhigh'):
        res = client.put(f'/api/agents/{agent_id}', json={'thinking': val})
        assert res.status_code == 200
        agent = json.loads(client.get(f'/api/agents/{agent_id}').data)
        assert agent['thinking'] == val


# ---------------------------------------------------------------------------
# Agent Spawn: model/thinking flags
# ---------------------------------------------------------------------------

def test_spawn_agent_with_thinking_override(client, default_workflow, default_board):
    """Agent with thinking='high' should include --thinking high in spawn command."""
    res = client.post('/api/agents', json={
        'name': 'HighThinker',
        'description': 'You are a high thinker.',
        'workflow_id': default_workflow['id'],
        'thinking': 'high',
    })
    aid = json.loads(res.data)['id']

    res = client.post('/api/statuses', json={
        'name': 'ThinkStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(res.data)['id']

    res = client.post('/api/tickets', json={
        'title': 'Think Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    captured_cmd = []
    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999
        captured_cmd[:] = cmd
        return FakeProc()

    with patch('app.subprocess.Popen', side_effect=capture_popen):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    assert '--thinking' in captured_cmd
    idx = captured_cmd.index('--thinking')
    assert captured_cmd[idx + 1] == 'high'


def test_spawn_agent_with_model_override(client, default_workflow, default_board):
    """Agent with model='gpt-4o' should include --model gpt-4o in spawn command."""
    res = client.post('/api/agents', json={
        'name': 'ModelAgent',
        'description': 'You are a model agent.',
        'workflow_id': default_workflow['id'],
        'model': 'gpt-4o',
    })
    aid = json.loads(res.data)['id']

    res = client.post('/api/statuses', json={
        'name': 'ModelStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(res.data)['id']

    res = client.post('/api/tickets', json={
        'title': 'Model Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    captured_cmd = []
    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999
        captured_cmd[:] = cmd
        return FakeProc()

    with patch('app.subprocess.Popen', side_effect=capture_popen):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    assert '--model' in captured_cmd
    idx = captured_cmd.index('--model')
    assert captured_cmd[idx + 1] == 'gpt-4o'


def test_spawn_agent_no_overrides_no_flags(client, default_workflow, default_board):
    """Agent with neither model nor thinking should NOT include --thinking or --model flags."""
    res = client.post('/api/agents', json={
        'name': 'PlainAgent',
        'description': 'You are a plain agent.',
        'workflow_id': default_workflow['id'],
    })
    aid = json.loads(res.data)['id']

    res = client.post('/api/statuses', json={
        'name': 'PlainStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(res.data)['id']

    res = client.post('/api/tickets', json={
        'title': 'Plain Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    captured_cmd = []
    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999
        captured_cmd[:] = cmd
        return FakeProc()

    with patch('app.subprocess.Popen', side_effect=capture_popen):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    assert '--thinking' not in captured_cmd
    assert '--model' not in captured_cmd


def test_spawn_agent_with_both_overrides(client, default_workflow, default_board):
    """Agent with both model and thinking should include both flags."""
    res = client.post('/api/agents', json={
        'name': 'BothAgent',
        'description': 'You are a both agent.',
        'workflow_id': default_workflow['id'],
        'model': 'claude-3-opus',
        'thinking': 'low',
    })
    aid = json.loads(res.data)['id']

    res = client.post('/api/statuses', json={
        'name': 'BothStage',
        'sort_order': 1,
        'agent_id': aid,
        'workflow_id': default_workflow['id'],
    })
    sid = json.loads(res.data)['id']

    res = client.post('/api/tickets', json={
        'title': 'Both Ticket',
        'board_id': default_board['id'],
    })
    tid = json.loads(res.data)['id']

    captured_cmd = []
    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999
        captured_cmd[:] = cmd
        return FakeProc()

    with patch('app.subprocess.Popen', side_effect=capture_popen):
        client.put(f'/api/tickets/{tid}', json={'status_id': sid})

    assert '--thinking' in captured_cmd
    idx = captured_cmd.index('--thinking')
    assert captured_cmd[idx + 1] == 'low'

    assert '--model' in captured_cmd
    idx = captured_cmd.index('--model')
    assert captured_cmd[idx + 1] == 'claude-3-opus'


# ---------------------------------------------------------------------------
# Import/Export: model/thinking fields
# ---------------------------------------------------------------------------

def test_export_includes_model_and_thinking(client, default_workflow):
    """Exported agents should include model and thinking fields."""
    # Create an agent with model/thinking
    res = client.post('/api/agents', json={
        'name': 'ExportAgent',
        'description': 'For export test',
        'workflow_id': default_workflow['id'],
        'model': 'gpt-4o',
        'thinking': 'xhigh',
    })
    assert res.status_code == 201

    res = client.get(f'/api/workflows/{default_workflow["id"]}/export')
    assert res.status_code == 200
    data = json.loads(res.data)
    agent = next(a for a in data['agents'] if a['name'] == 'ExportAgent')
    assert agent['model'] == 'gpt-4o'
    assert agent['thinking'] == 'xhigh'

    # Agents without overrides should have null model/thinking
    researcher = next(a for a in data['agents'] if a['name'] == 'Researcher')
    assert researcher['model'] is None
    assert researcher['thinking'] is None


def test_import_with_model_and_thinking(client):
    """Import should create agents with model/thinking from imported data."""
    workflow_json = {
        "version": "1.0",
        "name": "Import Model/Thinking Workflow",
        "agents": [
            {"name": "Thinker", "description": "With thinking", "thinking": "high"},
            {"name": "Modeler", "description": "With model", "model": "gpt-4o"},
            {"name": "Both", "description": "With both", "model": "claude-3", "thinking": "minimal"},
            {"name": "Plain", "description": "No overrides"},
        ],
        "statuses": [
            {"name": "Start", "sort_order": 1, "is_default": True, "is_terminal": False, "agent_name": None, "goal": None},
            {"name": "End", "sort_order": 2, "is_default": False, "is_terminal": True, "agent_name": None, "goal": None}
        ],
        "transitions": []
    }
    res = client.post('/api/workflows/import', json=workflow_json)
    assert res.status_code == 200
    data = json.loads(res.data)
    wf_id = data['workflow_id']

    # Verify agents have correct model/thinking
    agents_res = client.get(f'/api/agents?workflow_id={wf_id}')
    agents = json.loads(agents_res.data)

    thinker = next(a for a in agents if a['name'] == 'Thinker')
    assert thinker['thinking'] == 'high'
    assert thinker['model'] is None

    modeler = next(a for a in agents if a['name'] == 'Modeler')
    assert modeler['model'] == 'gpt-4o'
    assert modeler['thinking'] is None

    both = next(a for a in agents if a['name'] == 'Both')
    assert both['model'] == 'claude-3'
    assert both['thinking'] == 'minimal'

    plain = next(a for a in agents if a['name'] == 'Plain')
    assert plain['model'] is None
    assert plain['thinking'] is None


def test_import_export_roundtrip_with_model_thinking(client):
    """Roundtrip: import → export → re-import preserves model/thinking."""
    workflow_json = {
        "version": "1.0",
        "name": "Roundtrip MT",
        "agents": [
            {"name": "A1", "description": "d", "model": "gpt-4o", "thinking": "high"},
            {"name": "A2", "description": "d2"},
        ],
        "statuses": [
            {"name": "S1", "sort_order": 1, "is_default": True, "is_terminal": False, "agent_name": None, "goal": None},
        ],
        "transitions": []
    }
    res = client.post('/api/workflows/import', json=workflow_json)
    assert res.status_code == 200
    wf_id = json.loads(res.data)['workflow_id']

    # Export and verify
    res = client.get(f'/api/workflows/{wf_id}/export')
    exported = json.loads(res.data)
    a1 = next(a for a in exported['agents'] if a['name'] == 'A1')
    assert a1['model'] == 'gpt-4o'
    assert a1['thinking'] == 'high'
    a2 = next(a for a in exported['agents'] if a['name'] == 'A2')
    assert a2['model'] is None
    assert a2['thinking'] is None


# ---------------------------------------------------------------------------
# Assistant: no global env var fallback
# ---------------------------------------------------------------------------

def test_assistant_chat_no_thinking_flag_when_config_empty(client):
    """When assistant_config has default thinking (medium from DB), --thinking should be included."""
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"done"}\n')
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        # The DB default for assistant_config.thinking is 'medium'
        # So --thinking medium should be present
        assert '--thinking' in cmd
        assert cmd[cmd.index('--thinking') + 1] == 'medium'


def test_assistant_chat_omits_model_when_not_set(client):
    """When assistant_config has no model, --model should be omitted."""
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"done"}\n')
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert '--model' not in cmd


def test_assistant_chat_omits_thinking_and_model_when_cleared(client):
    """When assistant_config thinking is cleared (empty string = no override) and model is None,
    neither --thinking nor --model should appear in the command."""
    # Clear thinking override by sending empty string
    res = client.put('/api/assistant/config', json={'thinking': '', 'model': ''})
    assert res.status_code == 200

    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"done"}\n')
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert '--thinking' not in cmd
        assert '--model' not in cmd