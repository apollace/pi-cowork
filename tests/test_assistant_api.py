import io
import json
import os
import signal
from unittest.mock import patch, MagicMock

from pi_cowork.config import ASSISTANT_SESSION_DIR


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


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------

def test_assistant_settings_page_renders(client):
    """GET /assistant/settings should redirect to /settings."""
    res = client.get('/assistant/settings')
    assert res.status_code == 302
    assert '/settings' in res.headers.get('Location', '')


def test_settings_page_renders(client):
    res = client.get('/settings')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'Settings' in html
    assert 'Assistant' in html
    assert 'System Prompt' in html
    assert 'cfg-system-prompt' in html
    assert 'cfg-enabled' in html
    assert 'Logs & Storage' in html or 'Logs &amp; Storage' in html
    assert 'cfg-log-retention' in html
    assert 'btn-purge-terminal-logs' in html
    assert 'cfg-save' in html


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_get_config_defaults(client):
    res = client.get('/api/assistant/config')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['id'] == 1
    assert data['enabled'] == 1
    assert data['thinking'] == 'medium'
    assert data['working_directory'] == 'workspace'
    assert data['auto_context'] == 1


def test_put_config_updates(client):
    res = client.put('/api/assistant/config', json={
        'enabled': False,
        'auto_context': False,
        'model': 'gpt-4',
        'thinking': 'high',
        'working_directory': 'custom-ws',
        'system_prompt': 'Custom prompt',
    })
    assert res.status_code == 200

    res = client.get('/api/assistant/config')
    data = json.loads(res.data)
    assert data['enabled'] == 0
    assert data['auto_context'] == 0
    assert data['model'] == 'gpt-4'
    assert data['thinking'] == 'high'
    assert data['working_directory'] == 'custom-ws'
    assert data['system_prompt'] == 'Custom prompt'


def test_put_config_rejects_invalid_thinking(client):
    res = client.put('/api/assistant/config', json={'thinking': 'ultra'})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'thinking' in data['error']


def test_put_config_rejects_invalid_model(client):
    res = client.put('/api/assistant/config', json={'model': 'not-a-real-model'})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'model' in data['error']


def test_put_config_api_endpoints(client):
    res = client.put('/api/assistant/config', json={
        'api_endpoints': ['ticket_put', 'boards_list'],
    })
    assert res.status_code == 200

    res = client.get('/api/assistant/config')
    data = json.loads(res.data)
    assert data['api_endpoints'] == ['ticket_put', 'boards_list']


def test_put_config_empty_api_endpoints_defaults_to_all(client):
    """Empty list should be stored as NULL (default to all endpoints)."""
    res = client.put('/api/assistant/config', json={
        'api_endpoints': [],
    })
    assert res.status_code == 200

    res = client.get('/api/assistant/config')
    data = json.loads(res.data)
    assert data['api_endpoints'] is None


def test_put_config_api_endpoints_null_clears(client):
    res = client.put('/api/assistant/config', json={
        'api_endpoints': ['ticket_put'],
    })
    assert res.status_code == 200

    res = client.put('/api/assistant/config', json={
        'api_endpoints': None,
    })
    assert res.status_code == 200

    res = client.get('/api/assistant/config')
    data = json.loads(res.data)
    assert data['api_endpoints'] is None


def test_put_config_rejects_invalid_api_endpoints(client):
    res = client.put('/api/assistant/config', json={
        'api_endpoints': ['ticket_put', 'not_a_real_key'],
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'Unknown endpoint' in data['error']


def test_put_config_rejects_non_list_api_endpoints(client):
    res = client.put('/api/assistant/config', json={
        'api_endpoints': 'ticket_put',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'must be a list' in data['error']


# ---------------------------------------------------------------------------
# Chat — SSE streaming
# ---------------------------------------------------------------------------

def test_chat_sse_content_type(client):
    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
    assert res.status_code == 200
    assert res.mimetype == 'text/event-stream'


def test_chat_wrapped_ndjson_format(client):
    """Current pi CLI emits nested message_update events; verify normalization."""
    ndjson = (
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Hello "}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"world"}}\n'
        '{"type":"turn_end"}\n'
    )
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'Hello ' in body
        assert 'world' in body
        assert 'event: done' in body

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]['role'] == 'user'
    assert rows[0]['content'] == 'Hi'
    assert rows[1]['role'] == 'assistant'
    assert rows[1]['content'] == 'Hello world'


def test_chat_thinking_delta_wrapped_format(client):
    """Wrapped thinking_delta should be normalized and streamed."""
    ndjson = (
        '{"type":"message_update","assistantMessageEvent":{"type":"thinking_delta","delta":"Hmm"}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Answer"}}\n'
        '{"type":"turn_end"}\n'
    )
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'event: thinking' in body
        assert 'Answer' in body
        assert 'event: done' in body

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    assert rows[1]['content'] == 'Answer'


def test_chat_stores_messages_and_returns_response(client):
    ndjson = '{"type":"text_delta","chunk":"Hello there"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'Hello there' in body
        assert 'event: done' in body

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]['role'] == 'user'
    assert rows[0]['content'] == 'Hi'
    assert rows[1]['role'] == 'assistant'
    assert rows[1]['content'] == 'Hello there'


def test_chat_requires_message(client):
    res = client.post('/api/assistant/chat', json={})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'message is required' in data['error']

    res = client.post('/api/assistant/chat', json={'message': '   '})
    assert res.status_code == 400


def test_chat_error_handling(client):
    """Non-zero exit code with stderr should produce SSE error event."""
    fake = _make_mock_popen(ndjson='', stderr='pi not found', returncode=127)
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'event: error' in body
        assert 'pi not found' in body

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    # No assistant message inserted because accumulated_text is empty
    assert len(rows) == 1
    assert rows[0]['role'] == 'user'


def test_chat_uses_config_system_prompt_and_api_docs(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={
            'system_prompt': 'Custom system prompt',
        })
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index('--system-prompt') + 1]
        assert 'Custom system prompt' in system_prompt
        assert 'API Documentation' in system_prompt


def test_chat_system_prompt_defaults_include_api_docs(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={'system_prompt': None})
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index('--system-prompt') + 1]
        assert 'pi-CoWork Assistant' in system_prompt
        assert 'API Documentation' in system_prompt


def test_chat_prompt_includes_selected_endpoints(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={
            'api_endpoints': ['boards_list', 'workflows_list'],
        })
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index('--system-prompt') + 1]
        assert '/api/boards' in system_prompt
        assert '/api/workflows' in system_prompt
        assert '/api/tickets/' not in system_prompt


def test_chat_prompt_default_includes_all_endpoints(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={'api_endpoints': None})
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index('--system-prompt') + 1]
        assert '/api/tickets/' in system_prompt
        assert '/api/boards' in system_prompt
        assert '/api/workflows' in system_prompt
        # Literal placeholders should remain in assistant docs
        assert '{ticket_id}' in system_prompt


def test_chat_uses_config_model_and_thinking(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={
            'model': 'custom-model',
            'thinking': 'low',
        })
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert '--model' in cmd
        assert cmd[cmd.index('--model') + 1] == 'custom-model'
        assert '--thinking' in cmd
        assert cmd[cmd.index('--thinking') + 1] == 'low'


def test_chat_json_mode_flag(client):
    """Chat command must include '--mode json'."""
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert '--mode' in cmd
        assert cmd[cmd.index('--mode') + 1] == 'json'


def test_chat_injects_page_url_when_auto_context_enabled(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={'auto_context': True})
        res = client.post('/api/assistant/chat', json={'message': 'Hi', 'page_url': '/board'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert 'Current page context: /board' in prompt


def test_chat_does_not_inject_page_url_when_auto_context_disabled(client):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put('/api/assistant/config', json={'auto_context': False})
        res = client.post('/api/assistant/chat', json={'message': 'Hi', 'page_url': '/board'})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert 'Current page context:' not in prompt


def test_chat_text_delta_streaming(client):
    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"text_delta","chunk":" world"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'Hello' in body
        assert ' world' in body
        assert 'event: done' in body
        # Full text should appear in done payload
        assert 'Hello world' in body


def test_chat_done_event_has_full_text(client):
    ndjson = '{"type":"text_delta","chunk":"Full reply"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'event: done' in body
        assert 'Full reply' in body

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[1]['content'] == 'Full reply'


def test_chat_json_error_event(client):
    """When NDJSON contains an error event, SSE should forward it."""
    ndjson = '{"type":"error","error":"model failure"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson, returncode=0)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi'})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'event: error' in body
        assert 'model failure' in body

    history = client.get('/api/assistant/history')
    # No assistant message because no text was accumulated
    assert len(json.loads(history.data)) == 1


def test_chat_sequential_requests_not_blocked(client):
    """Two sequential requests should both complete without deadlock."""
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        res1 = client.post('/api/assistant/chat', json={'message': 'M1'})
        assert res1.status_code == 200
        res2 = client.post('/api/assistant/chat', json={'message': 'M2'})
        assert res2.status_code == 200

    history = client.get('/api/assistant/history')
    rows = json.loads(history.data)
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

def test_stop_endpoint_kills_active_run(client):
    from pi_cowork.assistant import _AssistantRun, _ASSISTANT_RUNS, _assistant_runs_lock
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 99999
    run = _AssistantRun(fake_proc, None)
    with _assistant_runs_lock:
        _ASSISTANT_RUNS[None] = run

    with patch('pi_cowork.assistant.os.kill') as mock_kill:
        res = client.post('/api/assistant/stop', json={})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True
        mock_kill.assert_called_once_with(99999, signal.SIGTERM)

    # Clean up
    with _assistant_runs_lock:
        _ASSISTANT_RUNS.pop(None, None)


def test_stop_endpoint_returns_false_when_no_run(client):
    res = client.post('/api/assistant/stop', json={})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['success'] is False


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_history_empty(client):
    res = client.get('/api/assistant/history')
    assert res.status_code == 200
    assert json.loads(res.data) == []


def test_history_returns_messages(client):
    ndjson = '{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        client.post('/api/assistant/chat', json={'message': 'M1'})

    res = client.get('/api/assistant/history')
    rows = json.loads(res.data)
    assert len(rows) == 2
    assert rows[0]['role'] == 'user'
    assert rows[1]['role'] == 'assistant'
    assert rows[1]['content'] == 'A'


# ---------------------------------------------------------------------------
# Compact
# ---------------------------------------------------------------------------

def test_compact_summarizes_and_clears(client):
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')):
        client.post('/api/assistant/chat', json={'message': 'M1'})
        client.post('/api/assistant/chat', json={'message': 'M2'})

    os.makedirs(ASSISTANT_SESSION_DIR, exist_ok=True)
    with open(os.path.join(ASSISTANT_SESSION_DIR, 'session.jsonl'), 'w') as f:
        f.write('{}')

    with patch('app.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='{"type":"compaction_start","reason":"manual"}', stderr='', returncode=0)
        res = client.post('/api/assistant/compact')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['summary'] == 'Conversation compacted by pi.'
        assert data['message_count'] == 4
        cmd = mock_run.call_args[0][0]
        assert '--mode' in cmd
        assert 'rpc' in cmd
        assert mock_run.call_args.kwargs.get('input') == '{"type":"compact"}'

    # DB should be empty
    history = client.get('/api/assistant/history')
    assert json.loads(history.data) == []

    # Summary setting should NOT be stored
    from pi_cowork.models import get_setting
    with client.application.app_context():
        assert get_setting('assistant_summary') is None

    # Session dir should STILL EXIST
    assert os.path.exists(ASSISTANT_SESSION_DIR)


def test_compact_empty_db(client):
    res = client.post('/api/assistant/compact')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['summary'] == ''
    assert data['message_count'] == 0


def test_compact_uses_config_model_and_thinking(client):
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')):
        client.post('/api/assistant/chat', json={'message': 'M1'})

    client.put('/api/assistant/config', json={
        'model': 'compact-model',
        'thinking': 'high',
    })
    with patch('app.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='{"type":"compaction_start"}', stderr='', returncode=0)
        res = client.post('/api/assistant/compact')
        assert res.status_code == 200
        cmd = mock_run.call_args[0][0]
        assert '--mode' in cmd
        assert 'rpc' in cmd
        assert '--model' in cmd
        assert cmd[cmd.index('--model') + 1] == 'compact-model'
        assert '--thinking' in cmd
        assert cmd[cmd.index('--thinking') + 1] == 'high'
        assert mock_run.call_args.kwargs.get('input') == '{"type":"compact"}'


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def test_reset_clears_all(client):
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')):
        client.post('/api/assistant/chat', json={'message': 'Hi'})

    os.makedirs(ASSISTANT_SESSION_DIR, exist_ok=True)
    with open(os.path.join(ASSISTANT_SESSION_DIR, 'session.jsonl'), 'w') as f:
        f.write('{}')

    from pi_cowork.models import set_setting
    with client.application.app_context():
        set_setting('assistant_summary', 'Old summary')

    with patch('app.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='{}', stderr='', returncode=0)
        res = client.post('/api/assistant/reset')
        assert res.status_code == 200
        assert json.loads(res.data) == {'success': True}
        cmd = mock_run.call_args[0][0]
        assert '--mode' in cmd
        assert 'rpc' in cmd
        assert mock_run.call_args.kwargs.get('input') == '{"type":"new_session"}'

    history = client.get('/api/assistant/history')
    assert json.loads(history.data) == []

    from pi_cowork.models import get_setting
    with client.application.app_context():
        assert get_setting('assistant_summary') is None

    assert os.path.exists(ASSISTANT_SESSION_DIR)


# ---------------------------------------------------------------------------
# Board Assistant
# ---------------------------------------------------------------------------

def test_board_chat_stores_messages_with_board_id(client, default_board):
    ndjson = '{"type":"text_delta","chunk":"Board reply"}\n{"type":"done"}\n'
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post('/api/assistant/chat', json={'message': 'Hi board', 'board_id': default_board['id']})
        assert res.status_code == 200
        body = res.data.decode('utf-8')
        assert 'Board reply' in body
        assert 'event: done' in body

    # Board history should contain the messages
    history = client.get(f'/api/assistant/history?board_id={default_board["id"]}')
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]['role'] == 'user'
    assert rows[0]['content'] == 'Hi board'
    assert rows[1]['role'] == 'assistant'
    assert rows[1]['content'] == 'Board reply'


def test_board_chat_isolated_per_board(client, default_board, new_workflow):
    """Messages for different boards should not mix."""
    # Create second board
    res = client.post('/api/boards', json={
        'name': 'Second Board',
        'workflow_id': new_workflow['id'],
    })
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        client.post('/api/assistant/chat', json={'message': 'B1', 'board_id': default_board['id']})
        client.post('/api/assistant/chat', json={'message': 'B2', 'board_id': board2['id']})

    h1 = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    h2 = json.loads(client.get(f'/api/assistant/history?board_id={board2["id"]}').data)
    assert len(h1) == 2
    assert h1[0]['content'] == 'B1'
    assert len(h2) == 2
    assert h2[0]['content'] == 'B2'


def test_board_chat_isolated_from_global(client, default_board):
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        client.post('/api/assistant/chat', json={'message': 'Global'})
        client.post('/api/assistant/chat', json={'message': 'Board', 'board_id': default_board['id']})

    global_hist = json.loads(client.get('/api/assistant/history').data)
    board_hist = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    assert len(global_hist) == 2
    assert global_hist[0]['content'] == 'Global'
    assert len(board_hist) == 2
    assert board_hist[0]['content'] == 'Board'


def test_board_chat_injects_board_context(client, default_board):
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.post('/api/assistant/chat', json={
            'message': 'Hi',
            'board_id': default_board['id'],
            'page_url': '/board',
        })
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert f"Current board context: {default_board['name']}" in prompt
        assert f"board_id={default_board['id']}" in prompt
        assert 'Current page context: /board' in prompt


def test_board_chat_uses_board_working_directory(client, default_board):
    # Update board working directory
    custom_dir = 'custom-board-ws'
    client.put(f'/api/boards/{default_board["id"]}', json={
        'name': default_board['name'],
        'workflow_id': default_board['workflow_id'],
        'working_directory': custom_dir,
    })
    with patch('pi_cowork.assistant.subprocess.Popen') as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.post('/api/assistant/chat', json={'message': 'Hi', 'board_id': default_board['id']})
        cwd = mock_popen.call_args.kwargs.get('cwd')
        assert custom_dir in cwd


def test_board_compact_affects_only_targeted_board(client, default_board, new_workflow):
    # Create second board
    res = client.post('/api/boards', json={
        'name': 'Second Board',
        'workflow_id': new_workflow['id'],
    })
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        client.post('/api/assistant/chat', json={'message': 'B1', 'board_id': default_board['id']})
        client.post('/api/assistant/chat', json={'message': 'B2', 'board_id': board2['id']})

    with patch('app.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='{}', stderr='', returncode=0)
        res = client.post('/api/assistant/compact', json={'board_id': default_board['id']})
        assert res.status_code == 200

    h1 = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    h2 = json.loads(client.get(f'/api/assistant/history?board_id={board2["id"]}').data)
    assert len(h1) == 0
    assert len(h2) == 2


def test_board_reset_affects_only_targeted_board(client, default_board, new_workflow):
    # Create second board
    res = client.post('/api/boards', json={
        'name': 'Second Board',
        'workflow_id': new_workflow['id'],
    })
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        client.post('/api/assistant/chat', json={'message': 'B1', 'board_id': default_board['id']})
        client.post('/api/assistant/chat', json={'message': 'B2', 'board_id': board2['id']})

    with patch('app.subprocess.run') as mock_run:
        mock_run.return_value = MagicMock(stdout='{}', stderr='', returncode=0)
        res = client.post('/api/assistant/reset', json={'board_id': default_board['id']})
        assert res.status_code == 200

    h1 = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    h2 = json.loads(client.get(f'/api/assistant/history?board_id={board2["id"]}').data)
    assert len(h1) == 0
    assert len(h2) == 2


def test_board_deletion_cascades_to_board_assistant_messages(client, default_board):
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch('pi_cowork.assistant.subprocess.Popen', side_effect=fake):
        client.post('/api/assistant/chat', json={'message': 'B1', 'board_id': default_board['id']})

    h = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    assert len(h) == 2

    # Delete the board
    res = client.delete(f"/api/boards/{default_board['id']}")
    assert res.status_code == 200

    # Messages should be gone
    h = json.loads(client.get(f'/api/assistant/history?board_id={default_board["id"]}').data)
    assert len(h) == 0


def test_board_chat_rejects_invalid_board_id(client):
    res = client.post('/api/assistant/chat', json={'message': 'Hi', 'board_id': 99999})
    assert res.status_code == 404
    data = json.loads(res.data)
    assert 'board not found' in data['error']


def test_board_chat_rejects_non_integer_board_id(client):
    res = client.post('/api/assistant/chat', json={'message': 'Hi', 'board_id': 'abc'})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'board_id must be an integer' in data['error']


def test_board_history_requires_integer_board_id(client):
    res = client.get('/api/assistant/history?board_id=abc')
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'board_id must be an integer' in data['error']


# ---------------------------------------------------------------------------
# Saved Prompts API
# ---------------------------------------------------------------------------

def test_saved_prompts_list_empty(client):
    res = client.get('/api/assistant/saved-prompts')
    assert res.status_code == 200
    assert json.loads(res.data) == []


def test_saved_prompts_create_and_list(client):
    res = client.post('/api/assistant/saved-prompts', json={
        'name': 'Review code',
        'prompt_text': 'Review the last commit for bugs.',
    })
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data['name'] == 'Review code'
    assert data['prompt_text'] == 'Review the last commit for bugs.'
    assert 'id' in data

    res = client.get('/api/assistant/saved-prompts')
    assert res.status_code == 200
    rows = json.loads(res.data)
    assert len(rows) == 1
    assert rows[0]['name'] == 'Review code'


def test_saved_prompts_create_requires_name(client):
    res = client.post('/api/assistant/saved-prompts', json={
        'prompt_text': 'Text only',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'name is required' in data['error']


def test_saved_prompts_create_requires_prompt_text(client):
    res = client.post('/api/assistant/saved-prompts', json={
        'name': 'Name only',
    })
    assert res.status_code == 400
    data = json.loads(res.data)
    assert 'prompt_text is required' in data['error']


def test_saved_prompts_create_rejects_duplicate_name(client):
    client.post('/api/assistant/saved-prompts', json={
        'name': 'Daily standup',
        'prompt_text': 'Summarize yesterday\'s work.',
    })
    res = client.post('/api/assistant/saved-prompts', json={
        'name': 'Daily standup',
        'prompt_text': 'Different text.',
    })
    assert res.status_code == 409
    data = json.loads(res.data)
    assert 'already exists' in data['error']


def test_saved_prompts_update(client):
    res = client.post('/api/assistant/saved-prompts', json={
        'name': 'Old',
        'prompt_text': 'Old text.',
    })
    pid = json.loads(res.data)['id']

    res = client.put(f'/api/assistant/saved-prompts/{pid}', json={
        'name': 'New',
        'prompt_text': 'New text.',
    })
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['name'] == 'New'
    assert data['prompt_text'] == 'New text.'


    res = client.get('/api/assistant/saved-prompts')
    rows = json.loads(res.data)
    assert len(rows) == 1
    assert rows[0]['name'] == 'New'


def test_saved_prompts_update_not_found(client):
    res = client.put('/api/assistant/saved-prompts/9999', json={
        'name': 'X',
        'prompt_text': 'Y',
    })
    assert res.status_code == 404
    data = json.loads(res.data)
    assert 'not found' in data['error']


def test_saved_prompts_update_rejects_duplicate_name(client):
    res1 = client.post('/api/assistant/saved-prompts', json={
        'name': 'A',
        'prompt_text': 'A text.',
    })
    client.post('/api/assistant/saved-prompts', json={
        'name': 'B',
        'prompt_text': 'B text.',
    })
    pid = json.loads(res1.data)['id']

    res = client.put(f'/api/assistant/saved-prompts/{pid}', json={
        'name': 'B',
        'prompt_text': 'A text updated.',
    })
    assert res.status_code == 409
    data = json.loads(res.data)
    assert 'already exists' in data['error']


def test_saved_prompts_delete(client):
    res = client.post('/api/assistant/saved-prompts', json={
        'name': 'Delete me',
        'prompt_text': 'Text.',
    })
    pid = json.loads(res.data)['id']

    res = client.delete(f'/api/assistant/saved-prompts/{pid}')
    assert res.status_code == 200
    assert json.loads(res.data)['success'] is True

    res = client.get('/api/assistant/saved-prompts')
    assert json.loads(res.data) == []


def test_saved_prompts_delete_not_found(client):
    res = client.delete('/api/assistant/saved-prompts/9999')
    assert res.status_code == 404
    data = json.loads(res.data)
    assert 'not found' in data['error']


# ---------------------------------------------------------------------------
# Saved Prompts UI Presence
# ---------------------------------------------------------------------------

SETTINGS_HTML_PATH = 'templates/settings.html'
BASE_HTML_PATH = 'templates/base.html'
BOARD_HTML_PATH = 'templates/board.html'
STYLE_CSS_PATH = 'static/style.css'
ASSISTANT_JS_PATH = 'static/assistant.js'
BOARD_ASSISTANT_JS_PATH = 'static/board_assistant.js'  # Removed — kept for path reference


# Board assistant was consolidated into the global assistant.
# The following tests are skipped as the board assistant has been removed.


def read(path):
    with open(path) as f:
        return f.read()


class TestSavedPromptsSettingsUI:
    def test_settings_page_has_saved_prompts_section(self):
        html = read(SETTINGS_HTML_PATH)
        assert 'Saved Prompts' in html, 'Expected Saved Prompts heading in settings'
        assert 'saved-prompts-list' in html, 'Expected saved-prompts-list container'
        assert 'sp-add-name' in html, 'Expected sp-add-name input'
        assert 'sp-add-text' in html, 'Expected sp-add-text textarea'

    def test_settings_page_has_inline_add_form(self):
        html = read(SETTINGS_HTML_PATH)
        assert 'createSavedPrompt' in html, 'Expected createSavedPrompt function call'
        assert 'deleteSavedPrompt' in html, 'Expected deleteSavedPrompt function reference'

    def test_settings_page_has_inline_edit_form(self):
        html = read(SETTINGS_HTML_PATH)
        assert 'startEditSavedPrompt' in html, 'Expected startEditSavedPrompt function reference'
        assert 'saveSavedPromptEdit' in html, 'Expected saveSavedPromptEdit function reference'
        assert 'cancelSavedPromptEdit' in html, 'Expected cancelSavedPromptEdit function reference'

    def test_settings_page_loads_saved_prompts(self):
        html = read(SETTINGS_HTML_PATH)
        assert 'loadSavedPrompts' in html, 'Expected loadSavedPrompts call in settings script'


class TestSavedPromptsGlobalAssistantUI:
    def test_base_html_has_saved_prompts_bar(self):
        html = read(BASE_HTML_PATH)
        assert 'assistant-saved-prompts' in html, 'Expected assistant-saved-prompts div in base.html'
        assert 'saved-prompts-bar' in html, 'Expected saved-prompts-bar class in base.html'

    def test_assistant_js_has_saved_prompts_logic(self):
        js = read(ASSISTANT_JS_PATH)
        assert 'loadSavedPrompts' in js, 'Expected loadSavedPrompts in assistant.js'
        assert 'renderSavedPrompts' in js, 'Expected renderSavedPrompts in assistant.js'
        assert 'saved-prompt-btn' in js, 'Expected saved-prompt-btn class in assistant.js'


class TestSavedPromptsBoardAssistantUI:
    # Board assistant was consolidated into the global assistant
    # These UI elements are no longer in board.html
    pass

    # def test_board_html_has_saved_prompts_bar(self):
    #     html = read(BOARD_HTML_PATH)
    #     assert 'board-assistant-saved-prompts' in html

    # def test_board_assistant_js_has_saved_prompts_logic(self):
    #     js = read(BOARD_ASSISTANT_JS_PATH)
    #     assert 'loadSavedPrompts' in js
    #     assert 'renderSavedPrompts' in js
    #     assert 'saved-prompt-btn' in js


class TestSavedPromptsCSS:
    def test_css_has_saved_prompts_bar(self):
        css = read(STYLE_CSS_PATH)
        assert '.saved-prompts-bar' in css, 'Expected .saved-prompts-bar styles in CSS'

    def test_css_has_saved_prompt_btn(self):
        css = read(STYLE_CSS_PATH)
        assert '.saved-prompt-btn' in css, 'Expected .saved-prompt-btn styles in CSS'

    def test_css_has_saved_prompts_table(self):
        css = read(STYLE_CSS_PATH)
        assert '.saved-prompts-table' in css, 'Expected .saved-prompts-table styles in CSS'

    def test_css_has_saved_prompts_inline_add(self):
        css = read(STYLE_CSS_PATH)
        assert '.saved-prompts-inline-add' in css, 'Expected .saved-prompts-inline-add styles in CSS'

    def test_css_has_saved_prompts_row_actions(self):
        css = read(STYLE_CSS_PATH)
        assert '.saved-prompts-row-actions' in css, 'Expected .saved-prompts-row-actions styles in CSS'
