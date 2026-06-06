"""API: Endpoint registry — returns metadata for UI checkboxes."""

from flask import Blueprint, jsonify

from pi_cowork.api_docs import ENDPOINT_REGISTRY

endpoint_registry_bp = Blueprint("endpoint_registry", __name__)


@endpoint_registry_bp.route("/api/endpoint-registry", methods=["GET"])
def api_endpoint_registry():
    """Return grouped endpoint metadata for the workflow UI.

    Response format::

        {
          "endpoints": [
            {
              "key": "ticket_put",
              "category": "Tickets",
              "method": "PUT",
              "path_template": "/api/tickets/{ticket_id}",
              "label": "update ticket (fields: status_id, title, body)"
            },
            ...
          ]
        }
    """
    entries = []
    for entry in ENDPOINT_REGISTRY:
        entries.append(
            {
                "key": entry["key"],
                "category": entry["category"],
                "method": entry["method"],
                "path_template": entry["path_template"],
                "label": entry["label"],
            }
        )
    return jsonify({"endpoints": entries})
