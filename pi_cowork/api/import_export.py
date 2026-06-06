"""API: Import/Export workflows."""

import sqlite3
from datetime import UTC, datetime

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict
from pi_cowork.models import get_workflow

import_export_bp = Blueprint("import_export", __name__)


@import_export_bp.route("/api/workflows/<int:workflow_id>/export", methods=["GET"])
def api_export_workflow(workflow_id):
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404
    agents = query_db(
        """
        SELECT name, description, model, thinking
        FROM agents WHERE workflow_id = ? ORDER BY name
    """,
        (workflow_id,),
    )
    statuses_rows = query_db(
        """
        SELECT s.name, s.sort_order, s.is_default, s.is_terminal, s.goal, s.model, s.thinking, a.name AS agent_name
        FROM statuses s
        LEFT JOIN agents a ON s.agent_id = a.id
        WHERE s.workflow_id = ?
        ORDER BY s.sort_order
    """,
        (workflow_id,),
    )
    transitions = query_db(
        """
        SELECT fs.name AS from_status_name, ts.name AS to_status_name, t.instructions
        FROM transitions t
        JOIN statuses fs ON t.from_status_id = fs.id
        JOIN statuses ts ON t.to_status_id = ts.id
        WHERE t.workflow_id = ?
        ORDER BY fs.sort_order, ts.sort_order
    """,
        (workflow_id,),
    )
    quality_gates = query_db(
        """
        SELECT qg.*, fs.name AS from_status_name, ts.name AS to_status_name
        FROM quality_gates qg
        JOIN statuses fs ON qg.from_status_id = fs.id
        JOIN statuses ts ON qg.to_status_id = ts.id
        WHERE qg.workflow_id = ?
        ORDER BY qg.sort_order
    """,
        (workflow_id,),
    )
    labels = query_db(
        """
        SELECT name, color
        FROM labels WHERE workflow_id = ?
        ORDER BY name
    """,
        (workflow_id,),
    )
    payload = {
        "version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(),
        "name": wf["name"],
        "description": wf.get("description") or "",
        "agents": [row_to_dict(r) for r in agents],
        "statuses": [row_to_dict(r) for r in statuses_rows],
        "transitions": [row_to_dict(r) for r in transitions],
        "quality_gates": [row_to_dict(r) for r in quality_gates],
        "labels": [row_to_dict(r) for r in labels],
    }
    return jsonify(payload)


@import_export_bp.route("/api/workflows/import", methods=["POST"])
def api_import_workflow():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400
    if data.get("version") != "1.0":
        return jsonify({"error": "Unsupported version. Expected '1.0'"}), 400

    agents_data = data.get("agents")
    statuses_data = data.get("statuses")
    transitions_data = data.get("transitions")
    if (
        not isinstance(agents_data, list)
        or not isinstance(statuses_data, list)
        or not isinstance(transitions_data, list)
    ):
        return jsonify({"error": "agents, statuses, and transitions must be arrays"}), 400

    defaults = [s for s in statuses_data if s.get("is_default")]
    if len(defaults) != 1:
        return jsonify({"error": "Exactly one status must have is_default=true"}), 400

    agent_names = {a.get("name") for a in agents_data if a.get("name")}
    for s in statuses_data:
        an = s.get("agent_name")
        if an is not None and an not in agent_names:
            return jsonify({"error": f"Status '{s.get('name')}' references unknown agent '{an}'"}), 400

    status_names = {s.get("name") for s in statuses_data if s.get("name")}
    for t in transitions_data:
        fs = t.get("from_status_name")
        ts = t.get("to_status_name")
        if fs not in status_names:
            return jsonify({"error": f"Transition references unknown from_status '{fs}'"}), 400
        if ts not in status_names:
            return jsonify({"error": f"Transition references unknown to_status '{ts}'"}), 400

    # Create new workflow
    wf_name = data.get("name", "Imported Workflow").strip()
    if not wf_name:
        wf_name = "Imported Workflow"
    existing = query_db("SELECT 1 FROM workflows WHERE name = ? LIMIT 1", (wf_name,), one=True)
    if existing:
        wf_name = f"{wf_name} {datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    wf_desc = (data.get("description") or "").strip() or None

    # Actually we need the connection directly
    from pi_cowork.db import get_db

    db = get_db()
    try:
        cur = db.execute("INSERT INTO workflows (name, description) VALUES (?, ?)", (wf_name, wf_desc))
        workflow_id = cur.lastrowid

        # Insert agents
        agent_id_map = {}
        for a in agents_data:
            name = a.get("name", "").strip()
            description = a.get("description", "")
            model = a.get("model") or None
            thinking = a.get("thinking") or None
            cur = db.execute(
                "INSERT INTO agents (name, description, workflow_id, model, thinking) VALUES (?, ?, ?, ?, ?)",
                (name, description, workflow_id, model, thinking),
            )
            agent_id_map[name] = cur.lastrowid

        # Insert statuses
        status_id_map = {}
        for s in statuses_data:
            name = s.get("name", "").strip()
            sort_order = int(s.get("sort_order", 0))
            is_default = 1 if s.get("is_default") else 0
            is_terminal = 1 if s.get("is_terminal") else 0
            agent_name = s.get("agent_name")
            agent_id = agent_id_map.get(agent_name) if agent_name else None
            goal = (s.get("goal") or "").strip() or None
            model = s.get("model") or None
            thinking = s.get("thinking") or None
            cur = db.execute(
                "INSERT INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, model, thinking, workflow_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, sort_order, is_default, is_terminal, agent_id, goal, model, thinking, workflow_id),
            )
            status_id_map[name] = cur.lastrowid

        # Insert transitions
        for t in transitions_data:
            from_id = status_id_map[t.get("from_status_name")]
            to_id = status_id_map[t.get("to_status_name")]
            instructions = (t.get("instructions") or "").strip() or None
            db.execute(
                "INSERT INTO transitions (from_status_id, to_status_id, instructions, workflow_id) VALUES (?, ?, ?, ?)",
                (from_id, to_id, instructions, workflow_id),
            )

        # Insert quality gates
        gates_data = data.get("quality_gates", [])
        gate_count = 0
        for g in gates_data:
            from_status_name = g.get("from_status_name")
            to_status_name = g.get("to_status_name")
            if not from_status_name or from_status_name not in status_id_map:
                continue
            if not to_status_name or to_status_name not in status_id_map:
                continue
            gate_type = g.get("gate_type", "manual")
            name = g.get("name", "Unnamed Gate")
            config = g.get("config")
            sort_order = int(g.get("sort_order", 0))
            enabled = 1 if g.get("enabled", True) else 0
            db.execute(
                "INSERT INTO quality_gates (from_status_id, to_status_id, gate_type, name, config, sort_order, enabled, workflow_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    status_id_map[from_status_name],
                    status_id_map[to_status_name],
                    gate_type,
                    name,
                    config,
                    sort_order,
                    enabled,
                    workflow_id,
                ),
            )
            gate_count += 1

        # Insert labels
        labels_data = data.get("labels", [])
        for lbl in labels_data:
            name = lbl.get("name", "").strip()
            color = (lbl.get("color") or "").strip() or "#6b7280"
            db.execute("INSERT INTO labels (name, color, workflow_id) VALUES (?, ?, ?)", (name, color, workflow_id))

        db.commit()
    except (sqlite3.IntegrityError, sqlite3.OperationalError, KeyError, ValueError) as e:
        db.rollback()
        return jsonify({"error": f"Import failed: {e}"}), 400

    return jsonify(
        {
            "success": True,
            "workflow_id": workflow_id,
            "agents": len(agents_data),
            "statuses": len(statuses_data),
            "transitions": len(transitions_data),
            "quality_gates": gate_count,
            "labels": len(labels_data),
        }
    ), 200
