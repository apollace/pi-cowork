"""API documentation registry and builder for agent prompts.

Provides a centralized registry of all API endpoints that can be exposed to
agents.  Each agent stores a list of endpoint keys (or NULL for the default
set).  ``build_api_docs()`` formats the selected endpoints into the text block
that gets injected into the agent's context message.
"""

from pi_cowork.auth import is_auth_enabled
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
            (
                "- GET {base_url}/api/tickets/{ticket_id}/agent_runs → list agent runs "
                "for ticket (includes elapsed_seconds)"
            ),
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
        "label": "manually re-trigger agent for ticket (optional field: reason)",
        "doc_lines": [
            "- POST {base_url}/api/tickets/{ticket_id}/spawn → manually re-trigger",
            "  agent for ticket (optional field: reason)",
        ],
    },
    {
        "key": "feedback_post",
        "category": "Feedback",
        "method": "POST",
        "path_template": "/api/feedback",
        "label": "create manual run feedback (fields: run_id, ticket_id, reason, expected_behavior)",
        "doc_lines": [
            "- POST {base_url}/api/feedback → create manual run feedback (fields: run_id, ticket_id, reason, "
            "expected_behavior). Returns 201 with feedback_id.",
        ],
    },
    {
        "key": "feedback_put",
        "category": "Feedback",
        "method": "PUT",
        "path_template": "/api/feedback/{feedback_id}",
        "label": "update feedback reason and expected_behavior (human-only)",
        "doc_lines": [
            "- PUT {base_url}/api/feedback/{feedback_id} → update feedback reason and expected_behavior (human-only)",
        ],
    },
    {
        "key": "feedback_list",
        "category": "Feedback",
        "method": "GET",
        "path_template": "/api/feedback",
        "label": (
            "list feedback rows (query: consumed, limit, feedback_type, ticket_id, "
            "agent_id, board_id, workflow_id, date_from, date_to, search, page, per_page)"
        ),
        "doc_lines": [
            "- GET {base_url}/api/feedback → list feedback rows (query: consumed (tristate — missing = all, "
            "true = consumed only, false = unconsumed only), feedback_type, ticket_id, agent_id, board_id, "
            "workflow_id, date_from, date_to, search, page, per_page). Returns paginated envelope {feedback, total, "
            "page, per_page, total_pages} with enriched feedback including preview, runtime context, board_id, "
            "board_name, workflow_id, and workflow_name.",
        ],
    },
    {
        "key": "feedback_preview",
        "category": "Feedback",
        "method": "GET",
        "path_template": "/api/feedback/{feedback_id}/preview",
        "label": "get canonical structured JSON preview for a feedback row",
        "doc_lines": [
            "- GET {base_url}/api/feedback/{feedback_id}/preview → get canonical structured JSON preview for a "
            "feedback row (includes ticket, agent, run, gate review, reason, expected_behavior, context, created_at, "
            "plus nested board and workflow objects).",
        ],
    },
    {
        "key": "feedback_consume",
        "category": "Feedback",
        "method": "POST",
        "path_template": "/api/feedback/{feedback_id}/consume",
        "label": "mark feedback as consumed (optional body: consumed_by_run_id)",
        "doc_lines": [
            "- POST {base_url}/api/feedback/{feedback_id}/consume → mark feedback as consumed. Optional JSON body: "
            "consumed_by_run_id. Returns 404 if not found, 409 if already consumed.",
        ],
    },
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
    {
        "key": "agent_put",
        "category": "Agents",
        "method": "PUT",
        "path_template": "/api/agents/{agent_id}",
        "label": (
            "update agent (fields: name, description, model, thinking, "
            "api_endpoints, skill_names (deprecated), excluded_skill_names)"
        ),
        "doc_lines": [
            (
                "- PUT {base_url}/api/agents/{agent_id} → update agent"
                " (fields: name, description, model, thinking, api_endpoints,"
                " skill_names (deprecated), excluded_skill_names)"
            ),
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
    {
        "key": "status_put",
        "category": "Statuses",
        "method": "PUT",
        "path_template": "/api/statuses/{status_id}",
        "label": ("update status (fields: name, sort_order, is_default, is_terminal, agent_id, goal, model, thinking)"),
        "doc_lines": [
            (
                "- PUT {base_url}/api/statuses/{status_id} → update status"
                " (fields: name, sort_order, is_default, is_terminal, agent_id,"
                " goal, model, thinking)"
            ),
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
    {
        "key": "transition_put",
        "category": "Transitions",
        "method": "PUT",
        "path_template": "/api/transitions/{transition_id}",
        "label": "update transition instructions",
        "doc_lines": [
            "- PUT {base_url}/api/transitions/{transition_id} → update transition instructions",
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
    # ── Skills ──
    {
        "key": "skills_list",
        "category": "Skills",
        "method": "GET",
        "path_template": "/api/skills",
        "label": "list skills (query: workflow_id optional, include_system optional; omit workflow_id for global-only)",
        "doc_lines": [
            "- GET {base_url}/api/skills?workflow_id={workflow_id} → list skills for workflow (workflow + global + "
            "system). Omit workflow_id to list only global skills. Add include_system=true to include system skills "
            "when listing without workflow_id.",
        ],
    },
    {
        "key": "skill_create",
        "category": "Skills",
        "method": "POST",
        "path_template": "/api/skills",
        "label": "create a skill (fields: name, description, content, workflow_id optional)",
        "doc_lines": [
            "- POST {base_url}/api/skills → create a skill (fields: name, description, content, workflow_id). "
            "Omit workflow_id to create a global skill.",
        ],
    },
    {
        "key": "skill_export",
        "category": "Skills",
        "method": "GET",
        "path_template": "/api/skills/{name}/export",
        "label": "export skill as ZIP (query: workflow_id optional; falls back to global)",
        "doc_lines": [
            "- GET {base_url}/api/skills/{name}/export?workflow_id={workflow_id} → download skill ZIP (falls back to "
            "global scope if workflow_id omitted or skill not found in workflow)",
        ],
    },
    {
        "key": "skill_delete",
        "category": "Skills",
        "method": "DELETE",
        "path_template": "/api/skills/{name}",
        "label": "delete skill folder (query: workflow_id optional; omit for global)",
        "doc_lines": [
            "- DELETE {base_url}/api/skills/{name}?workflow_id={workflow_id} → remove skill folder. "
            "Omit workflow_id to delete from global scope.",
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
    {
        "key": "ticket_answers_post",
        "category": "Comments",
        "method": "POST",
        "path_template": "/api/tickets/{ticket_id}/answers",
        "label": "batch-answer questions (field: answers, array of {question_id, answer})",
        "doc_lines": [
            (
                "- POST {base_url}/api/tickets/{ticket_id}/answers → batch-answer questions "
                "(field: answers, array of {question_id, answer}). Returns 200 with answered count."
            ),
        ],
    },
    {
        "key": "question_answer",
        "category": "Comments",
        "method": "PUT",
        "path_template": "/api/questions/{question_id}/answer",
        "label": "answer a single question (field: answer)",
        "doc_lines": [
            (
                "- PUT {base_url}/api/questions/{question_id}/answer → answer a single question "
                "(field: answer). Posts the answer as a formatted comment on the ticket."
            ),
        ],
    },
    {
        "key": "ticket_labels_delete",
        "category": "Labels",
        "method": "DELETE",
        "path_template": "/api/tickets/{ticket_id}/labels",
        "label": "remove a label from ticket (query: label_id)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/tickets/{ticket_id}/labels?label_id={label_id} → remove a "
                "single label from the ticket (query: label_id required)."
            ),
        ],
    },
    {
        "key": "boards_create",
        "category": "Boards",
        "method": "POST",
        "path_template": "/api/boards",
        "label": "create board (fields: name, workflow_id, working_directory, long_term_vision)",
        "doc_lines": [
            (
                "- POST {base_url}/api/boards → create board (fields: name, workflow_id, "
                "working_directory, long_term_vision). Returns 201 with board id."
            ),
        ],
    },
    {
        "key": "board_put",
        "category": "Boards",
        "method": "PUT",
        "path_template": "/api/boards/{board_id}",
        "label": "update board (fields: name, workflow_id, working_directory, long_term_vision)",
        "doc_lines": [
            (
                "- PUT {base_url}/api/boards/{board_id} → update board (fields: name, workflow_id, "
                "working_directory, long_term_vision)."
            ),
        ],
    },
    {
        "key": "board_delete",
        "category": "Boards",
        "method": "DELETE",
        "path_template": "/api/boards/{board_id}",
        "label": "delete board (destroys all tickets, comments, runs, queue, recurring)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/boards/{board_id} → delete board. Destructive: permanently "
                "deletes all tickets, comments, agent runs, queue entries, and recurring tasks for "
                "the board."
            ),
        ],
    },
    {
        "key": "boards_stats",
        "category": "Boards",
        "method": "GET",
        "path_template": "/api/boards/stats",
        "label": "get ticket counts per board",
        "doc_lines": [
            ("- GET {base_url}/api/boards/stats → get ticket counts per board (returns {board_id: ticket_count})."),
        ],
    },
    {
        "key": "workflows_create",
        "category": "Workflows",
        "method": "POST",
        "path_template": "/api/workflows",
        "label": "create workflow (fields: name, description, git_enabled)",
        "doc_lines": [
            (
                "- POST {base_url}/api/workflows → create workflow (fields: name, description, "
                "git_enabled boolean default false). Returns 201 with workflow id."
            ),
        ],
    },
    {
        "key": "workflow_put",
        "category": "Workflows",
        "method": "PUT",
        "path_template": "/api/workflows/{workflow_id}",
        "label": "update workflow (fields: name, description, git_enabled)",
        "doc_lines": [
            (
                "- PUT {base_url}/api/workflows/{workflow_id} → update workflow (fields: name, "
                "description, git_enabled)."
            ),
        ],
    },
    {
        "key": "workflow_delete",
        "category": "Workflows",
        "method": "DELETE",
        "path_template": "/api/workflows/{workflow_id}",
        "label": "delete workflow (blocked if any boards use it)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/workflows/{workflow_id} → delete workflow. Blocked (409) if "
                "any boards reference it; otherwise cascades agents, statuses, transitions, gates, "
                "and labels."
            ),
        ],
    },
    {
        "key": "workflow_export",
        "category": "Workflows",
        "method": "GET",
        "path_template": "/api/workflows/{workflow_id}/export",
        "label": "export workflow as JSON (agents, statuses, transitions, gates, labels)",
        "doc_lines": [
            (
                "- GET {base_url}/api/workflows/{workflow_id}/export → export the workflow as a JSON "
                "document (agents, statuses, transitions, quality_gates, labels)."
            ),
        ],
    },
    {
        "key": "workflow_import",
        "category": "Workflows",
        "method": "POST",
        "path_template": "/api/workflows/import",
        "label": "import workflow from JSON (creates a new workflow; appends timestamp on name clash)",
        "doc_lines": [
            (
                "- POST {base_url}/api/workflows/import → import a workflow from JSON body (version "
                "'1.0', agents, statuses, transitions, optional quality_gates/labels). Creates a NEW "
                "workflow; appends a timestamp if the name collides."
            ),
        ],
    },
    {
        "key": "agents_create",
        "category": "Agents",
        "method": "POST",
        "path_template": "/api/agents",
        "label": (
            "create agent (fields: name, description, workflow_id, model, thinking, "
            "api_endpoints, skill_names (deprecated), excluded_skill_names)"
        ),
        "doc_lines": [
            (
                "- POST {base_url}/api/agents → create agent (fields: name, description, "
                "workflow_id, model, thinking, api_endpoints (array of keys or null for defaults), "
                "skill_names (deprecated), excluded_skill_names). Returns 201 with agent id."
            ),
        ],
    },
    {
        "key": "agent_delete",
        "category": "Agents",
        "method": "DELETE",
        "path_template": "/api/agents/{agent_id}",
        "label": "delete agent (blocked if assigned to a status)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/agents/{agent_id} → delete agent. Blocked (409) if the "
                "agent is assigned to any status."
            ),
        ],
    },
    {
        "key": "statuses_create",
        "category": "Statuses",
        "method": "POST",
        "path_template": "/api/statuses",
        "label": (
            "create status (fields: name, sort_order, workflow_id, is_default, is_terminal, "
            "agent_id, goal, model, thinking)"
        ),
        "doc_lines": [
            (
                "- POST {base_url}/api/statuses → create status (fields: name, sort_order, "
                "workflow_id, is_default, is_terminal, agent_id, goal, model, thinking). Returns "
                "201 with status id."
            ),
        ],
    },
    {
        "key": "status_delete",
        "category": "Statuses",
        "method": "DELETE",
        "path_template": "/api/statuses/{status_id}",
        "label": "delete status (blocked if used by tickets or transitions; cascades gates and reviews)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/statuses/{status_id} → delete status. Blocked (409) if "
                "used by tickets or transitions; otherwise cascades quality gates and gate reviews."
            ),
        ],
    },
    {
        "key": "transitions_create",
        "category": "Transitions",
        "method": "POST",
        "path_template": "/api/transitions",
        "label": "create transition (fields: from_status_id, to_status_id, instructions, workflow_id)",
        "doc_lines": [
            (
                "- POST {base_url}/api/transitions → create transition (fields: from_status_id, "
                "to_status_id, instructions, workflow_id). Returns 201 with transition id."
            ),
        ],
    },
    {
        "key": "transition_delete",
        "category": "Transitions",
        "method": "DELETE",
        "path_template": "/api/transitions/{transition_id}",
        "label": "delete transition",
        "doc_lines": [
            "- DELETE {base_url}/api/transitions/{transition_id} → delete transition.",
        ],
    },
    {
        "key": "quality_gates_create",
        "category": "Quality Gates",
        "method": "POST",
        "path_template": "/api/quality_gates",
        "label": (
            "create gate (fields: from_status_id, to_status_id, gate_type, name, config, "
            "sort_order, enabled, notify_on_failure, include_in_feedback, workflow_id)"
        ),
        "doc_lines": [
            (
                "- POST {base_url}/api/quality_gates → create gate (fields: from_status_id, "
                "to_status_id, gate_type 'manual'/'cli', name, config (JSON, e.g. "
                '{"command":"pytest"} for cli), sort_order, enabled, notify_on_failure, '
                "include_in_feedback, workflow_id). Returns 201 with gate id."
            ),
        ],
    },
    {
        "key": "quality_gate_get",
        "category": "Quality Gates",
        "method": "GET",
        "path_template": "/api/quality_gates/{gate_id}",
        "label": "get quality gate details",
        "doc_lines": [
            "- GET {base_url}/api/quality_gates/{gate_id} → get quality gate details",
        ],
    },
    {
        "key": "quality_gate_put",
        "category": "Quality Gates",
        "method": "PUT",
        "path_template": "/api/quality_gates/{gate_id}",
        "label": (
            "update gate (fields: name, gate_type, config, sort_order, enabled, "
            "notify_on_failure, include_in_feedback, from_status_id, to_status_id)"
        ),
        "doc_lines": [
            (
                "- PUT {base_url}/api/quality_gates/{gate_id} → update gate (fields: name, "
                "gate_type, config, sort_order, enabled, notify_on_failure, include_in_feedback, "
                "from_status_id, to_status_id)."
            ),
        ],
    },
    {
        "key": "quality_gate_delete",
        "category": "Quality Gates",
        "method": "DELETE",
        "path_template": "/api/quality_gates/{gate_id}",
        "label": "delete gate (cascades gate reviews)",
        "doc_lines": [
            ("- DELETE {base_url}/api/quality_gates/{gate_id} → delete gate (cascades its gate reviews)."),
        ],
    },
    {
        "key": "gate_review_put",
        "category": "Gate Reviews",
        "method": "PUT",
        "path_template": "/api/gate_reviews/{review_id}",
        "label": (
            "approve/reject manual gate review (fields: status 'approved'/'rejected', comment; "
            "requires X-Human-Action header; rejection requires comment) — human-only"
        ),
        "doc_lines": [
            (
                "- PUT {base_url}/api/gate_reviews/{review_id} → approve or reject a manual gate "
                "review (fields: status 'approved'/'rejected', comment). Requires X-Human-Action "
                "header; rejection requires a non-empty comment. HUMAN-ONLY — agents must never "
                "call this."
            ),
        ],
    },
    {
        "key": "labels_create",
        "category": "Labels",
        "method": "POST",
        "path_template": "/api/labels",
        "label": "create label (fields: name, color, workflow_id)",
        "doc_lines": [
            (
                "- POST {base_url}/api/labels → create label (fields: name, color hex default "
                "'#6b7280', workflow_id). Returns 201 with label id."
            ),
        ],
    },
    {
        "key": "label_get",
        "category": "Labels",
        "method": "GET",
        "path_template": "/api/labels/{label_id}",
        "label": "get label details",
        "doc_lines": [
            "- GET {base_url}/api/labels/{label_id} → get label details",
        ],
    },
    {
        "key": "label_put",
        "category": "Labels",
        "method": "PUT",
        "path_template": "/api/labels/{label_id}",
        "label": "update label (fields: name, color)",
        "doc_lines": [
            ("- PUT {base_url}/api/labels/{label_id} → update label (fields: name, color)."),
        ],
    },
    {
        "key": "label_delete",
        "category": "Labels",
        "method": "DELETE",
        "path_template": "/api/labels/{label_id}",
        "label": "delete label",
        "doc_lines": [
            "- DELETE {base_url}/api/labels/{label_id} → delete label",
        ],
    },
    {
        "key": "skills_import",
        "category": "Skills",
        "method": "POST",
        "path_template": "/api/skills/import",
        "label": "import skill from ZIP (multipart field: file; optional form field: workflow_id)",
        "doc_lines": [
            (
                "- POST {base_url}/api/skills/import → import a skill from a ZIP archive "
                "(multipart/form-data field: file; optional form field: workflow_id for workflow "
                "scope, omit for global scope)."
            ),
        ],
    },
    {
        "key": "skills_import_github",
        "category": "Skills",
        "method": "POST",
        "path_template": "/api/skills/import-github",
        "label": "import skill from a public GitHub repo (JSON: url, optional workflow_id)",
        "doc_lines": [
            (
                "- POST {base_url}/api/skills/import-github → import a skill from a public GitHub "
                "repository (JSON body: url, optional workflow_id for workflow scope, omit for "
                "global scope). URL may point to a repo root or a tree/branch/subpath."
            ),
        ],
    },
    {
        "key": "recurring_create",
        "category": "Recurring",
        "method": "POST",
        "path_template": "/api/recurring",
        "label": (
            "create recurring task (fields: board_id, title, body, status_id, cron_expression, start_at, end_at)"
        ),
        "doc_lines": [
            (
                "- POST {base_url}/api/recurring → create recurring task (fields: board_id, title, "
                "body, status_id, cron_expression 5-field cron, start_at, end_at). Returns 201 "
                "with the task."
            ),
        ],
    },
    {
        "key": "recurring_put",
        "category": "Recurring",
        "method": "PUT",
        "path_template": "/api/recurring/{task_id}",
        "label": ("update recurring task (fields: title, body, status_id, cron_expression, start_at, end_at)"),
        "doc_lines": [
            (
                "- PUT {base_url}/api/recurring/{task_id} → update recurring task (fields: title, "
                "body, status_id, cron_expression, start_at, end_at)."
            ),
        ],
    },
    {
        "key": "recurring_delete",
        "category": "Recurring",
        "method": "DELETE",
        "path_template": "/api/recurring/{task_id}",
        "label": "delete recurring task (soft-disable if instances exist)",
        "doc_lines": [
            (
                "- DELETE {base_url}/api/recurring/{task_id} → delete recurring task. Soft-disables "
                "if instances exist; hard deletes otherwise."
            ),
        ],
    },
    {
        "key": "recurring_toggle",
        "category": "Recurring",
        "method": "POST",
        "path_template": "/api/recurring/{task_id}/toggle",
        "label": "toggle recurring task enabled/disabled",
        "doc_lines": [
            (
                "- POST {base_url}/api/recurring/{task_id}/toggle → toggle a recurring task "
                "enabled/disabled. Returns the updated task."
            ),
        ],
    },
    {
        "key": "recurring_trigger",
        "category": "Recurring",
        "method": "POST",
        "path_template": "/api/recurring/{task_id}/trigger",
        "label": "manually trigger a recurring task now (creates a ticket immediately)",
        "doc_lines": [
            (
                "- POST {base_url}/api/recurring/{task_id}/trigger → manually trigger a recurring "
                "task now; creates a ticket immediately regardless of schedule. Returns "
                "{success, ticket_id}."
            ),
        ],
    },
    {
        "key": "recurring_preview",
        "category": "Recurring",
        "method": "GET",
        "path_template": "/api/recurring/preview",
        "label": "preview next 5 trigger times + human-readable (query: cron)",
        "doc_lines": [
            (
                "- GET {base_url}/api/recurring/preview?cron={expr} → preview the next 5 trigger "
                "times and a human-readable description for a cron expression (query: cron "
                "required)."
            ),
        ],
    },
    {
        "key": "knowledge_categories",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/categories",
        "label": "list distinct knowledge categories (query: board_id optional)",
        "doc_lines": [
            (
                "- GET {base_url}/api/knowledge/categories?board_id={board_id} → list distinct "
                "knowledge categories (query: board_id optional to scope to a board)."
            ),
        ],
    },
    {
        "key": "knowledge_tags",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/tags",
        "label": "list all knowledge tags",
        "doc_lines": [
            "- GET {base_url}/api/knowledge/tags → list all knowledge tags.",
        ],
    },
    {
        "key": "knowledge_version_get",
        "category": "Knowledge",
        "method": "GET",
        "path_template": "/api/knowledge/{entry_id}/versions/{version_id}",
        "label": "get a specific version of a knowledge entry",
        "doc_lines": [
            (
                "- GET {base_url}/api/knowledge/{entry_id}/versions/{version_id} → get a specific "
                "version of a knowledge entry."
            ),
        ],
    },
    {
        "key": "settings_put",
        "category": "Settings",
        "method": "PUT",
        "path_template": "/api/settings/{key}",
        "label": "update a setting (field: value) — human-only",
        "doc_lines": [
            (
                "- PUT {base_url}/api/settings/{key} → update a setting (field: value). Changes "
                "runtime config such as limits; HUMAN-ONLY — agents must never call this."
            ),
        ],
    },
    {
        "key": "settings_purge_terminal_logs",
        "category": "Settings",
        "method": "POST",
        "path_template": "/api/settings/purge-terminal-logs",
        "label": "purge terminal log entries — human-only",
        "doc_lines": [
            (
                "- POST {base_url}/api/settings/purge-terminal-logs → purge terminal log entries. "
                "Destructive; HUMAN-ONLY — agents must never call this."
            ),
        ],
    },
    {
        "key": "system_logs_list",
        "category": "System Logs",
        "method": "GET",
        "path_template": "/api/system_logs",
        "label": (
            "list system logs (query: page, per_page, level, action_type, ticket_id, date_from, date_to, search)"
        ),
        "doc_lines": [
            (
                "- GET {base_url}/api/system_logs → list system logs (query: page, per_page, "
                "level, action_type, ticket_id, date_from, date_to, search). Returns a paginated "
                "envelope."
            ),
        ],
    },
    {
        "key": "system_logs_get",
        "category": "System Logs",
        "method": "GET",
        "path_template": "/api/system_logs/{log_id}",
        "label": "get a single system log entry",
        "doc_lines": [
            "- GET {base_url}/api/system_logs/{log_id} → get a single system log entry",
        ],
    },
    {
        "key": "system_logs_export",
        "category": "System Logs",
        "method": "GET",
        "path_template": "/api/system_logs/export",
        "label": ("export system logs (query: level, action_type, ticket_id, date_from, date_to, search)"),
        "doc_lines": [
            (
                "- GET {base_url}/api/system_logs/export → export system logs as a downloadable "
                "file (query: level, action_type, ticket_id, date_from, date_to, search)."
            ),
        ],
    },
    {
        "key": "agent_run_kill",
        "category": "Agent Runs",
        "method": "POST",
        "path_template": "/api/agent_runs/{run_id}/kill",
        "label": "kill a running agent run (returns feedback_id) — human-only",
        "doc_lines": [
            (
                "- POST {base_url}/api/agent_runs/{run_id}/kill → kill a running agent run "
                "(SIGTERM, escalates to SIGKILL). Returns {success, exit_code, escalated, "
                "feedback_id}. HUMAN-ONLY — agents must never call this."
            ),
        ],
    },
    {
        "key": "running_agent_runs",
        "category": "Agent Runs",
        "method": "GET",
        "path_template": "/api/running_agent_runs",
        "label": "list currently running agent runs",
        "doc_lines": [
            (
                "- GET {base_url}/api/running_agent_runs → list currently running agent runs "
                "(query: board_id; includes elapsed_seconds)."
            ),
        ],
    },
    {
        "key": "notifications_dismiss",
        "category": "Notifications",
        "method": "PUT",
        "path_template": "/api/notifications/dismiss",
        "label": "dismiss a notification (fields: ticket_id, type 'gate_review'/'question') — human-only",
        "doc_lines": [
            (
                "- PUT {base_url}/api/notifications/dismiss → dismiss a notification (fields: "
                "ticket_id, type 'gate_review' or 'question'). HUMAN-ONLY — agents must never "
                "call this."
            ),
        ],
    },
    {
        "key": "notifications_dismiss_all",
        "category": "Notifications",
        "method": "PUT",
        "path_template": "/api/notifications/dismiss-all",
        "label": "dismiss all notifications — human-only",
        "doc_lines": [
            (
                "- PUT {base_url}/api/notifications/dismiss-all → dismiss all notifications. "
                "HUMAN-ONLY — agents must never call this."
            ),
        ],
    },
    {
        "key": "pi_models",
        "category": "Misc",
        "method": "GET",
        "path_template": "/api/pi-models",
        "label": "list available models and thinking levels from the pi CLI",
        "doc_lines": [
            (
                "- GET {base_url}/api/pi-models → list available models and per-model thinking "
                "levels discovered from the pi CLI."
            ),
        ],
    },
    {
        "key": "observations_list",
        "category": "Observations",
        "method": "GET",
        "path_template": "/api/observations",
        "label": (
            "list observations across event_log, system_logs, agent_runs, and "
            "gate_reviews (query: ticket_id, type, date_from, date_to, search, page, per_page)"
        ),
        "doc_lines": [
            "- GET {base_url}/api/observations → list observations across event_log, system_logs, agent_runs, and "
            "gate_reviews (query: ticket_id, type, date_from, date_to, search, page, per_page). Returns paginated "
            "read-only aggregated audit view.",
        ],
    },
    {
        "key": "auth_setup_needed",
        "category": "Auth",
        "method": "GET",
        "path_template": "/api/auth/setup-needed",
        "label": "check whether first-run account setup is needed",
        "doc_lines": [
            "- GET {base_url}/api/auth/setup-needed → return {setup_needed: true/false}. "
            "Works without authentication so the login page can choose setup vs sign-in mode.",
        ],
    },
    {
        "key": "auth_setup",
        "category": "Auth",
        "method": "POST",
        "path_template": "/api/auth/setup",
        "label": "create first user account (human-only)",
        "doc_lines": [
            "- POST {base_url}/api/auth/setup → create the first user account (fields: username, password). "
            "Only works when no users exist; returns 409 if a user already exists. HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_login",
        "category": "Auth",
        "method": "POST",
        "path_template": "/api/auth/login",
        "label": "start a browser session (human-only)",
        "doc_lines": [
            "- POST {base_url}/api/auth/login → start a browser session (fields: username, password). "
            "Returns 200 on success or 401 on invalid credentials. HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_logout",
        "category": "Auth",
        "method": "POST",
        "path_template": "/api/auth/logout",
        "label": "clear the current browser session (human-only)",
        "doc_lines": [
            "- POST {base_url}/api/auth/logout → clear the current browser session. HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_me",
        "category": "Auth",
        "method": "GET",
        "path_template": "/api/auth/me",
        "label": "get current user info",
        "doc_lines": [
            "- GET {base_url}/api/auth/me → get current user info, or 401 if not logged in.",
        ],
    },
    {
        "key": "auth_password",
        "category": "Auth",
        "method": "PUT",
        "path_template": "/api/auth/password",
        "label": "change current user's password (fields: current_password, new_password) — human-only",
        "doc_lines": [
            "- PUT {base_url}/api/auth/password → change the current user's password (fields: current_password, "
            "new_password). Requires an active browser session; API tokens are not accepted. HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_tokens_list",
        "category": "Auth",
        "method": "GET",
        "path_template": "/api/auth/tokens",
        "label": "list current user's API tokens — human-only",
        "doc_lines": [
            "- GET {base_url}/api/auth/tokens → list API tokens for the current session user. Returns id, name, "
            "created_at, last_used_at (no hashes). HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_tokens_create",
        "category": "Auth",
        "method": "POST",
        "path_template": "/api/auth/tokens",
        "label": "create API token for current user (field: name) — human-only",
        "doc_lines": [
            "- POST {base_url}/api/auth/tokens → create a new API token for the current session user (field: name). "
            "Returns the plaintext token exactly once along with the token id. HUMAN-ONLY.",
        ],
    },
    {
        "key": "auth_tokens_delete",
        "category": "Auth",
        "method": "DELETE",
        "path_template": "/api/auth/tokens/{token_id}",
        "label": "revoke an API token belonging to the current user — human-only",
        "doc_lines": [
            "- DELETE {base_url}/api/auth/tokens/{token_id} → revoke an API token belonging to the current "
            "session user. HUMAN-ONLY.",
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
    # Authentication endpoints are human-only login/setup/logout/password/token controls.
    "auth_setup",
    "auth_setup_needed",
    "auth_login",
    "auth_logout",
    "auth_me",
    "auth_password",
    "auth_tokens_list",
    "auth_tokens_create",
    "auth_tokens_delete",
    # Gate review access lets agents approve their own quality gates.
    "gate_reviews_list",
    "gate_review_put",
    "quality_gates_list",
    # Notification management is a human-only concern.
    "notifications_list",
    "notifications_dismiss",
    "notifications_dismiss_all",
    # Feedback records are human-curated.
    "feedback_put",
    "feedback_post",
    # Killing agents is a human oversight action.
    "agent_run_kill",
    # Settings changes let an agent alter its own limits / destructive purges.
    "settings_put",
    "settings_purge_terminal_logs",
    # DB restore is a destructive human-only action.
    "db_backup_restore",
}


ALL_ENDPOINT_KEYS = [entry["key"] for entry in ENDPOINT_REGISTRY]


def build_api_docs(
    selected_keys, ticket_id, base_url=None, has_gates=False, board_id=None, workflow_id=None, agent_token=None
):
    """Build the API documentation text block for an agent prompt.

    Args:
        selected_keys: List of endpoint keys to include, or None/empty for
            the default set.
        ticket_id: The current ticket ID (used for URL substitution).
        base_url: API base URL. Defaults to config.PI_COWORK_URL.
        has_gates: If True, append the gate_pending note to the ticket_put entry.
        board_id: Board ID for substituting {board_id} in endpoint URLs.
        workflow_id: Workflow ID for substituting {workflow_id} in endpoint URLs.
        agent_token: Plaintext API token to inject into the docs as the
            ``Authorization: Bearer`` header.  When ``None``, auth-enabled
            prompts fall back to the generic auth note.

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

    # Conditional authentication note
    if is_auth_enabled():
        if agent_token:
            lines.insert(
                0,
                f"Headers: Authorization: Bearer {agent_token}",
            )
        else:
            lines.append(
                "When authentication is enabled, API requests from agents must include an "
                "`Authorization: Bearer <api_token>` header. Browser sessions are accepted automatically."
            )

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
    if is_auth_enabled():
        lines.append(
            "When authentication is enabled, include an `Authorization: Bearer <api_token>` "
            "header with every API request, or rely on an active browser session."
        )
    for key in keys:
        entry = _REGISTRY_MAP.get(key)
        if entry is None:
            continue
        for line_template in entry["doc_lines"]:
            line = line_template.replace("{base_url}", base_url)
            lines.append(line)

    return "\n".join(lines)
