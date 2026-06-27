"""API: Settings CRUD & purge operations."""

import os
import shutil

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict
from pi_cowork.models import get_setting, set_setting
from pi_cowork.system_logs import add_log

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/api/settings", methods=["GET"])
def api_settings():
    rows = query_db("SELECT key, value, updated_at FROM settings ORDER BY key")
    return jsonify([row_to_dict(r) for r in rows])


@settings_bp.route("/api/settings/<key>", methods=["GET"])
def api_get_setting(key):
    value = get_setting(key)
    if value is None:
        return jsonify({"error": "Setting not found"}), 404
    return jsonify({"key": key, "value": value})


@settings_bp.route("/api/settings/<key>", methods=["PUT"])
def api_update_setting(key):
    data = request.get_json() or {}
    value = data.get("value")
    if value is None:
        return jsonify({"error": "value is required"}), 400
    value = str(value).strip()

    # Auth guard: do not allow enabling authentication if no user exists.
    if key == "auth_enabled" and value in ("1", "true", "yes", "on"):
        count = query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"]
        if count == 0:
            return jsonify({"error": "Create an account first"}), 400

    set_setting(key, value)
    add_log(
        "INFO",
        "db_change",
        f"UPDATE settings/{key}",
        details={"operation": "UPDATE", "table": "settings", "record_id": key},
    )
    return jsonify({"success": True})


@settings_bp.route("/api/settings/purge-terminal-logs", methods=["POST"])
def api_purge_terminal_logs():
    """Delete file-based agent logs (.pi-logs dirs) for tickets in terminal statuses."""
    # Find all tickets in terminal statuses along with their board's working_directory
    rows = query_db("""
        SELECT t.id AS ticket_id, b.working_directory
        FROM tickets t
        JOIN statuses s ON t.status_id = s.id
        JOIN boards b ON t.board_id = b.id
        WHERE s.is_terminal = 1
    """)

    purged_count = 0
    purged_dirs = []

    for row in rows:
        ticket_id = row["ticket_id"]
        working_directory = row["working_directory"] or "workspace"

        # Resolve working directory (may be relative to PROJECT_ROOT)
        if not os.path.isabs(working_directory):
            from pi_cowork import config

            working_directory = os.path.join(config.PROJECT_ROOT, working_directory)

        log_dir = os.path.join(working_directory, ".pi-logs", f"ticket-{ticket_id}")

        if os.path.isdir(log_dir):
            try:
                shutil.rmtree(log_dir)
                purged_count += 1
                purged_dirs.append(log_dir)
            except OSError:
                pass  # Skip dirs we can't delete

    add_log(
        "INFO",
        "db_change",
        f"Purged terminal ticket logs: {purged_count} directories removed",
        details={"purged_count": purged_count, "dirs": purged_dirs},
    )

    return jsonify({"success": True, "purged_count": purged_count})
