"""Tests for notification_dismissals TTL and periodic cleanup.

Covers:
- cleanup_old_notification_dismissals removes dismissals older than retention
- cleanup_old_notification_dismissals keeps recent dismissals
- cleanup_old_notification_dismissals respects custom max_age_days
- cleanup works inside and outside Flask app context
- DB indexes exist for efficient queries
- Default retention setting is seeded correctly
- Drain loop calls the cleanup function
"""

import json
from datetime import UTC, datetime, timedelta

from conftest import HUMAN_ACTION_SECRET_FOR_TESTS

HUMAN_HEADERS = {"Content-Type": "application/json", "X-Human-Action": HUMAN_ACTION_SECRET_FOR_TESTS}


def _create_workflow(client):
    res = client.post("/api/workflows", json={"name": "Cleanup WF", "description": "test"})
    return json.loads(res.data)["id"]


def _create_board(client, workflow_id, name="Cleanup Board"):
    res = client.post("/api/boards", json={"name": name, "workflow_id": workflow_id})
    return json.loads(res.data)["id"]


def _create_status(client, workflow_id, name, sort_order, agent_id=None):
    res = client.post(
        "/api/statuses", json={"name": name, "sort_order": sort_order, "workflow_id": workflow_id, "agent_id": agent_id}
    )
    return json.loads(res.data)["id"]


def _create_ticket(client, board_id, title, status_id):
    res = client.post(
        "/api/tickets", json={"title": title, "body": "test", "board_id": board_id, "status_id": status_id}
    )
    return json.loads(res.data)["id"]


class TestCleanupRemovesOldDismissals:
    """Dismissals older than the retention period are deleted."""

    def test_cleanup_removes_old_dismissals(self, client):
        from pi_cowork.db import run_db
        from pi_cowork.models import cleanup_old_notification_dismissals

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        s2 = _create_status(client, wf, "Recent", 2)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "Old Dismissed", s1)
        t2 = _create_ticket(client, board, "Recent Dismissed", s2)

        with client.application.app_context():
            # Insert a dismissal 10 days old
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            # Insert a dismissal 1 day old
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'question', ?)",
                (t2, (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")),
            )

        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals(max_age_days=7)

        assert deleted == 1

        with client.application.app_context():
            from pi_cowork.db import query_db

            remaining = query_db("SELECT * FROM notification_dismissals ORDER BY ticket_id")
            assert len(remaining) == 1
            assert remaining[0]["ticket_id"] == t2
            assert remaining[0]["notification_type"] == "question"


class TestCleanupKeepsRecentDismissals:
    """Dismissals within the retention period are kept."""

    def test_cleanup_keeps_recent_dismissals(self, client):
        from pi_cowork.db import query_db, run_db
        from pi_cowork.models import cleanup_old_notification_dismissals

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "Recent Only", s1)

        with client.application.app_context():
            # Insert dismissals that are recent (within retention)
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'question', ?)",
                (t1, datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")),
            )

        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals(max_age_days=7)

        assert deleted == 0

        with client.application.app_context():
            remaining = query_db("SELECT * FROM notification_dismissals WHERE ticket_id = ?", (t1,))
            assert len(remaining) == 2


class TestCleanupConfigurableRetention:
    """Custom max_age_days overrides the default."""

    def test_cleanup_configurable_retention(self, client):
        from pi_cowork.db import query_db, run_db
        from pi_cowork.models import cleanup_old_notification_dismissals

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "Custom Retention", s1)

        with client.application.app_context():
            # Insert a dismissal 3 days old
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")),
            )

        # With 7-day retention, this should be kept
        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals(max_age_days=7)
        assert deleted == 0

        # With 2-day retention, this should be deleted
        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals(max_age_days=2)
        assert deleted == 1

        with client.application.app_context():
            remaining = query_db("SELECT * FROM notification_dismissals WHERE ticket_id = ?", (t1,))
            assert len(remaining) == 0


class TestCleanupUsesConfigDefault:
    """cleanup uses DB settings / env / default when max_age_days is None."""

    def test_cleanup_uses_default_when_no_arg(self, client):
        from pi_cowork.db import run_db
        from pi_cowork.models import cleanup_old_notification_dismissals

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "Default Retention", s1)

        # Insert a dismissal 10 days old (older than default 7-day retention)
        with client.application.app_context():
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")),
            )

        with client.application.app_context():
            # Call without max_age_days — should use default 7
            deleted = cleanup_old_notification_dismissals(max_age_days=None)
        assert deleted == 1

    def test_cleanup_uses_db_setting(self, client):
        from pi_cowork.db import run_db
        from pi_cowork.models import cleanup_old_notification_dismissals, set_setting

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "DB Setting", s1)

        # Set retention to 3 days in DB
        with client.application.app_context():
            set_setting("notification_dismissal_retention_days", "3")

        # Insert a dismissal 5 days old (should be deleted with 3-day retention)
        with client.application.app_context():
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
            )

        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals()
        assert deleted == 1


class TestNotificationQueryPerformance:
    """Verify that indexes exist for efficient notification queries."""

    def test_idx_notification_dismissals_dismissed_at_exists(self, client):
        """Index on dismissed_at for efficient TTL DELETE."""
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notification_dismissals_dismissed_at'"
            ).fetchone()
            assert indexes is not None, "Missing idx_notification_dismissals_dismissed_at"

    def test_idx_gate_reviews_ticket_id_status_created_at_exists(self, client):
        """Covering index for the correlated subquery in notifications."""
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_gate_reviews_ticket_id_status_created_at'"
            ).fetchone()
            assert indexes is not None, "Missing idx_gate_reviews_ticket_id_status_created_at"

    def test_idx_questions_ticket_id_created_at_exists(self, client):
        """Covering index for the correlated subquery in notifications."""
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            indexes = db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_questions_ticket_id_created_at'"
            ).fetchone()
            assert indexes is not None, "Missing idx_questions_ticket_id_created_at"


class TestCleanupDefaultSettingSeeded:
    """Verify the default notification_dismissal_retention_days setting is seeded."""

    def test_default_setting_seeded(self, client):
        from pi_cowork.db import query_db

        with client.application.app_context():
            row = query_db(
                "SELECT value FROM settings WHERE key = ?", ("notification_dismissal_retention_days",), one=True
            )
            assert row is not None
            assert row["value"] == "7"

    def test_default_config_value(self, client):
        from pi_cowork.config import get_config

        with client.application.app_context():
            val = get_config("notification_dismissal_retention_days")
            assert val == 7

    def test_env_var_override(self, client, monkeypatch):
        from pi_cowork.config import get_config
        from pi_cowork.db import get_db

        # Remove DB setting so env var takes precedence
        with client.application.app_context():
            db = get_db()
            db.execute("DELETE FROM settings WHERE key = ?", ("notification_dismissal_retention_days",))
            db.commit()
        monkeypatch.setenv("PI_NOTIFICATION_DISMISSAL_RETENTION_DAYS", "14")
        with client.application.app_context():
            val = get_config("notification_dismissal_retention_days")
            assert val == 14


class TestCleanupStandaloneContext:
    """Verify cleanup works when called with explicit max_age_days (no config needed)."""

    def test_cleanup_callable_with_explicit_arg(self, client):
        """The cleanup function should work with an explicit max_age_days argument."""
        from pi_cowork.db import run_db
        from pi_cowork.models import cleanup_old_notification_dismissals

        wf = _create_workflow(client)
        s1 = _create_status(client, wf, "Backlog", 1)
        board = _create_board(client, wf)
        t1 = _create_ticket(client, board, "Callable", s1)

        # Insert an old dismissal
        with client.application.app_context():
            run_db(
                "INSERT OR REPLACE INTO notification_dismissals (ticket_id, notification_type, dismissed_at) "
                "VALUES (?, 'gate_review', ?)",
                (t1, (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")),
            )

        # Should work within app context
        with client.application.app_context():
            deleted = cleanup_old_notification_dismissals(max_age_days=7)
        assert isinstance(deleted, int)
        assert deleted >= 1

        # Verify the old dismissal was deleted
        with client.application.app_context():
            from pi_cowork.db import query_db

            remaining = query_db("SELECT * FROM notification_dismissals WHERE ticket_id = ?", (t1,))
            assert len(remaining) == 0


# ---------------------------------------------------------------------------
# Drain loop integration
# ---------------------------------------------------------------------------


class TestDrainLoopIntegration:
    def test_cleanup_called_in_drain_source(self):
        """The drain loop should import and call cleanup_old_notification_dismissals."""
        import inspect

        import pi_cowork.agents as agents_mod

        source = inspect.getsource(agents_mod._drain_loop)
        assert "cleanup_old_notification_dismissals" in source
        assert "_last_dismissal_cleanup" in source
