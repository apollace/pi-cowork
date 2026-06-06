"""API: System Logs — list, filter, paginate, and export."""

from flask import Blueprint, Response, jsonify, request

from pi_cowork.system_logs import export_logs_text, get_system_log, get_system_logs

system_logs_bp = Blueprint("system_logs", __name__)


def _check_same_origin():
    """Reject requests to sensitive system_logs endpoints from external origins.

    This is a targeted mitigation: system_logs expose request/response bodies
    which may contain sensitive data, so we restrict access to same-origin
    browser requests (valid Origin/Referer header or local direct access).
    A full app-wide authentication system should be added separately.
    """
    from flask import request as flask_request

    origin = flask_request.headers.get("Origin", "")
    referer = flask_request.headers.get("Referer", "")
    # Allow direct API calls (no Origin/Referer — e.g. curl from localhost, tests)
    if not origin and not referer:
        return None
    host = flask_request.host
    for header_val in (origin, referer):
        if header_val:
            # Extract host from URL
            # e.g. "http://localhost:5000/api/..." → "localhost:5000"
            try:
                from urllib.parse import urlparse

                parsed = urlparse(header_val)
                if parsed.netloc == host:
                    return None  # same origin — OK
            except Exception:  # noqa: S112
                # Ignore malformed header values
                continue
    return jsonify({"error": "Forbidden: cross-origin requests are not allowed"}), 403


@system_logs_bp.route("/api/system_logs", methods=["GET"])
def api_system_logs():
    """Return paginated, filtered system logs."""
    origin_err = _check_same_origin()
    if origin_err:
        return origin_err
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    level = request.args.get("level")
    action_type = request.args.get("action_type")
    ticket_id = request.args.get("ticket_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")

    result = get_system_logs(
        page=page,
        per_page=per_page,
        level=level,
        action_type=action_type,
        ticket_id=ticket_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return jsonify(result)


@system_logs_bp.route("/api/system_logs/<int:log_id>", methods=["GET"])
def api_system_log_detail(log_id):
    """Return a single system log entry by ID."""
    origin_err = _check_same_origin()
    if origin_err:
        return origin_err
    log = get_system_log(log_id)
    if log is None:
        return jsonify({"error": "Log entry not found"}), 404
    return jsonify(log)


@system_logs_bp.route("/api/system_logs/export", methods=["GET"])
def api_system_logs_export():
    """Export filtered system logs as plain text for download."""
    origin_err = _check_same_origin()
    if origin_err:
        return origin_err
    level = request.args.get("level")
    action_type = request.args.get("action_type")
    ticket_id = request.args.get("ticket_id", type=int)
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")

    # Export all matching logs (no pagination, up to 10000)
    text = export_logs_text(
        per_page=10000,
        level=level,
        action_type=action_type,
        ticket_id=ticket_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    return Response(
        text, mimetype="text/plain", headers={"Content-Disposition": "attachment; filename=system_logs.txt"}
    )
