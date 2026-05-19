"""Update check/run logic and update-related routes."""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import flash, redirect, request, url_for, render_template

from pi_cowork import config
from pi_cowork.db import query_db


def _update_state_path():
    return Path(config.PROJECT_ROOT) / '.update-state.json'


def _read_and_clear_update_state():
    path = _update_state_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Only clear the state file when the PID differs from the one that
        # created it — that means the app has actually restarted.  Before the
        # restart (same PID) we keep the file around so it can survive the
        # process exit and be shown in the freshly-started instance.
        stored_pid = data.get('pid')
        if stored_pid is not None and stored_pid != os.getpid():
            # Post-restart: show the success message and clear the state.
            result = {
                'level': data.get('level', 'success'),
                'message': 'Update applied successfully. The app has been restarted.',
                'timestamp': data.get('timestamp'),
            }
            try:
                path.unlink()
            except OSError:
                pass
            return result
        # Pre-restart (same PID or no PID stored): show an "installing"
        # message but *do not* delete the file.
        return {
            'level': data.get('level', 'success'),
            'message': 'Installing update… The app will restart shortly.',
            'timestamp': data.get('timestamp'),
        }
    except (OSError, json.JSONDecodeError):
        try:
            path.unlink()
        except OSError:
            pass
        return None


def _git_available():
    return shutil.which('git') is not None


def _git_dir_exists():
    return (Path(config.PROJECT_ROOT) / '.git').is_dir()


def _run_git(args, cwd=None):
    result = subprocess.run(
        ['git'] + args,
        cwd=cwd or config.PROJECT_ROOT,
        capture_output=True,
        text=True
    )
    return result


def _get_git_info():
    branch = _run_git(['rev-parse', '--abbrev-ref', 'HEAD']).stdout.strip()
    commit = _run_git(['rev-parse', '--short', 'HEAD']).stdout.strip()
    return {'branch': branch or 'unknown', 'commit': commit or 'unknown'}


# ---------------------------------------------------------------------------
# Route registration (directly on app, no Blueprint prefix)
# ---------------------------------------------------------------------------

def register_update_routes(app):
    """Register update page routes on *app*."""

    @app.route('/update')
    def update_page():
        info = {'branch': 'unknown', 'commit': 'unknown'}
        if _git_available() and _git_dir_exists():
            try:
                info = _get_git_info()
            except Exception:
                pass
        return render_template('update.html', info=info)

    @app.route('/update/check', methods=['POST'])
    def update_check():
        if not _git_available():
            flash('Git is not installed on this system.', 'error')
            return redirect(url_for('update_page'))
        if not _git_dir_exists():
            flash('This app is not running from a git repository.', 'error')
            return redirect(url_for('update_page'))

        try:
            fetch = _run_git(['fetch'])
            if fetch.returncode != 0:
                flash(f'Git fetch failed: {fetch.stderr.strip()}', 'error')
                return redirect(url_for('update_page'))

            result = _run_git(['rev-list', '--count', 'HEAD..@{u}'])
            if result.returncode != 0:
                flash('Unable to determine update status. Is a remote tracking branch configured?', 'error')
                return redirect(url_for('update_page'))

            count = result.stdout.strip()
            if count == '0':
                flash('App is up to date.', 'success')
            else:
                flash(f'{count} new commit(s) available.', 'success')
        except Exception as e:
            flash(f'Check failed: {e}', 'error')

        return redirect(url_for('update_page'))

    @app.route('/update/run', methods=['POST'])
    def update_run():
        from flask import current_app
        if not _git_available():
            flash('Git is not installed.', 'error')
            return redirect(url_for('update_page'))
        if not _git_dir_exists():
            flash('Not a git repository.', 'error')
            return redirect(url_for('update_page'))

        try:
            status = _run_git(['status', '--porcelain'])
            if status.stdout.strip():
                flash('Working tree has uncommitted changes. Please commit or stash before updating.', 'error')
                return redirect(url_for('update_page'))

            result = _run_git(['rev-list', '--count', 'HEAD..@{u}'])
            if result.stdout.strip() == '0':
                flash('No updates to apply.', 'success')
                return redirect(url_for('update_page'))
        except Exception as e:
            flash(f'Pre-flight check failed: {e}', 'error')
            return redirect(url_for('update_page'))

        db_path = Path(current_app.config.get('DATABASE', config.DATABASE)).resolve()
        backup_dir = Path(config.PROJECT_ROOT) / 'backups'
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'pi-cowork_{timestamp}.db'
        try:
            shutil.copy2(str(db_path), str(backup_path))
        except Exception as e:
            flash(f'Database backup failed: {e}', 'error')
            return redirect(url_for('update_page'))

        try:
            pull = _run_git(['pull'])
            if pull.returncode != 0:
                err = pull.stderr.strip() or pull.stdout.strip() or 'Unknown error'
                flash(f'Git pull failed: {err}', 'error')
                return redirect(url_for('update_page'))
        except Exception as e:
            flash(f'Git pull failed: {e}', 'error')
            return redirect(url_for('update_page'))

        # Include the PID so the persistent-flash mechanism can tell the
        # difference between the pre-restart process (show "installing…")
        # and the post-restart process (show "applied" and clear the file).
        state = {
            'level': 'success',
            'message': 'Update installed successfully. The app has been restarted.',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'pid': os.getpid(),
        }
        try:
            _update_state_path().write_text(json.dumps(state))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error('Failed to write update state: %s', exc)

        reload_sentinel = Path(config.PROJECT_ROOT) / '.reload'
        try:
            reload_sentinel.touch()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error('Failed to write reload sentinel: %s', exc)

        # Use os._exit() instead of signal.SIGTERM.  SIGTERM causes
        # Werkzeug's server_close() to hang because it tries to join
        # SSE request threads that run infinite loops.  os._exit(0)
        # terminates immediately; start.sh detects the .reload sentinel
        # and restarts the process.
        def _shutdown():
            time.sleep(1.0)  # give the redirect response time to be sent
            os._exit(0)

        threading.Thread(target=_shutdown, daemon=True).start()
        return redirect(url_for('update_page'))