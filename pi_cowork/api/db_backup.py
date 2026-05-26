"""API: Database Backup & Restore — list, create, restore, and delete DB backups."""

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from pi_cowork import config
from pi_cowork.models import get_setting
from pi_cowork.system_logs import add_log

db_backup_bp = Blueprint('db_backup', __name__)

# Pattern to match backup filenames with embedded timestamps
_BACKUP_RE = re.compile(r'^(?:pi-cowork|pre-restore)_(\d{8}_\d{6})\.db$')


def _backup_dir():
    """Return the backups directory path, creating it if needed."""
    d = Path(config.PROJECT_ROOT) / 'backups'
    d.mkdir(exist_ok=True)
    return d


def _db_path():
    """Return the current database file path."""
    return Path(current_app.config.get('DATABASE', config.DATABASE))


def _safe_filename(filename):
    """Validate that a filename is a bare name within backups/ (no path traversal)."""
    if not filename:
        return False
    # Must not contain path separators or parent references
    if '/' in filename or '\\' in filename or '..' in filename:
        return False
    # Must match the expected backup filename pattern
    if not _BACKUP_RE.match(filename):
        return False
    return True


def _timestamp_from_filename(filename):
    """Extract and parse the timestamp from a backup filename.

    Returns an ISO-format string or None if parsing fails.
    """
    m = _BACKUP_RE.match(filename)
    if not m:
        return None
    ts_str = m.group(1)
    try:
        dt = datetime.strptime(ts_str, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def _retention_cleanup(backup_dir):
    """Delete oldest backups exceeding the configured retention limit.

    Reads `db_backup_max_count` setting (default 10).
    Sorts backups by timestamp descending, deletes oldest exceeding limit.
    """
    try:
        max_count = int(get_setting('db_backup_max_count', 10))
    except (ValueError, TypeError):
        max_count = 10

    if max_count < 1:
        return

    # Gather all .db backup files
    backup_files = []
    for f in backup_dir.iterdir():
        if f.is_file() and f.suffix == '.db' and _BACKUP_RE.match(f.name):
            ts = _timestamp_from_filename(f.name)
            if ts:
                backup_files.append((ts, f))

    if len(backup_files) <= max_count:
        return

    # Sort by timestamp descending (newest first)
    backup_files.sort(key=lambda x: x[0], reverse=True)

    # Delete oldest files exceeding the limit
    for _, fpath in backup_files[max_count:]:
        try:
            fpath.unlink()
            add_log('INFO', 'db_change', f'Retention cleanup deleted backup: {fpath.name}')
        except OSError as e:
            add_log('WARNING', 'db_change', f'Retention cleanup failed for {fpath.name}: {e}')


@db_backup_bp.route('/api/db-backup/list', methods=['GET'])
def api_list_backups():
    """List all backup files with name, size, and timestamp."""
    backup_dir = _backup_dir()
    backups = []

    for f in sorted(backup_dir.iterdir(), key=lambda x: x.name, reverse=True):
        if f.is_file() and f.suffix == '.db' and _BACKUP_RE.match(f.name):
            ts = _timestamp_from_filename(f.name)
            try:
                size = os.path.getsize(f)
            except OSError:
                size = 0
            backups.append({
                'filename': f.name,
                'size': size,
                'timestamp': ts,
            })

    return jsonify(backups)


@db_backup_bp.route('/api/db-backup/create', methods=['POST'])
def api_create_backup():
    """Create a manual backup of the current database."""
    db_file = _db_path()
    if not db_file.exists():
        add_log('ERROR', 'db_change', 'Backup failed: database file not found')
        return jsonify({"error": "Database file not found"}), 404

    backup_dir = _backup_dir()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_name = f'pi-cowork_{timestamp}.db'
    backup_path = backup_dir / backup_name

    try:
        shutil.copy2(str(db_file), str(backup_path))
        add_log('INFO', 'db_change', f'Database backup created: {backup_name}')
    except Exception as e:
        add_log('ERROR', 'db_change', f'Backup failed: {e}')
        return jsonify({"error": f"Backup failed: {e}"}), 500

    # Run retention cleanup
    _retention_cleanup(backup_dir)

    return jsonify({
        "success": True,
        "filename": backup_name,
        "size": os.path.getsize(backup_path),
    })


@db_backup_bp.route('/api/db-backup/restore', methods=['POST'])
def api_restore_backup():
    """Restore the database from a specified backup file.

    Creates a safety backup of the current DB first, then overwrites with
    the selected backup. Requires {"filename": "..."} in request body.
    """
    data = request.get_json() or {}
    filename = data.get('filename')

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    if not _safe_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    backup_dir = _backup_dir()
    source_path = backup_dir / filename

    if not source_path.exists():
        return jsonify({"error": "Backup file not found"}), 404

    # Ensure source is within backups dir (resolve symlinks)
    if not source_path.resolve().parent == backup_dir.resolve():
        return jsonify({"error": "Invalid backup path"}), 400

    db_file = _db_path()

    # Create pre-restore safety backup
    if db_file.exists():
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        safety_name = f'pre-restore_{timestamp}.db'
        safety_path = backup_dir / safety_name
        try:
            shutil.copy2(str(db_file), str(safety_path))
            add_log('INFO', 'db_change', f'Pre-restore safety backup created: {safety_name}')
        except Exception as e:
            add_log('ERROR', 'db_change', f'Pre-restore safety backup failed: {e}')
            return jsonify({"error": f"Pre-restore safety backup failed: {e}"}), 500

    # Restore from backup
    try:
        shutil.copy2(str(source_path), str(db_file))
        add_log('INFO', 'db_change', f'Database restored from backup: {filename}')
    except Exception as e:
        add_log('ERROR', 'db_change', f'Restore failed: {e}')
        return jsonify({"error": f"Restore failed: {e}"}), 500

    return jsonify({
        "success": True,
        "restored_from": filename,
    })


@db_backup_bp.route('/api/db-backup/delete', methods=['DELETE'])
def api_delete_backup():
    """Delete a specific backup file. Requires {"filename": "..."} in request body."""
    data = request.get_json() or {}
    filename = data.get('filename')

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    if not _safe_filename(filename):
        return jsonify({"error": "Invalid filename"}), 400

    backup_dir = _backup_dir()
    target_path = backup_dir / filename

    if not target_path.exists():
        return jsonify({"error": "Backup file not found"}), 404

    # Ensure target is within backups dir (resolve symlinks)
    if not target_path.resolve().parent == backup_dir.resolve():
        return jsonify({"error": "Invalid backup path"}), 400

    try:
        target_path.unlink()
        add_log('INFO', 'db_change', f'Backup deleted: {filename}')
    except Exception as e:
        add_log('ERROR', 'db_change', f'Backup delete failed: {e}')
        return jsonify({"error": f"Delete failed: {e}"}), 500

    return jsonify({"success": True})