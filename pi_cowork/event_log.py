"""Event log rotation / cleanup service.

Provides ``cleanup_old_event_logs()`` to delete rows from the ``event_log``
table that are older than a configurable retention period.  Mirrors the
pattern established by ``pi_cowork.system_logs.cleanup_old_logs()``.

Retention priority:
1. Explicit ``max_age_days`` argument
2. DB settings table (``event_log_retention_days`` key)
3. ``PI_EVENT_LOG_RETENTION_DAYS`` environment variable
4. Default of 30 days
"""

import logging
import os
import sqlite3
from datetime import UTC, datetime, timedelta

from pi_cowork.config import get_config

logger = logging.getLogger(__name__)


def _get_standalone_db():
    """Get a standalone DB connection (for use outside Flask request context)."""
    from pi_cowork import config

    path = os.environ.get("DATABASE", config.DATABASE)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cleanup_old_event_logs(max_age_days=None):
    """Delete ``event_log`` rows older than *max_age_days*.

    Called periodically from the drain loop.  Works inside and outside a
    Flask application context.

    Returns the number of rows deleted.
    """
    if max_age_days is None:
        max_age_days = get_config("event_log_retention_days")
        if max_age_days is None:
            max_age_days = 30

    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()

    try:
        from flask import has_app_context

        if has_app_context():
            from pi_cowork.db import get_db

            db = get_db()
            cur = db.execute("DELETE FROM event_log WHERE created_at < ?", (cutoff,))
            db.commit()
            deleted = cur.rowcount
        else:
            raise RuntimeError("No app context")
    except (ImportError, RuntimeError):
        conn = _get_standalone_db()
        try:
            cur = conn.execute("DELETE FROM event_log WHERE created_at < ?", (cutoff,))
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()

    if deleted:
        logger.info("Event log rotation: deleted %d entries older than %d days", deleted, max_age_days)
    return deleted
