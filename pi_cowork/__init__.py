"""pi_cowork — Flask application package.

Usage::

    from pi_cowork import create_app
    app = create_app()
"""

import json
import logging
import os
import sys
from pathlib import Path

from flask import Flask

from pi_cowork import config
from pi_cowork.db import close_connection, init_db
from pi_cowork.events import bus

logger = logging.getLogger(__name__)


def _load_secret_key():
    env_key = os.environ.get("FLASK_SECRET_KEY")
    if env_key:
        return env_key
    if "pytest" in sys.modules:
        return "test-secret"
    secret_path = Path(config.PROJECT_ROOT) / ".flask_secret"
    if secret_path.exists():
        return secret_path.read_text().strip()
    secret = os.urandom(32).hex()
    secret_path.write_text(secret)
    return secret


# ---------------------------------------------------------------------------
# Phase 4: Persistent audit subscriber
# ---------------------------------------------------------------------------


def _audit_subscriber(event_name=None, **kwargs):
    """Persist every published event into the event_log table."""
    try:
        from pi_cowork.db import get_db

        db = get_db()
        payload = json.dumps(kwargs) if kwargs else None
        db.execute("INSERT INTO event_log (event_name, payload) VALUES (?, ?)", (event_name, payload))
        db.commit()
    except Exception:
        logger.exception("Audit log write failed")


def _register_audit_subscribers():
    from pi_cowork import events as _ev

    for _attr in dir(_ev):
        if _attr.isupper() and isinstance(getattr(_ev, _attr), str):
            bus.subscribe(getattr(_ev, _attr), _audit_subscriber)


_register_audit_subscribers()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app():
    """Application factory: create and configure the Flask app."""
    app = Flask(
        __name__,
        template_folder=os.path.join(config.PROJECT_ROOT, "templates"),
        static_folder=os.path.join(config.PROJECT_ROOT, "static"),
    )
    app.secret_key = _load_secret_key()

    # Generate a random per-instance secret that the web UI uses to
    # authenticate human-only actions (e.g. gate review approvals).
    # Agents never receive this secret, so they cannot bypass manual gates.
    app.config["HUMAN_ACTION_SECRET"] = os.urandom(32).hex()

    # Config
    app.config["DATABASE"] = config.DATABASE

    # Teardown hooks
    @app.teardown_appcontext
    def _close_db(exception):
        close_connection(exception)

    # Register page routes (no Blueprint — preserves endpoint names for templates)
    from pi_cowork.pages import register_pages

    register_pages(app)

    # Register update routes (no Blueprint — preserves endpoint names for templates)
    from pi_cowork.update import register_update_routes

    register_update_routes(app)

    # Register assistant API (Blueprint)
    from pi_cowork.assistant import assistant_bp

    app.register_blueprint(assistant_bp)

    from pi_cowork.api import register_api_blueprints

    register_api_blueprints(app)

    # Register system log HTTP middleware (before_request + after_request)
    from pi_cowork.system_logs import log_http_request, record_request_start_time

    app.before_request(record_request_start_time)
    app.after_request(log_http_request)

    # Inject the human-action secret into all templates so the UI can
    # authenticate human-only operations (e.g. gate review approvals).
    @app.context_processor
    def inject_human_action_secret():
        return {"human_action_secret": app.config["HUMAN_ACTION_SECRET"]}

    # Register system log event bus subscribers
    from pi_cowork.system_logs import register_system_log_subscribers

    register_system_log_subscribers()

    # Register self-improvement observation subscribers
    from pi_cowork.self_improvement import register_self_improvement_subscribers

    register_self_improvement_subscribers()

    # Initialize DB once and start background tasks once
    @app.before_request
    def _auto_init_db():
        if not getattr(app, "_db_initialized", False):
            init_db(app)
            app._db_initialized = True

    @app.before_request
    def _start_background_tasks():
        if not getattr(app, "_drain_started", False) and not app.config.get("TESTING"):
            app._drain_started = True
            from pi_cowork.agents import register_background_tasks

            register_background_tasks(app)

    return app
