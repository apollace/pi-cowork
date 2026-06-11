PRAGMA foreign_keys = ON;

-- Workflows: reusable configurations of agents, statuses, and transitions
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    git_enabled BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Boards: CoWork instances assigned to a workflow
CREATE TABLE IF NOT EXISTS boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    working_directory TEXT NOT NULL DEFAULT 'workspace',
    long_term_vision TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Agents: autonomous AI workers that get triggered by status changes
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    model TEXT,
    thinking TEXT,
    api_endpoints TEXT,
    skill_names TEXT DEFAULT '[]',
    excluded_skill_names TEXT DEFAULT '[]',
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    UNIQUE(name, workflow_id)
);

-- Statuses: configurable CoWork columns
CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT 0,
    is_terminal BOOLEAN NOT NULL DEFAULT 0,
    agent_id INTEGER REFERENCES agents(id),
    goal TEXT,
    model TEXT,
    thinking TEXT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    UNIQUE(name, workflow_id)
);

-- Transitions: per-pair instructions for agents
CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_status_id INTEGER NOT NULL REFERENCES statuses(id),
    to_status_id INTEGER NOT NULL REFERENCES statuses(id),
    instructions TEXT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    UNIQUE(from_status_id, to_status_id)
);

-- Tickets: tasks on a board
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    board_id INTEGER NOT NULL REFERENCES boards(id),
    priority TEXT DEFAULT 'Medium',
    branch TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    agent_last_spawned_at DATETIME
);

-- Comments: append-only discussion on tickets
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Questions: unanswered agent questions awaiting human input
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    options TEXT, -- JSON array of predefined answer choices; NULL when free-text only
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Track every agent spawn for limits
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    status_id INTEGER,
    pid INTEGER,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT CHECK(status IN ('running','completed','failed')) DEFAULT 'running',
    exit_code INTEGER,
    log_path TEXT
);

-- Queue for blocked spawns
CREATE TABLE IF NOT EXISTS agent_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    status_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    reason TEXT CHECK(reason IN ('parallel','rate')) NOT NULL,
    old_status_id INTEGER
);

-- Quality gates: checks that must pass before transitioning from one status to another
CREATE TABLE IF NOT EXISTS quality_gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
    to_status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
    gate_type TEXT NOT NULL CHECK(gate_type IN ('manual', 'cli')),
    name TEXT NOT NULL,
    config TEXT,  -- JSON, e.g. {"command": "pytest --cov"} for CLI gates
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    notify_on_failure BOOLEAN NOT NULL DEFAULT 1,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    UNIQUE(from_status_id, to_status_id, name, workflow_id)
);

-- Gate reviews: instances of gate checks for specific ticket transitions
CREATE TABLE IF NOT EXISTS gate_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    gate_id INTEGER NOT NULL REFERENCES quality_gates(id) ON DELETE CASCADE,
    from_status_id INTEGER NOT NULL REFERENCES statuses(id),
    to_status_id INTEGER NOT NULL REFERENCES statuses(id),
    status TEXT NOT NULL CHECK(status IN ('pending', 'passed', 'failed', 'approved', 'rejected')) DEFAULT 'pending',
    output TEXT,  -- CLI stdout/stderr or human comment
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

-- Labels: workflow-scoped tags for tickets
CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT "#6b7280",
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    UNIQUE(name, workflow_id)
);

-- Settings: reusable key-value store for app configuration
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Ticket labels: many-to-many join
CREATE TABLE IF NOT EXISTS ticket_labels (
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (ticket_id, label_id)
);

-- Assistant messages: global single-session mirror for the in-app AI assistant
-- board_id=NULL means global assistant; otherwise per-board assistant
CREATE TABLE IF NOT EXISTS assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Assistant configuration: single-row table for in-app AI assistant settings
CREATE TABLE IF NOT EXISTS assistant_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT 1,
    model TEXT,
    thinking TEXT NOT NULL DEFAULT 'medium',
    working_directory TEXT NOT NULL DEFAULT 'workspace',
    system_prompt TEXT,
    auto_context BOOLEAN NOT NULL DEFAULT 1,
    api_endpoints TEXT,
    excluded_skill_names TEXT DEFAULT '[]',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO assistant_config (id) VALUES (1);

-- Recurring tasks: cron-scheduled ticket creation
CREATE TABLE IF NOT EXISTS recurring_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    cron_expression TEXT NOT NULL,
    next_trigger_at DATETIME,
    last_triggered_at DATETIME,
    start_at DATETIME,
    end_at DATETIME,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Recurring instances: links generated tickets back to parent recurring task
CREATE TABLE IF NOT EXISTS recurring_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recurring_task_id INTEGER NOT NULL REFERENCES recurring_tasks(id) ON DELETE CASCADE,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Ticket status overrides: per-ticket model/thinking overrides for specific statuses
CREATE TABLE IF NOT EXISTS ticket_status_overrides (
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
    model TEXT,
    thinking TEXT,
    PRIMARY KEY (ticket_id, status_id)
);

-- Saved prompts: pre-configured one-click prompts for the assistant
CREATE TABLE IF NOT EXISTS assistant_saved_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    prompt_text TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Event log: persistent audit trail for system events
CREATE TABLE IF NOT EXISTS event_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_name TEXT NOT NULL,
    payload TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- System logs: centralised application-level logging
CREATE TABLE IF NOT EXISTS system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL CHECK(level IN ('INFO','WARNING','ERROR','CRITICAL')),
    action_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    ticket_id INTEGER
);

-- Notification dismissals: timestamp-based per-ticket dismissal of gate/question notifications
CREATE TABLE IF NOT EXISTS notification_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    notification_type TEXT NOT NULL CHECK(notification_type IN ('gate_review', 'question')),
    dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticket_id, notification_type)
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_tickets_board_id ON tickets(board_id);
CREATE INDEX IF NOT EXISTS idx_comments_ticket_id ON comments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_ticket_id_status ON agent_runs(ticket_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_queue_ticket_id ON agent_queue(ticket_id);
CREATE INDEX IF NOT EXISTS idx_gate_reviews_ticket_id ON gate_reviews(ticket_id);
CREATE INDEX IF NOT EXISTS idx_questions_ticket_id ON questions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_labels_ticket_id ON ticket_labels(ticket_id);
CREATE INDEX IF NOT EXISTS idx_recurring_instances_ticket_id ON recurring_instances(ticket_id);
CREATE INDEX IF NOT EXISTS idx_labels_workflow_id ON labels(workflow_id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_system_logs_action_type ON system_logs(action_type);
CREATE INDEX IF NOT EXISTS idx_system_logs_ticket_id ON system_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_notification_dismissals_dismissed_at ON notification_dismissals(dismissed_at);
CREATE INDEX IF NOT EXISTS idx_gate_reviews_ticket_id_status_created_at ON gate_reviews(ticket_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_questions_ticket_id_created_at ON questions(ticket_id, created_at);

-- =============================================================================
-- SEED DATA
-- =============================================================================

INSERT OR IGNORE INTO workflows (name, description) VALUES
('Default Startup Workflow', 'Pre-configured workflow for a startup/content team');

INSERT OR IGNORE INTO boards (name, workflow_id, working_directory) VALUES
('Default', 1, 'workspace');

-- Seed agents (8 pre-built agents for a startup/content team)
-- Descriptions define the agent's role and identity only.
-- "When done" instructions are handled by the system prompt, not here.
INSERT OR IGNORE INTO agents (name, description, workflow_id) VALUES
('Researcher', 'You are a Researcher. Your job is to investigate topics assigned to you: feasibility, tech stack, competitors, content angles, or market trends. Summarize findings clearly and recommend the next status.', 1),
('Designer', 'You are a Designer. Create UI/UX, wireframes, design systems, or visual assets. Focus on usability and clarity.', 1),
('Developer', 'You are a Developer. You handle three phases: Clarifications (ask questions about requirements), Planning (write implementation plans), and Under Development (write code). Do not self-move from Planning to Under Development -- wait for human approval.', 1),
('Copywriter', 'You are a Copywriter. Draft marketing copy, blog posts, landing pages, emails, or any text content. Match the requested tone and audience.', 1),
('Writer Reviewer', 'You are a Writer Reviewer. Edit copy for grammar, tone, brand voice, and clarity. Provide constructive feedback.', 1),
('Marketer', 'You are a Marketer. Build marketing strategies, SEO plans, distribution tactics, and pricing ideas.', 1),
('Code Reviewer', 'You are a Code Reviewer. Review code for correctness, style, performance, and maintainability. Suggest improvements.', 1),
('QA / Tester', 'You are a QA / Tester. Validate functionality, reproduce bugs, write test plans, and verify fixes.', 1);

-- Seed statuses (14 columns: agent inboxes + utility columns)
-- Only seed statuses if the table is empty
-- We use a subquery approach: insert only if no row with this (name, workflow_id) exists
INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id) VALUES
('Backlog', 1, 1, 0, NULL, NULL, 1),
('Research', 2, 0, 0, 1, 'Investigate feasibility, tech stack, competitors, or content topics.', 1),
('Design', 3, 0, 0, 2, 'Create UI/UX, wireframes, or design systems.', 1),
('Clarifications', 4, 0, 0, 3, 'Clarify requirements, scope, and acceptance criteria.', 1),
('Planning', 5, 0, 0, 3, 'Write a detailed implementation plan.', 1),
('Under Development', 6, 0, 0, 3, 'Implement the approved plan.', 1),
('In Writing', 7, 0, 0, 4, 'Draft copy, blog posts, landing pages, or emails.', 1),
('Marketing', 8, 0, 0, 6, 'Build strategy, SEO, distribution plan, or pricing ideas.', 1),
('Code Review', 9, 0, 0, 7, 'Review code for correctness, style, and performance.', 1),
('Content Review', 10, 0, 0, 5, 'Edit copy for tone, grammar, and brand voice.', 1),
('QA / Testing', 11, 0, 0, 8, 'Validate functionality, reproduce bugs, and verify fixes.', 1),
('Blocked', 12, 0, 0, NULL, NULL, 1),
('Closed', 13, 0, 1, NULL, NULL, 1),
('Dropped', 14, 0, 1, NULL, NULL, 1);

-- Knowledge entries (current/live version)
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,  -- NULL = global
    title TEXT NOT NULL,
    content TEXT NOT NULL,  -- Markdown
    category TEXT DEFAULT NULL,
    auto_context BOOLEAN NOT NULL DEFAULT 0,  -- Inject into agent prompts?
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Knowledge tags (normalized)
CREATE TABLE IF NOT EXISTS knowledge_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Knowledge entry ↔ tag mapping
CREATE TABLE IF NOT EXISTS knowledge_entry_tags (
    entry_id INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES knowledge_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, tag_id)
);

-- Version history (full revision tracking)
CREATE TABLE IF NOT EXISTS knowledge_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    auto_context BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'human'  -- 'human' or 'agent'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_entries_board_id ON knowledge_entries(board_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_entries_category ON knowledge_entries(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_versions_entry_id ON knowledge_versions(entry_id);

-- Seed transitions (when to move — the "how" is in the API docs)
-- Instructions describe *when* to transition, not the API call (that's redundant with the API docs in the prompt).
INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id) VALUES
-- Research (Researcher)
(2, 3, 'When the topic needs UI/UX or design work before implementation.', 1),
(2, 4, 'When research is complete and the ticket is ready for development.', 1),
(2, 8, 'When research reveals a need for marketing strategy.', 1),

-- Design (Designer)
(3, 4, 'When design is complete. The Developer will begin implementation planning.', 1),

-- Clarifications (Developer)
(4, 5, 'When all questions are answered and requirements are clear. Write an implementation plan.', 1),
(4, 12, 'When the ticket is unclear, not feasible, or needs human triage.', 1),

-- Planning (Developer) — no transition to Under Development (human gate)
(5, 12, 'When the plan reveals the ticket is not viable.', 1),

-- Under Development (Developer)
(6, 9, 'When implementation is complete and basic tests pass.', 1),
(6, 12, 'When an external dependency or blocker is encountered.', 1),

-- In Writing (Copywriter)
(7, 10, 'When your draft is complete.', 1),

-- Marketing (Marketer)
(8, 10, 'When your strategy or campaign is ready for review.', 1),

-- Code Review (Code Reviewer)
(9, 11, 'When code review passes.', 1),
(9, 6, 'When issues are found. Return for fixes.', 1),

-- Content Review (Writer Reviewer)
(10, 11, 'When content is approved.', 1),
(10, 7, 'When edits are needed. Return to the writer.', 1),

-- QA / Testing (QA / Tester)
(11, 13, 'When all tests pass.', 1),
(11, 6, 'When bugs are found. Return to development.', 1),
(11, 7, 'When content issues are found. Return to the writer.', 1);

-- =============================================================================
-- SEED DATA — System Improvement workflow
-- =============================================================================

INSERT OR IGNORE INTO workflows (name, description) VALUES
('System Improvement', 'Self-evaluation and improvement workflow');

INSERT OR IGNORE INTO boards (name, workflow_id, working_directory)
SELECT 'System', id, 'workspace/system'
FROM workflows WHERE name = 'System Improvement';

-- Synthesizer agent for System Improvement workflow
INSERT OR IGNORE INTO agents (name, description, workflow_id, api_endpoints)
SELECT 'Synthesizer',
       'You are a Synthesizer. You analyze system observations, synthesize improvements, and apply changes to the system.',
       id,
       '["knowledge_list","knowledge_get","knowledge_create","knowledge_update","knowledge_delete","agents_list","agent_get","agent_put","statuses_list","status_get","status_put","transitions_list","transition_get","transition_put","skills_list","skill_create","ticket_get","ticket_comments_post","ticket_put","workflows_list","workflow_get"]'
FROM workflows WHERE name = 'System Improvement';

-- System Improvement statuses
INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Observe', 1, 1, 0, NULL, NULL, w.id FROM workflows w WHERE w.name = 'System Improvement';

INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Analyze', 2, 0, 0, a.id, 'Analyze all unprocessed observations, group by root cause, write findings as comments.', w.id
FROM workflows w, agents a
WHERE w.name = 'System Improvement' AND a.name = 'Synthesizer' AND a.workflow_id = w.id;

INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Synthesize', 3, 0, 0, a.id, 'Write concrete improvement proposals as knowledge entries with category draft-improvement.', w.id
FROM workflows w, agents a
WHERE w.name = 'System Improvement' AND a.name = 'Synthesizer' AND a.workflow_id = w.id;

INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Apply', 4, 0, 0, a.id, 'Read draft-improvement entries and apply changes via API.', w.id
FROM workflows w, agents a
WHERE w.name = 'System Improvement' AND a.name = 'Synthesizer' AND a.workflow_id = w.id;

INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Validate', 5, 0, 0, a.id, 'Verify improvements resolve the original observations.', w.id
FROM workflows w, agents a
WHERE w.name = 'System Improvement' AND a.name = 'Synthesizer' AND a.workflow_id = w.id;

INSERT OR IGNORE INTO statuses (name, sort_order, is_default, is_terminal, agent_id, goal, workflow_id)
SELECT 'Closed', 6, 0, 1, NULL, NULL, w.id FROM workflows w WHERE w.name = 'System Improvement';

-- System Improvement transitions
INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When there are observations to analyze.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Observe' AND s1.workflow_id = w.id AND s2.name = 'Analyze' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When analysis is complete and improvements are needed.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Analyze' AND s1.workflow_id = w.id AND s2.name = 'Synthesize' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When analysis reveals no action is needed.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Analyze' AND s1.workflow_id = w.id AND s2.name = 'Closed' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When improvement proposals are ready to apply.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Synthesize' AND s1.workflow_id = w.id AND s2.name = 'Apply' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When no concrete improvements are needed.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Synthesize' AND s1.workflow_id = w.id AND s2.name = 'Closed' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When changes have been applied.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Apply' AND s1.workflow_id = w.id AND s2.name = 'Validate' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When application failed and re-observation is needed.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Apply' AND s1.workflow_id = w.id AND s2.name = 'Observe' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When improvements are validated.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Validate' AND s1.workflow_id = w.id AND s2.name = 'Closed' AND s2.workflow_id = w.id;

INSERT OR IGNORE INTO transitions (from_status_id, to_status_id, instructions, workflow_id)
SELECT s1.id, s2.id, 'When validation failed and re-observation is needed.', w.id
FROM workflows w, statuses s1, statuses s2
WHERE w.name = 'System Improvement' AND s1.name = 'Validate' AND s1.workflow_id = w.id AND s2.name = 'Observe' AND s2.workflow_id = w.id;

-- Self-improvement settings
INSERT OR IGNORE INTO settings (key, value) VALUES
('self_improvement_enabled', '1'),
('self_improvement_batch_cron', '0 2 * * *'),
('high_comment_threshold', '10');

-- Self-improvement recurring batch task
INSERT INTO recurring_tasks (board_id, title, body, status_id, cron_expression, next_trigger_at, enabled)
SELECT b.id, 'Self-improvement batch', 'Batch analysis ticket for self-improvement loop.', s.id, '0 2 * * *', datetime('now', '+1 day'), 1
FROM boards b
JOIN workflows w ON b.workflow_id = w.id
JOIN statuses s ON s.workflow_id = w.id AND s.name = 'Analyze'
WHERE b.name = 'System' AND w.name = 'System Improvement'
  AND NOT EXISTS (
      SELECT 1 FROM recurring_tasks rt
      WHERE rt.board_id = b.id AND rt.title = 'Self-improvement batch'
  );
