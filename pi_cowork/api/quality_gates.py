"""API: Quality Gates CRUD."""

import json
import sqlite3

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, run_db, row_to_dict
from pi_cowork.models import get_status, get_workflow
from pi_cowork.system_logs import add_log

quality_gates_bp = Blueprint('quality_gates', __name__)


@quality_gates_bp.route('/api/quality_gates', methods=['GET'])
def api_quality_gates():
    from_status_id = request.args.get('from_status_id', type=int)
    to_status_id = request.args.get('to_status_id', type=int)
    workflow_id = request.args.get('workflow_id', type=int)
    if from_status_id is not None and to_status_id is not None:
        rows = query_db(
            "SELECT * FROM quality_gates WHERE from_status_id = ? AND to_status_id = ? ORDER BY sort_order",
            (from_status_id, to_status_id)
        )
    elif workflow_id:
        rows = query_db(
            """SELECT qg.*, fs.name AS from_status_name, ts.name AS to_status_name
               FROM quality_gates qg
               JOIN statuses fs ON qg.from_status_id = fs.id
               JOIN statuses ts ON qg.to_status_id = ts.id
               WHERE qg.workflow_id = ?
               ORDER BY qg.sort_order""",
            (workflow_id,)
        )
    else:
        return jsonify({"error": "from_status_id+to_status_id pair or workflow_id is required"}), 400
    return jsonify([row_to_dict(r) for r in rows])


@quality_gates_bp.route('/api/quality_gates', methods=['POST'])
def api_create_quality_gate():
    data = request.get_json() or {}
    from_status_id = data.get('from_status_id')
    to_status_id = data.get('to_status_id')
    gate_type = (data.get('gate_type') or '').strip()
    name = (data.get('name') or '').strip()
    config = data.get('config')
    sort_order = data.get('sort_order', 0)
    workflow_id = data.get('workflow_id')

    if not from_status_id or not to_status_id or not gate_type or not name or not workflow_id:
        return jsonify({"error": "from_status_id, to_status_id, gate_type, name, and workflow_id are required"}), 400
    if gate_type not in ('manual', 'cli'):
        return jsonify({"error": "gate_type must be 'manual' or 'cli'"}), 400
    from_status = get_status(from_status_id)
    to_status = get_status(to_status_id)
    if not from_status:
        return jsonify({"error": "From status not found"}), 404
    if not to_status:
        return jsonify({"error": "To status not found"}), 404
    if from_status['workflow_id'] != workflow_id or to_status['workflow_id'] != workflow_id:
        return jsonify({"error": "Both statuses must belong to the same workflow"}), 400
    wf = get_workflow(workflow_id)
    if not wf:
        return jsonify({"error": "Workflow not found"}), 404

    config_str = json.dumps(config) if isinstance(config, dict) else (config or None)
    enabled = 1 if data.get('enabled', True) else 0

    try:
        cur = run_db(
            "INSERT INTO quality_gates (from_status_id, to_status_id, gate_type, name, config, sort_order, enabled, workflow_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (from_status_id, to_status_id, gate_type, name, config_str, int(sort_order), enabled, workflow_id)
        )
        add_log('INFO', 'db_change', f'INSERT quality_gates/{cur.lastrowid}', details={'operation': 'INSERT', 'table': 'quality_gates', 'record_id': cur.lastrowid})
        return jsonify({"id": cur.lastrowid}), 201
    except sqlite3.IntegrityError as e:
        return jsonify({"error": f"Failed to create quality gate: {e}"}), 409


@quality_gates_bp.route('/api/quality_gates/<int:gate_id>', methods=['GET'])
def api_get_quality_gate(gate_id):
    row = query_db("SELECT * FROM quality_gates WHERE id = ?", (gate_id,), one=True)
    if not row:
        return jsonify({"error": "Quality gate not found"}), 404
    return jsonify(row_to_dict(row))


@quality_gates_bp.route('/api/quality_gates/<int:gate_id>', methods=['PUT'])
def api_update_quality_gate(gate_id):
    gate = query_db("SELECT * FROM quality_gates WHERE id = ?", (gate_id,), one=True)
    if not gate:
        return jsonify({"error": "Quality gate not found"}), 404
    data = request.get_json() or {}
    updates = []
    args = []
    if 'name' in data:
        updates.append("name = ?")
        args.append(data['name'].strip())
    if 'gate_type' in data:
        if data['gate_type'] not in ('manual', 'cli'):
            return jsonify({"error": "gate_type must be 'manual' or 'cli'"}), 400
        updates.append("gate_type = ?")
        args.append(data['gate_type'])
    if 'config' in data:
        config = data['config']
        config_str = json.dumps(config) if isinstance(config, dict) else (config or None)
        updates.append("config = ?")
        args.append(config_str)
    if 'sort_order' in data:
        updates.append("sort_order = ?")
        args.append(int(data['sort_order']))
    if 'enabled' in data:
        updates.append("enabled = ?")
        args.append(1 if data['enabled'] else 0)
    if 'from_status_id' in data:
        from_status_id = int(data['from_status_id'])
        status = get_status(from_status_id)
        if not status:
            return jsonify({"error": "From status not found"}), 404
        wf_id = gate['workflow_id']
        if status['workflow_id'] != wf_id:
            return jsonify({"error": "Status must belong to the gate's workflow"}), 400
        updates.append("from_status_id = ?")
        args.append(from_status_id)
    if 'to_status_id' in data:
        to_status_id = int(data['to_status_id'])
        status = get_status(to_status_id)
        if not status:
            return jsonify({"error": "To status not found"}), 404
        wf_id = gate['workflow_id']
        if status['workflow_id'] != wf_id:
            return jsonify({"error": "Status must belong to the gate's workflow"}), 400
        updates.append("to_status_id = ?")
        args.append(to_status_id)
    if not updates:
        return jsonify({"error": "No fields to update"}), 400
    args.append(gate_id)
    run_db(f"UPDATE quality_gates SET {', '.join(updates)} WHERE id = ?", tuple(args))
    add_log('INFO', 'db_change', f'UPDATE quality_gates/{gate_id}', details={'operation': 'UPDATE', 'table': 'quality_gates', 'record_id': gate_id})
    return jsonify({"success": True})


@quality_gates_bp.route('/api/quality_gates/<int:gate_id>', methods=['DELETE'])
def api_delete_quality_gate(gate_id):
    run_db("DELETE FROM quality_gates WHERE id = ?", (gate_id,))
    add_log('INFO', 'db_change', f'DELETE quality_gates/{gate_id}', details={'operation': 'DELETE', 'table': 'quality_gates', 'record_id': gate_id})
    return jsonify({"success": True})