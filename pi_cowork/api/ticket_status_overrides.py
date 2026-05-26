"""API: Ticket-level model & thinking overrides per status."""

from flask import Blueprint, jsonify, request

from pi_cowork.db import query_db, row_to_dict, run_db
from pi_cowork.models import (
    get_ticket_status_overrides, get_ticket_status_override,
    set_ticket_status_override, delete_ticket_status_override,
    get_status, get_agent,
)
from pi_cowork.api.pi_models import get_thinking_levels, get_model_ids

ticket_status_overrides_bp = Blueprint('ticket_status_overrides', __name__)


@ticket_status_overrides_bp.route('/api/tickets/<int:ticket_id>/status_overrides', methods=['GET'])
def api_get_ticket_status_overrides(ticket_id):
    """List all overrides for this ticket, enriched with status info and cascade data."""
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    overrides = get_ticket_status_overrides(ticket_id)

    # Enrich each override with cascade info for the UI
    for o in overrides:
        status = get_status(o['status_id'])
        if status:
            # Determine effective model and its source
            if o.get('model') and o['model'].strip():
                o['effective_model'] = o['model'].strip()
                o['model_source'] = 'ticket'
            elif status.get('model') and status['model'].strip():
                o['effective_model'] = status['model'].strip()
                o['model_source'] = 'status'
            elif status.get('agent_id'):
                agent = get_agent(status['agent_id'])
                if agent and agent.get('model'):
                    o['effective_model'] = agent['model']
                    o['model_source'] = 'agent'
                else:
                    o['effective_model'] = None
                    o['model_source'] = 'default'
            else:
                o['effective_model'] = None
                o['model_source'] = 'default'

            # Determine effective thinking and its source
            if o.get('thinking') and o['thinking'].strip():
                o['effective_thinking'] = o['thinking'].strip()
                o['thinking_source'] = 'ticket'
            elif status.get('thinking') and status['thinking'].strip():
                o['effective_thinking'] = status['thinking'].strip()
                o['thinking_source'] = 'status'
            elif status.get('agent_id'):
                agent = get_agent(status['agent_id'])
                if agent and agent.get('thinking'):
                    o['effective_thinking'] = agent['thinking']
                    o['thinking_source'] = 'agent'
                else:
                    o['effective_thinking'] = None
                    o['thinking_source'] = 'default'
            else:
                o['effective_thinking'] = None
                o['thinking_source'] = 'default'

            o['agent_id'] = status.get('agent_id')
        else:
            o['effective_model'] = None
            o['model_source'] = 'default'
            o['effective_thinking'] = None
            o['thinking_source'] = 'default'
            o['agent_id'] = None

    return jsonify(overrides)


@ticket_status_overrides_bp.route('/api/tickets/<int:ticket_id>/status_overrides', methods=['PUT'])
def api_set_ticket_status_override(ticket_id):
    """Upsert a ticket-status override."""
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    data = request.get_json() or {}
    status_id = data.get('status_id')
    if status_id is None:
        return jsonify({"error": "status_id is required"}), 400

    status = get_status(status_id)
    if not status:
        return jsonify({"error": "Status not found"}), 404

    model = data.get('model')
    thinking = data.get('thinking')

    # Validate model if provided
    if model is not None and model:
        valid_models = get_model_ids()
        if valid_models and model not in valid_models:
            return jsonify({"error": f"model must be one of: {', '.join(valid_models)}"}), 400

    # Validate thinking if provided
    if thinking is not None and thinking:
        valid_thinking = get_thinking_levels()
        if thinking not in valid_thinking:
            return jsonify({"error": f"thinking must be one of: {', '.join(valid_thinking)}"}), 400

    # Treat empty string / null as "clear this field" for the override
    # but keep the override row if at least one field is non-null
    model_val = model if model else None
    thinking_val = thinking if thinking else None

    # If both are None, delete the override entirely
    if model_val is None and thinking_val is None:
        delete_ticket_status_override(ticket_id, status_id)
        return jsonify({"success": True, "action": "deleted"})

    override = set_ticket_status_override(ticket_id, status_id, model=model_val, thinking=thinking_val)
    return jsonify(override)


@ticket_status_overrides_bp.route('/api/tickets/<int:ticket_id>/status_overrides/<int:status_id>', methods=['DELETE'])
def api_delete_ticket_status_override(ticket_id, status_id):
    """Clear a ticket-level override for a specific status."""
    ticket = query_db("SELECT id FROM tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        return jsonify({"error": "Ticket not found"}), 404

    delete_ticket_status_override(ticket_id, status_id)
    return jsonify({"success": True})