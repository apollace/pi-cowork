"""Assistant: global and per-board chat backed by DB."""

import json
import logging
import os
import subprocess
import threading
from pathlib import Path

from flask import Blueprint, jsonify, request

from pi_cowork import config
from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.api.pi_models import get_model_ids
from pi_cowork.api_docs import build_assistant_api_docs, _REGISTRY_MAP

logger = logging.getLogger(__name__)

assistant_bp = Blueprint('assistant', __name__)

# board_id (None for global) -> threading.Lock
_assistant_locks = {}
_locks_master = threading.Lock()


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


def _get_assistant_system_prompt(cfg):
    base = (cfg.get('system_prompt') or '').strip()
    if not base:
        base = config.DEFAULT_ASSISTANT_SYSTEM_PROMPT
    docs = build_assistant_api_docs(cfg.get('api_endpoints'))
    return f"{base}\n\n{docs}"


# ---------------------------------------------------------------------------
# Assistant API routes
# ---------------------------------------------------------------------------

@assistant_bp.route('/api/assistant/chat', methods=['POST'])
def api_assistant_chat():
    from flask import current_app
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

    with _get_lock(board_id):
        cfg = _get_assistant_config()

        if board_id is not None:
            run_db(
                "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
                (board_id, 'user', message)
            )
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
                (board_id,)
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
        work_dir = _assistant_work_dir(board_id)
        session_dir = _assistant_session_dir(board_id)
        system_prompt = _get_assistant_system_prompt(cfg)

        cmd = [
            "pi",
            "--system-prompt", system_prompt,
            "--print",
            "--session-dir", session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]
        cmd += [context_text]

        try:
            result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True, timeout=300)
            response_text = result.stdout.strip()
            if not response_text and result.returncode != 0:
                response_text = f"Assistant error (exit code {result.returncode}): {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            response_text = "Assistant timed out after 300 seconds."
        except Exception as e:
            response_text = f"Assistant failed to run: {e}"

        if board_id is not None:
            run_db(
                "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
                (board_id, 'assistant', response_text)
            )
        else:
            run_db(
                "INSERT INTO assistant_messages (role, content) VALUES (?, ?)",
                ('assistant', response_text)
            )

    return jsonify({"response": response_text})


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
    # any non-empty string is accepted

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
