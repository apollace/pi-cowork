"""Application configuration.

Dynamic configuration values are read from DB settings first, then env vars,
then hardcoded defaults via ``get_config()``. Module-level constants
(DATABASE, PROJECT_ROOT, etc.) remain static.

Tests may monkeypatch module-level values; code that needs live config
should use ``get_config()`` for the dynamic settings.
"""

import os
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

DATABASE = os.path.join(PROJECT_ROOT, "pi-cowork.db")

# ── Static defaults (used by get_config when no DB or env override) ──
DEFAULTS = {
    "pi_cowork_url": "http://localhost:5000",
    "port": "5000",
    "max_parallel": "1",
    "max_per_hour": "100",
    "warm_spawn_threshold": "3600",
    "run_max_age": "7200",
    "log_retention_days": "30",
    "event_log_retention_days": "30",
    "db_backup_max_count": "10",
    "notification_dismissal_retention_days": "7",
}

# ── Mapping: config key → env var name ──
ENV_MAP = {
    "pi_cowork_url": "PI_COWORK_URL",
    "port": "PI_PORT",
    "max_parallel": "PI_MAX_PARALLEL",
    "max_per_hour": "PI_MAX_PER_HOUR",
    "log_retention_days": "PI_LOG_RETENTION_DAYS",
    "event_log_retention_days": "PI_EVENT_LOG_RETENTION_DAYS",
    "notification_dismissal_retention_days": "PI_NOTIFICATION_DISMISSAL_RETENTION_DAYS",
}

# ── Type coercion for numeric settings ──
_INT_KEYS = {
    "port",
    "max_parallel",
    "max_per_hour",
    "warm_spawn_threshold",
    "run_max_age",
    "log_retention_days",
    "event_log_retention_days",
    "db_backup_max_count",
    "notification_dismissal_retention_days",
}


def get_config(key):
    """Resolve a configuration value with precedence: DB > env var > default.

    Returns the value as int for numeric keys, str otherwise.
    If a numeric key has a non-numeric DB value, falls back to env/default.
    This function is safe to call outside a Flask request context
    (falls back to env/default).
    """
    # 1. Try DB settings table
    db_value = None
    try:
        from pi_cowork.models import get_setting

        db_value = get_setting(key)
    except Exception:
        pass

    if db_value is not None:
        if key in _INT_KEYS:
            try:
                return int(db_value)
            except (ValueError, TypeError):
                pass  # Fall back through the chain
        else:
            return db_value

    # 2. Try env var
    env_name = ENV_MAP.get(key)
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value is not None:
            if key in _INT_KEYS:
                try:
                    return int(env_value)
                except (ValueError, TypeError):
                    pass
            else:
                return env_value

    # 3. Default
    default = DEFAULTS.get(key)
    if default is not None:
        return int(default) if key in _INT_KEYS else default

    return None


# ── Module-level aliases for backward compatibility ──
# These read from env vars at import time (used by existing tests that
# monkeypatch these module attributes).
PI_COWORK_URL = os.environ.get("PI_COWORK_URL", "http://localhost:5000")
PI_MAX_PARALLEL = int(os.environ.get("PI_MAX_PARALLEL", 1))
PI_MAX_PER_HOUR = int(os.environ.get("PI_MAX_PER_HOUR", 100))
WARM_SPAWN_THRESHOLD_SECONDS = 3600  # 1 hour
RUN_MAX_AGE_SECONDS = 7200  # 2 hours

DEFAULT_ASSISTANT_SYSTEM_PROMPT = (
    "You are the pi-CoWork Assistant. Help users with the cowork app, "
    "answer questions, suggest actions, and be concise."
)

ASSISTANT_WORK_DIR = str(Path(PROJECT_ROOT) / "workspace")
ASSISTANT_SESSION_DIR = os.path.join(ASSISTANT_WORK_DIR, ".pi-sessions", "assistant-global")
