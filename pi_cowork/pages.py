"""HTML page routes — registered directly on the app (no Blueprint prefix)."""

from pi_cowork.db import query_db, row_to_dict
from pi_cowork.update import _read_and_clear_update_state
from pi_cowork.models import get_comments


def register_pages(app):
    """Register page routes and context processors on *app*."""

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('board'))

    @app.route('/board')
    def board():
        from flask import render_template
        return render_template('board.html')

    @app.route('/ticket/<int:ticket_id>')
    def ticket_detail(ticket_id):
        from flask import render_template
        ticket = query_db("""
            SELECT t.*, s.name AS status_name, a.name AS agent_name, b.name AS board_name, b.workflow_id, w.git_enabled
            FROM tickets t
            JOIN statuses s ON t.status_id = s.id
            LEFT JOIN agents a ON s.agent_id = a.id
            JOIN boards b ON t.board_id = b.id
            JOIN workflows w ON b.workflow_id = w.id
            WHERE t.id = ?
        """, (ticket_id,), one=True)
        if not ticket:
            return "Not found", 404
        return render_template('ticket_detail.html', ticket=ticket)

    @app.route('/ticket/new')
    def new_ticket():
        from flask import render_template
        return render_template('ticket_form.html')

    @app.route('/ticket/<int:ticket_id>/edit')
    def edit_ticket(ticket_id):
        from flask import render_template
        ticket = query_db("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
        if not ticket:
            return "Not found", 404
        return render_template('ticket_form.html', ticket=ticket)

    @app.route('/workflows')
    def workflows_page():
        from flask import render_template
        return render_template('workflows.html')

    @app.route('/backup')
    def backup_page():
        from flask import render_template
        return render_template('backup.html')

    @app.route('/assistant/settings')
    def assistant_settings_page():
        from flask import redirect, url_for
        return redirect(url_for('settings_page'))

    @app.route('/settings')
    def settings_page():
        from flask import render_template
        return render_template('settings.html')

    @app.route('/system-logs')
    def system_logs_page():
        from flask import render_template
        return render_template('system_logs.html')

    @app.route('/database-backup')
    def database_backup_page():
        from flask import render_template
        return render_template('database_backup.html')

    @app.context_processor
    def inject_persistent_flash():
        state = _read_and_clear_update_state()
        return {'persistent_flash': state}