"""API documentation registry and builder for agent prompts.

Provides a centralized registry of all API endpoints that can be exposed to
agents.  Each agent stores a list of endpoint keys (or NULL for the default
set).  ``build_api_docs()`` formats the selected endpoints into the text block
that gets injected into the agent's context message.
"""

from pi_cowork.config import get_config

# ---------------------------------------------------------------------------
# Endpoint Registry
# ---------------------------------------------------------------------------

ENDPOINT_REGISTRY = [
    # ── Tickets (ticket-scoped) ──
    {
        "key": "ticket_put",
        "category": "Tickets",
        "method": "PUT",
        "path_template": "/api/tickets/{ticket_id}",
        "label": (
            "update ticket (fields: status_id, title, body, priority, branch) — "
            "branch only writable when workflow has git_enabled=True"
        ),
        "doc_lines": [
            (
                "- PUT {base_url}/api/tickets/{ticket_id} → update ticket "
                "(fields: status_id, title, body, priority, branch — branch only writable "
                "when workflow has git_enabled=True)"
            ),
        ],
    },
    {
        "key": "ticket_get",
        "category": "Tickets",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}",
        "label": "get ticket details (includes priority; includes branch when git_enabled)",
        "doc_lines": [
            (
                "- GET {base_url}/api/tickets/{ticket_id} → get ticket details "
                "(includes priority; includes branch when git_enabled)"
            ),
        ],
    },
    {
        "key": "ticket_comments_post",
        "category": "Comments",
        "method": "POST",
        "path_template": "/api/tickets/{ticket_id}/comments",
        "label": "add comment (field: body)",
        "doc_lines": [
            "- POST {base_url}/api/tickets/{ticket_id}/comments → add comment (field: body)",
        ],
    },
    {
        "key": "ticket_comments_get",
        "category": "Comments",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/comments",
        "label": "list comments",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/comments → list comments",
        ],
    },
    {
        "key": "ticket_questions_post",
        "category": "Comments",
        "method": "POST",
        "path_template": "/api/tickets/{ticket_id}/questions",
        "label": "ask questions (field: questions, array of {body, options})",
        "doc_lines": [
            (
                "- POST {base_url}/api/tickets/{ticket_id}/questions → ask questions "
                "(field: questions, array of {body, options}). ALWAYS provide the options "
                "field as a JSON array of answer choices whenever possible — humans can "
                "answer with one click instead of typing free text."
            ),
            "  Example: questions=[{'body': 'Which database?', 'options': ['SQLite', 'PostgreSQL']}]",
            (
                "When questions are posted, the agent is paused until a human answers them; "
                "answers appear as formatted comments (**Q:** ... **A:** ...)."
            ),
        ],
    },
    {
        "key": "ticket_questions_get",
        "category": "Comments",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/questions",
        "label": "list questions",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/questions → list questions",
        ],
    },
    {
        "key": "ticket_labels_get",
        "category": "Labels",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/labels",
        "label": "get ticket labels",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/labels → get ticket labels",
        ],
    },
    {
        "key": "ticket_labels_post",
        "category": "Labels",
        "method": "POST",
        "path_template": "/api/tickets/{ticket_id}/labels",
        "label": "set ticket labels (field: label_ids, array of ints)",
        "doc_lines": [
            "- POST {base_url}/api/tickets/{ticket_id}/labels → set ticket labels (field: label_ids, array of ints)",
        ],
    },
    {
        "key": "ticket_agent_runs_get",
        "category": "Agent Runs",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/agent_runs",
        "label": "list agent runs for ticket",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/agent_runs → list agent runs for ticket",
        ],
    },
    {
        "key": "ticket_recurring_get",
        "category": "Recurring",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/recurring",
        "label": "get parent recurring tasks",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/recurring → get parent recurring tasks",
        ],
    },
    {
        "key": "ticket_spawn",
        "category": "Agent Runs",
        "method": "POST",
        "path_template": "/api/tickets/{ticket_id}/spawn",
        "label": "manually re-trigger agent for ticket",
        "doc_lines": [
            "- POST {base_url}/api/tickets/{ticket_id}/spawn → manually re-trigger agent for ticket",
        ],
    },
    # ── Tickets (global list/create) ──
    {
        "key": "tickets_list",
        "category": "Tickets",
        "method": "GET",
        "path_template": "/api/tickets",
        "label": "list tickets (query: board_id, limit, offset)",
        "doc_lines": [
            "- GET {base_url}/api/tickets?board_id={board_id} → list tickets (query: board_id, limit, offset)",
        ],
    },
    {
        "key": "tickets_create",
        "category": "Tickets",
        "method": "POST",
        "path_template": "/api/tickets",
        "label": "create ticket (fields: title, body, board_id, status_id, labels, priority)",
        "doc_lines": [
            "- POST {base_url}/api/tickets → create ticket (fields: title, body, board_id, status_id, labels, "
            "priority)",
        ],
    },
    # ── Boards ──
    {
        "key": "boards_list",
        "category": "Boards",
        "method": "GET",
        "path_template": "/api/boards",
        "label": "list boards",
        "doc_lines": [
            "- GET {base_url}/api/boards → list boards",
        ],
    },
    {
        "key": "board_get",
        "category": "Boards",
        "method": "GET",
        "path_template": "/api/boards/{board_id}",
        "label": "get board details",
        "doc_lines": [
            "- GET {base_url}/api/boards/{board_id} → get board details",
        ],
    },
    # ── Workflows ──
    {
        "key": "workflows_list",
        "category": "Workflows",
        "method": "GET",
        "path_template": "/api/workflows",
        "label": "list workflows",
        "doc_lines": [
            "- GET {base_url}/api/workflows → list workflows",
        ],
    },
    {
        "key": "workflow_get",
        "category": "Workflows",
        "method": "GET",
        "path_template": "/api/workflows/{workflow_id}",
        "label": "get workflow details",
        "doc_lines": [
            "- GET {base_url}/api/workflows/{workflow_id} → get workflow details",
        ],
    },
    # ── Statuses ──
    {
        "key": "statuses_list",
        "category": "Statuses",
        "method": "GET",
        "path_template": "/api/statuses",
        "label": "list statuses for workflow (query: workflow_id)",
        "doc_lines": [
            "- GET {base_url}/api/statuses?workflow_id={workflow_id} → list statuses for workflow",
        ],
    },
    {
        "key": "status_get",
        "category": "Statuses",
        "method": "GET",
        "path_template": "/api/statuses/{status_id}",
        "label": "get status details",
        "doc_lines": [
            "- GET {base_url}/api/statuses/{status_id} → get status details",
        ],
    },
    # ── Transitions ──
    {
        "key": "transitions_list",
        "category": "Transitions",
        "method": "GET",
        "path_template": "/api/transitions",
        "label": "list transitions for workflow (query: workflow_id)",
        "doc_lines": [
            "- GET {base_url}/api/transitions?workflow_id={workflow_id} → list transitions for workflow",
        ],
    },
    {
        "key": "transition_get",
        "category": "Transitions",
        "method": "GET",
        "path_template": "/api/transitions/{transition_id}",
        "label": "get transition details",
        "doc_lines": [
            "- GET {base_url}/api/transitions/{transition_id} → get transition details",
        ],
    },
    # ── Agents ──
    {
        "key": "agents_list",
        "category": "Agents",
        "method": "GET",
        "path_template": "/api/agents",
        "label": "list agents for workflow (query: workflow_id)",
        "doc_lines": [
            "- GET {base_url}/api/agents?workflow_id={workflow_id} → list agents for workflow",
        ],
    },
    {
        "key": "agent_get",
        "category": "Agents",
        "method": "GET",
        "path_template": "/api/agents/{agent_id}",
        "label": "get agent details",
        "doc_lines": [
            "- GET {base_url}/api/agents/{agent_id} → get agent details",
        ],
    },
    # ── Labels ──
    {
        "key": "labels_list",
        "category": "Labels",
        "method": "GET",
        "path_template": "/api/labels",
        "label": "list labels for workflow (query: workflow_id)",
        "doc_lines": [
            "- GET {base_url}/api/labels?workflow_id={workflow_id} → list labels for workflow",
        ],
    },
    # ── Quality Gates ──
    {
        "key": "quality_gates_list",
        "category": "Quality Gates",
        "method": "GET",
        "path_template": "/api/quality_gates",
        "label": "list quality gates (query: from_status_id, to_status_id)",
        "doc_lines": [
            "- GET {base_url}/api/quality_gates?from_status_id={from}&to_status_id={to} → list quality gates for "
            "transition",
        ],
    },
    # ── Gate Reviews ──
    {
        "key": "gate_reviews_list",
        "category": "Gate Reviews",
        "method": "GET",
        "path_template": "/api/gate_reviews",
        "label": "list gate reviews (query: ticket_id)",
        "doc_lines": [
            "- GET {base_url}/api/gate_reviews?ticket_id={ticket_id} → list gate reviews for ticket",
        ],
    },
    # ── Agent Runs ──
    {
        "key": "agent_run_log",
        "category": "Agent Runs",
        "method": "GET",
        "path_template": "/api/agent_runs/{run_id}/log",
        "label": "fetch raw log file for agent run",
        "doc_lines": [
            "- GET {base_url}/api/agent_runs/{run_id}/log → fetch raw log file for agent run",
        ],
    },
    # ── Settings ──
    {
        "key": "settings_list",
        "category": "Settings",
        "method": "GET",
        "path_template": "/api/settings",
        "label": "list all settings",
        "doc_lines": [
            "- GET {base_url}/api/settings → list all settings",
        ],
    },
    {
        "key": "setting_get",
        "category": "Settings",
        "method": "GET",
        "path_template": "/api/settings/{key}",
        "label": "get a single setting value",
        "doc_lines": [
            "- GET {base_url}/api/settings/{key} → get a single setting value",
        ],
    },
    # ── Notifications ──
    {
        "key": "notifications_list",
        "category": "Notifications",
        "method": "GET",
        "path_template": "/api/notifications",
        "label": "list pending notifications",
        "doc_lines": [
            "- GET {base_url}/api/notifications → list pending notifications",
        ],
    },
    # ── Recurring ──
    {
        "key": "recurring_list",
        "category": "Recurring",
        "method": "GET",
        "path_template": "/api/recurring",
        "label": "list recurring tasks for board (query: board_id)",
        "doc_lines": [
            "- GET {base_url}/api/recurring?board_id={board_id} → list recurring tasks for board",
        ],
    },
    {
        "key": "recurring_get",
        "category": "Recurring",
        "method": "GET",
        "path_template": "/api/recurring/{task_id}",
        "label": "get recurring task details",
        "doc_lines": [
            "- GET {base_url}/api/recurring/{task_id} → get recurring task details",
        ],
    },
    # ── DB Backup ──
    {
        "key": "db_backup_list",
        "category": "DB Backup",
        "method": "GET",
        "path_template": "/api/db-backup/list",
        "label": "list all database backups (filename, size, timestamp)",
        "doc_lines": [
            "- GET {base_url}/api/db-backup/list → list all database backups (filename, size, timestamp)",
        ],
    },
    {
        "key": "db_backup_create",
        "category": "DB Backup",
        "method": "POST",
        "path_template": "/api/db-backup/create",
        "label": "create a manual backup of the current database",
        "doc_lines": [
            "- POST {base_url}/api/db-backup/create → create a manual backup of the current database",
        ],
    },
    {
        "key": "db_backup_restore",
        "category": "DB Backup",
        "method": "POST",
        "path_template": "/api/db-backup/restore",
        "label": "restore database from a backup (fields: filename, confirm); requires X-Human-Action header; creates "
        "a pre-restore safety backup "
        "first",
        "doc_lines": [
            "- POST {base_url}/api/db-backup/restore → restore database from a backup (fields: filename, confirm must "
            "be true); requires X-Human-Action header (human-only action); creates a pre-restore safety backup "
            "first",
        ],
    },
    {
        "key": "db_backup_delete",
        "category": "DB Backup",
        "method": "DELETE",
        "path_template": "/api/db-backup/delete",
        "label": "delete a specific backup file (field: filename)",
        "doc_lines": [
            "- DELETE {base_url}/api/db-backup/delete → delete a specific backup file (field: filename)",
        ],
    },
    # ── Ticket Status Overrides ──
    {
        "key": "ticket_status_overrides_get",
        "category": "Ticket Overrides",
        "method": "GET",
        "path_template": "/api/tickets/{ticket_id}/status_overrides",
        "label": "list ticket status overrides (per-status model/thinking overrides)",
        "doc_lines": [
            "- GET {base_url}/api/tickets/{ticket_id}/status_overrides → list ticket status overrides (per-status "
            "model/thinking overrides)",
        ],
    },
    {
        "key": "ticket_status_overrides_put",
        "category": "Ticket Overrides",
        "method": "PUT",
        "path_template": "/api/tickets/{ticket_id}/status_overrides",
        "label": "upsert ticket status override (fields: status_id, model, thinking)",
        "doc_lines": [
            "- PUT {base_url}/api/tickets/{ticket_id}/status_overrides → upsert ticket status override (fields: "
            "status_id, model, thinking)",
        ],
    },
    {
        "key": "ticket_status_override_delete",
        "category": "Ticket Overrides",
        "method": "DELETE",
        "path_template": "/api/tickets/{ticket_id}/status_overrides/{status_id}",
        "label": "clear ticket status override for a specific status",
        "doc_lines": [
            "- DELETE {base_url}/api/tickets/{ticket_id}/status_overrides/{status_id} → clear ticket status override "
            "for a specific status",
        ],
    },
    # ── Knowledge Management ──
    {
        "key": "knowledge_list",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge",
        "label": "list knowledge entries (query: board_id, search, category, auto_context, tags)",
        "doc_lines": [
            "- GET {base_url}/api/knowledge?board_id={board_id} → list knowledge entries (query: board_id, search, "
            "category, auto_context, tags). Omit board_id for global-only; provide board_id for global + "
            "board-specific.",
        ],
    },
    {
        "key": "knowledge_get",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/{entry_id}",
        "label": "get a knowledge entry by ID",
        "doc_lines": [
            "- GET {base_url}/api/knowledge/{entry_id} → get a knowledge entry by ID",
        ],
    },
    {
        "key": "knowledge_create",
        "category": "Knowledge",
        "method": "POST",
        "path_template": "/api/knowledge",
        "label": "create a knowledge entry (fields: title, content, board_id, category, auto_context, tags, "
        "sort_order)",
        "doc_lines": [
            "- POST {base_url}/api/knowledge → create a knowledge entry (fields: title, content, board_id or null for "
            "global, category, auto_context, tags as array of strings, sort_order, created_by "
            "'human'/'agent')",
        ],
    },
    {
        "key": "knowledge_update",
        "category": "Knowledge",
        "method": "PUT",
        "path_template": "/api/knowledge/{entry_id}",
        "label": "update a knowledge entry (fields: title, content, board_id, clear_board_id, category, auto_context, "
        "tags, sort_order)",
        "doc_lines": [
            "- PUT {base_url}/api/knowledge/{entry_id} → update a knowledge entry (fields: title, content, board_id, "
            "clear_board_id, category, auto_context, tags as array of strings, sort_order, updated_by "
            "'human'/'agent'). board_id sets the entry to a specific board; clear_board_id=True sets it to global "
            "(board_id=NULL). Omitting both leaves board_id unchanged. Providing both board_id and clear_board_id=True "
            "is an error. Auto-creates a version history "
            "record.",
        ],
    },
    {
        "key": "knowledge_delete",
        "category": "Knowledge",
        "method": "DELETE",
        "path_template": "/api/knowledge/{entry_id}",
        "label": "delete a knowledge entry (cascades versions and tags)",
        "doc_lines": [
            "- DELETE {base_url}/api/knowledge/{entry_id} → delete a knowledge entry (cascades versions and tags)",
        ],
    },
    {
        "key": "knowledge_search",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/search",
        "label": "search knowledge entries by query (params: q, board_id)",
        "doc_lines": [
            "- GET {base_url}/api/knowledge/search?q=query&board_id={board_id} → search knowledge entries by query "
            "(params: q required, board_id optional. Returns global + board-specific "
            "matches.)",
        ],
    },
    {
        "key": "knowledge_versions",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/{entry_id}/versions",
        "label": "list version history for a knowledge entry",
        "doc_lines": [
            "- GET {base_url}/api/knowledge/{entry_id}/versions → list version history for a knowledge entry",
        ],
    },
    {
        "key": "knowledge_version_restore",
        "category": "Knowledge",
        "method": "POST",
        "path_template": "/api/knowledge/{entry_id}/versions/{version_id}/restore",
        "label": "restore a previous version as current",
        "doc_lines": [
            "- POST {base_url}/api/knowledge/{entry_id}/versions/{version_id}/restore → restore a previous version as "
            "current (field: restored_by "
            "'human'/'agent')",
        ],
    },
]

# Key → registry entry lookup (built once at import time)
_REGISTRY_MAP = {entry["key"]: entry for entry in ENDPOINT_REGISTRY}

# Default set: the 3 endpoints originally hardcoded in spawn_agent()
DEFAULT_ENDPOINT_KEYS = [
    "ticket_put",
    "ticket_comments_post",
    "ticket_questions_post",
]


# Endpoints that must never be exposed to agents, even if explicitly configured.
# Gate review write access allows agents to approve their own quality gates,
# defeating the purpose of manual approval.
AGENT_RESTRICTED_KEYS = {
    "gate_reviews_list",
    "quality_gates_list",
    "notifications_list",
    "db_backup_restore",
}


ALL_ENDPOINT_KEYS = [entry["key"] for entry in ENDPOINT_REGISTRY]


def build_api_docs(selected_keys, ticket_id, base_url=None, has_gates=False, board_id=None, workflow_id=None):
    """Build the API documentation text block for an agent prompt.

    Args:
        selected_keys: List of endpoint keys to include, or None/empty for
            the default set.
        ticket_id: The current ticket ID (used for URL substitution).
        base_url: API base URL. Defaults to config.PI_COWORK_URL.
        has_gates: If True, append the gate_pending note to the ticket_put entry.
        board_id: Board ID for substituting {board_id} in endpoint URLs.
        workflow_id: Workflow ID for substituting {workflow_id} in endpoint URLs.

    Returns:
        A string with one doc line per selected endpoint, ending with the
        closing advisory line.
    """
    if base_url is None:
        base_url = get_config("pi_cowork_url")

    keys = selected_keys if selected_keys else DEFAULT_ENDPOINT_KEYS
    # Filter out restricted endpoints that agents must never see
    keys = [k for k in keys if k not in AGENT_RESTRICTED_KEYS]
    lines = []
    for key in keys:
        entry = _REGISTRY_MAP.get(key)
        if entry is None:
            continue
        for line_template in entry["doc_lines"]:
            line = (
                line_template.replace("{base_url}", base_url)
                .replace("{ticket_id}", str(ticket_id))
                .replace("{board_id}", str(board_id or ""))
                .replace("{workflow_id}", str(workflow_id or ""))
            )
            lines.append(line)

    # Conditional gate_pending note for ticket_put
    if has_gates and "ticket_put" in keys:
        gate_note = ' If response has "gate_pending": true, the move is blocked for human approval — you MUST NOT '
        "attempt to approve or bypass the gate review yourself. Add a comment and "
        "stop."
        # Append it to the first line that contains ticket_put
        for i, line in enumerate(lines):
            if ticket_id and f"/api/tickets/{ticket_id}" in line and "PUT" in line:
                lines[i] += gate_note
                break

    lines.append(
        "IMPORTANT: You must NOT call any gate review, notification resolve, or\n"
        "other approval/rejection endpoints. Quality gates exist for human oversight.\n"
        "Never attempt to approve your own work or bypass a gate review.\n"
        "If you are blocked by a gate, add a comment to the ticket and stop."
    )
    lines.append("If anything is ambiguous or missing, ask clarifying questions before proceeding.")
    return "\n".join(lines)


def build_assistant_api_docs(selected_keys, base_url=None):
    """Build the API documentation text block for the assistant system prompt.

    Unlike ``build_api_docs()`` (agent prompts), this:
    * defaults to **all** registry endpoints when *selected_keys* is null/empty
      (broad default for the assistant)
    * substitutes only ``{base_url}`` — ``{ticket_id}``, ``{board_id}`` and
      ``{workflow_id}`` are left literal because the assistant has no single
      ticket context
    * does **not** append agent-specific advisory lines (gate_pending, etc.)

    Args:
        selected_keys: List of endpoint keys, or None/empty for all endpoints.
        base_url: API base URL. Defaults to ``config.PI_COWORK_URL``.

    Returns:
        A string starting with ``## API Documentation`` followed by one doc
        line per selected endpoint.
    """
    if base_url is None:
        base_url = get_config("pi_cowork_url")

    keys = selected_keys if selected_keys else ALL_ENDPOINT_KEYS
    lines = ["## API Documentation"]
    for key in keys:
        entry = _REGISTRY_MAP.get(key)
        if entry is None:
            continue
        for line_template in entry["doc_lines"]:
            line = line_template.replace("{base_url}", base_url)
            lines.append(line)

    return "\n".join(lines)
