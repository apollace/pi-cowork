"""Assistant: global and per-board chat backed by DB."""

import json
import logging
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from pi_cowork import config
from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.api.pi_models import get_thinking_levels, get_model_ids
from pi_cowork.api_docs import build_assistant_api_docs, _REGISTRY_MAP

logger = logging.getLogger(__name__)

assistant_bp = Blueprint('assistant', __name__)

# board_id (None for global) -> threading.Lock
_assistant_locks = {}
_locks_master = threading.Lock()

# Active assistant runs for streaming (latest-wins model)
_ASSISTANT_RUNS = {}
_assistant_runs_lock = threading.Lock()


class _AssistantRun:
    def __init__(self, proc, scope):
        self.proc = proc
        self.scope = scope
        self.cancelled = False
        self.accumulated_text = []
        self.accumulated_thinking = []
        self.start_time = time.monotonic()


def _stop_assistant_run(scope, timeout=5):
    """Signal an active assistant run to stop. Returns True if a run existed."""
    with _assistant_runs_lock:
        run = _ASSISTANT_RUNS.get(scope)
    if not run:
        return False
    run.cancelled = True
    proc = run.proc
    if proc.poll() is None:
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def _kill_later():
        time.sleep(timeout)
        try:
            if proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    threading.Thread(target=_kill_later, daemon=True).start()
    return True


def _reader_thread(proc, q):
    """Read NDJSON lines from proc.stdout and push parsed events to queue."""
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Assistant NDJSON parse error: %s", line)
                continue
            q.put(event)
    finally:
        q.put({"type": "_stdout_closed"})


def _get_lock(board_id):
    """Return a per-board lock, creating it if necessary."""
    with _locks_master:
        if board_id not in _assistant_locks:
            _assistant_locks[board_id] = threading.Lock()
        return _assistant_locks[board_id]


def _get_assistant_config():
    row = query_db("SELECT * FROM assistant_config WHERE id = 1", one=True)
    if not row:
        return {
            'id': 1,
            'enabled': 1,
            'model': None,
            'thinking': None,
            'working_directory': 'workspace',
            'system_prompt': None,
            'auto_context': 1,
        }
    d = row_to_dict(row)
    # Empty string/thin null means "use pi default" (no override)
    if d.get('model') == '':
        d['model'] = None
    if not d.get('thinking'):
        d['thinking'] = None
    if d.get('system_prompt') == '':
        d['system_prompt'] = None
    # Parse api_endpoints JSON (NULL/empty -> None)
    ep = d.get('api_endpoints')
    if ep:
        try:
            d['api_endpoints'] = json.loads(ep)
        except (ValueError, TypeError):
            d['api_endpoints'] = None
    else:
        d['api_endpoints'] = None
    return d


def _get_board(board_id):
    if board_id is None:
        return None
    row = query_db("SELECT * FROM boards WHERE id = ?", (board_id,), one=True)
    return row_to_dict(row) if row else None


def _assistant_work_dir(board_id=None):
    if board_id is not None:
        board = _get_board(board_id)
        if board:
            wd = board.get('working_directory')
            if wd:
                path = Path(wd)
                if not path.is_absolute():
                    path = Path(config.PROJECT_ROOT) / path
                return str(path)
    # fallback to global config
    cfg = _get_assistant_config()
    working_directory = cfg.get('working_directory') or 'workspace'
    path = Path(working_directory)
    if not path.is_absolute():
        path = Path(config.PROJECT_ROOT) / path
    return str(path)


def _assistant_session_dir(board_id=None):
    work_dir = _assistant_work_dir(board_id)
    if board_id is not None:
        return os.path.join(work_dir, '.pi-sessions', f'assistant-board-{board_id}')
    return os.path.join(work_dir, '.pi-sessions', 'assistant-global')


def _get_assistant_system_prompt(cfg, board_id=None):
    base = (cfg.get('system_prompt') or '').strip()
    if not base:
        base = config.DEFAULT_ASSISTANT_SYSTEM_PROMPT
    docs = build_assistant_api_docs(cfg.get('api_endpoints'))
    prompt = f"{base}\n\n{docs}"
    # Inject board-relevant knowledge entries if auto_context is enabled
    if cfg.get('auto_context') and board_id is not None:
        from pi_cowork.models import get_auto_context_entries
        entries = get_auto_context_entries(board_id=board_id)
        if entries:
            lines = ["\nKnowledge:"]
            for ke in entries:
                scope = f"Board: {ke['board_name']}" if ke.get('board_id') else "Global"
                preview = (ke['content'] or '')[:200].replace('\n', ' ')
                if len(ke.get('content') or '') > 200:
                    preview += '...'
                lines.append(f"- [{ke['id']}] {ke['title']} ({scope}): {preview}")
            prompt += '\n'.join(lines)
    return prompt


# ---------------------------------------------------------------------------
# Assistant API routes
# ---------------------------------------------------------------------------

@assistant_bp.route('/api/assistant/chat', methods=['POST'])
def api_assistant_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    board_id = data.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        board = _get_board(board_id)
        if not board:
            return jsonify({"error": "board not found"}), 404

    scope = board_id

    with _get_lock(scope):
        cfg = _get_assistant_config()

        if scope is not None:
            run_db(
                "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
                (scope, 'user', message)
            )
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
                (scope,)
            )
        else:
            run_db(
                "INSERT INTO assistant_messages (role, content) VALUES (?, ?)",
                ('user', message)
            )
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id IS NULL ORDER BY created_at, id"
            )

        history_parts = [f"{r['role'].upper()}: {r['content']}" for r in rows]
        context_text = "\n\n".join(history_parts)

        extra_context = []
        if cfg.get('auto_context') and data.get('page_url'):
            extra_context.append(f"Current page context: {data['page_url']}")
        if board_id is not None and board:
            extra_context.append(f"Current board context: {board['name']} (board_id={board_id})")
        if extra_context:
            context_text = "\n\n".join(extra_context + [context_text])

        thinking = cfg.get('thinking')
        model = cfg.get('model')
        work_dir = _assistant_work_dir(scope)
        session_dir = _assistant_session_dir(scope)
        system_prompt = _get_assistant_system_prompt(cfg, board_id=board_id)

        # Stop any existing run for this scope (latest-wins)
        _stop_assistant_run(scope)

        cmd = [
            "pi",
            "--system-prompt", system_prompt,
            "--print",
            "--mode", "json",
            "--session-dir", session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]
        cmd += [context_text]

        proc = subprocess.Popen(
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        q = queue.Queue()
        run = _AssistantRun(proc, scope)
        threading.Thread(target=_reader_thread, args=(proc, q), daemon=True).start()

        with _assistant_runs_lock:
            _ASSISTANT_RUNS[scope] = run

    _app = current_app._get_current_object()

    def _generator():
        last_keepalive = time.monotonic()
        try:
            while True:
                try:
                    event = q.get(timeout=0.5)
                except queue.Empty:
                    if proc.poll() is not None:
                        try:
                            event = q.get(timeout=0.2)
                        except queue.Empty:
                            returncode = proc.wait()
                            stderr_text = proc.stderr.read().strip() if hasattr(proc.stderr, 'read') else ''
                            if run.cancelled:
                                event = {"type": "stopped"}
                            elif returncode != 0:
                                event = {"type": "error", "error": stderr_text or f"exit code {returncode}"}
                            else:
                                event = {"type": "done"}
                    else:
                        now = time.monotonic()
                        if now - last_keepalive >= 25:
                            last_keepalive = now
                            yield ": keepalive\n\n"
                        continue

                if event.get("type") == "_stdout_closed":
                    returncode = proc.wait()
                    stderr_text = proc.stderr.read().strip() if hasattr(proc.stderr, 'read') else ''
                    if run.cancelled:
                        event = {"type": "stopped"}
                    elif returncode != 0:
                        event = {"type": "error", "error": stderr_text or f"exit code {returncode}"}
                    else:
                        event = {"type": "done"}

                if event.get("type") == "text_delta":
                    run.accumulated_text.append(event.get("chunk", ""))
                    yield f"data: {json.dumps(event)}\n\n"
                elif event.get("type") == "thinking_delta":
                    run.accumulated_thinking.append(event.get("chunk", ""))
                    yield f"event: thinking\ndata: {json.dumps(event)}\n\n"
                elif event.get("type") == "toolcall_start":
                    yield f"event: status\ndata: {json.dumps({'type': 'tool_start', 'name': event.get('name', '')})}\n\n"
                elif event.get("type") == "toolcall_end":
                    yield f"event: status\ndata: {json.dumps({'type': 'tool_end', 'name': event.get('name', '')})}\n\n"
                elif event.get("type") == "done":
                    event["full_text"] = "".join(run.accumulated_text)
                    yield f"event: done\ndata: {json.dumps(event)}\n\n"
                    break
                elif event.get("type") == "error":
                    yield f"event: error\ndata: {json.dumps(event)}\n\n"
                    break
                elif event.get("type") == "stopped":
                    event["partial"] = "".join(run.accumulated_text)
                    yield f"event: stopped\ndata: {json.dumps(event)}\n\n"
                    break
        finally:
            if proc.poll() is None:
                try:
                    os.kill(proc.pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass
            full_text = "".join(run.accumulated_text)
            if full_text:
                with _app.app_context():
                    if scope is not None:
                        run_db(
                            "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
                            (scope, "assistant", full_text)
                        )
                    else:
                        run_db(
                            "INSERT INTO assistant_messages (role, content) VALUES (?, ?)",
                            ("assistant", full_text)
                        )
            with _assistant_runs_lock:
                if _ASSISTANT_RUNS.get(scope) is run:
                    del _ASSISTANT_RUNS[scope]

    # In test mode, materialise the generator so side effects (DB writes in
    # finally) run before the test client returns.  Production keeps true
    # streaming.
    if request.environ.get('SERVER_NAME') == 'localhost' or current_app.config.get('TESTING'):
        body = b"".join(chunk.encode("utf-8") for chunk in _generator())
        return Response(body, mimetype="text/event-stream")
    return Response(_generator(), mimetype="text/event-stream")


@assistant_bp.route('/api/assistant/stop', methods=['POST'])
def api_assistant_stop():
    data = request.get_json(silent=True) or {}
    board_id = data.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
    scope = board_id
    stopped = _stop_assistant_run(scope)
    return jsonify({"success": stopped})


@assistant_bp.route('/api/assistant/history', methods=['GET'])
def api_assistant_history():
    board_id = request.args.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        rows = query_db(
            "SELECT id, role, content, created_at FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
            (board_id,)
        )
    else:
        rows = query_db(
            "SELECT id, role, content, created_at FROM assistant_messages WHERE board_id IS NULL ORDER BY created_at, id"
        )
    return jsonify([row_to_dict(r) for r in rows])


@assistant_bp.route('/api/assistant/compact', methods=['POST'])
def api_assistant_compact():
    data = request.get_json(silent=True) or {}
    board_id = data.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        board = _get_board(board_id)
        if not board:
            return jsonify({"error": "board not found"}), 404

    with _get_lock(board_id):
        cfg = _get_assistant_config()
        if board_id is not None:
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
                (board_id,)
            )
        else:
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id IS NULL ORDER BY created_at, id"
            )

        message_count = len(rows)
        if not rows:
            return jsonify({"summary": "", "message_count": 0})

        thinking = cfg.get('thinking')
        model = cfg.get('model')
        work_dir = _assistant_work_dir(board_id)
        session_dir = _assistant_session_dir(board_id)

        cmd = [
            "pi",
            "--mode", "rpc",
            "--print",
            "--session-dir", session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]

        try:
            result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=60, input='{"type":"compact"}')
            if result.returncode != 0:
                return jsonify({"error": result.stderr.strip() or "RPC compact failed"}), 500
            try:
                json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                return jsonify({"error": f"RPC compact returned invalid JSON: {result.stdout.strip()}"}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Compact timed out after 60 seconds."}), 500
        except Exception as e:
            return jsonify({"error": f"Compact failed to run: {e}"}), 500

        if board_id is not None:
            run_db("DELETE FROM assistant_messages WHERE board_id = ?", (board_id,))
        else:
            run_db("DELETE FROM assistant_messages WHERE board_id IS NULL")
        run_db("DELETE FROM settings WHERE key = ?", ('assistant_summary',))

    return jsonify({"summary": "Conversation compacted by pi.", "message_count": message_count})


@assistant_bp.route('/api/assistant/reset', methods=['POST'])
def api_assistant_reset():
    data = request.get_json(silent=True) or {}
    board_id = data.get('board_id')
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        board = _get_board(board_id)
        if not board:
            return jsonify({"error": "board not found"}), 404

    with _get_lock(board_id):
        cfg = _get_assistant_config()
        work_dir = _assistant_work_dir(board_id)
        session_dir = _assistant_session_dir(board_id)
        thinking = cfg.get('thinking')
        model = cfg.get('model')

        cmd = [
            "pi",
            "--mode", "rpc",
            "--print",
            "--session-dir", session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]

        try:
            result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=60, input='{"type":"new_session"}')
            if result.returncode != 0:
                return jsonify({"error": result.stderr.strip() or "RPC reset failed"}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Reset timed out after 60 seconds."}), 500
        except Exception as e:
            return jsonify({"error": f"Reset failed to run: {e}"}), 500

        if board_id is not None:
            run_db("DELETE FROM assistant_messages WHERE board_id = ?", (board_id,))
        else:
            run_db("DELETE FROM assistant_messages WHERE board_id IS NULL")
        run_db("DELETE FROM settings WHERE key = ?", ('assistant_summary',))

    return jsonify({"success": True})


@assistant_bp.route('/api/assistant/config', methods=['GET'])
def api_assistant_config_get():
    cfg = _get_assistant_config()
    return jsonify(cfg)


@assistant_bp.route('/api/assistant/config', methods=['PUT'])
def api_assistant_config_put():
    data = request.get_json(silent=True) or {}
    current = _get_assistant_config()

    thinking = data.get('thinking', current['thinking'])
    # Allow '' or null to clear the override (use pi defaults)
    # Store '' as the 'no override' sentinel (DB has NOT NULL constraint)
    if thinking is None or thinking == '':
        thinking = ''  # sentinel: no override
    elif thinking not in get_thinking_levels():
        return jsonify({"error": "thinking must be one of: off, minimal, low, medium, high, xhigh, or empty to clear"}), 400

    enabled = data.get('enabled')
    if enabled is not None:
        enabled = 1 if enabled else 0
    else:
        enabled = current['enabled']

    auto_context = data.get('auto_context')
    if auto_context is not None:
        auto_context = 1 if auto_context else 0
    else:
        auto_context = current['auto_context']

    model = data.get('model', current['model'])
    if model == '':
        model = None
    if model:
        valid_models = get_model_ids()
        if valid_models and model not in valid_models:
            return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400

    working_directory = data.get('working_directory', current['working_directory'])

    system_prompt = data.get('system_prompt', current['system_prompt'])
    if system_prompt == '':
        system_prompt = None

    api_endpoints = data.get('api_endpoints')
    if api_endpoints is not None:
        if not isinstance(api_endpoints, list):
            return jsonify({"error": "api_endpoints must be a list of endpoint keys or null"}), 400
        invalid = [k for k in api_endpoints if k not in _REGISTRY_MAP]
        if invalid:
            return jsonify({"error": f"Unknown endpoint keys: {', '.join(invalid)}"}), 400
        # Empty list -> default to all (store as NULL)
        api_endpoints_json = json.dumps(api_endpoints) if api_endpoints else None
    else:
        api_endpoints_json = None

    run_db("""
        INSERT INTO assistant_config (id, enabled, model, thinking, working_directory, system_prompt, auto_context, api_endpoints, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            enabled = excluded.enabled,
            model = excluded.model,
            thinking = excluded.thinking,
            working_directory = excluded.working_directory,
            system_prompt = excluded.system_prompt,
            auto_context = excluded.auto_context,
            api_endpoints = excluded.api_endpoints,
            updated_at = excluded.updated_at
    """, (enabled, model, thinking, working_directory, system_prompt, auto_context, api_endpoints_json))
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Saved prompts
# ---------------------------------------------------------------------------

@assistant_bp.route('/api/assistant/saved-prompts', methods=['GET'])
def api_assistant_saved_prompts_list():
    rows = query_db(
        "SELECT id, name, prompt_text, sort_order, created_at FROM assistant_saved_prompts ORDER BY sort_order, created_at"
    )
    return jsonify([row_to_dict(r) for r in rows])


@assistant_bp.route('/api/assistant/saved-prompts', methods=['POST'])
def api_assistant_saved_prompts_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    prompt_text = (data.get('prompt_text') or '').strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not prompt_text:
        return jsonify({"error": "prompt_text is required"}), 400
    sort_order = data.get('sort_order', 0)
    try:
        sort_order = int(sort_order)
    except (ValueError, TypeError):
        sort_order = 0
    try:
        cursor = run_db(
            "INSERT INTO assistant_saved_prompts (name, prompt_text, sort_order) VALUES (?, ?, ?)",
            (name, prompt_text, sort_order)
        )
        return jsonify({"id": cursor.lastrowid, "name": name, "prompt_text": prompt_text, "sort_order": sort_order}), 201
    except Exception as e:
        if 'unique' in str(e).lower():
            return jsonify({"error": "A saved prompt with that name already exists"}), 409
        return jsonify({"error": str(e)}), 500


@assistant_bp.route('/api/assistant/saved-prompts/<int:id>', methods=['PUT'])
def api_assistant_saved_prompts_update(id):
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    prompt_text = (data.get('prompt_text') or '').strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not prompt_text:
        return jsonify({"error": "prompt_text is required"}), 400
    sort_order = data.get('sort_order', 0)
    try:
        sort_order = int(sort_order)
    except (ValueError, TypeError):
        sort_order = 0
    existing = query_db("SELECT id FROM assistant_saved_prompts WHERE id = ?", (id,), one=True)
    if not existing:
        return jsonify({"error": "saved prompt not found"}), 404
    try:
        run_db(
            "UPDATE assistant_saved_prompts SET name = ?, prompt_text = ?, sort_order = ? WHERE id = ?",
            (name, prompt_text, sort_order, id)
        )
        return jsonify({"id": id, "name": name, "prompt_text": prompt_text, "sort_order": sort_order})
    except Exception as e:
        if 'unique' in str(e).lower():
            return jsonify({"error": "A saved prompt with that name already exists"}), 409
        return jsonify({"error": str(e)}), 500


@assistant_bp.route('/api/assistant/saved-prompts/<int:id>', methods=['DELETE'])
def api_assistant_saved_prompts_delete(id):
    existing = query_db("SELECT id FROM assistant_saved_prompts WHERE id = ?", (id,), one=True)
    if not existing:
        return jsonify({"error": "saved prompt not found"}), 404
    run_db("DELETE FROM assistant_saved_prompts WHERE id = ?", (id,))
    return jsonify({"success": True})
