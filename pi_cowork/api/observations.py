"""API: Observations — read-only aggregated view across event_log, system_logs,
agent_runs, and gate_reviews.
"""

from flask import Blueprint, jsonify, request

from pi_cowork.db import get_db

observations_bp = Blueprint("observations", __name__)


def _get_observations(
    ticket_id=None,
    obs_type=None,
    date_from=None,
    date_to=None,
    search=None,
    page=1,
    per_page=50,
):
    db = get_db()

    # Build the unified subquery (no per-table WHERE — filters applied on outer query)
    unified_subquery = """
        SELECT
            id,
            'event_log' AS source_table,
            id AS source_id,
            event_name AS type,
            NULL AS ticket_id,
            NULL AS agent_run_id,
            event_name AS title,
            payload AS body,
            created_at
        FROM event_log
        UNION ALL
        SELECT
            id,
            'system_logs' AS source_table,
            id AS source_id,
            action_type AS type,
            ticket_id,
            NULL AS agent_run_id,
            level || ' ' || action_type AS title,
            COALESCE(message, '') || COALESCE('\n' || details, '') AS body,
            timestamp AS created_at
        FROM system_logs
        UNION ALL
        SELECT
            id,
            'agent_runs' AS source_table,
            id AS source_id,
            status AS type,
            ticket_id,
            id AS agent_run_id,
            'Agent run ' || status AS title,
            'Agent ID ' || agent_id || ' in status ' || status
            || COALESCE(' (exit code ' || exit_code || ')', '') AS body,
            started_at AS created_at
        FROM agent_runs
        UNION ALL
        SELECT
            id,
            'gate_reviews' AS source_table,
            id AS source_id,
            status AS type,
            ticket_id,
            NULL AS agent_run_id,
            'Gate review ' || status AS title,
            output AS body,
            created_at
        FROM gate_reviews
    """

    conditions = []
    params = []

    if ticket_id is not None:
        conditions.append("ticket_id = ?")
        params.append(ticket_id)
    if obs_type:
        conditions.append("type = ?")
        params.append(obs_type)
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to)
    if search:
        conditions.append("(title LIKE ? OR body LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    union_sql = "".join(
        [
            "SELECT * FROM (",
            unified_subquery,
            ") AS combined ",
            where_clause,
            " ORDER BY created_at DESC LIMIT ? OFFSET ?",
        ]
    )

    count_sql = "".join(
        [
            "SELECT COUNT(*) FROM (",
            unified_subquery,
            ") AS combined ",
            where_clause,
        ]
    )

    offset = (page - 1) * per_page
    query_params = params + [per_page, offset]
    count_params = params

    rows = db.execute(union_sql, query_params).fetchall()
    total = db.execute(count_sql, count_params).fetchone()[0]

    observations = []
    for row in rows:
        observations.append(
            {
                "id": row["id"],
                "source_table": row["source_table"],
                "source_id": row["source_id"],
                "type": row["type"],
                "ticket_id": row["ticket_id"],
                "agent_run_id": row["agent_run_id"],
                "title": row["title"],
                "body": row["body"],
                "created_at": row["created_at"],
            }
        )

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return {
        "observations": observations,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


@observations_bp.route("/api/observations", methods=["GET"])
def api_observations():
    """Return paginated, filtered observations across all audit tables."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    ticket_id = request.args.get("ticket_id", type=int)
    obs_type = request.args.get("type")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    search = request.args.get("search")

    result = _get_observations(
        ticket_id=ticket_id,
        obs_type=obs_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        page=page,
        per_page=per_page,
    )
    return jsonify(result)
