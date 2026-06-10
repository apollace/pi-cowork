"""HTML page routes — registered directly on the app (no Blueprint prefix)."""

from flask import redirect, render_template, url_for

from pi_cowork.db import query_db
from pi_cowork.update import _read_and_clear_update_state


def index():
    return redirect(url_for("board"))


def board():
    return render_template("board.html")


def ticket_detail(ticket_id):
    ticket = query_db(
        """
        SELECT t.*, s.name AS status_name, a.name AS agent_name, b.name AS board_name, b.workflow_id, w.git_enabled
        FROM tickets t
        JOIN statuses s ON t.status_id = s.id
        LEFT JOIN agents a ON s.agent_id = a.id
        JOIN boards b ON t.board_id = b.id
        JOIN workflows w ON b.workflow_id = w.id
        WHERE t.id = ?
    """,
        (ticket_id,),
        one=True,
    )
    if not ticket:
        return "Not found", 404
    return render_template("ticket_detail.html", ticket=ticket)


def new_ticket():
    return render_template("ticket_form.html")


def edit_ticket(ticket_id):
    ticket = query_db("SELECT * FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return "Not found", 404
    return render_template("ticket_form.html", ticket=ticket)


def workflows_page():
    return render_template("workflows.html")


def assistant_settings_page():
    return redirect(url_for("settings_page"))


def skills_page():
    return render_template("skills.html")


def settings_page():
    return render_template("settings.html")


def system_logs_page():
    return render_template("system_logs.html")


def database_backup_page():
    return render_template("database_backup.html")


def knowledge_page():
    return render_template("knowledge.html")


def inject_persistent_flash():
    state = _read_and_clear_update_state()
    return {"persistent_flash": state}


def register_pages(app):
    """Register page routes and context processors on *app*."""
    app.route("/")(index)
    app.route("/board")(board)
    app.route("/ticket/<int:ticket_id>")(ticket_detail)
    app.route("/ticket/new")(new_ticket)
    app.route("/ticket/<int:ticket_id>/edit")(edit_ticket)
    app.route("/workflows")(workflows_page)
    app.route("/assistant/settings")(assistant_settings_page)
    app.route("/skills")(skills_page)
    app.route("/settings")(settings_page)
    app.route("/system-logs")(system_logs_page)
    app.route("/database-backup")(database_backup_page)
    app.route("/knowledge")(knowledge_page)
    app.context_processor(inject_persistent_flash)
