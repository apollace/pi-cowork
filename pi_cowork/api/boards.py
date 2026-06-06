"""API: Boards."""

import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import get_board, get_board_with_workflow, get_workflow
from pi_cowork.system_logs import add_log

boards_bp = Blueprint("boards", __name__)


@boards_bp.route("/api/boards", methods=["GET"])
def api_boards():
    rows = query_db("""
        SELECT b.*, w.name AS workflow_name, w.git_enabled AS workflow_git_enabled
        FROM boards b
        JOIN workflows w ON b.workflow_id = w.id
        ORDER BY b.name
    """)
    result = []
    for r in rows:
        d = row_to_dict(r)
        d["git_enabled"] = bool(d.pop("workflow_git_enabled", 0))
        result.append(d)
    return jsonify(result)


@boards_bp.route("/api/boards", methods=["POST"])
def api_create_board():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    workflow_id = data.get("workflow_id")
    if not name:
        return jsonify({"error": "name is required"}), 400
    if workflow_id is None:
        return jsonify({"error": "workflow_id is required"}), 400
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    try:
        wd = (data.get("working_directory") or "").strip()
        wd_path = Path(wd)
        wd_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return jsonify({"error": f"Cannot create working directory: {e}"}), 400

    long_term_vision = (data.get("long_term_vision") or "").strip() or None
    try:
        cur = run_db(
            "INSERT INTO boards (name, workflow_id, working_directory, long_term_vision) VALUES (?, ?, ?, ?)",
            (name, workflow_id, str(wd_path.resolve()), long_term_vision),
        )
        add_log(
            "INFO",
            "db_change",
            f"INSERT boards/{cur.lastrowid}",
            details={"operation": "INSERT", "table": "boards", "record_id": cur.lastrowid},
        )
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Board name already exists"}), 409


@boards_bp.route("/api/boards/stats", methods=["GET"])
def api_board_stats():
    """Ticket counts per board."""
    rows = query_db("""
        SELECT b.id AS board_id, COUNT(t.id) AS ticket_count
        FROM boards b
        LEFT JOIN tickets t ON t.board_id = b.id
        GROUP BY b.id
    """)
    return jsonify({r["board_id"]: r["ticket_count"] for r in rows})


@boards_bp.route("/api/boards/<int:board_id>", methods=["GET"])
def api_get_board(board_id):
    board = get_board_with_workflow(board_id)
    if not board:
        return jsonify({"error": "Board not found"}), 404
    # Expose git_enabled from the workflow
    board["git_enabled"] = bool(board.pop("workflow_git_enabled", 0))
    return jsonify(board)


@boards_bp.route("/api/boards/<int:board_id>", methods=["PUT"])
def api_update_board(board_id):
    board = get_board(board_id)
    if not board:
        return jsonify({"error": "Board not found"}), 404
    data = request.get_json() or {}
    updates = []
    args = []
    if "name" in data:
        updates.append("name = ?")
        args.append(data["name"].strip())
    if "workflow_id" in data:
        wf = get_workflow(data["workflow_id"])
        if not wf:
            return jsonify({"error": "Workflow not found"}), 404
        updates.append("workflow_id = ?")
        args.append(data["workflow_id"])
    if "working_directory" in data:
        wd = data["working_directory"].strip()
        wd_path = Path(wd)
        try:
            wd_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return jsonify({"error": f"Cannot create working directory: {e}"}), 400
        updates.append("working_directory = ?")
        args.append(str(wd_path.resolve()))
    if "long_term_vision" in data:
        vision = (data["long_term_vision"] or "").strip() or None
        updates.append("long_term_vision = ?")
        args.append(vision)
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(board_id)
    try:
        run_db(f"UPDATE boards SET {', '.join(updates)} WHERE id = ?", tuple(args))
    except sqlite3.IntegrityError:
        return jsonify({"error": "Board name already exists"}), 409
    add_log(
        "INFO",
        "db_change",
        f"UPDATE boards/{board_id}",
        details={"operation": "UPDATE", "table": "boards", "record_id": board_id},
    )
    return jsonify({"success": True})


@boards_bp.route("/api/boards/<int:board_id>", methods=["DELETE"])
def api_delete_board(board_id):
    board = get_board(board_id)
    if not board:
        return jsonify({"error": "Board not found"}), 404
    run_db("DELETE FROM gate_reviews WHERE ticket_id IN (SELECT id FROM tickets WHERE board_id = ?)", (board_id,))
    run_db("DELETE FROM agent_queue WHERE ticket_id IN (SELECT id FROM tickets WHERE board_id = ?)", (board_id,))
    run_db("DELETE FROM agent_runs WHERE ticket_id IN (SELECT id FROM tickets WHERE board_id = ?)", (board_id,))
    run_db("DELETE FROM comments WHERE ticket_id IN (SELECT id FROM tickets WHERE board_id = ?)", (board_id,))
    run_db("DELETE FROM tickets WHERE board_id = ?", (board_id,))
    run_db("DELETE FROM boards WHERE id = ?", (board_id,))
    add_log(
        "INFO",
        "db_change",
        f"DELETE boards/{board_id}",
        details={"operation": "DELETE", "table": "boards", "record_id": board_id},
    )
    return jsonify({"success": True})
