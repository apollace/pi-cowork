"""Database helpers: connection management, query utilities, migrations."""

import os
import sqlite3

from flask import current_app, g

from pi_cowork import config


def get_db():
    """Return a per-request SQLite connection (stored on Flask's ``g``).

    Uses WAL journal mode so that writes do not block concurrent readers,
    which is the main source of latency when agents write audit logs while
    the board is loading.
    """
    db = getattr(g, "_database", None)
    if db is None:
        path = current_app.config.get("DATABASE", config.DATABASE)
        db = g._database = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
    return db


def query_db(query, args=(), one=False):
    """Run a SELECT and return rows (or a single row if ``one=True``)."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def run_db(query, args=()):
    """Run a write query, commit, and return the cursor."""
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur


def row_to_dict(row):
    """Convert a ``sqlite3.Row`` to a plain dict."""
    return dict(zip(row.keys(), row))


def _migrate(db):
    """Idempotent migration runner to keep schema up-to-date."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    migrations = [
        ("add_agent_runs_exit_code", "ALTER TABLE agent_runs ADD COLUMN exit_code INTEGER"),
        (
            "create_settings_table",
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        (
            "create_assistant_messages",
            """
            CREATE TABLE IF NOT EXISTS assistant_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        (
            "create_assistant_config_table",
            """
            CREATE TABLE IF NOT EXISTS assistant_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled BOOLEAN NOT NULL DEFAULT 1,
                model TEXT,
                thinking TEXT NOT NULL DEFAULT 'medium',
                working_directory TEXT NOT NULL DEFAULT 'workspace',
                system_prompt TEXT,
                auto_context BOOLEAN NOT NULL DEFAULT 1,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        ("seed_assistant_config", "INSERT OR IGNORE INTO assistant_config (id) VALUES (1)"),
        # Phase 4 — persistent audit log
        (
            "create_event_log_table",
            """
            CREATE TABLE IF NOT EXISTS event_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_name TEXT NOT NULL,
                payload TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        # Ticket #37 — Centralised system logs
        (
            "create_system_logs_table",
            """
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL CHECK(level IN ('INFO','WARNING','ERROR','CRITICAL')),
                action_type TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                ticket_id INTEGER
            )
        """,
        ),
        (
            "create_system_logs_idx_timestamp",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp)",
        ),
        ("create_system_logs_idx_level", "CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level)"),
        (
            "create_system_logs_idx_action_type",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_action_type ON system_logs(action_type)",
        ),
        (
            "create_system_logs_idx_ticket_id",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_ticket_id ON system_logs(ticket_id)",
        ),
        # Ticket #39 — Board long-term vision
        ("add_boards_long_term_vision", "ALTER TABLE boards ADD COLUMN long_term_vision TEXT"),
        # Ticket #43 — seed default log_retention_days setting
        ("seed_log_retention_days", "INSERT OR IGNORE INTO settings (key, value) VALUES ('log_retention_days', '30')"),
        # Ticket #46 — Per-agent model & thinking overrides
        ("add_agents_model_column", "ALTER TABLE agents ADD COLUMN model TEXT"),
        ("add_agents_thinking_column", "ALTER TABLE agents ADD COLUMN thinking TEXT"),
        # Ticket #47 — Recurring tasks
        (
            "create_recurring_tasks",
            """
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
            )
        """,
        ),
        (
            "create_recurring_instances",
            """
            CREATE TABLE IF NOT EXISTS recurring_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recurring_task_id INTEGER NOT NULL REFERENCES recurring_tasks(id) ON DELETE CASCADE,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        # Ticket #50 — Move quality gates to transition (from, to) pairs
        ("migrate_quality_gates_drop", "DROP TABLE IF EXISTS quality_gates"),
        (
            "migrate_quality_gates_recreate",
            """
            CREATE TABLE quality_gates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
                to_status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
                gate_type TEXT NOT NULL CHECK(gate_type IN ('manual', 'cli')),
                name TEXT NOT NULL,
                config TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                workflow_id INTEGER NOT NULL REFERENCES workflows(id),
                UNIQUE(from_status_id, to_status_id, name, workflow_id)
            )
        """,
        ),
        # Ticket #52 — Notification dismissals
        (
            "create_notification_dismissals",
            """
            CREATE TABLE IF NOT EXISTS notification_dismissals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL CHECK(notification_type IN ('gate_review', 'question')),
                dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ticket_id, notification_type)
            )
        """,
        ),
        # Ticket #54 — Per-agent API endpoint selection
        ("add_agents_api_endpoints", "ALTER TABLE agents ADD COLUMN api_endpoints TEXT"),
        # Ticket #57 — Settings UI: seed dynamic config keys
        (
            "seed_pi_cowork_url",
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('pi_cowork_url', 'http://localhost:5000')",
        ),
        ("seed_max_parallel", "INSERT OR IGNORE INTO settings (key, value) VALUES ('max_parallel', '1')"),
        ("seed_max_per_hour", "INSERT OR IGNORE INTO settings (key, value) VALUES ('max_per_hour', '100')"),
        (
            "seed_warm_spawn_threshold",
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('warm_spawn_threshold', '3600')",
        ),
        ("seed_run_max_age", "INSERT OR IGNORE INTO settings (key, value) VALUES ('run_max_age', '7200')"),
        # Ticket #67 — Configurable port
        ("seed_port", "INSERT OR IGNORE INTO settings (key, value) VALUES ('port', '5000')"),
        # Ticket #59 — Store old_status_id in agent_queue for transition context
        ("add_agent_queue_old_status_id", "ALTER TABLE agent_queue ADD COLUMN old_status_id INTEGER"),
        # Ticket #63 — Add priority to tickets
        ("add_tickets_priority", "ALTER TABLE tickets ADD COLUMN priority TEXT DEFAULT 'Medium'"),
        ("backfill_tickets_priority", "UPDATE tickets SET priority = 'Medium' WHERE priority IS NULL"),
        # Ticket #64 — Assistant per-endpoint API docs
        ("add_assistant_api_endpoints", "ALTER TABLE assistant_config ADD COLUMN api_endpoints TEXT"),
        # Ticket #71 — Board agent assistant
        (
            "add_assistant_messages_board_id",
            "ALTER TABLE assistant_messages ADD COLUMN board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE",
        ),
        # Ticket #69 — Per-status model & thinking overrides
        ("add_statuses_model_column", "ALTER TABLE statuses ADD COLUMN model TEXT"),
        ("add_statuses_thinking_column", "ALTER TABLE statuses ADD COLUMN thinking TEXT"),
        # Ticket #72 — Saved prompts for assistant
        (
            "create_assistant_saved_prompts",
            """
            CREATE TABLE IF NOT EXISTS assistant_saved_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                prompt_text TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        # Ticket #82 — Git integration columns
        ("add_workflows_git_enabled", "ALTER TABLE workflows ADD COLUMN git_enabled BOOLEAN NOT NULL DEFAULT 0"),
        ("add_tickets_branch", "ALTER TABLE tickets ADD COLUMN branch TEXT"),
        # Ticket #83 — Performance indexes for board loading
        ("idx_tickets_board_id", "CREATE INDEX IF NOT EXISTS idx_tickets_board_id ON tickets(board_id)"),
        ("idx_comments_ticket_id", "CREATE INDEX IF NOT EXISTS idx_comments_ticket_id ON comments(ticket_id)"),
        (
            "idx_agent_runs_ticket_id_status",
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_ticket_id_status ON agent_runs(ticket_id, status)",
        ),
        ("idx_agent_queue_ticket_id", "CREATE INDEX IF NOT EXISTS idx_agent_queue_ticket_id ON agent_queue(ticket_id)"),
        (
            "idx_gate_reviews_ticket_id",
            "CREATE INDEX IF NOT EXISTS idx_gate_reviews_ticket_id ON gate_reviews(ticket_id)",
        ),
        ("idx_questions_ticket_id", "CREATE INDEX IF NOT EXISTS idx_questions_ticket_id ON questions(ticket_id)"),
        (
            "idx_ticket_labels_ticket_id",
            "CREATE INDEX IF NOT EXISTS idx_ticket_labels_ticket_id ON ticket_labels(ticket_id)",
        ),
        (
            "idx_recurring_instances_ticket_id",
            "CREATE INDEX IF NOT EXISTS idx_recurring_instances_ticket_id ON recurring_instances(ticket_id)",
        ),
        ("idx_labels_workflow_id", "CREATE INDEX IF NOT EXISTS idx_labels_workflow_id ON labels(workflow_id)"),
        # Ticket #85 — Database backup retention setting
        (
            "seed_db_backup_max_count",
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('db_backup_max_count', '10')",
        ),
        # Ticket #89 — Ticket-level model & thinking overrides
        (
            "create_ticket_status_overrides",
            """
            CREATE TABLE IF NOT EXISTS ticket_status_overrides (
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                status_id INTEGER NOT NULL REFERENCES statuses(id) ON DELETE CASCADE,
                model TEXT,
                thinking TEXT,
                PRIMARY KEY (ticket_id, status_id)
            )
        """,
        ),
        # Ticket #90 — Knowledge Management System
        (
            "create_knowledge_entries",
            """
            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER REFERENCES boards(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT NULL,
                auto_context BOOLEAN NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """,
        ),
        (
            "create_knowledge_tags",
            """
            CREATE TABLE IF NOT EXISTS knowledge_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        """,
        ),
        (
            "create_knowledge_entry_tags",
            """
            CREATE TABLE IF NOT EXISTS knowledge_entry_tags (
                entry_id INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES knowledge_tags(id) ON DELETE CASCADE,
                PRIMARY KEY (entry_id, tag_id)
            )
        """,
        ),
        (
            "create_knowledge_versions",
            """
            CREATE TABLE IF NOT EXISTS knowledge_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT,
                auto_context BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT DEFAULT 'human'
            )
        """,
        ),
        (
            "idx_knowledge_entries_board_id",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_entries_board_id ON knowledge_entries(board_id)",
        ),
        (
            "idx_knowledge_entries_category",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_entries_category ON knowledge_entries(category)",
        ),
        (
            "idx_knowledge_versions_entry_id",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_versions_entry_id ON knowledge_versions(entry_id)",
        ),
        # Ticket #97 — Event log rotation: index for efficient cleanup
        (
            "create_event_log_idx_created_at",
            "CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at)",
        ),
        (
            "seed_event_log_retention_days",
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('event_log_retention_days', '30')",
        ),
        # Ticket #98 — Notification dismissals TTL and periodic cleanup
        (
            "idx_notification_dismissals_dismissed_at",
            "CREATE INDEX IF NOT EXISTS idx_notification_dismissals_dismissed_at ON notification_dismissals(dismissed_at)",
        ),
        (
            "idx_gate_reviews_ticket_id_status_created_at",
            "CREATE INDEX IF NOT EXISTS idx_gate_reviews_ticket_id_status_created_at ON gate_reviews(ticket_id, status, created_at)",
        ),
        (
            "idx_questions_ticket_id_created_at",
            "CREATE INDEX IF NOT EXISTS idx_questions_ticket_id_created_at ON questions(ticket_id, created_at)",
        ),
        (
            "seed_notification_dismissal_retention_days",
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('notification_dismissal_retention_days', '7')",
        ),
        # Ticket #84 — Store ticket status_id in agent_runs
        ("add_agent_runs_status_id", "ALTER TABLE agent_runs ADD COLUMN status_id INTEGER"),
    ]
    for name, sql in migrations:
        already_applied = db.execute("SELECT 1 FROM _migrations WHERE name = ?", (name,)).fetchone()
        if already_applied:
            continue
        try:
            db.execute(sql)
        except sqlite3.OperationalError as e:
            err = str(e).lower()
            if "duplicate column" in err or "already exists" in err:
                pass  # Column/table already present on a pre-migration DB
            else:
                raise
        db.execute("INSERT INTO _migrations (name) VALUES (?)", (name,))
        db.commit()


_ORIGINAL_SCHEMA_PATH = os.path.join(config.PROJECT_ROOT, "schema.sql")  # resolved at import time


def init_db(app):
    """Initialise schema and run migrations within *app*'s context."""
    with app.app_context():
        db = get_db()
        with open(_ORIGINAL_SCHEMA_PATH) as f:
            db.cursor().executescript(f.read())
        db.commit()
        _migrate(db)


def close_connection(exception):
    """Teardown handler — close the per-request DB connection."""
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()
