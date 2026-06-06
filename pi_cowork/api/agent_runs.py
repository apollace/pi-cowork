"""API: Agent Runs — logs, kill, live stream."""

import contextlib
import os
import signal
import time
from datetime import UTC, datetime

from flask import Blueprint, jsonify, request, stream_with_context

from pi_cowork import agents as _agents_mod
from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import add_comment
from pi_cowork.system_logs import add_log

agent_runs_bp = Blueprint("agent_runs", __name__)


@agent_runs_bp.route("/api/tickets/<int:ticket_id>/agent_runs", methods=["GET"])
def api_ticket_agent_runs(ticket_id):
    rows = query_db(
        """
        SELECT ar.*, a.name AS agent_name, s.name AS status_name
        FROM agent_runs ar
        JOIN agents a ON ar.agent_id = a.id
        LEFT JOIN statuses s ON ar.status_id = s.id
        WHERE ar.ticket_id = ?
        ORDER BY ar.started_at DESC
    """,
        (ticket_id,),
    )
    return jsonify([row_to_dict(r) for r in rows])


@agent_runs_bp.route("/api/agent_runs/<int:run_id>/log", methods=["GET"])
def api_agent_run_log(run_id):
    row = query_db("SELECT log_path FROM agent_runs WHERE id = ?", (run_id,), one=True)
    if not row or not row["log_path"]:
        return jsonify({"error": "Log not found"}), 404
    path = row["log_path"]
    if not os.path.isfile(path):
        return jsonify({"error": "Log file missing"}), 404
    with open(path) as f:
        content = f.read()
    return content, 200, {"Content-Type": "text/plain"}


@agent_runs_bp.route("/api/running_agent_runs", methods=["GET"])
def api_running_agent_runs():
    board_id = request.args.get("board_id", type=int)
    if board_id is None:
        return jsonify({"error": "board_id is required"}), 400
    rows = query_db(
        """
        SELECT ar.id, ar.ticket_id, ar.agent_id, ar.started_at, a.name AS agent_name,
               t.title AS ticket_title, s.name AS status_name
        FROM agent_runs ar
        JOIN agents a ON ar.agent_id = a.id
        JOIN tickets t ON ar.ticket_id = t.id
        LEFT JOIN statuses s ON ar.status_id = s.id
        WHERE ar.status = 'running' AND t.board_id = ?
        ORDER BY ar.started_at DESC
    """,
        (board_id,),
    )
    return jsonify([row_to_dict(r) for r in rows])


@agent_runs_bp.route("/api/agent_runs/<int:run_id>/kill", methods=["POST"])
def api_kill_agent_run(run_id):
    row = query_db("SELECT * FROM agent_runs WHERE id = ?", (run_id,), one=True)
    if not row:
        return jsonify({"error": "Agent run not found"}), 404

    run = row_to_dict(row)

    if run["status"] != "running":
        return jsonify({"error": f"Agent run is not running (status: {run['status']})"}), 409

    pid = run["pid"]
    if pid is None:
        return jsonify({"error": "Agent run has no PID (process never started properly)"}), 400

    ticket_id = run["ticket_id"]

    if not _agents_mod._is_our_process(pid):
        now = datetime.now(UTC).isoformat()
        run_db(
            "UPDATE agent_runs SET status = 'failed', completed_at = ?, exit_code = ? WHERE id = ?", (now, -15, run_id)
        )
        add_comment(ticket_id, "🛑 Agent killed by user (process already terminated)")
        add_log(
            "WARNING",
            "agent_event",
            f"Agent run {run_id} killed by user (process already terminated)",
            details={"agent_name": run.get("agent_name", "Unknown"), "run_id": run_id, "exit_code": -15},
            ticket_id=ticket_id,
        )
        return jsonify({"success": True, "exit_code": -15, "escalated": False})

    escalated = False
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        now = datetime.now(UTC).isoformat()
        run_db(
            "UPDATE agent_runs SET status = 'failed', completed_at = ?, exit_code = ? WHERE id = ?", (now, -15, run_id)
        )
        add_comment(ticket_id, "🛑 Agent killed by user (process already terminated)")
        add_log(
            "WARNING",
            "agent_event",
            f"Agent run {run_id} killed by user (process already terminated)",
            details={"agent_name": run.get("agent_name", "Unknown"), "run_id": run_id, "exit_code": -15},
            ticket_id=ticket_id,
        )
        return jsonify({"success": True, "exit_code": -15, "escalated": False})

    for _ in range(10):
        time.sleep(0.5)
        if not _agents_mod._is_our_process(pid):
            break
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
        escalated = True

    exit_code = -9 if escalated else -15
    now = datetime.now(UTC).isoformat()
    run_db(
        "UPDATE agent_runs SET status = 'failed', completed_at = ?, exit_code = ? WHERE id = ?",
        (now, exit_code, run_id),
    )
    comment = "🛑 Agent killed by user"
    if escalated:
        comment += " (escalated to SIGKILL after SIGTERM timeout)"
    add_comment(ticket_id, comment)
    add_log(
        "WARNING",
        "agent_event",
        f"Agent run {run_id} killed by user",
        details={
            "agent_name": run.get("agent_name", "Unknown"),
            "run_id": run_id,
            "exit_code": exit_code,
            "escalated": escalated,
        },
        ticket_id=ticket_id,
    )
    return jsonify({"success": True, "exit_code": exit_code, "escalated": escalated})


@agent_runs_bp.route("/api/agent_runs/<int:run_id>/stream", methods=["GET"])
def api_agent_run_stream(run_id):
    from flask import current_app

    row = query_db("SELECT log_path, status FROM agent_runs WHERE id = ?", (run_id,), one=True)
    if not row or not row["log_path"]:
        return jsonify({"error": "Log not found"}), 404
    log_path = row["log_path"]

    # If the run is already not running, return a minimal response instead of
    # opening a long-lived stream that would immediately close.
    if row["status"] != "running":
        return jsonify({"error": "Run is not active", "status": row["status"]}), 410

    def event_stream():
        last_size = 0
        last_keepalive = time.monotonic()
        start_time = time.monotonic()
        # Safety ceiling: 24 hours.  A running stream should never live longer
        # than this; the agent watcher will mark the run completed long before.
        max_lifetime = 86400

        while True:
            # Safety: hard timeout so zombie streams cannot spin forever.
            if time.monotonic() - start_time > max_lifetime:
                yield ": stream timeout after 24h\n\n"
                break

            if not os.path.isfile(log_path):
                yield "event: error\ndata: Log file not found\n\n"
                break
            current_size = os.path.getsize(log_path)
            if current_size > last_size:
                with open(log_path) as f:
                    f.seek(last_size)
                    chunk = f.read(current_size - last_size)
                for line in chunk.split("\n"):
                    yield f"data: {line}\n"
                yield "\n"
                last_size = current_size
                last_keepalive = time.monotonic()

            # Check whether the run has finished (or the row was deleted).
            # The previous code used `if fresh and …` which meant a deleted
            # row (fresh=None) would NEVER break out of the loop, producing an
            # infinite spinning loop that polled stat() + query_db() every
            # second until the process was killed.
            fresh = query_db("SELECT status FROM agent_runs WHERE id = ?", (run_id,), one=True)
            if fresh is None or fresh["status"] != "running":
                yield "event: done\ndata: completed\n\n"
                break

            # Yield a keepalive comment at least every ~25 s of silence.
            # This is essential: Flask can only detect client disconnection
            # when the generator attempts to yield.  Without periodic yields,
            # a stale generator would spin forever — hitting the filesystem
            # and database every second in a tight polling loop.
            now = time.monotonic()
            if now - last_keepalive >= 25:
                yield ": keepalive\n\n"
                last_keepalive = now

            time.sleep(1)

    return current_app.response_class(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@agent_runs_bp.route("/agent_run/<int:run_id>/live")
def agent_run_live(run_id):
    from flask import render_template

    row = query_db(
        """
        SELECT ar.*, a.name AS agent_name,
               t.id AS ticket_id, t.title AS ticket_title,
               s.name AS status_name
        FROM agent_runs ar
        JOIN agents a ON ar.agent_id = a.id
        JOIN tickets t ON ar.ticket_id = t.id
        LEFT JOIN statuses s ON ar.status_id = s.id
        WHERE ar.id = ?
    """,
        (run_id,),
        one=True,
    )
    if not row:
        return "Not found", 404
    return render_template("run_live.html", run=row_to_dict(row))
