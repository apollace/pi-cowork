"""Thin entry point — re-exports the Flask app for backwards compatibility.

``start.sh`` runs ``python3 app.py``, and tests do ``from app import app``.
Both still work because this module exposes ``app`` at module level.

All names that tests monkeypatch or ``patch()`` are re-exported here so that
``patch('app.X')`` continues to work without any test changes for module-level
imports like ``subprocess``, ``os``, ``signal``, ``shutil``, ``threading``, etc.
For module-internal functions like ``_is_our_process`` that moved to
``pi_cowork.agents``, tests must patch the correct module path.
"""

import datetime
import os
import shutil
import signal
import subprocess
import threading
import time

from pi_cowork import config, create_app
from pi_cowork.config import get_config

# Backwards-compat re-exports for tests that patch app.<module> directly
datetime = datetime
subprocess = subprocess
os = os
signal = signal
shutil = shutil
threading = threading
time = time

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

if __name__ == "__main__":
    import os as _os

    _debug = _os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true")
    with app.app_context():
        _port = get_config("port")
    app.run(debug=_debug, host="0.0.0.0", port=_port)
