"""Thin entry point — re-exports the Flask app for backwards compatibility.

``start.sh`` runs ``python3 app.py``, and tests do ``from app import app``.
Both still work because this module exposes ``app`` at module level.

All names that tests monkeypatch or ``patch()`` are re-exported here so that
``patch('app.X')`` continues to work without any test changes for module-level
imports like ``subprocess``, ``os``, ``signal``, ``shutil``, ``threading``, etc.
For module-internal functions like ``_is_our_process`` that moved to
``pi_cowork.agents``, tests must patch the correct module path.
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

from pi_cowork import create_app, config
from pi_cowork.config import get_config
from pi_cowork.db import get_db, init_db, query_db, run_db
from pi_cowork.models import (
    get_comments, add_comment, get_questions, count_unanswered_questions,
    has_unanswered_questions, get_workflow, get_board, get_board_with_workflow,
    get_statuses, get_status, get_agents, get_agent, get_transitions_from,
    get_quality_gates, get_ticket_labels, get_labels, get_label, get_setting,
    set_setting, set_ticket_labels, get_all_quality_gates,
    get_pending_gate_reviews, has_pending_gate_reviews, run_cli_gate,
    row_to_dict,
    get_recurring_tasks, get_recurring_task, create_recurring_task,
    update_recurring_task, delete_recurring_task, toggle_recurring_task,
    get_recurring_parents, compute_next_trigger, process_recurring_tasks,
    cron_human_readable,
)
from pi_cowork.agents import (
    _is_our_process, _read_log, _start_log_reader, _start_watcher,
    _watch_agent,
    cleanup_runs, count_running, count_hourly, queue_agent, drain_queue,
    try_spawn_or_queue, spawn_agent,
)
from pi_cowork.update import (
    _update_state_path, _read_and_clear_update_state, _git_available,
    _git_dir_exists, _run_git, _get_git_info,
)
from pi_cowork.events import bus

app = create_app()

# Re-export config constants so ``from app import PI_MAX_PARALLEL`` still works
# For dynamic settings, use get_config() instead — it reads DB > env > default
PI_MAX_PARALLEL = config.PI_MAX_PARALLEL
PI_MAX_PER_HOUR = config.PI_MAX_PER_HOUR
PI_COWORK_URL = config.PI_COWORK_URL
DATABASE = config.DATABASE
PROJECT_ROOT = config.PROJECT_ROOT
WARM_SPAWN_THRESHOLD_SECONDS = config.WARM_SPAWN_THRESHOLD_SECONDS
RUN_MAX_AGE_SECONDS = config.RUN_MAX_AGE_SECONDS
ASSISTANT_SESSION_DIR = config.ASSISTANT_SESSION_DIR
ASSISTANT_WORK_DIR = config.ASSISTANT_WORK_DIR
DEFAULT_ASSISTANT_SYSTEM_PROMPT = config.DEFAULT_ASSISTANT_SYSTEM_PROMPT

if __name__ == '__main__':
    import os as _os
    _debug = _os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true')
    with app.app_context():
        _port = get_config('port')
    app.run(debug=_debug, host='0.0.0.0', port=_port)