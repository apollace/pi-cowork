"""Assistant: global and per-board chat backed by DB."""

import contextlib
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
from pi_cowork.api.pi_models import get_model_ids, get_thinking_levels
from pi_cowork.api_docs import _REGISTRY_MAP, build_assistant_api_docs
from pi_cowork.db import query_db, row_to_dict, run_db

logger = logging.getLogger(__name__)

assistant_bp = Blueprint("assistant", __name__)

# board_id (None for global) -> threading.Lock
_assistant_locks = {}
_locks_master = threading.Lock()

# Active assistant runs for streaming (latest-wins model)
_ASSISTANT_RUNS = {}
_assistant_runs_lock = threading.Lock()


def _is_pi_process_alive(pid):
    """Check whether *pid* is still a running ``pi`` process.

    Guards against PID recycling by inspecting ``/proc/<pid>/cmdline``.
    """
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return False
    return "pi" in cmdline


class _AssistantRun:
    def __init__(self, proc, scope, run_id, log_path):
        self.proc = proc
        self.scope = scope
        self.run_id = run_id
        self.log_path = log_path
        self.cancelled = False
        self.finalized = False
        self.generator_done = threading.Event()
        self.replay_done = threading.Event()
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
    if proc is None:
        return True
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.kill(proc.pid, signal.SIGTERM)

    def _kill_later():
        time.sleep(timeout)
        try:
            if proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

    threading.Thread(target=_kill_later, daemon=True).start()
    return True


def _normalize_ndjson_event(event):
    """Normalize wrapped pi NDJSON events to flat legacy format.

    Current pi CLI emits nested events:
      {"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"..."}}
      {"type":"agent_end"}

    Legacy format was flat:
      {"type":"text_delta","chunk":"..."}
      {"type":"done"}

    Pass through events that are already in flat format.

    Note: ``agent_end`` (not ``turn_end``) is the true stream terminator.
    The pi CLI may emit multiple ``turn_end`` events during a multi-turn
    tool call, so only ``agent_end`` is mapped to ``done``.
    """
    if not isinstance(event, dict):
        return event

    # Unwrap message_update wrapper
    if event.get("type") == "message_update":
        inner = event.get("assistantMessageEvent") or {}
        if not inner:
            return event
        normalized = dict(inner)
        # Map delta -> chunk for text/thinking deltas
        if inner.get("type") in ("text_delta", "thinking_delta") and "delta" in inner:
            normalized["chunk"] = inner["delta"]
        return normalized

    # Map agent_end -> done (turn_end is NOT the final event)
    if event.get("type") == "agent_end":
        return {"type": "done"}

    return event


def _reader_thread(proc, q, log_path):
    """Read NDJSON lines from proc.stdout and push parsed events to queue.

    Also writes every raw NDJSON line to *log_path* so reconnect can replay.
    After stdout closes, captures stderr and appends it as a ``_stderr`` line
    to the log for diagnostics.
    """
    try:
        with open(log_path, "w", encoding="utf-8") as log_f:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                log_f.write(line + "\n")
                log_f.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Assistant NDJSON parse error: %s", line)
                    continue
                q.put(event)
    finally:
        sentinel = {"type": "_stdout_closed"}
        try:
            with open(log_path, "a", encoding="utf-8") as log_f:
                log_f.write(json.dumps(sentinel) + "\n")
                # Capture stderr for diagnostics (non-fatal if read fails)
                try:
                    stderr_text = proc.stderr.read().strip() if hasattr(proc.stderr, "read") else ""
                except Exception:
                    stderr_text = ""
                if stderr_text:
                    stderr_event = {"type": "_stderr", "text": stderr_text}
                    log_f.write(json.dumps(stderr_event) + "\n")
                log_f.flush()
        except OSError:
            pass
        q.put(sentinel)


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
            "id": 1,
            "enabled": 1,
            "model": None,
            "thinking": None,
            "working_directory": "workspace",
            "system_prompt": None,
            "auto_context": 1,
            "excluded_skill_names": [],
        }
    d = row_to_dict(row)
    # Empty string/thin null means "use pi default" (no override)
    if d.get("model") == "":
        d["model"] = None
    if not d.get("thinking"):
        d["thinking"] = None
    if d.get("system_prompt") == "":
        d["system_prompt"] = None
    # Parse api_endpoints JSON (NULL/empty -> None)
    ep = d.get("api_endpoints")
    if ep:
        try:
            d["api_endpoints"] = json.loads(ep)
        except (ValueError, TypeError):
            d["api_endpoints"] = None
    else:
        d["api_endpoints"] = None
    # Parse excluded_skill_names JSON (NULL/empty -> [])
    ex = d.get("excluded_skill_names")
    if ex:
        try:
            d["excluded_skill_names"] = json.loads(ex)
        except (ValueError, TypeError):
            d["excluded_skill_names"] = []
    else:
        d["excluded_skill_names"] = []
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
            wd = board.get("working_directory")
            if wd:
                path = Path(wd)
                if not path.is_absolute():
                    path = Path(config.PROJECT_ROOT) / path
                return str(path)
    # fallback to global config
    cfg = _get_assistant_config()
    working_directory = cfg.get("working_directory") or "workspace"
    path = Path(working_directory)
    if not path.is_absolute():
        path = Path(config.PROJECT_ROOT) / path
    return str(path)


def _assistant_session_dir(board_id=None):
    work_dir = _assistant_work_dir(board_id)
    if board_id is not None:
        return os.path.join(work_dir, ".pi-sessions", f"assistant-board-{board_id}")
    return os.path.join(work_dir, ".pi-sessions", "assistant-global")


def _get_assistant_system_prompt(cfg, board_id=None):
    base = (cfg.get("system_prompt") or "").strip()
    if not base:
        base = config.DEFAULT_ASSISTANT_SYSTEM_PROMPT
    docs = build_assistant_api_docs(cfg.get("api_endpoints"))
    prompt = f"{base}\n\n{docs}"
    # Inject board-relevant knowledge entries if auto_context is enabled
    if cfg.get("auto_context") and board_id is not None:
        from pi_cowork.models import get_auto_context_entries

        entries = get_auto_context_entries(board_id=board_id)
        if entries:
            lines = ["\nKnowledge:"]
            for ke in entries:
                scope = f"Board: {ke['board_name']}" if ke.get("board_id") else "Global"
                preview = (ke["content"] or "")[:200].replace("\n", " ")
                if len(ke.get("content") or "") > 200:
                    preview += "..."
                lines.append(f"- [{ke['id']}] {ke['title']} ({scope}): {preview}")
            prompt += "\n".join(lines)
    return prompt


def _resolve_board_id(data):
    """Validate and resolve board_id from request data.

    Returns ``(board_id, board, error_response)``.
    ``error_response`` is a Flask ``Response`` tuple when validation fails,
    otherwise ``None``.
    """
    board_id = data.get("board_id")
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return None, None, (jsonify({"error": "board_id must be an integer"}), 400)
        board = _get_board(board_id)
        if not board:
            return None, None, (jsonify({"error": "board not found"}), 404)
        return board_id, board, None
    return None, None, None


def _save_user_message_and_get_history(scope, message):
    """Persist user message and return full conversation history."""
    if scope is not None:
        run_db(
            "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
            (scope, "user", message),
        )
        rows = query_db(
            "SELECT role, content FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
            (scope,),
        )
    else:
        run_db(
            "INSERT INTO assistant_messages (role, content) VALUES (?, ?)",
            ("user", message),
        )
        rows = query_db("SELECT role, content FROM assistant_messages WHERE board_id IS NULL ORDER BY created_at, id")
    return rows


def _build_context_text(message, cfg, data, board_id, board):
    """Assemble the context text sent to the ``pi`` CLI.

    Only the *new* user message is included — pi's native ``--continue``
    session management handles conversation continuity.  The ``assistant_messages``
    DB table is display-only.
    """
    from pi_cowork.skill_packages import (
        get_built_in_skill_names,
        get_global_skill_names,
        read_skill_package,
        resolve_global_or_built_in_skill_dir,
    )

    extra_context = []
    if cfg.get("auto_context") and data.get("page_url"):
        extra_context.append(f"Current page context: {data['page_url']}")
    if board_id is not None and board:
        extra_context.append(f"Current board context: {board['name']} (board_id={board_id})")

    # Skills block
    excluded = set(cfg.get("excluded_skill_names") or [])
    built_in = get_built_in_skill_names()
    global_skills = get_global_skill_names()
    all_skill_names = sorted(set(built_in) | set(global_skills))
    skill_meta_lines = []
    for name in all_skill_names:
        if name in excluded:
            continue
        pkg = read_skill_package(resolve_global_or_built_in_skill_dir(name))
        if pkg:
            skill_meta_lines.append(f"- {pkg['name']}: {pkg.get('description') or 'No description'}")
    if skill_meta_lines:
        extra_context.append("Skills available to you:\n" + "\n".join(skill_meta_lines))

    # Build context: extra context (if any) + the new user message
    parts = extra_context + [message]
    return "\n\n".join(parts)


def _prepare_assistant_skills(session_dir):
    """Copy built-in and global skills to the assistant session directory.

    Returns a list of --skill arguments (pairs of flag + dir) to append to the pi CLI.
    """
    from pi_cowork.skill_packages import (
        copy_skill_to_session,
        get_built_in_skill_names,
        get_global_skill_names,
        resolve_global_or_built_in_skill_dir,
    )

    built_in = get_built_in_skill_names()
    global_skills = get_global_skill_names()
    cfg = _get_assistant_config()
    excluded = set(cfg.get("excluded_skill_names") or [])
    all_skill_names = sorted(set(built_in) | set(global_skills))
    skill_args = []
    for name in all_skill_names:
        if name in excluded:
            continue
        src = resolve_global_or_built_in_skill_dir(name)
        if src and os.path.isdir(src):
            dst = os.path.join(session_dir, "skills", name)
            copy_skill_to_session(src, dst)
            skill_args += ["--skill", dst]
    return skill_args


def _poll_queue_event(proc, q, run, last_keepalive):
    """Get next event from the assistant reader queue.

    Handles keepalive generation when the queue is empty and the process is
    still running.  Returns ``(event, last_keepalive, is_keepalive)``.
    """
    while True:
        try:
            return q.get(timeout=0.5), last_keepalive, False
        except queue.Empty:
            if proc.poll() is not None:
                returncode = proc.wait()
                # stderr may have been consumed by _reader_thread; read from log
                _, _, stderr_text = _reconstruct_text_from_log(run.log_path)
                stderr_text = stderr_text.strip()
                if run.cancelled:
                    event = {"type": "stopped"}
                elif returncode != 0:
                    event = {"type": "error", "error": stderr_text or f"exit code {returncode}"}
                else:
                    event = {"type": "done"}
                return event, last_keepalive, False
            now = time.monotonic()
            if now - last_keepalive >= 25:
                return {"type": "_keepalive"}, now, True


def _process_stdout_closed(proc, run):
    """Wait for the assistant process to finish and return a terminal event."""
    returncode = proc.wait()
    # stderr may have been consumed by _reader_thread; read from log
    _, _, stderr_text = _reconstruct_text_from_log(run.log_path)
    stderr_text = stderr_text.strip()
    if run.cancelled:
        return {"type": "stopped"}
    elif returncode != 0:
        return {"type": "error", "error": stderr_text or f"exit code {returncode}"}
    else:
        return {"type": "done"}


def _yield_for_event(event, run):
    """Return ``(yield_string, should_break)`` for a single assistant event."""
    etype = event.get("type")
    if etype == "text_delta":
        run.accumulated_text.append(event.get("chunk", ""))
        return f"data: {json.dumps(event)}\n\n", False
    elif etype == "thinking_delta":
        run.accumulated_thinking.append(event.get("chunk", ""))
        return f"event: thinking\ndata: {json.dumps(event)}\n\n", False
    elif etype == "toolcall_start":
        payload = json.dumps({"type": "tool_start", "name": event.get("name", "")})
        return f"event: status\ndata: {payload}\n\n", False
    elif etype == "toolcall_end":
        payload = json.dumps({"type": "tool_end", "name": event.get("name", "")})
        return f"event: status\ndata: {payload}\n\n", False
    elif etype == "done":
        event["full_text"] = "".join(run.accumulated_text)
        return f"event: done\ndata: {json.dumps(event)}\n\n", True
    elif etype == "error":
        return f"event: error\ndata: {json.dumps(event)}\n\n", True
    elif etype == "stopped":
        event["partial"] = "".join(run.accumulated_text)
        return f"event: stopped\ndata: {json.dumps(event)}\n\n", True
    return None, False


def _log_has_stdout_closed(log_path):
    """Return True if the assistant log contains the stdout-closed sentinel."""
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "_stdout_closed":
                    return True
    except (FileNotFoundError, OSError):
        pass
    return False


def _reconstruct_text_from_log(log_path):
    """Parse the NDJSON log file and return the complete assistant text.

    Normalises each event via ``_normalize_ndjson_event`` and concatenates
    all ``text_delta`` chunks.  The log file is the source of truth because
    ``_reader_thread`` writes every stdout line regardless of whether the
    SSE generator is still consuming the queue (e.g. after a browser
    disconnect).

    Returns ``(text, thinking, stderr)`` — the concatenated text-delta
    chunks, thinking-delta chunks, and any captured stderr string.
    """
    text_parts = []
    thinking_parts = []
    stderr_text = ""
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "_stderr":
                    stderr_text = event.get("text", "")
                    continue
                event = _normalize_ndjson_event(event)
                etype = event.get("type")
                if etype == "text_delta":
                    text_parts.append(event.get("chunk", ""))
                elif etype == "thinking_delta":
                    thinking_parts.append(event.get("chunk", ""))
    except (FileNotFoundError, OSError):
        pass
    return "".join(text_parts), "".join(thinking_parts), stderr_text


def _finalize_and_save(run, scope, _app):
    """Persist the assistant response and clean up _ASSISTANT_RUNS.

    Idempotent: guarded by ``run.finalized``.

    ``full_text`` is reconstructed from the log file (which always contains
    the complete output) rather than ``run.accumulated_text`` (which is only
    populated while the SSE generator is actively consuming events and may
    be incomplete after a browser disconnect).
    """
    if run.finalized:
        return
    run.finalized = True

    log_text, log_thinking, log_stderr = _reconstruct_text_from_log(run.log_path)
    # Prefer log-file reconstruction (complete); fall back to accumulated_text
    # only when the log file is missing/unreadable but events were consumed.
    full_text = log_text or "".join(run.accumulated_text)
    if run.cancelled:
        status = "stopped"
    elif run.proc is None:
        # Reattached run: infer final state from the log file when PID disappears.
        status = "completed" if _log_has_stdout_closed(run.log_path) else "failed"
    elif run.proc.returncode != 0:
        status = "failed"
    else:
        status = "completed"

    # Diagnostics: warn when the process exited cleanly but produced no text
    # or much less text than thinking (possible early-exit / model issue).
    if status == "completed" and not full_text:
        logger.warning(
            "Assistant run %s completed with empty full_text (thinking=%d chars, stderr=%r)",
            run.run_id,
            len(log_thinking),
            log_stderr[:200],
        )
    elif status == "completed" and full_text and log_thinking and len(full_text) < len(log_thinking) // 10:
        logger.warning(
            "Assistant run %s completed with very short text vs thinking (text=%d chars, thinking=%d chars)",
            run.run_id,
            len(full_text),
            len(log_thinking),
        )
    if log_stderr and status == "failed":
        logger.warning("Assistant run %s failed with stderr: %s", run.run_id, log_stderr[:500])

    with _app.app_context():
        run_db(
            "UPDATE assistant_runs SET status = ?, completed_at = CURRENT_TIMESTAMP, full_text = ? WHERE id = ?",
            (status, full_text, run.run_id),
        )
        if full_text:
            if scope is not None:
                run_db(
                    "INSERT INTO assistant_messages (board_id, role, content) VALUES (?, ?, ?)",
                    (scope, "assistant", full_text),
                )
            else:
                run_db(
                    "INSERT INTO assistant_messages (role, content) VALUES (?, ?)",
                    ("assistant", full_text),
                )

    with _assistant_runs_lock:
        if _ASSISTANT_RUNS.get(scope) is run:
            del _ASSISTANT_RUNS[scope]


def _watcher_thread(proc, run, scope, _app):
    """Wait for the assistant process to exit, then finalize after the generator disconnects."""
    proc.wait()
    run.generator_done.wait()
    _finalize_and_save(run, scope, _app)


def _reattached_watcher_thread(run, scope, pid, _app):
    """Poll a reattached assistant PID until it exits, then finalize.

    Used when a ``running`` DB row survives a server restart or worker change
    and a new request reattaches to the existing process.
    """
    try:
        while _is_pi_process_alive(pid) and not run.cancelled and not run.generator_done.is_set():
            time.sleep(1)
    finally:
        # Give the reconnect stream time to replay the existing log before we
        # finalize from the log file.
        run.replay_done.wait(timeout=5)
        _finalize_and_save(run, scope, _app)
        run.generator_done.set()
        with _assistant_runs_lock:
            if _ASSISTANT_RUNS.get(scope) is run:
                del _ASSISTANT_RUNS[scope]


def _assistant_stream_generator(proc, q, run, scope, _app):
    """SSE generator that yields NDJSON events from the ``pi`` assistant process."""
    last_keepalive = time.monotonic()
    try:
        while True:
            event, last_keepalive, is_keepalive = _poll_queue_event(proc, q, run, last_keepalive)
            if is_keepalive:
                yield ": keepalive\n\n"
                continue

            event = _normalize_ndjson_event(event)

            if event.get("type") == "_stdout_closed":
                event = _process_stdout_closed(proc, run)

            yield_str, should_break = _yield_for_event(event, run)
            if yield_str:
                yield yield_str
            if should_break:
                break
    finally:
        run.generator_done.set()
        # In TESTING mode the generator is consumed synchronously; finalize inline
        # so assertions that follow the POST see the persisted message immediately.
        if proc.poll() is not None or _app.config.get("TESTING"):
            _finalize_and_save(run, scope, _app)


def _event_to_sse(event):
    """Convert a single NDJSON event dict to an SSE frame string, or None."""
    etype = event.get("type")
    if etype == "text_delta":
        return f"data: {json.dumps(event)}\n\n"
    if etype == "thinking_delta":
        return f"event: thinking\ndata: {json.dumps(event)}\n\n"
    if etype == "toolcall_start":
        payload = json.dumps({"type": "tool_start", "name": event.get("name", "")})
        return f"event: status\ndata: {payload}\n\n"
    if etype == "toolcall_end":
        payload = json.dumps({"type": "tool_end", "name": event.get("name", "")})
        return f"event: status\ndata: {payload}\n\n"
    return None


def _read_log_frames(f, skip=0, run=None):
    """Parse NDJSON lines from an open file handle.

    Skips the first *skip* lines, then parses each non-empty line as JSON,
    normalizes it, and converts it to an SSE frame.  Stops when an event
    with ``type == "_stdout_closed"`` is encountered.

    When *run* is provided, text/thinking deltas are accumulated onto the run
    so that a reattached stream (``run.proc is None``) can finalize with the
    correct full_text.  In-memory reconnect runs (``run.proc is not None``)
    already have ``accumulated_text`` from the original generator, so we skip
    accumulation to avoid duplication.

    Returns a tuple ``(lines_consumed, stdout_closed, frames)`` where
    *frames* is a list of SSE frame strings.
    """
    lines_consumed = 0
    stdout_closed = False
    frames = []
    for i, line in enumerate(f):
        if i < skip:
            lines_consumed += 1
            continue
        lines_consumed += 1
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = _normalize_ndjson_event(event)
        # Accumulate only for reattached runs that lost their in-memory state.
        if run is not None and run.proc is None:
            etype = event.get("type")
            if etype == "text_delta":
                run.accumulated_text.append(event.get("chunk", ""))
            elif etype == "thinking_delta":
                run.accumulated_thinking.append(event.get("chunk", ""))
        if event.get("type") == "_stdout_closed":
            stdout_closed = True
            break
        frame = _event_to_sse(event)
        if frame:
            frames.append(frame)
    return lines_consumed, stdout_closed, frames


def _assistant_stream_generator_reconnect(run, scope, _app):
    """SSE generator for reconnecting to an active or recently finished run.

    Replays existing log events, then tails the log file.  Once the run
    disappears from ``_ASSISTANT_RUNS``, queries the DB for final status
    and yields a synthetic terminal event.
    """
    log_path = run.log_path
    last_keepalive = time.monotonic()
    lines_seen = 0
    stdout_closed = False

    # Replay existing log lines
    with open(log_path, encoding="utf-8") as f:
        lines_seen, stdout_closed, frames = _read_log_frames(f, run=run)
    for frame in frames:
        yield frame
    run.replay_done.set()

    # Tail the log while the run is active
    while True:
        with _assistant_runs_lock:
            still_active = _ASSISTANT_RUNS.get(scope) is run
        if not still_active:
            break

        if not stdout_closed:
            with open(log_path, encoding="utf-8") as f:
                lines_seen, stdout_closed, frames = _read_log_frames(f, skip=lines_seen, run=run)
            if frames or stdout_closed:
                for frame in frames:
                    yield frame
                continue

        now = time.monotonic()
        if now - last_keepalive >= 25:
            yield ": keepalive\n\n"
            last_keepalive = now
        time.sleep(0.5)

    # Run is finalized — query DB for terminal status
    with _app.app_context():
        row = query_db(
            "SELECT status, full_text FROM assistant_runs WHERE id = ?",
            (run.run_id,),
            one=True,
        )
    if row:
        status = row["status"]
        full_text = row["full_text"] or ""
        if status == "completed":
            event = {"type": "done", "full_text": full_text}
            yield f"event: done\ndata: {json.dumps(event)}\n\n"
        elif status == "stopped":
            event = {"type": "stopped", "partial": full_text}
            yield f"event: stopped\ndata: {json.dumps(event)}\n\n"
        else:
            event = {"type": "error", "error": "Assistant process failed"}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
    else:
        event = {"type": "error", "error": "Run not found"}
        yield f"event: error\ndata: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Assistant API routes
# ---------------------------------------------------------------------------


@assistant_bp.route("/api/assistant/chat", methods=["POST"])
def api_assistant_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    board_id, board, error = _resolve_board_id(data)
    if error:
        return error

    scope = board_id

    with _get_lock(scope):
        cfg = _get_assistant_config()
        # Persist user message for UI display; pi's --continue handles conversation context
        _save_user_message_and_get_history(scope, message)
        context_text = _build_context_text(message, cfg, data, board_id, board)

        thinking = cfg.get("thinking")
        model = cfg.get("model")
        work_dir = _assistant_work_dir(scope)
        session_dir = _assistant_session_dir(scope)
        system_prompt = _get_assistant_system_prompt(cfg, board_id=board_id)

        # Stop any existing run for this scope (latest-wins)
        _stop_assistant_run(scope)

        skill_args = _prepare_assistant_skills(session_dir)

        # Create log directory and DB row for this run
        log_dir = os.path.join(session_dir, "runs")
        os.makedirs(log_dir, exist_ok=True)

        cmd = [
            "pi",
            "--system-prompt",
            system_prompt,
            "--print",
            "--continue",
            "--mode",
            "json",
            "--session-dir",
            session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]
        cmd += skill_args
        cmd += [context_text]

        proc = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        run_db(
            "INSERT INTO assistant_runs (board_id, status, log_path, pid) VALUES (?, 'running', ?, ?)",
            (scope, "", proc.pid),
        )
        run_id = query_db("SELECT last_insert_rowid() as id", one=True)["id"]
        log_path = os.path.join(log_dir, f"run-{run_id}.log")
        run_db(
            "UPDATE assistant_runs SET log_path = ? WHERE id = ?",
            (log_path, run_id),
        )

        q = queue.Queue()
        run = _AssistantRun(proc, scope, run_id, log_path)
        threading.Thread(target=_reader_thread, args=(proc, q, log_path), daemon=True).start()
        _app = current_app._get_current_object()
        threading.Thread(target=_watcher_thread, args=(proc, run, scope, _app), daemon=True).start()

        with _assistant_runs_lock:
            _ASSISTANT_RUNS[scope] = run

    gen = _assistant_stream_generator(proc, q, run, scope, _app)
    if request.environ.get("SERVER_NAME") == "localhost" or current_app.config.get("TESTING"):
        body = b"".join(chunk.encode("utf-8") for chunk in gen)
        return Response(body, mimetype="text/event-stream")
    return Response(gen, mimetype="text/event-stream")


@assistant_bp.route("/api/assistant/stop", methods=["POST"])
def api_assistant_stop():
    data = request.get_json(silent=True) or {}
    board_id = data.get("board_id")
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
    scope = board_id
    stopped = _stop_assistant_run(scope)
    return jsonify({"success": stopped})


@assistant_bp.route("/api/assistant/active-run", methods=["GET"])
def api_assistant_active_run():
    board_id = request.args.get("board_id")
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
    scope = board_id
    row = query_db(
        "SELECT id, status, started_at"
        " FROM assistant_runs WHERE board_id IS ? AND status = 'running'"
        " ORDER BY started_at DESC LIMIT 1",
        (scope,),
        one=True,
    )
    if not row:
        return jsonify(None)
    return jsonify(row_to_dict(row))


@assistant_bp.route("/api/assistant/stream", methods=["GET"])
def api_assistant_stream():
    board_id = request.args.get("board_id")
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
    scope = board_id

    run_id = request.args.get("run_id")
    if run_id is None:
        return jsonify({"error": "run_id is required"}), 400
    try:
        run_id = int(run_id)
    except (ValueError, TypeError):
        return jsonify({"error": "run_id must be an integer"}), 400

    # Look up the run row
    row = query_db(
        "SELECT id, board_id, status, log_path, pid, started_at, full_text FROM assistant_runs WHERE id = ?",
        (run_id,),
        one=True,
    )
    if not row:
        # Run not found — yield synthetic error immediately
        def _not_found_gen():
            event = {"type": "error", "error": "Run not found"}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"

        return Response(_not_found_gen(), mimetype="text/event-stream")

    # Validate scope matches
    if row["board_id"] != scope:
        return jsonify({"error": "scope mismatch"}), 403

    # Check if there's an active in-memory run object
    with _assistant_runs_lock:
        active_run = _ASSISTANT_RUNS.get(scope)

    _app = current_app._get_current_object()

    if active_run and active_run.run_id == run_id:
        gen = _assistant_stream_generator_reconnect(active_run, scope, _app)
    elif not active_run and row["status"] == "running" and _is_pi_process_alive(row["pid"]):
        # The in-memory run state is gone (server restart, different worker) but
        # the pi process is still alive. Reattach and stream from the existing log.
        run = _AssistantRun(None, scope, run_id, row["log_path"])
        threading.Thread(
            target=_reattached_watcher_thread,
            args=(run, scope, row["pid"], _app),
            daemon=True,
        ).start()
        with _assistant_runs_lock:
            _ASSISTANT_RUNS[scope] = run
        gen = _assistant_stream_generator_reconnect(run, scope, _app)
    else:
        # Already finalized — yield synthetic terminal event based on DB status
        def _finalized_gen():
            status = row["status"]
            full_text = row["full_text"] or ""
            if status == "completed":
                event = {"type": "done", "full_text": full_text}
                yield f"event: done\ndata: {json.dumps(event)}\n\n"
            elif status == "stopped":
                event = {"type": "stopped", "partial": full_text}
                yield f"event: stopped\ndata: {json.dumps(event)}\n\n"
            else:
                event = {"type": "error", "error": "Assistant process failed"}
                yield f"event: error\ndata: {json.dumps(event)}\n\n"

        return Response(_finalized_gen(), mimetype="text/event-stream")

    if request.environ.get("SERVER_NAME") == "localhost" or current_app.config.get("TESTING"):
        body = b"".join(chunk.encode("utf-8") for chunk in gen)
        return Response(body, mimetype="text/event-stream")
    return Response(gen, mimetype="text/event-stream")


@assistant_bp.route("/api/assistant/history", methods=["GET"])
def api_assistant_history():
    board_id = request.args.get("board_id")
    if board_id is not None:
        try:
            board_id = int(board_id)
        except (ValueError, TypeError):
            return jsonify({"error": "board_id must be an integer"}), 400
        rows = query_db(
            "SELECT id, role, content, created_at FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id",
            (board_id,),
        )
    else:
        rows = query_db(
            "SELECT id, role, content, created_at FROM assistant_messages"
            " WHERE board_id IS NULL ORDER BY created_at, id"
        )
    return jsonify([row_to_dict(r) for r in rows])


@assistant_bp.route("/api/assistant/compact", methods=["POST"])
def api_assistant_compact():
    data = request.get_json(silent=True) or {}
    board_id = data.get("board_id")
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
                "SELECT role, content FROM assistant_messages WHERE board_id = ? ORDER BY created_at, id", (board_id,)
            )
        else:
            rows = query_db(
                "SELECT role, content FROM assistant_messages WHERE board_id IS NULL ORDER BY created_at, id"
            )

        message_count = len(rows)
        if not rows:
            return jsonify({"summary": "", "message_count": 0})

        thinking = cfg.get("thinking")
        model = cfg.get("model")
        work_dir = _assistant_work_dir(board_id)
        session_dir = _assistant_session_dir(board_id)

        cmd = [
            "pi",
            "--mode",
            "rpc",
            "--print",
            "--continue",
            "--session-dir",
            session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]

        try:
            result = subprocess.run(  # noqa: S603
                cmd, cwd=work_dir, capture_output=True, text=True, timeout=60, input='{"type":"compact"}'
            )
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

        # Clean up assistant_runs and their log files for this scope
        run_rows = query_db(
            "SELECT log_path FROM assistant_runs WHERE board_id IS ?",
            (board_id,),
        )
        for r in run_rows:
            lp = r["log_path"]
            if lp and os.path.exists(lp):
                with contextlib.suppress(OSError):
                    os.unlink(lp)
        if board_id is not None:
            run_db("DELETE FROM assistant_messages WHERE board_id = ?", (board_id,))
            run_db("DELETE FROM assistant_runs WHERE board_id = ?", (board_id,))
        else:
            run_db("DELETE FROM assistant_messages WHERE board_id IS NULL")
            run_db("DELETE FROM assistant_runs WHERE board_id IS NULL")
        run_db("DELETE FROM settings WHERE key = ?", ("assistant_summary",))

    return jsonify({"summary": "Conversation compacted by pi.", "message_count": message_count})


@assistant_bp.route("/api/assistant/reset", methods=["POST"])
def api_assistant_reset():
    data = request.get_json(silent=True) or {}
    board_id = data.get("board_id")
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
        thinking = cfg.get("thinking")
        model = cfg.get("model")

        cmd = [
            "pi",
            "--mode",
            "rpc",
            "--print",
            "--continue",
            "--session-dir",
            session_dir,
        ]
        if thinking:
            cmd += ["--thinking", thinking]
        if model:
            cmd += ["--model", model]

        try:
            result = subprocess.run(  # noqa: S603
                cmd, cwd=work_dir, capture_output=True, text=True, timeout=60, input='{"type":"new_session"}'
            )
            if result.returncode != 0:
                return jsonify({"error": result.stderr.strip() or "RPC reset failed"}), 500
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Reset timed out after 60 seconds."}), 500
        except Exception as e:
            return jsonify({"error": f"Reset failed to run: {e}"}), 500

        # Clean up assistant_runs and their log files for this scope
        run_rows = query_db(
            "SELECT log_path FROM assistant_runs WHERE board_id IS ?",
            (board_id,),
        )
        for r in run_rows:
            lp = r["log_path"]
            if lp and os.path.exists(lp):
                with contextlib.suppress(OSError):
                    os.unlink(lp)
        if board_id is not None:
            run_db("DELETE FROM assistant_messages WHERE board_id = ?", (board_id,))
            run_db("DELETE FROM assistant_runs WHERE board_id = ?", (board_id,))
        else:
            run_db("DELETE FROM assistant_messages WHERE board_id IS NULL")
            run_db("DELETE FROM assistant_runs WHERE board_id IS NULL")
        run_db("DELETE FROM settings WHERE key = ?", ("assistant_summary",))

    return jsonify({"success": True})


@assistant_bp.route("/api/assistant/config", methods=["GET"])
def api_assistant_config_get():
    cfg = _get_assistant_config()
    return jsonify(cfg)


@assistant_bp.route("/api/assistant/config", methods=["PUT"])
def api_assistant_config_put():
    data = request.get_json(silent=True) or {}
    current = _get_assistant_config()

    thinking = data.get("thinking", current["thinking"])
    # Allow '' or null to clear the override (use pi defaults)
    # Store '' as the 'no override' sentinel (DB has NOT NULL constraint)
    if thinking is None or thinking == "":
        thinking = ""  # sentinel: no override
    elif thinking not in get_thinking_levels():
        return jsonify(
            {"error": "thinking must be one of: off, minimal, low, medium, high, xhigh, or empty to clear"}
        ), 400

    enabled = data.get("enabled")
    enabled = (1 if enabled else 0) if enabled is not None else current["enabled"]

    auto_context = data.get("auto_context")
    auto_context = (1 if auto_context else 0) if auto_context is not None else current["auto_context"]

    model = data.get("model", current["model"])
    if model == "":
        model = None
    if model:
        valid_models = get_model_ids()
        if valid_models and model not in valid_models:
            return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400

    working_directory = data.get("working_directory", current["working_directory"])

    system_prompt = data.get("system_prompt", current["system_prompt"])
    if system_prompt == "":
        system_prompt = None

    api_endpoints = data.get("api_endpoints")
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

    excluded_skill_names = data.get("excluded_skill_names")
    if excluded_skill_names is not None:
        if not isinstance(excluded_skill_names, list):
            return jsonify({"error": "excluded_skill_names must be a list of strings or null"}), 400
        cleaned = [str(n).strip() for n in excluded_skill_names if str(n).strip()]
        excluded_skill_names_json = json.dumps(cleaned)
    else:
        excluded_skill_names_json = current.get("excluded_skill_names")
        if isinstance(excluded_skill_names_json, list):
            excluded_skill_names_json = json.dumps(excluded_skill_names_json)

    run_db(
        """
        INSERT INTO assistant_config (
            id, enabled, model, thinking, working_directory,
            system_prompt, auto_context, api_endpoints,
            excluded_skill_names, updated_at
        )
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            enabled = excluded.enabled,
            model = excluded.model,
            thinking = excluded.thinking,
            working_directory = excluded.working_directory,
            system_prompt = excluded.system_prompt,
            auto_context = excluded.auto_context,
            api_endpoints = excluded.api_endpoints,
            excluded_skill_names = excluded.excluded_skill_names,
            updated_at = excluded.updated_at
    """,
        (
            enabled,
            model,
            thinking,
            working_directory,
            system_prompt,
            auto_context,
            api_endpoints_json,
            excluded_skill_names_json,
        ),
    )
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Saved prompts
# ---------------------------------------------------------------------------


@assistant_bp.route("/api/assistant/saved-prompts", methods=["GET"])
def api_assistant_saved_prompts_list():
    rows = query_db(
        "SELECT id, name, prompt_text, sort_order, created_at"
        " FROM assistant_saved_prompts ORDER BY sort_order, created_at"
    )
    return jsonify([row_to_dict(r) for r in rows])


@assistant_bp.route("/api/assistant/saved-prompts", methods=["POST"])
def api_assistant_saved_prompts_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    prompt_text = (data.get("prompt_text") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not prompt_text:
        return jsonify({"error": "prompt_text is required"}), 400
    sort_order = data.get("sort_order", 0)
    try:
        sort_order = int(sort_order)
    except (ValueError, TypeError):
        sort_order = 0
    try:
        cursor = run_db(
            "INSERT INTO assistant_saved_prompts (name, prompt_text, sort_order) VALUES (?, ?, ?)",
            (name, prompt_text, sort_order),
        )
        return jsonify(
            {"id": cursor.lastrowid, "name": name, "prompt_text": prompt_text, "sort_order": sort_order}
        ), 201
    except Exception as e:
        if "unique" in str(e).lower():
            return jsonify({"error": "A saved prompt with that name already exists"}), 409
        return jsonify({"error": str(e)}), 500


@assistant_bp.route("/api/assistant/saved-prompts/<int:id>", methods=["PUT"])
def api_assistant_saved_prompts_update(id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    prompt_text = (data.get("prompt_text") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not prompt_text:
        return jsonify({"error": "prompt_text is required"}), 400
    sort_order = data.get("sort_order", 0)
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
            (name, prompt_text, sort_order, id),
        )
        return jsonify({"id": id, "name": name, "prompt_text": prompt_text, "sort_order": sort_order})
    except Exception as e:
        if "unique" in str(e).lower():
            return jsonify({"error": "A saved prompt with that name already exists"}), 409
        return jsonify({"error": str(e)}), 500


@assistant_bp.route("/api/assistant/saved-prompts/<int:id>", methods=["DELETE"])
def api_assistant_saved_prompts_delete(id):
    existing = query_db("SELECT id FROM assistant_saved_prompts WHERE id = ?", (id,), one=True)
    if not existing:
        return jsonify({"error": "saved prompt not found"}), 404
    run_db("DELETE FROM assistant_saved_prompts WHERE id = ?", (id,))
    return jsonify({"success": True})
