import io
import json
import os
import signal
from unittest.mock import MagicMock, patch

from pi_cowork.assistant import (
    _ASSISTANT_RUNS,
    _assistant_runs_lock,
    _assistant_stream_generator_reconnect,
    _AssistantRun,
)
from pi_cowork.config import ASSISTANT_SESSION_DIR
from pi_cowork.db import query_db, run_db


def _make_mock_popen(ndjson="", stderr="", returncode=0):
    """Return a side-effect function that creates a mock Popen with NDJSON stdout."""

    def _fake(*args, **kwargs):
        proc = MagicMock()
        proc.stdout = io.StringIO(ndjson)
        proc.stderr = io.StringIO(stderr)
        proc.pid = 12345
        proc.poll.return_value = None
        proc.wait.return_value = returncode
        proc.returncode = returncode
        return proc

    return _fake


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------


def test_assistant_settings_page_renders(client):
    """GET /assistant/settings should redirect to /settings."""
    res = client.get("/assistant/settings")
    assert res.status_code == 302
    assert "/settings" in res.headers.get("Location", "")


def test_settings_page_renders(client):
    res = client.get("/settings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Settings" in html
    assert "Assistant" in html
    assert "System Prompt" in html
    assert "cfg-system-prompt" in html
    assert "cfg-enabled" in html
    assert "Logs & Storage" in html or "Logs &amp; Storage" in html
    assert "cfg-log-retention" in html
    assert "btn-purge-terminal-logs" in html
    assert "cfg-save" in html


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_get_config_defaults(client):
    res = client.get("/api/assistant/config")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["id"] == 1
    assert data["enabled"] == 1
    assert data["thinking"] == "medium"
    assert data["working_directory"] == "workspace"
    assert data["auto_context"] == 1


def test_put_config_updates(client):
    res = client.put(
        "/api/assistant/config",
        json={
            "enabled": False,
            "auto_context": False,
            "model": "gpt-4",
            "thinking": "high",
            "working_directory": "custom-ws",
            "system_prompt": "Custom prompt",
        },
    )
    assert res.status_code == 200

    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["enabled"] == 0
    assert data["auto_context"] == 0
    assert data["model"] == "gpt-4"
    assert data["thinking"] == "high"
    assert data["working_directory"] == "custom-ws"
    assert data["system_prompt"] == "Custom prompt"


def test_put_config_rejects_invalid_thinking(client):
    res = client.put("/api/assistant/config", json={"thinking": "ultra"})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "thinking" in data["error"]


def test_put_config_rejects_invalid_model(client):
    res = client.put("/api/assistant/config", json={"model": "not-a-real-model"})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "model" in data["error"]


def test_put_config_api_endpoints(client):
    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": ["ticket_put", "boards_list"],
        },
    )
    assert res.status_code == 200

    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["api_endpoints"] == ["ticket_put", "boards_list"]


def test_put_config_empty_api_endpoints_defaults_to_all(client):
    """Empty list should be stored as NULL (default to all endpoints)."""
    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": [],
        },
    )
    assert res.status_code == 200

    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["api_endpoints"] is None


def test_put_config_api_endpoints_null_clears(client):
    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": ["ticket_put"],
        },
    )
    assert res.status_code == 200

    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": None,
        },
    )
    assert res.status_code == 200

    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["api_endpoints"] is None


def test_put_config_rejects_invalid_api_endpoints(client):
    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": ["ticket_put", "not_a_real_key"],
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "Unknown endpoint" in data["error"]


def test_put_config_rejects_non_list_api_endpoints(client):
    res = client.put(
        "/api/assistant/config",
        json={
            "api_endpoints": "ticket_put",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "must be a list" in data["error"]


# ---------------------------------------------------------------------------
# Chat — SSE streaming
# ---------------------------------------------------------------------------


def test_chat_sse_content_type(client):
    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"


def test_chat_wrapped_ndjson_format(client):
    """Current pi CLI emits nested message_update events; verify normalization."""
    ndjson = (
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Hello "}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"world"}}\n'
        '{"type":"agent_end"}\n'
    )
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "Hello " in body
        assert "world" in body
        assert "event: done" in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Hi"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"] == "Hello world"


def test_chat_thinking_delta_wrapped_format(client):
    """Wrapped thinking_delta should be normalized and streamed."""
    ndjson = (
        '{"type":"message_update","assistantMessageEvent":{"type":"thinking_delta","delta":"Hmm"}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Answer"}}\n'
        '{"type":"agent_end"}\n'
    )
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "event: thinking" in body
        assert "Answer" in body
        assert "event: done" in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert rows[1]["content"] == "Answer"


def test_chat_multi_turn_tool_call_does_not_prematurely_end(client):
    """Multiple turn_end events during a tool call must not break the stream.

    Sequence: toolcall_start -> toolcall_end -> turn_end (after tool result)
    -> text_delta chunks -> turn_end (after final response) -> agent_end.
    Only agent_end should terminate the stream.
    """
    ndjson = (
        '{"type":"toolcall_start","name":"search_web"}\n'
        '{"type":"toolcall_end","name":"search_web"}\n'
        '{"type":"turn_end"}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"The"}}\n'
        '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":" answer"}}\n'
        '{"type":"turn_end"}\n'
        '{"type":"agent_end"}\n'
    )
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")

    # Tool status events
    assert "tool_start" in body
    assert "tool_end" in body

    # Text should be fully accumulated
    assert "The" in body
    assert " answer" in body

    # Only one done event, at the very end
    assert body.count("event: done") == 1
    assert "event: done" in body

    # No premature error/stopped
    assert "event: error" not in body
    assert "event: stopped" not in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Hi"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"] == "The answer"


def test_chat_stores_messages_and_returns_response(client):
    ndjson = '{"type":"text_delta","chunk":"Hello there"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "Hello there" in body
        assert "event: done" in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Hi"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"] == "Hello there"


def test_chat_requires_message(client):
    res = client.post("/api/assistant/chat", json={})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "message is required" in data["error"]

    res = client.post("/api/assistant/chat", json={"message": "   "})
    assert res.status_code == 400


def test_chat_error_handling(client):
    """Non-zero exit code with stderr should produce SSE error event."""
    fake = _make_mock_popen(ndjson="", stderr="pi not found", returncode=127)
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "event: error" in body
        assert "pi not found" in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    # No assistant message inserted because accumulated_text is empty
    assert len(rows) == 1
    assert rows[0]["role"] == "user"


def test_chat_uses_config_system_prompt_and_api_docs(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put(
            "/api/assistant/config",
            json={
                "system_prompt": "Custom system prompt",
            },
        )
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index("--system-prompt") + 1]
        assert "Custom system prompt" in system_prompt
        assert "API Documentation" in system_prompt


def test_chat_system_prompt_defaults_include_api_docs(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put("/api/assistant/config", json={"system_prompt": None})
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index("--system-prompt") + 1]
        assert "pi-CoWork Assistant" in system_prompt
        assert "API Documentation" in system_prompt


def test_chat_prompt_includes_selected_endpoints(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put(
            "/api/assistant/config",
            json={
                "api_endpoints": ["boards_list", "workflows_list"],
            },
        )
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index("--system-prompt") + 1]
        assert "/api/boards" in system_prompt
        assert "/api/workflows" in system_prompt
        assert "/api/tickets/" not in system_prompt


def test_chat_prompt_default_includes_all_endpoints(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put("/api/assistant/config", json={"api_endpoints": None})
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        system_prompt = cmd[cmd.index("--system-prompt") + 1]
        assert "/api/tickets/" in system_prompt
        assert "/api/boards" in system_prompt
        assert "/api/workflows" in system_prompt
        # Literal placeholders should remain in assistant docs
        assert "{ticket_id}" in system_prompt


def test_chat_uses_config_model_and_thinking(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put(
            "/api/assistant/config",
            json={
                "model": "custom-model",
                "thinking": "low",
            },
        )
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "custom-model"
        assert "--thinking" in cmd
        assert cmd[cmd.index("--thinking") + 1] == "low"


def test_chat_json_mode_flag(client):
    """Chat command must include '--mode json'."""
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        assert "--mode" in cmd
        assert cmd[cmd.index("--mode") + 1] == "json"


def test_chat_injects_page_url_when_auto_context_enabled(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put("/api/assistant/config", json={"auto_context": True})
        res = client.post("/api/assistant/chat", json={"message": "Hi", "page_url": "/board"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert "Current page context: /board" in prompt


def test_chat_does_not_inject_page_url_when_auto_context_disabled(client):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.put("/api/assistant/config", json={"auto_context": False})
        res = client.post("/api/assistant/chat", json={"message": "Hi", "page_url": "/board"})
        assert res.status_code == 200
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert "Current page context:" not in prompt


def test_chat_text_delta_streaming(client):
    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"text_delta","chunk":" world"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "Hello" in body
        assert " world" in body
        assert "event: done" in body
        # Full text should appear in done payload
        assert "Hello world" in body


def test_chat_done_event_has_full_text(client):
    ndjson = '{"type":"text_delta","chunk":"Full reply"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "event: done" in body
        assert "Full reply" in body

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[1]["content"] == "Full reply"


def test_chat_json_error_event(client):
    """When NDJSON contains an error event, SSE should forward it."""
    ndjson = '{"type":"error","error":"model failure"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson, returncode=0)):
        res = client.post("/api/assistant/chat", json={"message": "Hi"})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "event: error" in body
        assert "model failure" in body

    history = client.get("/api/assistant/history")
    # No assistant message because no text was accumulated
    assert len(json.loads(history.data)) == 1


def test_chat_sequential_requests_not_blocked(client):
    """Two sequential requests should both complete without deadlock."""
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        res1 = client.post("/api/assistant/chat", json={"message": "M1"})
        assert res1.status_code == 200
        res2 = client.post("/api/assistant/chat", json={"message": "M2"})
        assert res2.status_code == 200

    history = client.get("/api/assistant/history")
    rows = json.loads(history.data)
    assert len(rows) == 4


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def test_stop_endpoint_kills_active_run(client):
    from pi_cowork.assistant import _ASSISTANT_RUNS, _assistant_runs_lock, _AssistantRun

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 99999
    run = _AssistantRun(fake_proc, None, 1, os.devnull)
    with _assistant_runs_lock:
        _ASSISTANT_RUNS[None] = run

    with patch("pi_cowork.assistant.os.kill") as mock_kill:
        res = client.post("/api/assistant/stop", json={})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        mock_kill.assert_called_once_with(99999, signal.SIGTERM)

    # Clean up
    with _assistant_runs_lock:
        _ASSISTANT_RUNS.pop(None, None)


def test_stop_endpoint_returns_false_when_no_run(client):
    res = client.post("/api/assistant/stop", json={})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is False


# ---------------------------------------------------------------------------
# Active Run
# ---------------------------------------------------------------------------


def test_active_run_returns_running_after_chat(client):
    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        client.post("/api/assistant/chat", json={"message": "Hi"})

    # In TESTING mode the generator finalizes inline, so active-run sees completed status
    res = client.get("/api/assistant/active-run")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data is None

    # But the run row should exist in the DB with completed status
    with client.application.app_context():
        row = query_db(
            "SELECT status, full_text FROM assistant_runs WHERE board_id IS NULL ORDER BY id DESC LIMIT 1",
            one=True,
        )
    assert row is not None
    assert row["status"] == "completed"
    assert row["full_text"] == "Hello"


def test_active_run_returns_null_when_no_run(client):
    res = client.get("/api/assistant/active-run")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data is None


# ---------------------------------------------------------------------------
# Reconnect stream
# ---------------------------------------------------------------------------


def test_reconnect_finalized_completed_run(client):
    # Seed a completed run row and log file
    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-reconnect-test.log")
    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"Replay "}\n')
        f.write('{"type":"text_delta","chunk":"text"}\n')
        f.write('{"type":"_stdout_closed"}\n')

    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid, full_text) VALUES (?, 'completed', ?, ?, ?)",
            (None, log_path, 12345, "Replay text"),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get(f"/api/assistant/stream?run_id={run_id}")
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    body = res.data.decode("utf-8")
    assert "Replay text" in body
    assert "event: done" in body


def test_reconnect_finalized_stopped_run(client):
    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-reconnect-stopped.log")
    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"Partial"}\n')
        f.write('{"type":"_stdout_closed"}\n')

    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid, full_text) VALUES (?, 'stopped', ?, ?, ?)",
            (None, log_path, 12345, "Partial"),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get(f"/api/assistant/stream?run_id={run_id}")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert "event: stopped" in body
    assert "Partial" in body


def test_reconnect_not_found_run(client):
    res = client.get("/api/assistant/stream?run_id=99999")
    assert res.status_code == 200
    body = res.data.decode("utf-8")
    assert "event: error" in body
    assert "Run not found" in body


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_empty(client):
    res = client.get("/api/assistant/history")
    assert res.status_code == 200
    assert json.loads(res.data) == []


def test_history_returns_messages(client):
    ndjson = '{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        client.post("/api/assistant/chat", json={"message": "M1"})

    res = client.get("/api/assistant/history")
    rows = json.loads(res.data)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"] == "A"


# ---------------------------------------------------------------------------
# Compact
# ---------------------------------------------------------------------------


def test_compact_summarizes_and_clears(client):
    with patch(
        "pi_cowork.assistant.subprocess.Popen",
        side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'),
    ):
        client.post("/api/assistant/chat", json={"message": "M1"})
        client.post("/api/assistant/chat", json={"message": "M2"})

    os.makedirs(ASSISTANT_SESSION_DIR, exist_ok=True)
    with open(os.path.join(ASSISTANT_SESSION_DIR, "session.jsonl"), "w") as f:
        f.write("{}")

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout='{"type":"compaction_start","reason":"manual"}', stderr="", returncode=0
        )
        res = client.post("/api/assistant/compact")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["summary"] == "Conversation compacted by pi."
        assert data["message_count"] == 4
        cmd = mock_run.call_args[0][0]
        assert "--mode" in cmd
        assert "rpc" in cmd
        assert mock_run.call_args.kwargs.get("input") == '{"type":"compact"}'

    # DB should be empty
    history = client.get("/api/assistant/history")
    assert json.loads(history.data) == []

    # Summary setting should NOT be stored
    from pi_cowork.models import get_setting

    with client.application.app_context():
        assert get_setting("assistant_summary") is None

    # Session dir should STILL EXIST
    assert os.path.exists(ASSISTANT_SESSION_DIR)


def test_compact_empty_db(client):
    res = client.post("/api/assistant/compact")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["summary"] == ""
    assert data["message_count"] == 0


def test_compact_uses_config_model_and_thinking(client):
    with patch(
        "pi_cowork.assistant.subprocess.Popen",
        side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'),
    ):
        client.post("/api/assistant/chat", json={"message": "M1"})

    client.put(
        "/api/assistant/config",
        json={
            "model": "compact-model",
            "thinking": "high",
        },
    )
    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout='{"type":"compaction_start"}', stderr="", returncode=0)
        res = client.post("/api/assistant/compact")
        assert res.status_code == 200
        cmd = mock_run.call_args[0][0]
        assert "--mode" in cmd
        assert "rpc" in cmd
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "compact-model"
        assert "--thinking" in cmd
        assert cmd[cmd.index("--thinking") + 1] == "high"
        assert mock_run.call_args.kwargs.get("input") == '{"type":"compact"}'


def test_compact_deletes_assistant_runs(client):
    with patch(
        "pi_cowork.assistant.subprocess.Popen",
        side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'),
    ):
        client.post("/api/assistant/chat", json={"message": "M1"})

    with client.application.app_context():
        before = query_db("SELECT COUNT(*) as c FROM assistant_runs", one=True)["c"]
    assert before >= 1

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout='{"type":"compaction_start"}', stderr="", returncode=0)
        client.post("/api/assistant/compact")

    with client.application.app_context():
        after = query_db("SELECT COUNT(*) as c FROM assistant_runs", one=True)["c"]
    assert after == 0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_clears_all(client):
    with patch(
        "pi_cowork.assistant.subprocess.Popen",
        side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'),
    ):
        client.post("/api/assistant/chat", json={"message": "Hi"})

    os.makedirs(ASSISTANT_SESSION_DIR, exist_ok=True)
    with open(os.path.join(ASSISTANT_SESSION_DIR, "session.jsonl"), "w") as f:
        f.write("{}")

    from pi_cowork.models import set_setting

    with client.application.app_context():
        set_setting("assistant_summary", "Old summary")

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)
        res = client.post("/api/assistant/reset")
        assert res.status_code == 200
        assert json.loads(res.data) == {"success": True}
        cmd = mock_run.call_args[0][0]
        assert "--mode" in cmd
        assert "rpc" in cmd
        assert mock_run.call_args.kwargs.get("input") == '{"type":"new_session"}'

    history = client.get("/api/assistant/history")
    assert json.loads(history.data) == []

    from pi_cowork.models import get_setting

    with client.application.app_context():
        assert get_setting("assistant_summary") is None

    assert os.path.exists(ASSISTANT_SESSION_DIR)


# ---------------------------------------------------------------------------
# Board Assistant
# ---------------------------------------------------------------------------


def test_board_chat_stores_messages_with_board_id(client, default_board):
    ndjson = '{"type":"text_delta","chunk":"Board reply"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)):
        res = client.post("/api/assistant/chat", json={"message": "Hi board", "board_id": default_board["id"]})
        assert res.status_code == 200
        body = res.data.decode("utf-8")
        assert "Board reply" in body
        assert "event: done" in body

    # Board history should contain the messages
    history = client.get(f"/api/assistant/history?board_id={default_board['id']}")
    rows = json.loads(history.data)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[0]["content"] == "Hi board"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["content"] == "Board reply"


def test_board_chat_isolated_per_board(client, default_board, new_workflow):
    """Messages for different boards should not mix."""
    # Create second board
    res = client.post(
        "/api/boards",
        json={
            "name": "Second Board",
            "workflow_id": new_workflow["id"],
        },
    )
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        client.post("/api/assistant/chat", json={"message": "B1", "board_id": default_board["id"]})
        client.post("/api/assistant/chat", json={"message": "B2", "board_id": board2["id"]})

    h1 = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    h2 = json.loads(client.get(f"/api/assistant/history?board_id={board2['id']}").data)
    assert len(h1) == 2
    assert h1[0]["content"] == "B1"
    assert len(h2) == 2
    assert h2[0]["content"] == "B2"


def test_board_chat_isolated_from_global(client, default_board):
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        client.post("/api/assistant/chat", json={"message": "Global"})
        client.post("/api/assistant/chat", json={"message": "Board", "board_id": default_board["id"]})

    global_hist = json.loads(client.get("/api/assistant/history").data)
    board_hist = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    assert len(global_hist) == 2
    assert global_hist[0]["content"] == "Global"
    assert len(board_hist) == 2
    assert board_hist[0]["content"] == "Board"


def test_board_chat_injects_board_context(client, default_board):
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.post(
            "/api/assistant/chat",
            json={
                "message": "Hi",
                "board_id": default_board["id"],
                "page_url": "/board",
            },
        )
        cmd = mock_popen.call_args[0][0]
        prompt = cmd[-1]
        assert f"Current board context: {default_board['name']}" in prompt
        assert f"board_id={default_board['id']}" in prompt
        assert "Current page context: /board" in prompt


def test_board_chat_uses_board_working_directory(client, default_board):
    # Update board working directory
    custom_dir = "custom-board-ws"
    client.put(
        f"/api/boards/{default_board['id']}",
        json={
            "name": default_board["name"],
            "workflow_id": default_board["workflow_id"],
            "working_directory": custom_dir,
        },
    )
    with patch("pi_cowork.assistant.subprocess.Popen") as mock_popen:
        mock_popen.side_effect = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
        client.post("/api/assistant/chat", json={"message": "Hi", "board_id": default_board["id"]})
        cwd = mock_popen.call_args.kwargs.get("cwd")
        assert custom_dir in cwd


def test_board_compact_affects_only_targeted_board(client, default_board, new_workflow):
    # Create second board
    res = client.post(
        "/api/boards",
        json={
            "name": "Second Board",
            "workflow_id": new_workflow["id"],
        },
    )
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        client.post("/api/assistant/chat", json={"message": "B1", "board_id": default_board["id"]})
        client.post("/api/assistant/chat", json={"message": "B2", "board_id": board2["id"]})

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)
        res = client.post("/api/assistant/compact", json={"board_id": default_board["id"]})
        assert res.status_code == 200

    h1 = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    h2 = json.loads(client.get(f"/api/assistant/history?board_id={board2['id']}").data)
    assert len(h1) == 0
    assert len(h2) == 2


def test_reset_deletes_assistant_runs(client):
    with patch(
        "pi_cowork.assistant.subprocess.Popen",
        side_effect=_make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n'),
    ):
        client.post("/api/assistant/chat", json={"message": "Hi"})

    with client.application.app_context():
        before = query_db("SELECT COUNT(*) as c FROM assistant_runs", one=True)["c"]
    assert before >= 1

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)
        client.post("/api/assistant/reset")

    with client.application.app_context():
        after = query_db("SELECT COUNT(*) as c FROM assistant_runs", one=True)["c"]
    assert after == 0


def test_board_reset_affects_only_targeted_board(client, default_board, new_workflow):
    # Create second board
    res = client.post(
        "/api/boards",
        json={
            "name": "Second Board",
            "workflow_id": new_workflow["id"],
        },
    )
    board2 = json.loads(res.data)

    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        client.post("/api/assistant/chat", json={"message": "B1", "board_id": default_board["id"]})
        client.post("/api/assistant/chat", json={"message": "B2", "board_id": board2["id"]})

    with patch("app.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)
        res = client.post("/api/assistant/reset", json={"board_id": default_board["id"]})
        assert res.status_code == 200

    h1 = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    h2 = json.loads(client.get(f"/api/assistant/history?board_id={board2['id']}").data)
    assert len(h1) == 0
    assert len(h2) == 2


def test_board_deletion_cascades_to_board_assistant_messages(client, default_board):
    fake = _make_mock_popen(ndjson='{"type":"text_delta","chunk":"A"}\n{"type":"done"}\n')
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=fake):
        client.post("/api/assistant/chat", json={"message": "B1", "board_id": default_board["id"]})

    h = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    assert len(h) == 2

    # Delete the board
    res = client.delete(f"/api/boards/{default_board['id']}")
    assert res.status_code == 200

    # Messages should be gone
    h = json.loads(client.get(f"/api/assistant/history?board_id={default_board['id']}").data)
    assert len(h) == 0


def test_board_chat_rejects_invalid_board_id(client):
    res = client.post("/api/assistant/chat", json={"message": "Hi", "board_id": 99999})
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "board not found" in data["error"]


def test_board_chat_rejects_non_integer_board_id(client):
    res = client.post("/api/assistant/chat", json={"message": "Hi", "board_id": "abc"})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "board_id must be an integer" in data["error"]


def test_board_history_requires_integer_board_id(client):
    res = client.get("/api/assistant/history?board_id=abc")
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "board_id must be an integer" in data["error"]


# ---------------------------------------------------------------------------
# Saved Prompts API
# ---------------------------------------------------------------------------


def test_saved_prompts_list_empty(client):
    res = client.get("/api/assistant/saved-prompts")
    assert res.status_code == 200
    assert json.loads(res.data) == []


def test_saved_prompts_create_and_list(client):
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Review code",
            "prompt_text": "Review the last commit for bugs.",
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "Review code"
    assert data["prompt_text"] == "Review the last commit for bugs."
    assert "id" in data

    res = client.get("/api/assistant/saved-prompts")
    assert res.status_code == 200
    rows = json.loads(res.data)
    assert len(rows) == 1
    assert rows[0]["name"] == "Review code"


def test_saved_prompts_create_requires_name(client):
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "prompt_text": "Text only",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "name is required" in data["error"]


def test_saved_prompts_create_requires_prompt_text(client):
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Name only",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "prompt_text is required" in data["error"]


def test_saved_prompts_create_rejects_duplicate_name(client):
    client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Daily standup",
            "prompt_text": "Summarize yesterday's work.",
        },
    )
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Daily standup",
            "prompt_text": "Different text.",
        },
    )
    assert res.status_code == 409
    data = json.loads(res.data)
    assert "already exists" in data["error"]


def test_saved_prompts_update(client):
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Old",
            "prompt_text": "Old text.",
        },
    )
    pid = json.loads(res.data)["id"]

    res = client.put(
        f"/api/assistant/saved-prompts/{pid}",
        json={
            "name": "New",
            "prompt_text": "New text.",
        },
    )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["name"] == "New"
    assert data["prompt_text"] == "New text."

    res = client.get("/api/assistant/saved-prompts")
    rows = json.loads(res.data)
    assert len(rows) == 1
    assert rows[0]["name"] == "New"


def test_saved_prompts_update_not_found(client):
    res = client.put(
        "/api/assistant/saved-prompts/9999",
        json={
            "name": "X",
            "prompt_text": "Y",
        },
    )
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "not found" in data["error"]


def test_saved_prompts_update_rejects_duplicate_name(client):
    res1 = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "A",
            "prompt_text": "A text.",
        },
    )
    client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "B",
            "prompt_text": "B text.",
        },
    )
    pid = json.loads(res1.data)["id"]

    res = client.put(
        f"/api/assistant/saved-prompts/{pid}",
        json={
            "name": "B",
            "prompt_text": "A text updated.",
        },
    )
    assert res.status_code == 409
    data = json.loads(res.data)
    assert "already exists" in data["error"]


def test_saved_prompts_delete(client):
    res = client.post(
        "/api/assistant/saved-prompts",
        json={
            "name": "Delete me",
            "prompt_text": "Text.",
        },
    )
    pid = json.loads(res.data)["id"]

    res = client.delete(f"/api/assistant/saved-prompts/{pid}")
    assert res.status_code == 200
    assert json.loads(res.data)["success"] is True

    res = client.get("/api/assistant/saved-prompts")
    assert json.loads(res.data) == []


def test_saved_prompts_delete_not_found(client):
    res = client.delete("/api/assistant/saved-prompts/9999")
    assert res.status_code == 404
    data = json.loads(res.data)
    assert "not found" in data["error"]


# ---------------------------------------------------------------------------
# Saved Prompts UI Presence
# ---------------------------------------------------------------------------

SETTINGS_HTML_PATH = "templates/settings.html"
BASE_HTML_PATH = "templates/base.html"
BOARD_HTML_PATH = "templates/board.html"
STYLE_CSS_PATH = "static/style.css"
ASSISTANT_JS_PATH = "static/assistant.js"
BOARD_ASSISTANT_JS_PATH = "static/board_assistant.js"  # Removed — kept for path reference


# Board assistant was consolidated into the global assistant.
# The following tests are skipped as the board assistant has been removed.


def read(path):
    with open(path) as f:
        return f.read()


class TestSavedPromptsSettingsUI:
    def test_settings_page_has_saved_prompts_section(self):
        html = read(SETTINGS_HTML_PATH)
        assert "Saved Prompts" in html, "Expected Saved Prompts heading in settings"
        assert "saved-prompts-list" in html, "Expected saved-prompts-list container"
        assert "sp-add-name" in html, "Expected sp-add-name input"
        assert "sp-add-text" in html, "Expected sp-add-text textarea"

    def test_settings_page_has_inline_add_form(self):
        html = read(SETTINGS_HTML_PATH)
        assert "createSavedPrompt" in html, "Expected createSavedPrompt function call"
        assert "deleteSavedPrompt" in html, "Expected deleteSavedPrompt function reference"

    def test_settings_page_has_inline_edit_form(self):
        html = read(SETTINGS_HTML_PATH)
        assert "startEditSavedPrompt" in html, "Expected startEditSavedPrompt function reference"
        assert "saveSavedPromptEdit" in html, "Expected saveSavedPromptEdit function reference"
        assert "cancelSavedPromptEdit" in html, "Expected cancelSavedPromptEdit function reference"

    def test_settings_page_loads_saved_prompts(self):
        html = read(SETTINGS_HTML_PATH)
        assert "loadSavedPrompts" in html, "Expected loadSavedPrompts call in settings script"


class TestSavedPromptsGlobalAssistantUI:
    def test_base_html_has_saved_prompts_bar(self):
        html = read(BASE_HTML_PATH)
        assert "assistant-saved-prompts" in html, "Expected assistant-saved-prompts div in base.html"
        assert "saved-prompts-bar" in html, "Expected saved-prompts-bar class in base.html"

    def test_assistant_js_has_saved_prompts_logic(self):
        js = read(ASSISTANT_JS_PATH)
        assert "loadSavedPrompts" in js, "Expected loadSavedPrompts in assistant.js"
        assert "renderSavedPrompts" in js, "Expected renderSavedPrompts in assistant.js"
        assert "saved-prompt-btn" in js, "Expected saved-prompt-btn class in assistant.js"


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
        assert ".saved-prompts-bar" in css, "Expected .saved-prompts-bar styles in CSS"

    def test_css_has_saved_prompt_btn(self):
        css = read(STYLE_CSS_PATH)
        assert ".saved-prompt-btn" in css, "Expected .saved-prompt-btn styles in CSS"

    def test_css_has_saved_prompts_table(self):
        css = read(STYLE_CSS_PATH)
        assert ".saved-prompts-table" in css, "Expected .saved-prompts-table styles in CSS"

    def test_css_has_saved_prompts_inline_add(self):
        css = read(STYLE_CSS_PATH)
        assert ".saved-prompts-inline-add" in css, "Expected .saved-prompts-inline-add styles in CSS"

    def test_css_has_saved_prompts_row_actions(self):
        css = read(STYLE_CSS_PATH)
        assert ".saved-prompts-row-actions" in css, "Expected .saved-prompts-row-actions styles in CSS"


# ---------------------------------------------------------------------------
# Quick Config (Model & Thinking) UI
# ---------------------------------------------------------------------------


class TestAssistantQuickConfigUI:
    def test_base_html_has_quick_config(self):
        html = read(BASE_HTML_PATH)
        assert "assistant-quick-config" in html, "Expected assistant-quick-config in base.html"
        assert "assistant-model" in html, "Expected assistant-model select in base.html"
        assert "assistant-thinking" in html, "Expected assistant-thinking select in base.html"

    def test_assistant_js_has_quick_config_logic(self):
        js = read(ASSISTANT_JS_PATH)
        assert "loadPiModels" in js, "Expected loadPiModels in assistant.js"
        assert "populateModelSelect" in js, "Expected populateModelSelect in assistant.js"
        assert "populateThinkingSelect" in js, "Expected populateThinkingSelect in assistant.js"
        assert "saveQuickConfig" in js, "Expected saveQuickConfig in assistant.js"
        assert "assistant-model" in js, "Expected assistant-model reference in assistant.js"
        assert "assistant-thinking" in js, "Expected assistant-thinking reference in assistant.js"

    def test_css_has_quick_config_styles(self):
        css = read(STYLE_CSS_PATH)
        assert ".assistant-quick-config" in css, "Expected .assistant-quick-config styles in CSS"
        assert ".assistant-quick-config-field" in css, "Expected .assistant-quick-config-field styles in CSS"


def test_board_page_has_assistant_quick_config(client):
    res = client.get("/board")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "assistant-quick-config" in html
    assert "assistant-model" in html
    assert "assistant-thinking" in html


def test_quick_config_api_updates_model_and_thinking(client):
    res = client.put("/api/assistant/config", json={"model": "custom-model", "thinking": "high"})
    assert res.status_code == 200
    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["model"] == "custom-model"
    assert data["thinking"] == "high"


# ---------------------------------------------------------------------------
# Excluded Skills (Ticket #151)
# ---------------------------------------------------------------------------


def test_get_config_includes_excluded_skill_names(client):
    res = client.get("/api/assistant/config")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert "excluded_skill_names" in data
    assert data["excluded_skill_names"] == []


def test_put_config_excluded_skill_names(client):
    res = client.put("/api/assistant/config", json={"excluded_skill_names": ["ux-design"]})
    assert res.status_code == 200
    res = client.get("/api/assistant/config")
    data = json.loads(res.data)
    assert data["excluded_skill_names"] == ["ux-design"]


def test_put_config_rejects_invalid_excluded_skill_names(client):
    res = client.put("/api/assistant/config", json={"excluded_skill_names": "not-a-list"})
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "excluded_skill_names" in data["error"]


def test_assistant_chat_includes_built_in_skills(client, temp_skills_folder):
    from pi_cowork.skill_packages import get_built_in_skills_folder

    folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(folder, "assistant-skill"), exist_ok=True)
    with open(os.path.join(folder, "assistant-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: assistant-skill\ndescription: Assistant skill\n---\n\nContent.")

    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)) as mock_popen:
        res = client.post("/api/assistant/chat", json={"message": "Hi"})

    assert res.status_code == 200
    cmd = mock_popen.call_args[0][0]
    assert "--skill" in cmd
    idx = cmd.index("--skill")
    assert "assistant-skill" in cmd[idx + 1]
    context_msg = cmd[-1]
    assert "Skills available to you:" in context_msg
    assert "assistant-skill" in context_msg


def test_assistant_chat_excludes_skills_when_configured(client, temp_skills_folder):
    from pi_cowork.skill_packages import get_built_in_skills_folder

    folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(folder, "blocked-skill"), exist_ok=True)
    with open(os.path.join(folder, "blocked-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: blocked-skill\ndescription: Blocked\n---\n\nContent.")
    os.makedirs(os.path.join(folder, "allowed-skill"), exist_ok=True)
    with open(os.path.join(folder, "allowed-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: allowed-skill\ndescription: Allowed\n---\n\nContent.")

    client.put("/api/assistant/config", json={"excluded_skill_names": ["blocked-skill"]})

    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)) as mock_popen:
        res = client.post("/api/assistant/chat", json={"message": "Hi"})

    assert res.status_code == 200
    cmd = mock_popen.call_args[0][0]
    context_msg = cmd[-1]
    assert "allowed-skill" in context_msg
    assert "blocked-skill" not in context_msg
    skill_args = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--skill"]
    assert any("allowed-skill" in s for s in skill_args)
    assert not any("blocked-skill" in s for s in skill_args)


def test_assistant_chat_includes_global_skills(client, temp_skills_folder):
    from pi_cowork.skill_packages import get_built_in_skills_folder

    # Create a built-in skill
    bi_folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(bi_folder, "bi-skill"), exist_ok=True)
    with open(os.path.join(bi_folder, "bi-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: bi-skill\ndescription: Built-in skill\n---\n\nContent.")

    # Create a global skill
    global_folder = os.path.join(temp_skills_folder, "global")
    os.makedirs(os.path.join(global_folder, "global-skill"), exist_ok=True)
    with open(os.path.join(global_folder, "global-skill", "SKILL.md"), "w") as f:
        f.write("---\nname: global-skill\ndescription: Global skill\n---\n\nContent.")

    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)) as mock_popen:
        res = client.post("/api/assistant/chat", json={"message": "Hi"})

    assert res.status_code == 200
    cmd = mock_popen.call_args[0][0]
    context_msg = cmd[-1]
    assert "Skills available to you:" in context_msg
    assert "bi-skill" in context_msg
    assert "global-skill" in context_msg
    skill_args = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--skill"]
    assert any("bi-skill" in s for s in skill_args)
    assert any("global-skill" in s for s in skill_args)


def test_assistant_chat_excludes_global_skills_when_configured(client, temp_skills_folder):
    from pi_cowork.skill_packages import get_built_in_skills_folder

    # Create a built-in skill
    bi_folder = get_built_in_skills_folder()
    os.makedirs(os.path.join(bi_folder, "allowed-bi"), exist_ok=True)
    with open(os.path.join(bi_folder, "allowed-bi", "SKILL.md"), "w") as f:
        f.write("---\nname: allowed-bi\ndescription: Allowed built-in\n---\n\nContent.")

    # Create global skills: one excluded, one allowed
    global_folder = os.path.join(temp_skills_folder, "global")
    os.makedirs(os.path.join(global_folder, "blocked-global"), exist_ok=True)
    with open(os.path.join(global_folder, "blocked-global", "SKILL.md"), "w") as f:
        f.write("---\nname: blocked-global\ndescription: Blocked global\n---\n\nContent.")
    os.makedirs(os.path.join(global_folder, "allowed-global"), exist_ok=True)
    with open(os.path.join(global_folder, "allowed-global", "SKILL.md"), "w") as f:
        f.write("---\nname: allowed-global\ndescription: Allowed global\n---\n\nContent.")

    client.put("/api/assistant/config", json={"excluded_skill_names": ["blocked-global"]})

    ndjson = '{"type":"text_delta","chunk":"Hello"}\n{"type":"done"}\n'
    with patch("pi_cowork.assistant.subprocess.Popen", side_effect=_make_mock_popen(ndjson=ndjson)) as mock_popen:
        res = client.post("/api/assistant/chat", json={"message": "Hi"})

    assert res.status_code == 200
    cmd = mock_popen.call_args[0][0]
    context_msg = cmd[-1]
    assert "allowed-bi" in context_msg
    assert "allowed-global" in context_msg
    assert "blocked-global" not in context_msg
    skill_args = [cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i] == "--skill"]
    assert any("allowed-bi" in s for s in skill_args)
    assert any("allowed-global" in s for s in skill_args)
    assert not any("blocked-global" in s for s in skill_args)


# ---------------------------------------------------------------------------
# Reconnect bug fixes (Ticket #173)
# ---------------------------------------------------------------------------


def test_reconnect_active_run_does_not_duplicate_text(client):
    """Replayed events in reconnect must not mutate run.accumulated_text."""
    from pi_cowork.assistant import (
        _ASSISTANT_RUNS,
        _assistant_runs_lock,
        _assistant_stream_generator_reconnect,
        _AssistantRun,
    )

    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-dup-test.log")
    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"Hello "}\n')
        f.write('{"type":"text_delta","chunk":"World"}\n')
        f.write('{"type":"_stdout_closed"}\n')

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 99999
    run = _AssistantRun(fake_proc, None, 1, log_path)
    run.accumulated_text = ["Hello ", "World"]  # Already accumulated by original generator

    with _assistant_runs_lock:
        _ASSISTANT_RUNS[None] = run

    try:
        call_count = [0]

        def _sleep_and_remove(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 1:
                with _assistant_runs_lock:
                    _ASSISTANT_RUNS.pop(None, None)
            return None

        with patch("pi_cowork.assistant.time.sleep", side_effect=_sleep_and_remove):
            gen = _assistant_stream_generator_reconnect(run, None, client.application)
            chunks = list(gen)

        body = "".join(chunks)
        assert "Hello " in body
        assert "World" in body
        # The bug would double accumulated_text; fixed behavior preserves it
        assert run.accumulated_text == ["Hello ", "World"]
    finally:
        with _assistant_runs_lock:
            _ASSISTANT_RUNS.pop(None, None)


def test_reconnect_active_run_tails_new_log_events(client):
    """New log events written after reconnect starts must be streamed."""

    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-tail-test.log")

    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"Hello "}\n')

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 99999
    run = _AssistantRun(fake_proc, None, 1, log_path)

    with _assistant_runs_lock:
        _ASSISTANT_RUNS[None] = run

    try:
        call_count = [0]

        def _sleep_and_append(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                with open(log_path, "a") as f:
                    f.write('{"type":"text_delta","chunk":"World"}\n')
            elif call_count[0] == 2:
                with open(log_path, "a") as f:
                    f.write('{"type":"_stdout_closed"}\n')
            elif call_count[0] >= 3:
                with _assistant_runs_lock:
                    _ASSISTANT_RUNS.pop(None, None)
            return None

        with patch("pi_cowork.assistant.time.sleep", side_effect=_sleep_and_append):
            gen = _assistant_stream_generator_reconnect(run, None, client.application)
            chunks = list(gen)

        body = "".join(chunks)
        assert "Hello " in body
        assert "World" in body
    finally:
        with _assistant_runs_lock:
            _ASSISTANT_RUNS.pop(None, None)


def test_reconnect_finalized_empty_log_yields_full_text(client):
    """A finalized run with no text events in the log must still yield full_text
    in the synthetic done event so the frontend can display the complete message."""
    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-empty-log.log")
    with open(log_path, "w") as f:
        f.write('{"type":"_stdout_closed"}\n')

    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid, full_text) VALUES (?, 'completed', ?, ?, ?)",
            (None, log_path, 12345, "Full text from DB"),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get(f"/api/assistant/stream?run_id={run_id}")
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    body = res.data.decode("utf-8")
    assert "event: done" in body
    assert "Full text from DB" in body


def test_active_run_filters_by_board_id(client, default_board):
    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid) VALUES (?, 'running', ?, ?)",
            (None, os.devnull, 111),
        )
        global_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid) VALUES (?, 'running', ?, ?)",
            (default_board["id"], os.devnull, 222),
        )
        board_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get("/api/assistant/active-run")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data is not None
    assert data["id"] == global_id

    res = client.get(f"/api/assistant/active-run?board_id={default_board['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data is not None
    assert data["id"] == board_id


def test_reconnect_stream_scope_mismatch_returns_403(client, default_board):
    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-scope-test.log")
    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"X"}\n')

    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid, full_text) VALUES (?, 'completed', ?, ?, ?)",
            (default_board["id"], log_path, 12345, "X"),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get(f"/api/assistant/stream?run_id={run_id}&board_id=99999")
    assert res.status_code == 403
    data = json.loads(res.data)
    assert "scope mismatch" in data["error"]


def test_active_run_returns_running_run(client):
    """GET /api/assistant/active-run returns the latest running run."""
    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid) VALUES (?, 'running', ?, ?)",
            (None, os.devnull, 12345),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    res = client.get("/api/assistant/active-run")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data is not None
    assert data["id"] == run_id
    assert data["status"] == "running"


class TestAssistantJsBoardScope:
    """Verify loadHistory, doCompact, and doReset pass board_id (Ticket #195)."""

    def test_load_history_passes_board_id(self):
        js = read(ASSISTANT_JS_PATH)
        # loadHistory should build a URL that includes board_id
        assert "getAssistantBoardId" in js
        # Find the loadHistory function body and check it uses board_id
        assert "board_id=" in js, "Expected board_id query param somewhere in assistant.js"

    def test_do_compact_passes_board_id(self):
        js = read(ASSISTANT_JS_PATH)
        assert "doCompact" in js
        assert "assistant/compact" in js
        assert "board_id: getAssistantBoardId()" in js

    def test_do_reset_passes_board_id(self):
        js = read(ASSISTANT_JS_PATH)
        assert "doReset" in js
        assert "assistant/reset" in js
        assert "board_id: getAssistantBoardId()" in js


def test_stream_reattaches_to_running_run_when_in_memory_state_lost(client):
    """If in-memory state is gone but the DB row is running and the PID is alive,
    GET /api/assistant/stream reattaches and replays the existing log."""
    import pi_cowork.assistant as assistant_mod

    log_dir = os.path.join(ASSISTANT_SESSION_DIR, "runs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "run-reattach-test.log")
    with open(log_path, "w") as f:
        f.write('{"type":"text_delta","chunk":"Reattached"}\n')
        f.write('{"type":"_stdout_closed"}\n')

    with client.application.app_context():
        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid) VALUES (?, 'running', ?, ?)",
            (None, log_path, 77777),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]

    try:
        with (
            patch("pi_cowork.assistant._is_pi_process_alive", side_effect=[True, False]),
            patch("pi_cowork.assistant.time.sleep", return_value=None),
        ):
            res = client.get(f"/api/assistant/stream?run_id={run_id}")
    finally:
        with assistant_mod._assistant_runs_lock:
            assistant_mod._ASSISTANT_RUNS.pop(None, None)

    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    body = res.data.decode("utf-8")
    assert "Reattached" in body
    assert "event: done" in body

    with client.application.app_context():
        row = query_db(
            "SELECT status, full_text FROM assistant_runs WHERE id = ?",
            (run_id,),
            one=True,
        )
    assert row["status"] == "completed"
    assert row["full_text"] == "Reattached"
