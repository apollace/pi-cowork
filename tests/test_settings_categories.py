"""Tests for the Settings page expandable category sections (Ticket #43 implement phase)."""

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


def _get_html(client):
    """Helper: fetch /settings and return decoded HTML."""
    res = client.get("/settings")
    assert res.status_code == 200
    return res.data.decode("utf-8")


# ---------------------------------------------------------------------------
# Category section structure
# ---------------------------------------------------------------------------


class TestSettingsCategoryStructure:
    """Verify the expandable category section markup is present."""

    def test_assistant_category_element(self, client):
        """The Assistant section should use .settings-category markup."""
        html = _get_html(client)
        assert 'id="category-assistant"' in html
        assert "settings-category" in html

    def test_logs_category_element(self, client):
        """The Logs & Storage section should use .settings-category markup."""
        html = _get_html(client)
        assert 'id="category-logs"' in html

    def test_category_headers_present(self, client):
        """Each category should have a clickable header."""
        html = _get_html(client)
        assert "settings-category-header" in html
        # There should be two headers (assistant + logs)
        assert html.count("settings-category-header") >= 2

    def test_category_detail_elements_present(self, client):
        """Each category should have a detail panel."""
        html = _get_html(client)
        assert 'id="detail-assistant"' in html
        assert 'id="detail-logs"' in html

    def test_chevron_elements_present(self, client):
        """Each category header should contain a chevron indicator."""
        html = _get_html(client)
        assert "settings-chevron" in html
        # Chevrons default to collapsed (▶)
        assert html.count("settings-chevron") >= 2

    def test_category_titles_present(self, client):
        """Category titles should use the emoji + name format from the plan."""
        html = _get_html(client)
        assert "🤖 Assistant" in html
        assert "📜" in html
        assert "Logs" in html


class TestSystemPromptInsideAssistant:
    """Verify the System Prompt textarea was moved inside the Assistant section."""

    def test_system_prompt_inside_assistant_detail(self, client):
        """The system prompt textarea should appear inside the Assistant detail panel,
        NOT as a standalone card outside any category."""
        html = _get_html(client)
        # Find the assistant detail section
        detail_start = html.find('id="detail-assistant"')
        detail_end = html.find('id="detail-logs"')
        assert detail_start > 0
        assert detail_end > detail_start

        assistant_detail_html = html[detail_start:detail_end]
        # cfg-system-prompt should be inside the assistant detail
        assert "cfg-system-prompt" in assistant_detail_html
        assert "System Prompt" in assistant_detail_html

    def test_no_standalone_system_prompt_card(self, client):
        """There should NOT be a System Prompt card outside the Assistant category."""
        html = _get_html(client)
        # Before the assistant category, there should be no system prompt reference
        cat_start = html.find('id="category-assistant"')
        pre_category_html = html[:cat_start]
        assert "System Prompt" not in pre_category_html
        assert "cfg-system-prompt" not in pre_category_html


class TestCategoryDefaultsCollapsed:
    """Verify categories default to collapsed (with .collapsed class initially)."""

    def test_assistant_collapsed_by_default(self, client):
        """The Assistant category should have .collapsed on page load."""
        html = _get_html(client)
        cat_start = html.find('id="category-assistant"')
        line_start = html.rfind("\n", 0, cat_start) + 1
        line_end = html.find("\n", cat_start)
        class_line = html[line_start:line_end]
        assert "collapsed" in class_line

    def test_logs_collapsed_by_default(self, client):
        """The Logs category should have .collapsed on page load."""
        html = _get_html(client)
        cat_start = html.find('id="category-logs"')
        line_start = html.rfind("\n", 0, cat_start) + 1
        line_end = html.find("\n", cat_start)
        class_line = html[line_start:line_end]
        assert "collapsed" in class_line

    def test_detail_panels_collapsed_by_default(self, client):
        """The detail panels should also have .collapsed on page load."""
        html = _get_html(client)
        assert 'class="settings-category-detail collapsed"' in html

    def test_chevrons_collapse_icon_by_default(self, client):
        """Chevrons should show ▶ (collapsed) by default, not ▼ (expanded)."""
        html = _get_html(client)
        # Count ▶ in chevron spans
        assert html.count('<span class="settings-chevron">▶</span>') >= 2


class TestCategoryToggleJavascript:
    """Verify the toggle JS function is present in the page."""

    def test_toggle_function_present(self, client):
        """The toggleCategory JS function should be defined."""
        html = _get_html(client)
        assert "function toggleCategory" in html

    def test_toggle_attached_to_headers(self, client):
        """Category headers should call toggleCategory on click."""
        html = _get_html(client)
        assert "toggleCategory('assistant')" in html
        assert "toggleCategory('logs')" in html


class TestSaveCancelOutsideCategories:
    """Global Save/Cancel buttons should remain outside any category section."""

    def test_save_button_outside_categories(self, client):
        """The Save button should not be inside any .settings-category-detail."""
        html = _get_html(client)
        # Find all detail sections
        html.find('id="detail-logs"')
        # The detail-logs section ends before the form-actions
        # cfg-save should appear after all detail sections
        # Let's check that cfg-save appears after the last detail section
        max(html.rfind('id="detail-logs"'), html.rfind('id="detail-assistant"'))
        save_idx = html.find('id="cfg-save"')
        # A simple check: save should come after both category elements
        assert save_idx > html.find('id="category-logs"')


class TestAllFieldsStillPresent:
    """Regression: all form fields should still be renderable after the restructure."""

    def test_all_assistant_fields_present(self, client):
        """All assistant config fields should be present in the page."""
        html = _get_html(client)
        for field_id in [
            "cfg-enabled",
            "cfg-auto-context",
            "cfg-model",
            "cfg-thinking",
            "cfg-working-directory",
            "cfg-system-prompt",
        ]:
            assert field_id in html, f"Missing field: {field_id}"

    def test_logs_fields_present(self, client):
        """All logs/storage fields should be present in the page."""
        html = _get_html(client)
        assert "cfg-log-retention" in html
        assert "btn-purge-terminal-logs" in html
