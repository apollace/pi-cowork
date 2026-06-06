"""Centralised system logging service.

Provides functions to add, query, filter, paginate, export, and rotate logs
stored in the ``system_logs`` database table.

Log levels: INFO, WARNING, ERROR, CRITICAL
Action types: http_request, db_change, agent_event

Note on ``ticket_id``: the column has no foreign-key constraint intentionally
so that log entries survive ticket deletion (audit integrity).
"""

import contextlib
import json
import logging
import os
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta

from pi_cowork import config
from pi_cowork.config import get_config

logger = logging.getLogger(__name__)

VALID_LEVELS = ("INFO", "WARNING", "ERROR", "CRITICAL")
VALID_ACTION_TYPES = ("http_request", "db_change", "agent_event")

# Maximum body size stored in details JSON (characters, not bytes)
MAX_BODY_SIZE = 10240  # 10 KB worth of characters

# Field names whose values should be redacted from logged request/response bodies
_SENSITIVE_KEY_NAMES = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth",
    "authorization",
    "cookie",
    "session_id",
    "private_key",
)
# Build alternation pattern for use in regexes
_KEY_ALT = "|".join(re.escape(k) for k in _SENSITIVE_KEY_NAMES)


def _truncate(text, max_len=MAX_BODY_SIZE):
    """Truncate text to max_len characters, appending '…[truncated]' if cut."""
    if text is None:
        return None
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…[truncated]"


def _redact_sensitive(text):
    """Redact values of sensitive fields in a JSON-ish string.

    Attempts to match common key-value patterns like ``"password": "xxx"``
    or ``password=xxx`` and replaces the value with ``[REDACTED]``.
    """
    if text is None:
        return None
    # JSON-style:  "key": "value"  or  "key": value
    text = re.sub(
        r'("(' + _KEY_ALT + r')"\s*:\s*)"[^"]*"',
        r'\1"[REDACTED]"',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r'("(' + _KEY_ALT + r')"\s*:\s*)(-?\d+\.?\d*|true|false|null)',
        r'\1"[REDACTED]"',
        text,
        flags=re.IGNORECASE,
    )
    # Form-style:  key=value&
    text = re.sub(
        r"(" + _KEY_ALT + r")=([^&\s]+)",
        r"\1=[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _escape_like(text):
    """Escape SQL LIKE wildcards (% and _) in user-supplied search text."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _get_standalone_db():
    """Get a standalone DB connection (for use outside Flask request context)."""
    path = os.environ.get("DATABASE", config.DATABASE)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def add_log(level, action_type, message, details=None, ticket_id=None):
    """Insert a system log entry.

    Safe to call from any context (Flask request or background thread).
    If called outside a Flask request context, uses a standalone DB connection.
    Failures are logged to the Python logger but never raise to the caller.
    """
    if level not in VALID_LEVELS:
        logger.warning("Invalid log level %r, defaulting to INFO", level)
        level = "INFO"
    if action_type not in VALID_ACTION_TYPES:
        logger.warning("Invalid action_type %r, defaulting to 'db_change'", action_type)
        action_type = "db_change"

    timestamp = datetime.now(UTC).isoformat()
    details_json = None
    if details is not None:
        details_json = json.dumps(details, default=str)

    # Try to use Flask's g._database if available
    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, "
                "details, ticket_id) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, level, action_type, message, details_json, ticket_id),
            )
            db.commit()
            return
    except Exception:
        logger.exception("system_logs.add_log failed via Flask DB connection, falling back to standalone")

    # Fallback: standalone connection (e.g., background thread or test)
    try:
        conn = _get_standalone_db()
        try:
            conn.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, "
                "details, ticket_id) VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, level, action_type, message, details_json, ticket_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("system_logs.add_log failed (standalone connection)")


def get_system_log(log_id):
    """Return a single system log entry by ID, or ``None`` if not found.

    Works inside or outside a Flask app context.
    """
    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            use_flask = True
            db = get_db()
        else:
            use_flask = False
    except (ImportError, RuntimeError):
        use_flask = False

    if not use_flask:
        db = _get_standalone_db()

    try:
        row = db.execute("SELECT * FROM system_logs WHERE id = ?", (log_id,)).fetchone()
        if row is None:
            return None
        d = dict(zip(row.keys(), row, strict=False))
        if d.get("details"):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d["details"] = json.loads(d["details"])
        return d
    finally:
        if not use_flask:
            db.close()


def get_system_logs(  # noqa: C901
    page=1,
    per_page=50,
    level=None,
    action_type=None,
    ticket_id=None,
    date_from=None,
    date_to=None,
    search=None,
    include_details=False,
):
    """Query system logs with pagination and filtering.

    Returns a dict: {logs, total, page, per_page, total_pages}

    When ``include_details`` is False (the default), the ``details`` column
    is excluded from the query and replaced with a ``has_details`` boolean
    (0/1 from SQLite). This avoids fetching, parsing, and serialising
    potentially large JSON blobs for list views that only need a preview
    indicator.  Callers that need full details (e.g. the export function)
    should pass ``include_details=True``.

    The ``where`` clause fragments are built from a fixed set of
    whitelisted conditions — user input never appears raw in the SQL.
    """
    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            use_flask = True
            db = get_db()
        else:
            use_flask = False
    except (ImportError, RuntimeError):
        use_flask = False

    if not use_flask:
        db = _get_standalone_db()

    try:
        conditions = []
        params = []

        if level:
            conditions.append("level = ?")
            params.append(level)
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if ticket_id:
            conditions.append("ticket_id = ?")
            params.append(int(ticket_id))
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)
        if search:
            conditions.append("message LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(search)}%")

        # where clause is assembled only from whitelisted fragments above
        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        # Total count
        count_row = db.execute(f"SELECT COUNT(*) as cnt FROM system_logs {where}", tuple(params)).fetchone()  # noqa: S608
        total = count_row["cnt"] if count_row else 0

        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        if include_details:
            select_sql = "SELECT * FROM system_logs"
        else:
            select_sql = (
                "SELECT id, timestamp, level, action_type, message, ticket_id, "
                "CASE WHEN details IS NOT NULL THEN 1 ELSE 0 END AS has_details "
                "FROM system_logs"
            )

        rows = db.execute(
            f"{select_sql} {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?", (*tuple(params), per_page, offset)
        ).fetchall()

        logs = []
        for row in rows:
            d = dict(zip(row.keys(), row, strict=False))
            if include_details:
                if d.get("details"):
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        d["details"] = json.loads(d["details"])
            else:
                # Convert SQLite integer 0/1 to Python boolean
                d["has_details"] = bool(d.get("has_details", 0))
            logs.append(d)

        return {
            "logs": logs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    finally:
        if not use_flask:
            db.close()


def cleanup_old_logs(max_age_days=None):
    """Delete log entries older than max_age_days.

    Called periodically from the drain loop. Retention priority:
    1. Explicit max_age_days argument
    2. DB settings table (log_retention_days key)
    3. PI_LOG_RETENTION_DAYS environment variable
    4. Default of 30 days
    """
    if max_age_days is None:
        max_age_days = get_config("log_retention_days")
        if max_age_days is None:
            max_age_days = 30

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            db = get_db()
            cur = db.execute("DELETE FROM system_logs WHERE timestamp < ?", (cutoff,))
            db.commit()
            deleted = cur.rowcount
        else:
            raise RuntimeError("No app context")
    except (ImportError, RuntimeError):
        conn = _get_standalone_db()
        try:
            cur = conn.execute("DELETE FROM system_logs WHERE timestamp < ?", (cutoff,))
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()

    if deleted:
        logger.info("Log rotation: deleted %d entries older than %d days", deleted, max_age_days)
    return deleted


def export_logs_text(
    page=1, per_page=50, level=None, action_type=None, ticket_id=None, date_from=None, date_to=None, search=None
):
    """Export filtered logs as plain text.

    Returns a plain-text string suitable for download.
    """
    result = get_system_logs(
        page=page,
        per_page=per_page,
        level=level,
        action_type=action_type,
        ticket_id=ticket_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        include_details=True,
    )

    lines = []
    for log in result["logs"]:
        ts = log.get("timestamp", "")
        lvl = log.get("level", "")
        at = log.get("action_type", "")
        msg = log.get("message", "")
        tid = log.get("ticket_id")
        details = log.get("details")

        line = f"[{ts}] {lvl} [{at}] {msg}"
        if tid:
            line += f" (ticket #{tid})"
        if details:
            if isinstance(details, dict):
                detail_parts = []
                for k, v in details.items():
                    detail_parts.append(f"{k}={v}")
                line += " | " + " ".join(detail_parts)
            else:
                line += f" | {details}"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP request logging middleware
# ---------------------------------------------------------------------------

# Paths to skip to avoid recursion and noise
_SKIP_PATHS = ("/api/system_logs", "/api/notifications", "/static/")
_SKIP_METHODS = ("GET", "HEAD", "OPTIONS")

# Slow request threshold (seconds)
SLOW_REQUEST_THRESHOLD = 1.0


def record_request_start_time():
    """Flask before_request hook to store request start time."""
    from flask import g

    g._request_start_time = time.monotonic()


def _should_skip_path(path):
    """Check if a request path should be skipped for logging."""
    return any(path.startswith(skip) for skip in _SKIP_PATHS)


def log_http_request(response):
    """Flask after_request hook to log POST/PUT/DELETE requests and slow requests.

    For all HTTP methods, checks if the request took longer than
    SLOW_REQUEST_THRESHOLD seconds and logs a WARNING if so.

    For POST/PUT/DELETE (non-skip methods), also logs an INFO-level
    audit record with request/response details.

    Skips streaming responses (e.g. SSE event streams) to avoid consuming
    the stream body into memory.  Skips GET/HEAD/OPTIONS for the audit
    log (read operations are intentionally not audited), but still
    checks them for slow-request detection.
    """
    try:
        from flask import g
        from flask import request as flask_request
    except RuntimeError:
        return response

    path = flask_request.path

    # Skip certain paths entirely (recursion, noise)
    if _should_skip_path(path):
        return response

    # --- Slow request detection (all HTTP methods) ---
    start_time = getattr(g, "_request_start_time", None)
    if start_time is not None:
        elapsed = time.monotonic() - start_time
        if elapsed > SLOW_REQUEST_THRESHOLD:
            status_code = response.status_code
            slow_message = f"SLOW API: {flask_request.method} {path} → {status_code} took {elapsed:.2f}s"
            slow_details = {
                "method": flask_request.method,
                "url": flask_request.url,
                "status_code": status_code,
                "elapsed_seconds": round(elapsed, 2),
            }
            # Try to extract ticket_id from URL pattern
            ticket_id = None
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "tickets":
                with contextlib.suppress(ValueError, IndexError):
                    ticket_id = int(parts[2])
            add_log("WARNING", "http_request", slow_message, details=slow_details, ticket_id=ticket_id)

    # --- Audit log (POST/PUT/DELETE only) ---
    if flask_request.method in _SKIP_METHODS:
        return response

    # Skip streaming responses — calling get_data() on them could hang or
    # consume the entire stream into memory (e.g. SSE agent-run streams)
    if response.is_streamed:
        return response

    # Determine level from status code
    status_code = response.status_code
    if status_code < 400:
        level = "INFO"
    elif status_code < 500:
        level = "WARNING"
    else:
        level = "ERROR"

    # Build details
    details = {
        "method": flask_request.method,
        "url": flask_request.url,
        "status_code": status_code,
    }

    # Capture request body (truncated & redacted)
    try:
        req_body = flask_request.get_data(as_text=True)
        details["request_body"] = _truncate(_redact_sensitive(req_body))
    except Exception:
        details["request_body"] = None

    # Capture response body (truncated & redacted)
    # Safe to call because we already checked response.is_streamed is False
    try:
        resp_body = response.get_data(as_text=True)
        details["response_body"] = _truncate(_redact_sensitive(resp_body))
    except Exception:
        details["response_body"] = None

    message = f"{flask_request.method} {path} → {status_code}"

    # Try to extract ticket_id from URL pattern /api/tickets/<id>/...
    ticket_id = None
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "tickets":
        with contextlib.suppress(ValueError, IndexError):
            ticket_id = int(parts[2])

    add_log(level, "http_request", message, details=details, ticket_id=ticket_id)

    return response


# ---------------------------------------------------------------------------
# Agent event logging — bus subscribers
# ---------------------------------------------------------------------------


def _agent_spawned_subscriber(event_name=None, **kwargs):
    ticket_id = kwargs.get("ticket_id")
    agent_name = kwargs.get("agent_name", "Unknown")
    run_id = kwargs.get("run_id")
    add_log(
        "INFO",
        "agent_event",
        f"Agent '{agent_name}' started for ticket #{ticket_id}",
        details={"agent_name": agent_name, "run_id": run_id},
        ticket_id=ticket_id,
    )


def _agent_completed_subscriber(event_name=None, **kwargs):
    ticket_id = kwargs.get("ticket_id")
    agent_name = kwargs.get("agent_name", "Unknown")
    run_id = kwargs.get("run_id")
    add_log(
        "INFO",
        "agent_event",
        f"Agent '{agent_name}' completed for ticket #{ticket_id}",
        details={"agent_name": agent_name, "run_id": run_id, "exit_code": 0},
        ticket_id=ticket_id,
    )


def _agent_failed_subscriber(event_name=None, **kwargs):
    ticket_id = kwargs.get("ticket_id")
    agent_name = kwargs.get("agent_name", "Unknown")
    run_id = kwargs.get("run_id")
    exit_code = kwargs.get("exit_code")
    add_log(
        "ERROR",
        "agent_event",
        f"Agent '{agent_name}' failed for ticket #{ticket_id}",
        details={"agent_name": agent_name, "run_id": run_id, "exit_code": exit_code, "error": f"exit_code={exit_code}"},
        ticket_id=ticket_id,
    )


def register_system_log_subscribers():
    """Register event bus subscribers for agent events."""
    from pi_cowork.events import AGENT_COMPLETED, AGENT_FAILED, AGENT_SPAWNED, bus

    bus.subscribe(AGENT_SPAWNED, _agent_spawned_subscriber)
    bus.subscribe(AGENT_COMPLETED, _agent_completed_subscriber)
    bus.subscribe(AGENT_FAILED, _agent_failed_subscriber)
