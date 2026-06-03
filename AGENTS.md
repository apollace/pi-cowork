# pi-CoWork

A minimal CoWork web app with AI agent integration. Supports multiple boards and reusable workflows. Mobile and desktop friendly.

## What It Does

- **Multiple CoWork boards** — each board is a workspace for tickets
- **Reusable workflows** — define agents, statuses, and transitions once, reuse across many boards
- **8 pre-built agents** for a startup/content creation team
- Create/edit tickets. No ticket deletion (terminal statuses act as archival).
- Tickets have: ID, title, description, status, priority, board, comments
- Each board has a working directory where its agents run
- **Statuses are agent inboxes** — moving a ticket to a column hands it to that agent. Creating a ticket in a status that has an agent also triggers that agent.
- Comments are append-only (system comments added when agents start/fail)
- **Quality gates** — configurable checks (manual approval, CLI) on specific status transitions that must pass before a ticket can move from one status to another

## Stack

- Python 3.11+ + Flask
- SQLite (stdlib `sqlite3`)
- Vanilla HTML/CSS/JS. No frontend framework. No build step.
- **Requires `pi` CLI installed** for agent spawning

## Structure

```
pi-cowork/
├── app.py                 # Flask app, routes, DB init, agent spawning
├── pi_cowork/api/pi_models.py  # pi CLI model discovery with caching
├── schema.sql             # DB schema + seed data
├── requirements.txt       # Flask, pytest
├── pi-cowork.db           # SQLite database (created on first run)
├── start.sh               # Start app in background
├── stop.sh                # Stop background app
├── workspace/             # Shared working directory for all agents
├── static/
│   ├── style.css          # All styling, responsive, mobile-first
│   └── app.js             # Board rendering, dynamic columns
├── templates/
│   ├── base.html
│   ├── board.html         # CoWork board with board selector dropdown
│   ├── ticket_form.html   # Create / edit ticket
│   ├── ticket_detail.html # Ticket view + comments + gate reviews + agent badge
│   ├── knowledge.html     # Knowledge management page
│   ├── workflows.html     # Workflows + agents/statuses/transitions/quality gates + import workflow
└── tests/                 # pytest suite (930+ tests)
    ├── conftest.py
    ├── test_tickets_api.py
    ├── test_agents_api.py
    ├── test_statuses_api.py
    ├── test_transitions_api.py
    ├── test_agent_limits.py
    ├── test_agent_logs.py
    ├── test_agent_spawn.py
    ├── test_import_export.py
    ├── test_quality_gates.py
    ├── test_workflows_boards.py
    ├── test_agent_completion.py
    └── test_pi_models.py
```

## Running

```bash
./start.sh   # background, binds 0.0.0.0:$PI_PORT (default 5000)
./stop.sh    # kill background process
```

Dev mode (foreground):
```bash
python3 app.py          # reads $PI_PORT or defaults to 5000
PI_PORT=8080 python3 app.py
```

Tests:
```bash
PYTHONPATH=$(pwd) pytest tests/ -v
```

## Settings Architecture

All dynamic configuration is resolved via `pi_cowork.config.get_config(key)` with a **three-tier precedence**: DB settings table → environment variable → hardcoded default.

| Setting Key | DB Key | Env Var | Default | Type | Category |
|-------------|--------|---------|---------|------|----------|
| API Base URL | `pi_cowork_url` | `PI_COWORK_URL` | `http://localhost:5000` | str | ⚙️ General |
| **Port** | `port` | `PI_PORT` | `5000` | int | ⚙️ General |
| Max Parallel Agents | `max_parallel` | `PI_MAX_PARALLEL` | `1` | int | ⚙️ General |
| Max Spawns Per Hour | `max_per_hour` | `PI_MAX_PER_HOUR` | `100` | int | ⚙️ General |
| Warm Spawn Threshold (sec) | `warm_spawn_threshold` | _(none)_ | `3600` | int | ⚙️ General |
| Run Max Age (sec) | `run_max_age` | _(none)_ | `7200` | int | ⚙️ General |
| Log Retention Days | `log_retention_days` | `PI_LOG_RETENTION_DAYS` | `30` | int | 📜 Logs & Storage |
| Event Log Retention Days | `event_log_retention_days` | `PI_EVENT_LOG_RETENTION_DAYS` | `30` | int | 📜 Logs & Storage |
| Max DB Backups Retained | `db_backup_max_count` | _(none)_ | `10` | int | 📜 Logs & Storage |

**Kept as env-only** (security/runtime concerns):
- `FLASK_SECRET_KEY` — security concern, must not be in DB
- `DATABASE` — used at import time, can't change at runtime
- `FLASK_DEBUG` — deployment concern

**Module-level aliases** (`config.PI_MAX_PARALLEL`, etc.) still exist for backward compatibility but should not be used by new code — use `get_config()` instead. Tests that need to control limits should update the DB settings via `set_setting('max_parallel', '5')` rather than monkeypatching module-level constants.

**Settings UI** has three collapsible categories:
1. 🤖 **Assistant** — enabled, auto-context, model, thinking, working-dir, system-prompt, api-endpoints, saved-prompts
2. ⚙️ **General** — pi_cowork_url, **port**, max_parallel, max_per_hour, warm_spawn_threshold, run_max_age
3. 📜 **Logs & Storage** — log_retention_days, event_log_retention_days, db_backup_max_count, purge terminal logs

## Data Model

```
Workflow (agents + statuses + transitions + quality_gates)
  └── Board (tickets)
        └── Tickets (comments, agent runs, gate_reviews)
```

- **Workflow** = reusable template (agents, statuses, transitions, quality gates)
- **Board** = CoWork instance assigned to exactly one workflow. Has its own working directory where agents run.
- **Ticket** = lives on exactly one board, inherits its workflow's statuses
- **Quality Gate** = check on a status transition (from, to) pair that must pass before the transition completes (manual approval or CLI command)
- **Gate Review** = instance of a gate check for a specific ticket transition
- Multiple boards can share the same workflow
- Deleting a board permanently deletes all its tickets, comments, agent runs, gate reviews, and queue entries
- Deleting a workflow requires that no boards reference it
- **`assistant_saved_prompts`** — global reusable prompt snippets for both global and board assistants (columns: `id`, `name` UNIQUE, `prompt_text`, `sort_order`, `created_at`)
- **`ticket_status_overrides`** — per-ticket model/thinking overrides per status (compound PK: `ticket_id, status_id`, both with `ON DELETE CASCADE`; nullable `model`, `thinking` columns)

## Pre-built Default Workflow (8 Agents)

The seeded `Default Startup Workflow` includes:

| Agent | Inbox Status(es) | Role |
|-------|-----------------|------|
| **Researcher** | Research | Investigate feasibility, tech stack, competitors, content topics |
| **Designer** | Design | Create UI/UX, wireframes, design systems |
| **Developer** | Clarifications, Planning, Under Development | Ask questions → write plan → implement (human-gated) |
| **Copywriter** | In Writing | Draft marketing copy, blog posts, landing pages, emails |
| **Writer Reviewer** | Content Review | Edit copy for tone, grammar, brand voice |
| **Marketer** | Marketing | Build strategy, SEO, distribution, pricing ideas |
| **Code Reviewer** | Code Review | Review code for correctness, style, performance |
| **QA / Tester** | QA / Testing | Validate functionality, reproduce bugs, verify fixes |

### Statuses (14) — Agent Inbox Model

| Status | Agent | Purpose |
|--------|-------|---------|
| **Backlog** (default) | — | Raw ideas, untriaged |
| **Research** | Researcher | Investigate and recommend next steps |
| **Design** | Designer | Create UI/UX and visual assets |
| **Clarifications** | Developer | Ask questions about requirements and scope |
| **Planning** | Developer | Write detailed implementation plan. **Human gate: do not self-move to Under Development** |
| **Under Development** | Developer | Implement the approved plan |
| **In Writing** | Copywriter | Draft copy and content |
| **Marketing** | Marketer | Build marketing strategy and campaigns |
| **Code Review** | Code Reviewer | Review code for correctness and quality |
| **Content Review** | Writer Reviewer | Edit copy for tone and brand voice |
| **QA / Testing** | QA / Tester | Validate functionality and verify fixes |
| **Blocked** | — | External dependency or needs human triage/decision |
| **Closed** (terminal) | — | Done |
| **Dropped** (terminal) | — | Cancelled |

### Developer Flow (3-phase with human gates)

```
Clarifications → Planning → Under Development → Code Review → QA / Testing → Closed
        ↓              ↓
      Blocked        Blocked
```

- **Clarifications → Planning**: Developer asks questions until scope is clear
- **Planning → Under Development**: **HUMAN ONLY** — move when you approve the plan
- **Planning → Blocked**: Plan reveals ticket is not viable

## Agent Logs

Every agent spawn creates a log file at:

```
{board.working_directory}/.pi-logs/ticket-{ticket_id}/run-{run_id}.log
```

Each log contains:
- `=== SYSTEM PROMPT ===` — the agent's identity + behavioral directives
- `=== CONTEXT MESSAGE ===` — ticket details, comments, goal, transitions, API, done instruction
- `=== AGENT OUTPUT ===` — everything the agent wrote to stdout/stderr

Failed spawns also create a log file with the error, and an `agent_runs` row with `status='failed'`.

**Viewing logs:**
- `GET /api/tickets/{id}/agent_runs` — list all runs for a ticket
- `GET /api/agent_runs/{id}/log` — fetch the raw log file
- UI: Ticket detail page (`/ticket/{id}`) has an Agent Runs section with inline "📋 Log" buttons that expand log content per run

Logs are retained forever. No size cap.

## Agent Spawning

When a ticket is moved to a status with an agent assigned, or when a ticket is created in such a status:

1. `pi` is spawned as a background subprocess in the **board's** `working_directory`
2. Command: `pi --system-prompt "<prompt>" --print --session-dir <dir> [--thinking <level>] [--model <model>] "<context>"`
3. `--thinking` and `--model` are only included if an override is active at any level; resolution order: ticket override → status override → agent setting → `pi` CLI built-in defaults (lowest). Each field resolves independently.
4. The **system prompt** contains only the agent's description plus two short directives: follow the goal at the end of the context message, and always add a comment when done
5. The **context message** is structured with the most important directives at the tail end (recency bias) — see structure below
6. A system comment is added: "Agent started/resumed working at..."
7. Sessions are cached per (agent, ticket) pair at `{board.working_dir}/.pi-sessions/<agent-id>/ticket-{id}/`

### System Prompt (lean, identity-only)

```
{agent.description}

Your task and allowed actions change with each prompt. Always follow the instructions at the end of the prompt, not your general expertise.
After completing your task, write a comment on the ticket summarizing what you did.
```

### Context Message — Cold Spawn (no session or >1h stale)

```
Ticket #13: Prompt is not structured appropriately.
Board: pi-cowork-development (board_id=3)

Note: This ticket was moved from "Backlog" to "Clarify" before you were spawned.

Description:
{ticket body}

Comments:
- [timestamp] message

API:
- PUT http://localhost:5000/api/tickets/13 → update ticket (fields: status_id, title, body)
- POST http://localhost:5000/api/tickets/13/comments → add comment (field: body)

This is a new prompt, forget the goals you had from previous prompts.
Your goal: Clarify — Check the provided ticket and ask any clarification needed.
Allowed transitions: Clarify → Plan (status_id=86), Clarify → Clarification Needed (status_id=442)
When done: add a comment to the ticket summarizing your work, then you're finished.
```

The "Note: This ticket was moved from..." line only appears when `old_status_id` is provided (e.g. from the agent queue). If there was no status transition, this line is omitted.

### Context Message — Warm Spawn with status change

```
[Update] Ticket #13: Prompt is not structured appropriately.
Board: pi-cowork-development (board_id=3)
Moved from "Backlog" to "Clarify".

New comments since last update:
- [timestamp] message

API:
- PUT http://localhost:5000/api/tickets/13 → update ticket (fields: status_id, title, body)
- POST http://localhost:5000/api/tickets/13/comments → add comment (field: body)

This is a new prompt, forget the goals you had from previous prompts.
Your goal: Clarify — Check the provided ticket and ask any clarification needed.
Allowed transitions: Clarify → Plan (status_id=86), Clarify → Clarification Needed (status_id=442)
When done: add a comment to the ticket summarizing your work, then you're finished.
```

### Context Message — Warm Spawn in same status

```
[Update] Ticket #13: Prompt is not structured appropriately.
Board: pi-cowork-development (board_id=3)
Still in "Clarify".

New comments since last update:
- [timestamp] message

API:
- PUT ... POST ...

Continue your goal: Clarify — Check the provided ticket and ask any clarification needed.
Allowed transitions: ...
When done: add a comment to the ticket summarizing your work, then you're finished.
```

**Key design principles:**
- Goal and transitions appear **at the end** (recency bias — LLMs attend most to the tail)
- "Forget previous goals" on every new-status spawn, "Continue your goal" on same-status warm spawns
- System prompt is stable across spawns — no duplicated status info fighting with the context
- API endpoints are trimmed to only what the agent needs (PUT ticket, POST comment)
- Quality gates annotated inline as `⚠️gate` on transitions
- When gates exist, PUT docs mention `gate_pending` behavior

**Terminal cleanup:** Moving to `is_terminal=true` (Closed/Dropped) deletes ALL agent session directories for that ticket across all agents and resets `agent_last_spawned_at`.

**Concurrency limits:**
- `PI_MAX_PARALLEL` (default 1): max concurrent agents
- `PI_MAX_PER_HOUR` (default 100): max spawns per hour (rolling window)
- Excess triggers are queued persistently and drained FIFO
- Queue auto-cancels if ticket is manually moved out of the expected status
- `spawn_agent()` returns `True`/`False`; `drain_queue()` uses the return value to decide whether to delete the queue entry (not a racy DB check)
- `try_spawn_or_queue()` cleans up stale queue entries before spawning directly
- `queue_agent()` deduplicates entries (deletes existing un-started entries before insert)
- `cleanup_runs()` also sweeps stale queue entries (running agent already exists, entries >2h old, or same agent already completed/failed after queue entry was created)

If the board's `working_directory` is empty or unset, no spawn happens and the ticket stays put.

If `pi` fails to launch or exits non-zero, an error comment is added.

## API (JSON)

### Workflows
| Route | Method | Description |
|-------|--------|-------------|
| `/api/workflows` | GET/POST | List / create workflows |
| `/api/workflows/<id>` | GET/PUT/DELETE | Get / update / delete workflow (delete blocked if boards exist) |
| `/api/workflows/<id>/export` | GET | Export workflow as JSON |
| `/api/workflows/import` | POST | Import workflow JSON (creates new workflow) |

### Boards
| Route | Method | Description |
|-------|--------|-------------|
| `/api/boards` | GET/POST | List / create boards |
| `/api/boards/<id>` | GET/PUT/DELETE | Get / update / delete board (delete destroys all tickets, comments, runs, queue) |

### Tickets
| Route | Method | Description |
|-------|--------|-------------|
| `/api/tickets?board_id=<id>&include_terminal=true` | GET | List tickets for a board (default: exclude terminal; no limit/offset) |
| `/api/tickets` | POST | Create ticket (requires `board_id`) |
| `/api/tickets/<id>` | GET/PUT | Get / update ticket |
| `/api/tickets/<id>/comments` | GET/POST | List / add comment |

### Agents (scoped by workflow)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/agents?workflow_id=<id>` | GET | List agents for a workflow |
| `/api/agents` | POST | Create agent (requires `workflow_id`) |
| `/api/agents/<id>` | GET/PUT/DELETE | Get / update / remove agent (delete blocked if assigned to a status) |
| `/api/endpoint-registry` | GET | List all API endpoint keys available for agent prompts (grouped by category) |
| `/api/pi-models` | GET | List available models and thinking levels from the pi CLI |

### Statuses (scoped by workflow)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/statuses?workflow_id=<id>` | GET | List statuses for a workflow |
| `/api/statuses` | POST | Create status (requires `workflow_id`) |
| `/api/statuses/<id>` | GET/PUT/DELETE | Get / update / remove status (delete blocked if used by tickets or transitions) |

### Transitions (scoped by workflow)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/transitions?workflow_id=<id>` | GET | List transitions for a workflow |
| `/api/transitions` | POST | Create transition (requires `workflow_id`) |
| `/api/transitions/<id>` | GET/PUT/DELETE | Get / update / remove transition |

### Quality Gates (scoped by transition)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/quality_gates?from_status_id=<id>&to_status_id=<id>` | GET | List gates for a transition |
| `/api/quality_gates` | POST | Create gate |
| `/api/quality_gates/<id>` | GET/PUT/DELETE | Get / update / delete gate |

### Gate Reviews
| Route | Method | Description |
|-------|--------|-------------|
| `/api/gate_reviews?ticket_id=<id>` | GET | List reviews for a ticket |
| `/api/gate_reviews/<id>` | PUT | Approve/reject manual review |

### Agent Runs
| Route | Method | Description |
|-------|--------|-------------|
| `/api/tickets/<id>/agent_runs` | GET | List agent runs for a ticket |
| `/api/agent_runs/<id>/log` | GET | Fetch raw log file |

### Ticket Status Overrides
| Route | Method | Description |
|-------|--------|-------------|
| `/api/tickets/<id>/status_overrides` | GET | List ticket-status overrides (enriched with cascade info) |
| `/api/tickets/<id>/status_overrides` | PUT | Upsert override (`status_id`, `model`, `thinking`) |
| `/api/tickets/<id>/status_overrides/<sid>` | DELETE | Clear override for a specific status |

**Board fields:**
- `name` (string, required, unique)
- `workflow_id` (integer, required)
- `working_directory` (string) — path where `pi` runs for this board's agents (defaults to `workspace`)

**Ticket fields:**
- `title` (string, required)
- `body` (text) — description / details
- `board_id` (integer, required)
- `status_id` (integer) — current status; defaults to the workflow's default status
- `priority` (TEXT) — values: `Low`, `Medium`, `High`, `Critical`; defaults to `Medium`
- `branch` (TEXT, nullable) — git branch name; only visible/writable when workflow has `git_enabled=True`
- Ticket list sort order: **priority DESC** (Critical → High → Medium → Low), **then created_at DESC**

**Board listing response** (`GET /api/tickets?board_id=<id>`) uses a lightweight payload:
- **`include_terminal`** query parameter (default: `false`): when `false`, only non-terminal tickets are returned (`s.is_terminal = 0`); when `true`, all tickets are returned including terminal ones
- **No pagination**: `limit` and `offset` parameters are removed — all matching tickets are returned. Previously `limit=100` caused tickets beyond 100 to be invisible
- Returns `comment_count` (integer) instead of `comments` (array) — reduces serialized data for board views
- Also includes: `labels` (array), `queued` (bool), `queue_reason` (string or null), `gate_pending` (bool), `question_count` (int), `recurring_parents` (array)
- All bulk data is fetched via batch queries, not N+1 per-ticket lookups

**Ticket detail response** (`GET /api/tickets/<id>`) returns full `comments` array plus `running_agents`, `agent_run_count`, `last_agent_run` etc.

**Agent fields:**
- `name` (string, required, unique per workflow)
- `description` (string) — used as `--system-prompt` for `pi`
- `model` (string, nullable) — optional `--model` override for `pi`; `NULL` means use pi default
- `thinking` (string, nullable) — optional `--thinking` level for `pi`; one of: `off`, `minimal`, `low`, `medium`, `high`, `xhigh`; `NULL` means use pi default
- `api_endpoints` (array of strings or null) — list of endpoint keys from `ENDPOINT_REGISTRY` to include in agent prompt; `NULL` uses defaults (`ticket_put`, `ticket_comments_post`, `ticket_questions_post`)
- `workflow_id` (integer) — required

**Status fields:**
- `name` (string, required, unique per workflow)
- `sort_order` (integer)
- `is_default` (boolean) — default status for new tickets in boards using this workflow
- `is_terminal` (boolean) — terminal statuses (Closed/Dropped) act as deletion
- `agent_id` (integer, nullable) — agent to spawn when ticket enters this status
- `goal` (text, nullable) — what the agent should aim for; injected into spawn prompt
- `workflow_id` (integer) — required

**Transition fields:**
- `from_status_id` (integer, required)
- `to_status_id` (integer, required)
- `instructions` (text, nullable) — shown to agent as allowed next steps
- `workflow_id` (integer) — required

**Quality Gate fields:**
- `from_status_id` (integer, required) — source status of the transition this gate guards
- `to_status_id` (integer, required) — destination status of the transition this gate guards
- `gate_type` (string, required) — `'manual'` or `'cli'`
- `name` (string, required)
- `config` (JSON, nullable) — for CLI gates: `{"command": "pytest --cov"}`
- `sort_order` (integer, default 0) — evaluation order
- `enabled` (boolean, default true)
- `workflow_id` (integer) — required

**Gate Review fields:**
- `ticket_id` (integer, required)
- `gate_id` (integer, required)
- `from_status_id` (integer, required)
- `to_status_id` (integer, required)
- `status` (string) — `'pending'`, `'passed'`, `'failed'`, `'approved'`, `'rejected'`
- `output` (text, nullable) — CLI stdout/stderr or human comment
- `created_at`, `completed_at` (timestamps)

## Import / Export

**Export** — downloads a workflow as JSON:
```json
{
  "version": "1.0",
  "exported_at": "...",
  "name": "My Workflow",
  "description": "...",
  "agents": [...],
  "statuses": [...],
  "transitions": [...],
  "quality_gates": [...]
}
```

**Import** — creates a **new workflow** from JSON. No existing data is deleted. If the name collides, a timestamp is appended. Quality gates are recreated if present in the export.

## Quality Gates

Quality gates are checks that must pass when a ticket transitions from one status to another. They're configured per **status transition** (from, to pair) — any ticket moving along that transition must pass all gates first.

### Gate Types
- **Manual** — requires human approval in the UI (approve/reject)
- **CLI** — runs a shell command in the board's working directory; exit 0 = pass, non-zero = fail

### How It Works
1. Agent (or human) requests a status change via `PUT /api/tickets/<id>`
2. If the transition (from current → target status) has enabled quality gates, the ticket **stays in its current status**
3. Gate reviews are created (one per gate) and processed in `sort_order`:
   - CLI gates run automatically; exit 0 → passed, non-zero → failed
   - Manual gates stay pending until a human approves/rejects
4. **All gates must pass** (AND logic). If any fails, the transition is rejected:
   - A comment is added explaining the rejection
   - All pending reviews for this transition are cleared
   - The agent is re-triggered in the current status with the feedback
5. If all gates pass, the ticket moves to the new status and normal spawn logic runs
6. While any gate review is pending, the agent is **blocked** from spawning

### Rejection Flow
- Human rejects a manual gate → comment required → added to ticket → agent re-triggered in current status
- CLI gate fails → stderr added as comment → transition rejected, pending reviews cleared
- **Note:** When a CLI gate fails, the agent is **not** auto-re-triggered. The running agent (if any) will see the failure comment in its context on the next warm spawn. Auto-re-triggering caused infinite loops (spawn → try same transition → gate fails → re-spawn → …).
- Agents are informed about quality gates in their context message, so they know not to retry blocked transitions

### API Endpoints
| Route | Method | Description |
|-------|--------|-------------|
| `/api/quality_gates?from_status_id=<id>&to_status_id=<id>` | GET | List gates for a transition |
| `/api/quality_gates` | POST | Create gate (fields: from_status_id, to_status_id, gate_type, name, config, sort_order, workflow_id) |
| `/api/quality_gates/<id>` | PUT/DELETE | Update / delete gate (delete cascades reviews) |
| `/api/gate_reviews?ticket_id=<id>` | GET | List reviews for a ticket |
| `/api/gate_reviews/<id>` | PUT | Approve/reject manual review (fields: status, comment) |

Ticket API responses include `gate_pending: true/false`.

### UI
- Board cards show 🚧 Gate badge for tickets with pending reviews
- Ticket detail page shows a prominent gate review section with approve/reject buttons
- Workflows page includes a Quality Gates subsection with CRUD per transition

## Recurring Tasks

Recurring tasks automatically create tickets on a cron-like schedule, managed through a "Recurring" tab on the board page.

### Data Model

**`recurring_tasks`** table:
- `id`, `board_id` (FK → boards, CASCADE), `title`, `body`, `status_id` (FK → statuses)
- `cron_expression` (5-field cron), `next_trigger_at`, `last_triggered_at`
- `start_at`, `end_at`, `enabled` (boolean), `created_at`, `updated_at`

**`recurring_instances`** table (links generated tickets back to parent):
- `id`, `recurring_task_id` (FK, CASCADE), `ticket_id` (FK, CASCADE), `triggered_at`

### Scheduler
- `process_recurring_tasks()` runs every 60 seconds in the background drain loop (`_drain_loop` in `agents.py`)
- Checks for tasks with `enabled=1` and `next_trigger_at <= now`
- Creates tickets: title = `[Recurring {datetime}] {task.title}`
- Links via `recurring_instances` row
- Adds system comment on new ticket
- Updates `last_triggered_at` and recomputes `next_trigger_at` via croniter
- Auto-disables when `end_at` is reached

### API (Blueprint: `recurring_bp` at `/api/recurring`)
| Route | Method | Description |
|-------|--------|-------------|
| `/api/recurring?board_id=<id>` | GET | List recurring tasks for a board |
| `/api/recurring` | POST | Create (fields: board_id, title, body, status_id, cron_expression, start_at, end_at) |
| `/api/recurring/<id>` | GET/PUT/DELETE | Get / update / delete (soft-disables if instances exist) |
| `/api/recurring/<id>/toggle` | POST | Toggle enabled/disabled |
| `/api/recurring/<id>/trigger` | POST | Manually trigger now (creates ticket immediately) |
| `/api/recurring/preview?cron=<expr>` | GET | Preview next 5 trigger times + human-readable |
| `/api/tickets/<id>/recurring` | GET | Get parent recurring tasks of a ticket |

### Cron Expression Handling
- **Validation**: croniter used to validate all cron expressions. Invalid → 400 error.
- **Human-readable**: Common patterns mapped (`0 9 * * *` → "Daily at 9:00 AM", etc.). Falls back to raw expression.
- **Preview**: `/api/recurring/preview` returns next 5 ISO timestamps.
- **Next trigger**: `compute_next_trigger(cron_expression, after=...)` uses croniter.

### Ticket Integration
- Ticket list/detail responses include `recurring_parents` array
- Board cards show 🔄 badge for tickets generated from recurring tasks
- Ticket detail page shows recurring parent info section

### Edge Cases
- Disabled tasks: `next_trigger_at` is NULLed; no tickets created
- Re-enabling: recomputes `next_trigger_at` from `last_triggered_at` (or `start_at`)
- Delete: soft-disable if instances exist; hard delete if none
- Board CASCADE: deleting a board deletes all recurring_tasks and recurring_instances
- Start in future: `next_trigger_at` set to first fire after start_at
- End in past: rejected on create; auto-disables on next cycle during processing
- Manual trigger: creates ticket regardless of schedule; recomputes next from now

### Frontend
- Board page has tab bar: "Board" / "Recurring"
- Recurring tab (`static/recurring.js`) shows table with Create/Edit form, cron presets, live preview
- Styles in `static/style.css` (`.board-tabs`, `.recurring-table`, `.cron-preview-box`)

### Dependency
- `croniter` (added to `requirements.txt`)

## Git Integration

Each workflow has a `git_enabled` boolean flag (default `False`). When enabled:

- **Branch management**: On agent spawn, `ensure_ticket_branch()` (in `pi_cowork/git_helpers.py`) creates or reuses a per-ticket branch named `ticket-<id>-<slug>`, checks it out, rebases onto `origin/main`, and persists the branch name in `tickets.branch`.
- **Agent context**: The agent context message includes `Git: working on branch <name> in <dir>.` with a protected-branch guard reminder.
- **API visibility**: `branch` is included in ticket API responses **only when** the workflow has `git_enabled=True`. When disabled, `branch` is omitted from responses.
- **API write guard**: `PUT /api/tickets/<id>` with `branch` field returns 400 if the workflow does not have `git_enabled`.
- **Board responses**: `GET /api/boards/<id>` and `GET /api/boards/` include a `git_enabled` boolean from the linked workflow.
- **Workflow CRUD**: `POST /api/workflows` and `PUT /api/workflows/<id>` accept `git_enabled` (boolean, default `False`).
- **UI**: Workflow cards show a ⭐ Git indicator. The ticket detail sidebar shows the branch when git is enabled and the branch exists. Board cards show a branch badge pill.
- **Migrations**: `add_workflows_git_enabled` and `add_tickets_branch` are idempotent ALTER TABLE migrations that add `git_enabled BOOLEAN DEFAULT 0` to workflows and `branch TEXT` to tickets.
- **`pi_cowork/git_helpers.py`** still exists and is fully functional; the integration glue in `agents.py`, `api/tickets.py`, `api/workflows.py`, `api/boards.py`, `models.py`, and `pages.py` was what was lost in the revert and has been re-added.

## Key Decisions

- **No ticket deletion** — terminal statuses only (Closed/Dropped).
- **Board deletion is destructive** — all tickets, comments, agent runs, and queue entries for that board are permanently deleted.
- **Agent delete blocked** if assigned to a status.
- **Status delete blocked** if used by tickets or transitions. Deleting a status cascades to its quality gates and gate reviews.
- **Quality gate delete** cascades to its gate reviews.
- **Workflow delete blocked** if any boards use it.
- **Comments append-only** — no edit/delete UI or API. System comments track agent lifecycle.
- **Board loads dynamically** via JS fetching `/api/tickets?board_id=`. The board listing API uses batch queries and returns `comment_count` (integer) instead of full comment arrays to reduce payload size and DB round-trips. The ticket detail endpoint (`/api/tickets/\<id\>`) still returns full `comments` arrays.
- **Detail pages server-rendered** for simplicity.
- **SQLite FK enforcement** enabled via `PRAGMA foreign_keys = ON`. **WAL mode** enabled via `PRAGMA journal_mode = WAL` so writes never block readers.
- **No auth, no users** — out of scope.
- **Process termination from daemon threads** — `sys.exit(0)` only terminates the calling thread when invoked from a non-main thread (daemon or otherwise). The `SystemExit` exception is caught by the threading machinery and the main process keeps running. To terminate the entire Flask process from a background thread, use `os.kill(os.getpid(), signal.SIGTERM)` instead. This is how the update/restart mechanism in `_shutdown()` works.
- **`get_config()` requires an active Flask app context to read DB settings** — calling it outside `app.app_context()` (e.g., in `if __name__ == '__main__'` blocks, background threads, or CLI scripts) silently falls back to env/default because the `get_setting` → `query_db` → `get_db()` chain raises when `current_app` / `flask.g` are missing. Always wrap startup config reads in `with app.app_context():`.
- **Agent queue management** — `spawn_agent()` returns `True` if an agent_run was created, `False` if the spawn was skipped (e.g. unanswered questions). `drain_queue()` uses this return value instead of a racy `SELECT COUNT(*) ... WHERE status='running'` check to decide whether to delete the queue entry. `try_spawn_or_queue()` cleans up stale queue entries before spawning directly (no stale "Queued" labels). `queue_agent()` deduplicates by deleting any existing un-started entry before inserting. `cleanup_runs()` also removes stale queue entries (where ticket already has a running agent, entries older than 2 hours, or entries where the same agent already completed/failed for the ticket after the queue entry was created).
- **Full ticket context in all spawn paths** — every code path that spawns an agent (create, update, gate approval, drain queue, recurring) must fetch the ticket via a 3-table JOIN (`tickets JOIN boards JOIN workflows`) to include `board_name`, `workflow_name`, and `workflow_id`. The bare `SELECT * FROM tickets WHERE id = ?` does NOT include these fields and will cause `Board: Unknown` and empty `workflow_id` in agent prompts. If you add a new spawn path, always use the JOIN query.
- **Agent queue preserves old_status_id** — the `agent_queue` table has an `old_status_id` column. `try_spawn_or_queue()` passes `old_status_id` to `queue_agent()`, and `drain_queue()` reads it from the queue entry and passes it to `spawn_agent()`. This ensures that even queued agents get proper transition context ("Moved from X to Y") in their prompts.
- **Recurring tasks spawn agents** — both `process_recurring_tasks()` (background scheduler) and `api_trigger_recurring()` (manual trigger) now spawn agents when the ticket's initial status has an agent assigned. This mirrors `api_create_ticket()`. Without this, recurring task tickets in agent-assigned statuses would sit idle.
- **Agent completion** — watcher thread per spawn calls `proc.wait()` for immediate, accurate detection with exit codes. Exit code 0 → `completed`, nonzero → `failed` + auto-comment. `cleanup_runs()` is a safety net for orphaned runs after Flask restarts, using `_is_our_process(pid)` (reads `/proc/<pid>/cmdline`) instead of `os.kill` to guard against PID recycling. `pid=NULL` → `failed` (process never started). No more `os.kill(pid, 0)`.
- **Lean prompt architecture** — system prompt contains only agent identity + two behavioral directives. All state-specific info (goal, transitions, status context) lives in the context message at the tail end, exploiting LLM recency bias. No duplicated mandate or rules blocks.
- **Per-agent model and thinking** — each agent can optionally override `model` and `thinking` for the `pi` CLI. These are stored as nullable columns on the `agents` table. If not set, the `pi` CLI uses its own defaults (no `--model` or `--thinking` flags are passed). There are no global `PI_MODEL`/`PI_THINKING` environment variables; agent-level settings or `pi` CLI defaults suffice. The assistant config has its own separate `model`/`thinking` columns (with `thinking NOT NULL DEFAULT 'medium'`), which when set to empty string means "use pi default" (no `--thinking` flag).
- **Models and thinking levels sourced from `pi --list-models` and pi internals** — `pi_cowork/api/pi_models.py` runs `pi --list-models` to discover available models, parses the tabular output, and caches results for 5 minutes (`_CACHE_TTL_SECONDS = 300`). Thinking level validation across agents, statuses, and the assistant all call `get_thinking_levels()`, which falls back to the hardcoded tuple (`'off'`, `'minimal'`, `'low'`, `'medium'`, `'high'`, `'xhigh'`) if the CLI is unavailable. **Per-model exact thinking levels** are resolved by running a Node.js subprocess that imports `ModelRegistry` and `getSupportedThinkingLevels` from the installed `@earendil-works/pi-coding-agent` / `@earendil-works/pi-ai` modules. This handles both built-in models and custom models from `~/.pi/agent/models.json`, including per-model `thinkingLevelMap` overrides. If the Node.js helper fails (e.g. Node.js missing or modules not found), each model falls back to the boolean `thinking` field from `pi --list-models` (`thinking=true` → all levels, `thinking=false` → `off` only). **Model values are also validated** via `get_model_ids()`: if `pi --list-models` returns models, create/update endpoints reject unknown model ids with 400; if the CLI is unavailable (empty list), any non-empty string is accepted for backward compatibility. The `/api/pi-models` endpoint exposes model lists with a per-model `thinking_levels` array so the frontend can render `<select>` dropdowns that show only the exact levels each model supports. The UI preserves unknown existing model values by adding them as "(unavailable)" options rather than discarding them. The `/api/pi-models` response includes `thinking`, `images`, and `thinking_levels` fields on each model object. The frontend dynamically filters the thinking dropdown based on the selected model's `thinking_levels`: when a model is selected, only its supported levels are shown; when no model is selected, all global levels are shown. Invalid current values are reset to default. This `populateThinkingSelect` + `getModelThinkingLevels` pattern is replicated across `workflows.html`, `assistant_settings.html`, and `settings.html`.
- **Per-status model and thinking overrides** — each status can optionally override `model` and `thinking` (nullable columns on the `statuses` table). When spawning an agent for a ticket in that status, the effective values are resolved with precedence: status override (highest) → agent override → `pi` CLI built-in defaults (lowest). This allows a workflow to tune model/thinking per stage (e.g., use a cheaper model for "Clarifications" and a stronger one for "Code Review") regardless of which agent is assigned.
- **Per-ticket model and thinking overrides** — the `ticket_status_overrides` table stores per-ticket, per-status overrides for `model` and `thinking` (compound PK: `ticket_id, status_id`, both with `ON DELETE CASCADE`). When spawning an agent, the effective values resolve with precedence: **ticket override → status override → agent setting → pi CLI default**. Each field (model, thinking) resolves independently through the cascade. This allows overriding the model or thinking for a specific ticket in a specific status without changing the workflow-level defaults. API: `GET/PUT /api/tickets/{id}/status_overrides`, `DELETE /api/tickets/{id}/status_overrides/{status_id}`. The `GET` endpoint enriches overrides with cascade info (`model_source`, `effective_model`, `thinking_source`, `effective_thinking`) so the UI can display where each value comes from. The ticket detail page includes a collapsible "Model & Effort" sidebar card showing all statuses with assigned agents, with model/thinking dropdowns for each.
- **Per-agent API endpoints** — agents previously received a hardcoded set of 3 API endpoints (PUT ticket, POST comment, POST questions) in their prompts. Now each agent can specify which API endpoints to expose via the `api_endpoints` column (JSON array of endpoint keys from `ENDPOINT_REGISTRY` in `pi_cowork/api_docs.py`, or `NULL` for the default 3: `ticket_put`, `ticket_comments_post`, `ticket_questions_post`). The `build_api_docs()` function resolves endpoint keys to formatted prompt lines, handling `has_gates` conditional logic and `base_url`/`ticket_id`/`board_id`/`workflow_id` template substitution. Backward compatible: agents with `NULL` `api_endpoints` get the original 3 endpoints. The UI uses `GET /api/endpoint-registry` to render checkboxes grouped by category in the workflow page's agent form.
- **Agent-restricted endpoints** — `AGENT_RESTRICTED_KEYS` in `pi_cowork/api_docs.py` defines endpoints that must never be exposed to agents even if explicitly configured: `gate_reviews_list`, `quality_gates_list`, `notifications_list`, `db_backup_restore`. These endpoints either allow agents to approve their own quality gates (defeating human oversight) or perform destructive human-only actions.
- **X-Human-Action security pattern** — destructive or oversight-critical endpoints (gate review approval, DB restore) require a valid `X-Human-Action` header containing the `HUMAN_ACTION_SECRET` (random per-instance hex string in `app.config`). The secret is injected into Jinja templates via `{{ human_action_secret }}` so the web UI can include it in requests, but AI agents never receive it. Requests with missing or invalid headers are rejected with 403. When adding a new endpoint that should be human-only, add both the header check (matching the pattern in `gate_reviews.py` or `db_backup.py`) and the endpoint key to `AGENT_RESTRICTED_KEYS`.
- **Board context in prompts** — agents receive board name and board_id so they know which board they're operating on. No workflow_id is included (not needed for API calls).
- **Status goals** — each status defines a `goal` that appears in the `Your goal:` / `Continue your goal:` directive at the end of the context message. No goal falls back to just the status name.
- **Quality gates in prompts** — when a transition has quality gates, it's annotated inline with `⚠️gate` and the PUT API docs mention `gate_pending` behavior. No separate warning paragraphs.
- **Session reuse** — agents reuse sessions per (agent, ticket) pair to cache tokens. Sessions stored under `{working_dir}/.pi-sessions/<agent-id>/`.
- **Quality gates** — configurable per status transition (from, to pair). Multiple gates are ANDed (all must pass). CLI gates run automatically; manual gates require human approval. Agent spawning is blocked while any gate review is pending. Rejection of manual gates re-triggers the agent with feedback. CLI gate failure does NOT auto-re-trigger (prevents infinite loops). Orphaned gate reviews are cleaned up when the ticket moves to an unrelated status.
- **Assistant API endpoints** — the assistant also supports per-endpoint API doc selection via the `assistant_config.api_endpoints` column. Unlike agents (which default to 3 endpoints), the assistant defaults to ALL registry endpoints (`build_assistant_api_docs`). The settings UI loads the same `/api/endpoint-registry` endpoint and defaults all checkboxes to selected; saving with all selected sends `null` to use the broad default.
- **Board Context in Assistant** — the global ✨ assistant accepts an optional `board_id` parameter in its API (`/api/assistant/chat`, `/api/assistant/history`, `/api/assistant/compact`, `/api/assistant/reset`). When `board_id` is provided, it uses an isolated session per board (session dir: `{board.working_directory}/.pi-sessions/assistant-board-{board_id}`). The `board_assistant.js` and its dedicated panel/bubble UI have been removed from `board.html` — instead, the global assistant (in `base.html` + `assistant.js`) serves all pages. API endpoints remain backward-compatible (no `board_id` = global session). **Saved prompts** — global reusable prompt snippets stored in `assistant_saved_prompts` (columns: `id`, `name` UNIQUE, `prompt_text`, `sort_order`, `created_at`). Configured in Settings UI under the Assistant category. Rendered as pill buttons above the chat input in the global assistant panel (`base.html` + `assistant.js`). Clicking a pill injects `prompt_text` into the input field (not auto-sent). API: `GET/POST /api/assistant/saved-prompts`, `PUT/DELETE /api/assistant/saved-prompts/<id>`.
- **Slow API request logging** — `pi_cowork/system_logs.py` has a `before_request` hook (`record_request_start_time`) that stores `time.monotonic()` on `flask.g`, and an `after_request` hook (`log_http_request`) that checks elapsed time against `SLOW_REQUEST_THRESHOLD` (default 1.0s). Requests exceeding the threshold produce a WARNING-level system log with message prefix `SLOW API:`. This applies to **all** HTTP methods (including GET), not just audited methods (POST/PUT/DELETE). A slow POST generates both the INFO audit log and the WARNING slow log. Skipped paths (`/api/system_logs`, `/api/notifications`, `/static/`) are excluded from both slow detection and audit logging.

## Real-time UI Updates (SSE)

The UI updates in real-time via Server-Sent Events (SSE), replacing all polling.

### Architecture

- **SSE Endpoint**: `GET /api/events/stream?board_id=<id>` (`pi_cowork/api/events.py`)
  - Opens a long-lived SSE connection per browser tab
  - Subscribes dynamically to all 12 EventBus event types
  - Events are pushed into a thread-safe `queue.Queue` by the subscriber (O(1), no DB calls in hot path)
  - Generator loop pulls from the queue and yields named SSE frames
  - Optional `board_id` filter: only events whose ticket belongs to that board
  - Board ID resolution: `TICKET_CREATED` includes `board_id` in kwargs; other events resolve via lightweight DB lookup (`_get_board_id_for_ticket`)
  - Heartbeat (`: keepalive\n\n`) every 25s to prevent proxy timeouts
  - On disconnect, subscriber is removed from bus and connection counter decremented
  - Max 50 concurrent connections (returns 429 if exceeded)

- **Frontend (base.html)**: A single shared `EventSource` connection
  - Connected on page load, board_id from `localStorage.activeBoard`
  - Reconnects when board changes (storage event) or SSE stream drops
  - Dispatches all 12 event types as `CustomEvent`s on `window` (`sse:ticket.created`, `sse:comment.added`, etc.)
  - `sse:open` event dispatched on connect/reconnect → triggers full refresh to re-sync state
  - `window._reconnectSSE()` available for programmatic reconnection

- **Board page (app.js)**: Listens for all board-relevant SSE events → debounced `refresh()` (500ms)
  - Replaces the former 30s polling interval

- **Ticket detail (ticket_detail.html)**: Listens for ticket-scoped SSE events (filtered by `ticket_id`)
  - On page load, ensures SSE connection is established for the ticket's board: compares `localStorage.activeBoard` with Jinja-rendered `ticket.board_id` (using `String()` to handle type mismatch); updates localStorage if they differ; always calls `_reconnectSSE()` to ensure SSE is connected
  - `comment.added` → `loadComments()`
  - `question.asked/answered` → `loadQuestions()` + `loadComments()`
  - `gate.pending/passed/failed` → `loadGateReviews()` + `loadComments()`
  - `agent.spawned` → `refreshTicketStatus()` + `loadAgentRuns()` + `initRunAgentButton()`
  - `agent.completed/failed` → `refreshTicketStatus()` + `loadAgentRuns()` + `initRunAgentButton()` + `loadComments()`
  - `ticket.updated` → `refreshTicketStatus()` + `loadLabels()` + `loadComments()`
  - `ticket.status_changed` → full reload of all sections
  - `sse:open` (reconnect) → `refreshTicketStatus()` + full reload of all sections (resync)
  - All debounced at 300ms (except `sse:open` which is 100ms)

- **Notifications (base.html)**: Listens for `gate.*` and `question.*` events → debounced `loadNotifications()` (1s)
  - Replaces the former 30s polling interval
  - Notification panel supports dismiss (hide) and resolve (reject/delete underlying data) per item and clear-all
  - dismissed notifications are filtered via `notification_dismissals` table using timestamp-based comparison: a dismissal hides notifications until a genuinely new event (question/gate review) is created after the `dismissed_at` timestamp

### SSE Event Format

Each EventBus event is forwarded as a named SSE frame:
```
event: ticket.created\ndata: {"ticket_id":42,"title":"...","board_id":3,"status_id":86}\n\n
event: comment.added\ndata: {"ticket_id":42,"body":"..."}\n\n
event: ticket.status_changed\ndata: {"ticket_id":42,"old_status_id":86,"new_status_id":87}\n\n```

### Important Notes

- The **existing agent log SSE** (`/api/agent_runs/<id>/stream`) is **unchanged** — it serves a different purpose (line-by-line log streaming)
- The SSE generator subscribes/unsubscribes from the EventBus on connect/disconnect — no leaks
- **Timestamp-based notification dismissals** — `notification_dismissals.dismissed_at` is compared against `MAX(created_at)` of the underlying events (gate reviews or questions). A dismissed notification stays hidden until a new event is created after `dismissed_at`. The old `clear_notification_dismissal()` auto-clear mechanism was removed — it deleted the entire dismissal row on every new event, causing notifications to always reappear even for already-seen events. All database timestamps used in comparisons must use SQLite-compatible format (`YYYY-MM-DD HH:MM:SS`), not Python's `.isoformat()` which includes timezone offsets incompatible with SQLite string comparisons.
- **No new dependencies**: `queue.Queue` + Flask `stream_with_context` only

## Label UI Architecture

`LabelPicker` is a shared JS class in `templates/base.html` with two rendering modes:

- **Inline mode** (`popover: false`, default) — renders labels and controls directly inside a container element. Used on ticket detail and ticket form pages.
- **Popover mode** (`popover: true`) — renders a positioned dropdown overlay (`position: absolute`, `z-index: 1000`) appended to `document.body`. Used on board kanban cards via the `toggleCardLabels()` function. The popover anchors near the trigger button, supports click-away and Escape to close, and re-renders on every toggle.

Both modes share the same collapsible "Create new label" section (`+ Create new label` / `− Create new label` toggle), collapsed by default (`_createExpanded: false`). This prevents the 24-swatch color palette from cluttering every label picker instance.

Label pills (`.badge.label-pill`) use opacity `33` for backgrounds (e.g., `${color}33`) and `55` for borders, improving readability over the previous `22`/`44` values. The `.label-pill` class adds `min-width: 1.8rem` and `0.6rem` horizontal padding.

Board card `toggleCardLabels()` uses a global `_activePopover` / `_activePopoverTicketId` tracker so only one popover is open at a time. Opening a new popover closes the previous one. The popover's `onChange` callback rebuilds the card's label pills inline (replacing the `+` button too).

## UI Conventions (Ticket #79)

The UI underwent a broad set of improvements. Key conventions:

### Toast Notifications
- `window.showToast(message, type, duration)` replaces all `alert()` calls in the UI
- Types: `'success'`, `'error'`, `'warning'`, `'info'`. Default: `'info'`, duration: 4000ms
- Toast container is in `base.html` with class `toast-container`
- CSS classes: `.toast`, `.toast-success`, `.toast-error`, `.toast-warning`, `.toast-info`

### Markdown Rendering
- `marked.js` loaded from CDN in `base.html`
- `window.renderMarkdown(text)` renders markdown content to HTML
- Used in ticket descriptions (`ticket_detail.html`) and comments
- CSS class `.markdown-content` styles rendered markdown (code blocks, blockquotes, tables, etc.)

### Two-Column Ticket Detail Layout
- `.ticket-layout` uses CSS Grid: `1fr 280px`
- Main content area (`.ticket-main`) contains description, gates, agent runs, questions, comments
- Sidebar (`.ticket-sidebar`) is sticky and contains metadata, labels, recurring info
- Responsive: collapses to single column on mobile (≤768px)

### Breadcrumb Navigation
- Ticket detail and form pages include a `.breadcrumb` nav above the page title
- Format: `Board › #ID` or `Board › #ID › Edit`
- CSS classes: `.breadcrumb`, `.breadcrumb-sep`, `.breadcrumb-current`

### Board Page Improvements
- **Filter Dropdown (Ticket #87)**: Priority toggles, label checkboxes, and the terminal-status checkbox are collapsed into a dropdown popover triggered by a **Filters** button. Architecture:
  - `.filter-dropdown-wrapper` — relative-positioned container
  - `.filter-dropdown-trigger` — the "Filters" button that toggles the panel
  - `.filter-badge` (`id="filter-badge"`) — active-filter count badge on the trigger (hidden when 0)
  - `.filter-dropdown-panel` — absolute-positioned popover containing sections:
    - `.filter-dropdown-section` with `.filter-dropdown-section-title` — Priority / Labels / Display
    - `.priority-toggle` buttons live inside the Priority section
    - `.filter-dropdown-checkbox` — class on the "Show terminal statuses" label (moved from standalone)
  - Panel opens/closes via JS (`app.js`): toggle on click, close on click-outside or Escape key
  - **Viewport-aware positioning** (`positionFilterDropdown()`): panel repositions to stay within the viewport:
    - `.dropdown-right` class — aligns to right edge of trigger when panel would overflow the right edge
    - `.dropdown-above` class — positions above the trigger when panel would overflow the bottom edge
    - `maxHeight` constraint — when panel doesn't fit above or below, constrains height with `overflow-y: auto`
    - Repositions on `resize` and `scroll` events while open
  - CSS classes: `.filter-dropdown-wrapper`, `.filter-dropdown-trigger`, `.filter-dropdown-panel`, `.filter-dropdown-section`, `.filter-dropdown-section-title`, `.filter-dropdown-checkbox`, `.filter-badge`, `.dropdown-right`, `.dropdown-above`, `.scrollable`
- **Filter Summary**: Active filters shown as dismissible pills (`.filter-pill`) with a "Clear all" button (`.filter-clear-all`)
- **Loading Skeleton**: `.board-skeleton` with `.skeleton` elements shown while board data loads
- **Card redesign (Ticket #80)**: Cards use three-zone layout, priority accent borders, and read-only status pills (see UI Design Guidelines below)

### Global Search
- Sidebar search input (`.sidebar-search`) was removed (#86)
- Board page still supports URL `search` param deep-linking (`/board?search=...`) and pre-fills the ticket filter

### Assistant Consolidation
- The dedicated board assistant (🎯 bubble + `board_assistant.js`) has been removed from `board.html`
- The global ✨ assistant (in `base.html` + `assistant.js`) serves all pages
- The backend `/api/assistant/chat?board_id=...` API still accepts `board_id`, so board-context conversations continue to work
- `board_assistant.js` file still exists for backward compatibility but is no longer loaded

## UI Design Guidelines (Ticket #80)

Board cards were redesigned from a flat layout to a three-zone layout with priority accents and a styled inline status select.

### Card Layout
- **Three-zone structure**: `.card-header` (ID + priority pill) → `.card-body` (title + labels, inside `.card-link`) → `.card-footer` (status select + badges, outside `.card-link` to avoid navigation conflict)
- Card padding removed; zones use their own padding with gaps
- `.card-footer` uses `border-top: 1px solid var(--border-secondary)` for visual separation

### Priority System
- **Accent border**: Card root gets `card-priority-*` class (e.g., `.card-priority-Critical`) → `border-left: 3px solid <color>` on `.card`
- **Label pill**: `.card-priority-label.p-*` shows priority as a colored pill in the header (e.g., `.card-priority-label.p-Critical`)
- Priority colors: Critical `#dc2626`, High `#d97706`, Medium `#2563eb`, Low `#6b7280`
- CSS classes and JS `priorityColors` map use identical color values

### CSS Variables
- `--border-secondary: #f1f5f9` — subtle separator for card footer top border

### Badges and Chips
- Status shown as styled `.card-status-select` (appearance:none + custom SVG chevron, pill-shaped) — wired to `moveTicket()` via change event with `stopPropagation` so it doesn't trigger card link navigation
- Agent/queued/gate/question/recurring badges live in `.card-footer`
- `.card-label-add` — circular dashed `+` button to add labels (replaces `btn small ghost`)

### Animations
- `card-entrance` keyframe animation replaces old `card-in` (adds subtle `translateY(4px)` fade-in)
- Hover: only `border-color` and `box-shadow` transitions; no `transform: translateY(-1px)`

### Typography and Spacing
- `.card-header`: flex row, space-between alignment, compact padding
- `.card-body`: title + labels, standard text sizing
- `.card-footer`: compact top padding, `--border-secondary` separator

### What Was Removed
- `.card-status-pill` (read-only text pill) — replaced by `.card-status-select` styled inline dropdown
- `.card-actions` — status is now an inline select in `.card-footer`
- `.card-meta` — replaced by zone-specific classes
- `translateY(-1px)` hover transform on `.card`
- Inline `priorityDot` with inline styles → replaced by `.card-priority-label.p-*` pill

## UX Design Guidelines (Ticket #81)

Comprehensive UI guidelines covering design tokens, component rules, and interaction patterns. See **`skills/ux-design.md`** for the full details.

Key principles: clarity over cleverness, consistency (reuse design tokens), progressive disclosure, mobile-first responsive (640px/768px breakpoints), accessibility fundamentals (focus rings, keyboard nav, contrast ≥ 4.5:1), vanilla-only (no frameworks, no build step).

## What to Avoid

- Writing documentation tests for `AGENTS.md` or skill files — they are reference docs, not testable specs. Use tests for code behaviour, not prose content.
- Adding heavy frontend frameworks — keep it vanilla.
- Adding complex UIs or auth without explicit user request.
- Breaking existing test coverage — run tests before committing.
- Moving agent spawn logic outside `spawn_agent()`, `spawn_agent_for_ticket()`, `api_update_ticket()`, `api_create_ticket()`, `process_recurring_tasks()`, or `api_trigger_recurring()`. `spawn_agent_for_ticket(ticket_id, status_id)` in `pi_cowork/agents.py` is the shared helper used by `api_create_ticket`, `process_recurring_tasks`, and `api_trigger_recurring` to avoid duplicating the get-status→get-agent→query-full-ticket→try_spawn_or_queue pattern. All paths spawn agents correctly.
- Calling `request.get_json()` (without `silent=True`) on POST endpoints that may receive an empty body or non-JSON content type. Flask returns 415 Unsupported Media Type. Use `request.get_json(silent=True) or {}` for safe parsing.

## Known Constraints & Recurring Pitfalls

- **Patch `time.sleep` in kill-handler tests** — `pi_cowork/api/agent_runs.py` uses `time.sleep(0.5)` in the SIGKILL escalation polling loop. Tests that exercise the kill endpoint must patch `pi_cowork.api.agent_runs.time.sleep` to avoid real sleeps (5s total for the escalation path). Without this patch, tests are slow and flaky under CI load.
- **Board listing API uses `comment_count` not `comments`** — `GET /api/tickets?board_id=` returns `comment_count` (integer) instead of `comments` (full array) to reduce payload size. The detail endpoint `GET /api/tickets/<id>` still returns the full `comments` array. Do not reintroduce per-ticket comment fetching in the board listing.
- **Board listing API excludes terminal tickets by default** — `GET /api/tickets?board_id=` adds `AND s.is_terminal = 0` to the WHERE clause unless `include_terminal=true` is passed. The frontend's "Show terminal" checkbox triggers a new `refresh()` call with `include_terminal=true` when checked and `include_terminal=false` when unchecked. There is no `limit`/`offset` pagination — all matching tickets are returned. Previous `limit=100` default caused tickets beyond 100 to be invisible.
- **SQLite runs in WAL mode** — `get_db()` sets `PRAGMA journal_mode = WAL` so that writes (audit logging, agent events) do not block concurrent reads (board loading). Do not change this back to DELETE mode.
- **Batch queries for board listing** — The board listing endpoint uses bulk `WHERE ticket_id IN (...)` queries instead of per-ticket N+1 lookups. Batch functions: `get_comment_counts()`, `get_ticket_labels_batch()`, `get_recurring_parents_batch()`. Queue, gate, and question queries are also scoped to the board's ticket IDs rather than global. Do not reintroduce N+1 patterns.
- **Performance indexes** — The following indexes exist and must not be dropped: `idx_tickets_board_id`, `idx_comments_ticket_id`, `idx_agent_runs_ticket_id_status`, `idx_agent_queue_ticket_id`, `idx_gate_reviews_ticket_id`, `idx_questions_ticket_id`, `idx_ticket_labels_ticket_id`, `idx_recurring_instances_ticket_id`, `idx_labels_workflow_id`, `idx_knowledge_entries_board_id`, `idx_knowledge_entries_category`, `idx_knowledge_versions_entry_id`, `idx_event_log_created_at`, `idx_system_logs_timestamp`, `idx_system_logs_level`, `idx_system_logs_action_type`, `idx_system_logs_ticket_id`.
- **`get_model_ids` and `get_thinking_levels` monkeypatching in tests** — the `mock_model_ids` autouse fixture in `conftest.py` patches `get_model_ids` and `get_thinking_levels` in `pi_cowork.api.pi_models` and every API module that imports them at module level. When adding a new API blueprint that imports either function, you **must** also add a `monkeypatch.setattr(your_module, 'get_model_ids', fake)` line to the `mock_model_ids` fixture in `conftest.py`, otherwise model/thinking validation in the new module will use the real (cached or empty) CLI output instead of the test mock list, causing spurious 400 errors in tests.
- **Knowledge management** — A per-board and global knowledge base for storing Markdown reference entries. Entries with `auto_context=1` are automatically injected into agent prompts and assistant context; all entries are searchable via API endpoints. Agents have read AND write access (via `created_by`/`updated_by` tracking as `'human'` or `'agent'`). Full version history is maintained in the `knowledge_versions` table every time an entry is created or updated. The `knowledge_entries` table uses `board_id=NULL` for global entries (visible across all boards) and `board_id=<id>` for board-scoped entries. When listing entries with `board_id` specified, both global and board-specific entries are returned. The `update_knowledge_entry()` model function uses `board_id=0` as a sentinel value meaning "not changed" (since `None` is a valid value meaning "make this global"). Tag management uses normalized `knowledge_tags` with a many-to-many `knowledge_entry_tags` junction table.
- **Periodic cleanup in the drain loop** — The background drain loop (`_drain_loop` in `agents.py`) runs two daily (86400s) cleanup tasks: `cleanup_old_logs()` (system_logs table, `log_retention_days` setting) and `cleanup_old_event_logs()` (event_log table, `event_log_retention_days` setting). Both follow the same config precedence pattern: explicit arg → DB setting → env var → default 30. Both work inside and outside Flask app context. When adding a new table that needs periodic rotation, add a `_last_*_cleanup` tracker and a daily call in `_drain_loop`, create the cleanup function in a dedicated module (mirroring `system_logs.py` / `event_log.py`), add a seed migration for the retention-days setting, and add a `created_at` index for efficient deletion.
