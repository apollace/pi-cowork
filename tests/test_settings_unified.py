"""Tests for the unified Settings feature (Ticket #43)."""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("PI_MAX_PARALLEL", "100")
os.environ.setdefault("PI_MAX_PER_HOUR", "100")

import contextlib

from app import app as flask_app
from app import init_db
from pi_cowork import agents as agents_module
from pi_cowork import config
from pi_cowork.models import set_setting
from pi_cowork.system_logs import add_log, cleanup_old_logs


def _fake_start_watcher(proc, run_id, ticket_id, agent_name, log_f):
    pass


def _fake_log_reader(pipe, log_f):
    with contextlib.suppress(ValueError, OSError, AttributeError):
        pipe.close()
    with contextlib.suppress(ValueError, OSError):
        log_f.close()


@pytest.fixture(autouse=True)
def mock_watcher(monkeypatch):
    monkeypatch.setattr(agents_module, "_start_watcher", _fake_start_watcher)


@pytest.fixture(autouse=True)
def mock_log_reader(monkeypatch):
    monkeypatch.setattr(agents_module, "_start_log_reader", _fake_log_reader)


@pytest.fixture(autouse=True)
def reset_limits(monkeypatch):
    config.PI_MAX_PARALLEL = 100
    config.PI_MAX_PER_HOUR = 100
    monkeypatch.setenv("PI_MAX_PARALLEL", "100")
    monkeypatch.setenv("PI_MAX_PER_HOUR", "100")


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    flask_app.config["TESTING"] = True
    flask_app.config["DATABASE"] = db_path

    with flask_app.app_context():
        init_db(flask_app)
        with flask_app.test_client() as client:
            agents_module._drain_app = flask_app
            yield client
            agents_module._drain_app = None

    os.close(db_fd)
    os.unlink(db_path)


def _create_workflow_and_board(client):
    """Helper: create a workflow and board with a terminal status."""
    res = client.post("/api/workflows", json={"name": "Test WF"})
    wf_id = json.loads(res.data)["id"]
    # Create a non-terminal default status
    res = client.post(
        "/api/statuses",
        json={"name": "Backlog", "sort_order": 1, "is_default": True, "is_terminal": False, "workflow_id": wf_id},
    )
    status_id = json.loads(res.data)["id"]
    # Create a terminal status
    res = client.post(
        "/api/statuses",
        json={"name": "Closed", "sort_order": 2, "is_default": False, "is_terminal": True, "workflow_id": wf_id},
    )
    terminal_status_id = json.loads(res.data)["id"]
    res = client.post("/api/boards", json={"name": "Test Board", "workflow_id": wf_id})
    board_data = json.loads(res.data)
    return board_data, wf_id, status_id, terminal_status_id


def _create_ticket(client, board_id, status_id=None):
    """Helper: create a ticket, return its ID."""
    data = {"title": "Test Ticket", "board_id": board_id}
    if status_id:
        data["status_id"] = status_id
    res = client.post("/api/tickets", json=data)
    return json.loads(res.data)["id"]


# ---------------------------------------------------------------------------
# /settings page route
# ---------------------------------------------------------------------------


class TestSettingsPageRoute:
    def test_settings_page_renders(self, client):
        """GET /settings should return 200 with the unified settings page."""
        res = client.get("/settings")
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Settings" in html
        assert "Assistant" in html
        assert "Logs" in html
        assert "cfg-log-retention" in html
        assert "btn-purge-terminal-logs" in html

    def test_settings_page_has_assistant_section(self, client):
        """The unified settings page should include assistant config fields."""
        res = client.get("/settings")
        html = res.data.decode("utf-8")
        assert "cfg-enabled" in html
        assert "cfg-auto-context" in html
        assert "cfg-model" in html
        assert "cfg-thinking" in html
        assert "cfg-working-directory" in html
        assert "cfg-system-prompt" in html

    def test_settings_page_has_logs_section(self, client):
        """The unified settings page should include log retention + purge."""
        res = client.get("/settings")
        html = res.data.decode("utf-8")
        assert "cfg-log-retention" in html
        assert "Purge terminal ticket logs" in html

    def test_settings_sidebar_link(self, client):
        """The sidebar should contain a Settings link."""
        res = client.get("/board")
        html = res.data.decode("utf-8")
        assert "Settings" in html
        assert "/settings" in html


# ---------------------------------------------------------------------------
# /assistant/settings redirect
# ---------------------------------------------------------------------------


class TestAssistantSettingsRedirect:
    def test_assistant_settings_redirects(self, client):
        """GET /assistant/settings should redirect to /settings."""
        res = client.get("/assistant/settings")
        assert res.status_code == 302
        assert "/settings" in res.headers.get("Location", "")

    def test_assistant_settings_follow_redirect(self, client):
        """Following the redirect should land on the unified settings page."""
        res = client.get("/assistant/settings", follow_redirects=True)
        assert res.status_code == 200
        html = res.data.decode("utf-8")
        assert "Settings" in html


# ---------------------------------------------------------------------------
# log_retention_days setting CRUD
# ---------------------------------------------------------------------------


class TestLogRetentionDaysSetting:
    def test_default_log_retention_seeded(self, client):
        """After init, log_retention_days should be set to 30 by default."""
        res = client.get("/api/settings/log_retention_days")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["key"] == "log_retention_days"
        assert data["value"] == "30"

    def test_update_log_retention(self, client):
        """PUT /api/settings/log_retention_days should update the value."""
        res = client.put("/api/settings/log_retention_days", json={"value": "60"})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

        res = client.get("/api/settings/log_retention_days")
        data = json.loads(res.data)
        assert data["value"] == "60"

    def test_log_retention_invalid_value(self, client):
        """Setting log_retention_days to non-numeric should still be accepted
        (validation is on the frontend)."""
        res = client.put("/api/settings/log_retention_days", json={"value": "abc"})
        assert res.status_code == 200
        # The value is stored as a string; cleanup_old_logs will handle it gracefully

    def test_log_retention_in_settings_list(self, client):
        """log_retention_days should appear in the full settings listing."""
        res = client.get("/api/settings")
        data = json.loads(res.data)
        keys = {item["key"] for item in data}
        assert "log_retention_days" in keys


# ---------------------------------------------------------------------------
# Purge terminal logs endpoint
# ---------------------------------------------------------------------------


class TestPurgeTerminalLogs:
    def test_purge_no_terminal_tickets(self, client):
        """Purging when there are no terminal tickets should return 0."""
        res = client.post("/api/settings/purge-terminal-logs")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        assert data["purged_count"] == 0

    def test_purge_terminal_tickets_no_log_dirs(self, client):
        """Purging terminal tickets with no .pi-logs dirs should return 0."""
        board_data, _wf_id, _status_id, terminal_status_id = _create_workflow_and_board(client)
        # Create a ticket in terminal status
        _create_ticket(client, board_data["id"], terminal_status_id)
        res = client.post("/api/settings/purge-terminal-logs")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        assert data["purged_count"] == 0

    def test_purge_deletes_log_dirs(self, client, tmp_path):
        """Purging should delete .pi-logs/ticket-{id} dirs for terminal tickets."""
        # Create a board with a custom working directory
        wf_res = client.post("/api/workflows", json={"name": "Purge WF"})
        wf_id = json.loads(wf_res.data)["id"]

        status_res = client.post(
            "/api/statuses",
            json={"name": "Backlog", "sort_order": 1, "is_default": True, "is_terminal": False, "workflow_id": wf_id},
        )
        json.loads(status_res.data)["id"]

        terminal_res = client.post(
            "/api/statuses",
            json={"name": "Closed", "sort_order": 2, "is_default": False, "is_terminal": True, "workflow_id": wf_id},
        )
        terminal_status_id = json.loads(terminal_res.data)["id"]

        board_res = client.post(
            "/api/boards",
            json={
                "name": "Purge Board",
                "workflow_id": wf_id,
                "working_directory": str(tmp_path),
            },
        )
        board_data = json.loads(board_res.data)

        ticket_id = _create_ticket(client, board_data["id"], terminal_status_id)

        # Create a fake .pi-logs/ticket-{id} directory
        log_dir = tmp_path / ".pi-logs" / f"ticket-{ticket_id}"
        log_dir.mkdir(parents=True)
        (log_dir / "agent.log").write_text("fake log content")

        assert log_dir.exists()

        res = client.post("/api/settings/purge-terminal-logs")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        assert data["purged_count"] >= 1
        assert not log_dir.exists()

    def test_purge_does_not_delete_non_terminal_logs(self, client, tmp_path):
        """Purging should NOT delete .pi-logs dirs for non-terminal tickets."""
        wf_res = client.post("/api/workflows", json={"name": "NoPurge WF"})
        wf_id = json.loads(wf_res.data)["id"]

        status_res = client.post(
            "/api/statuses",
            json={"name": "Open", "sort_order": 1, "is_default": True, "is_terminal": False, "workflow_id": wf_id},
        )
        status_id = json.loads(status_res.data)["id"]

        board_res = client.post(
            "/api/boards",
            json={
                "name": "NoPurge Board",
                "workflow_id": wf_id,
                "working_directory": str(tmp_path),
            },
        )
        board_data = json.loads(board_res.data)

        ticket_id = _create_ticket(client, board_data["id"], status_id)

        # Create a fake .pi-logs dir for non-terminal ticket
        log_dir = tmp_path / ".pi-logs" / f"ticket-{ticket_id}"
        log_dir.mkdir(parents=True)
        (log_dir / "agent.log").write_text("active log content")

        res = client.post("/api/settings/purge-terminal-logs")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True
        # Non-terminal ticket's log dir should still exist
        assert log_dir.exists()

    def test_purge_logs_action(self, client):
        """Purging should create a system log entry."""
        res = client.post("/api/settings/purge-terminal-logs")
        assert res.status_code == 200

        from pi_cowork.db import get_db

        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE '%Purged terminal ticket logs%'"
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# cleanup_old_logs reads from DB setting
# ---------------------------------------------------------------------------


class TestCleanupOldLogsDBSetting:
    def test_cleanup_reads_db_setting(self, client, monkeypatch):
        """cleanup_old_logs should read log_retention_days from the DB settings table."""
        # Set retention to 0 days via DB — everything should be deleted
        set_setting("log_retention_days", "0")

        # Add a recent log
        add_log("INFO", "db_change", "Recent test log for cleanup")

        # Override env var to a large value to prove DB takes precedence
        monkeypatch.setenv("PI_LOG_RETENTION_DAYS", "9999")

        deleted = cleanup_old_logs()
        # With retention=0, the just-inserted log should be deleted
        assert deleted >= 1

    def test_cleanup_falls_back_to_env_var(self, client, monkeypatch):
        """When DB setting is absent, cleanup should fall back to env var."""
        # Remove the DB setting
        from pi_cowork.db import get_db

        get_db().execute("DELETE FROM settings WHERE key = 'log_retention_days'")
        get_db().commit()

        # Point standalone DB to the test DB so fallback path reads correct data
        monkeypatch.setenv("DATABASE", str(flask_app.config["DATABASE"]))

        # Set env var to 0 — should delete everything
        monkeypatch.setenv("PI_LOG_RETENTION_DAYS", "0")

        add_log("INFO", "db_change", "Test fall back to env")

        deleted = cleanup_old_logs()
        assert deleted >= 1

    def test_cleanup_falls_back_to_default(self, client, monkeypatch):
        """When DB setting and env var are absent, cleanup should default to 30 days."""
        from pi_cowork.db import get_db

        get_db().execute("DELETE FROM settings WHERE key = 'log_retention_days'")
        get_db().commit()

        # Point standalone DB to the test DB so fallback path reads correct data
        monkeypatch.setenv("DATABASE", str(flask_app.config["DATABASE"]))

        monkeypatch.delenv("PI_LOG_RETENTION_DAYS", raising=False)

        add_log("INFO", "db_change", "Recent log for default test")

        deleted = cleanup_old_logs()
        # Recent log should NOT be deleted (default retention is 30 days)
        assert deleted == 0

    def test_cleanup_explicit_max_age_overrides_db(self, client):
        """Explicit max_age_days argument should override both DB setting and env var."""
        set_setting("log_retention_days", "9999")  # DB says keep everything

        add_log("INFO", "db_change", "Log to be deleted")

        # But explicit argument says 0
        deleted = cleanup_old_logs(max_age_days=0)
        assert deleted >= 1

    def test_cleanup_gracefully_handles_non_numeric_db_setting(self, client, monkeypatch):
        """If log_retention_days in DB is non-numeric, cleanup should fall back
        gracefully instead of crashing with a TypeError."""
        # Set a non-numeric value directly in the DB
        set_setting("log_retention_days", "abc")

        # Point standalone DB to the test DB so fallback path reads correct data
        monkeypatch.setenv("DATABASE", str(flask_app.config["DATABASE"]))

        # Set env var to 0 so fallback deletes everything — proves we fell back
        monkeypatch.setenv("PI_LOG_RETENTION_DAYS", "0")

        add_log("INFO", "db_change", "Test log for non-numeric retention")

        # This should NOT crash — it should fall back through the priority chain
        deleted = cleanup_old_logs()
        assert deleted >= 1
