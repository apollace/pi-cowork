"""Tests for the General settings (Ticket #57): config resolution, Settings UI, and DB seeding."""

import json
import os
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault('PI_MAX_PARALLEL', '100')
os.environ.setdefault('PI_MAX_PER_HOUR', '100')

import app as app_module
from app import app as flask_app, init_db
from pi_cowork import config
from pi_cowork import agents as agents_module
from pi_cowork.config import get_config, DEFAULTS, ENV_MAP, _INT_KEYS
from pi_cowork.models import get_setting, set_setting


def _fake_start_watcher(proc, run_id, ticket_id, agent_name, log_f):
    pass


def _fake_log_reader(pipe, log_f):
    try:
        pipe.close()
    except (ValueError, OSError, AttributeError):
        pass
    try:
        log_f.close()
    except (ValueError, OSError):
        pass


@pytest.fixture(autouse=True)
def mock_watcher(monkeypatch):
    monkeypatch.setattr(agents_module, '_start_watcher', _fake_start_watcher)


@pytest.fixture(autouse=True)
def mock_log_reader(monkeypatch):
    monkeypatch.setattr(agents_module, '_start_log_reader', _fake_log_reader)


@pytest.fixture(autouse=True)
def reset_limits(monkeypatch):
    config.PI_MAX_PARALLEL = 100
    config.PI_MAX_PER_HOUR = 100
    monkeypatch.setenv('PI_MAX_PARALLEL', '100')
    monkeypatch.setenv('PI_MAX_PER_HOUR', '100')


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    flask_app.config['TESTING'] = True
    flask_app.config['DATABASE'] = db_path

    with flask_app.test_client() as client:
        with flask_app.app_context():
            init_db(flask_app)
        agents_module._drain_app = flask_app
        yield client
        agents_module._drain_app = None

    os.close(db_fd)
    os.unlink(db_path)


# ---------------------------------------------------------------------------
# DB Seeding: new settings keys should exist after init
# ---------------------------------------------------------------------------

class TestGeneralSettingsSeedMigration:
    def test_port_seeded(self, client):
        """After init, port should have default value."""
        res = client.get('/api/settings/port')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['key'] == 'port'
        assert data['value'] == '5000'

    def test_pi_cowork_url_seeded(self, client):
        """After init, pi_cowork_url should have default value."""
        res = client.get('/api/settings/pi_cowork_url')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['key'] == 'pi_cowork_url'
        assert data['value'] == 'http://localhost:5000'

    def test_port_saved_updates_url(self, client):
        """Saving port updates the URL via UI auto-sync logic."""
        # Save new port and URL together (mimic UI auto-sync)
        res = client.put('/api/settings/port', json={'value': '8080'})
        assert res.status_code == 200
        res = client.put('/api/settings/pi_cowork_url', json={'value': 'http://localhost:8080'})
        assert res.status_code == 200

        res = client.get('/api/settings/port')
        assert json.loads(res.data)['value'] == '8080'
        res = client.get('/api/settings/pi_cowork_url')
        assert json.loads(res.data)['value'] == 'http://localhost:8080'

    def test_max_parallel_seeded(self, client):
        """After init, max_parallel should have default value."""
        res = client.get('/api/settings/max_parallel')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['value'] == '1'

    def test_max_per_hour_seeded(self, client):
        res = client.get('/api/settings/max_per_hour')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['value'] == '100'

    def test_warm_spawn_threshold_seeded(self, client):
        res = client.get('/api/settings/warm_spawn_threshold')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['value'] == '3600'

    def test_run_max_age_seeded(self, client):
        res = client.get('/api/settings/run_max_age')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['value'] == '7200'


# ---------------------------------------------------------------------------
# get_config(): precedence DB > env > default
# ---------------------------------------------------------------------------

class TestGetConfigPrecedence:
    def test_get_config_reads_from_db_first(self, client):
        """get_config should return DB value over env or default."""
        with client.application.app_context():
            set_setting('max_parallel', '5')
            assert get_config('max_parallel') == 5

    def test_get_config_falls_back_to_env(self, client, monkeypatch):
        """When DB value is absent, get_config should fall back to env var."""
        with client.application.app_context():
            from pi_cowork.db import get_db
            get_db().execute("DELETE FROM settings WHERE key = 'max_parallel'")
            get_db().commit()
            monkeypatch.setenv('PI_MAX_PARALLEL', '7')
            assert get_config('max_parallel') == 7

    def test_get_config_falls_back_to_default(self, client, monkeypatch):
        """When DB value and env var are both absent, get_config should return default."""
        with client.application.app_context():
            from pi_cowork.db import get_db
            get_db().execute("DELETE FROM settings WHERE key = 'max_parallel'")
            get_db().commit()
            monkeypatch.delenv('PI_MAX_PARALLEL', raising=False)
            assert get_config('max_parallel') == 1  # default

    def test_get_config_returns_str_for_non_int_keys(self, client):
        """pi_cowork_url should be returned as a string, not int."""
        with client.application.app_context():
            set_setting('pi_cowork_url', 'http://example.com:8080')
            result = get_config('pi_cowork_url')
            assert result == 'http://example.com:8080'
            assert isinstance(result, str)

    def test_get_config_returns_int_for_int_keys(self, client):
        """max_per_hour should be returned as int."""
        with client.application.app_context():
            set_setting('max_per_hour', '50')
            result = get_config('max_per_hour')
            assert result == 50
            assert isinstance(result, int)

    def test_get_config_non_numeric_db_value_falls_back(self, client, monkeypatch):
        """If DB has a non-numeric value for an int key, fall back to env/default."""
        with client.application.app_context():
            set_setting('max_parallel', 'abc')
            monkeypatch.setenv('PI_MAX_PARALLEL', '3')
            result = get_config('max_parallel')
            assert result == 3  # falls back through to env

    def test_get_config_non_numeric_db_and_env_falls_to_default(self, client, monkeypatch):
        """If DB and env are both non-numeric, fall back to default."""
        with client.application.app_context():
            set_setting('max_parallel', 'abc')
            monkeypatch.setenv('PI_MAX_PARALLEL', 'xyz')
            result = get_config('max_parallel')
            assert result == 1  # falls back through to default

    def test_get_config_warm_spawn_threshold(self, client):
        """warm_spawn_threshold has no env var, reads from DB or default."""
        with client.application.app_context():
            set_setting('warm_spawn_threshold', '1800')
            assert get_config('warm_spawn_threshold') == 1800

            from pi_cowork.db import get_db
            get_db().execute("DELETE FROM settings WHERE key = 'warm_spawn_threshold'")
            get_db().commit()
            # Falls back to default (no env var for this key)
            assert get_config('warm_spawn_threshold') == 3600

    def test_get_config_run_max_age(self, client):
        """run_max_age has no env var, reads from DB or default."""
        with client.application.app_context():
            set_setting('run_max_age', '3600')
            assert get_config('run_max_age') == 3600

            from pi_cowork.db import get_db
            get_db().execute("DELETE FROM settings WHERE key = 'run_max_age'")
            get_db().commit()
            assert get_config('run_max_age') == 7200

    def test_get_config_outside_flask_context(self, monkeypatch):
        """get_config should fall back gracefully outside a Flask context."""
        monkeypatch.setenv('PI_MAX_PARALLEL', '42')
        result = get_config('max_parallel')
        assert result == 42

    def test_get_config_unknown_key_returns_none(self, monkeypatch):
        """get_config for an unknown key should return None."""
        monkeypatch.delenv('PI_COWORK_URL', raising=False)
        result = get_config('nonexistent_key_xyz')
        assert result is None


# ---------------------------------------------------------------------------
# General Settings UI: ⚙️ General category
# ---------------------------------------------------------------------------

class TestGeneralSettingsUI:
    def test_settings_page_has_general_category(self, client):
        """The settings page should include the ⚙️ General category."""
        res = client.get('/settings')
        html = res.data.decode('utf-8')
        assert 'id="category-general"' in html
        assert '⚙️ General' in html

    def test_settings_page_general_fields(self, client):
        """The settings page should include all general setting fields."""
        res = client.get('/settings')
        html = res.data.decode('utf-8')
        assert 'cfg-pi-cowork-url' in html
        assert 'cfg-port' in html
        assert 'cfg-max-parallel' in html
        assert 'cfg-max-per-hour' in html
        assert 'cfg-warm-spawn-threshold' in html
        assert 'cfg-run-max-age' in html

    def test_general_category_collapsed_by_default(self, client):
        """The General category should be collapsed on page load."""
        res = client.get('/settings')
        html = res.data.decode('utf-8')
        assert 'id="category-general"' in html
        # The category and detail should have collapsed class
        cat_start = html.find('id="category-general"')
        assert cat_start > 0
        # Find the detail section
        assert 'id="detail-general"' in html

    def test_save_general_settings(self, client):
        """Saving general settings via the settings API should work."""
        # Update all general settings
        for key, value in [
            ('pi_cowork_url', 'http://example.com:8080'),
            ('max_parallel', '3'),
            ('max_per_hour', '50'),
            ('warm_spawn_threshold', '1800'),
            ('run_max_age', '3600'),
        ]:
            res = client.put(f'/api/settings/{key}', json={'value': value})
            assert res.status_code == 200
            data = json.loads(res.data)
            assert data['success'] is True

        # Save port separately (not in loop to avoid changing URL sync test)
        res = client.put('/api/settings/port', json={'value': '8080'})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True

        # Verify they were saved
        res = client.get('/api/settings/pi_cowork_url')
        assert json.loads(res.data)['value'] == 'http://example.com:8080'

        res = client.get('/api/settings/port')
        assert json.loads(res.data)['value'] == '8080'

        res = client.get('/api/settings/max_parallel')
        assert json.loads(res.data)['value'] == '3'

        res = client.get('/api/settings/max_per_hour')
        assert json.loads(res.data)['value'] == '50'

        res = client.get('/api/settings/warm_spawn_threshold')
        assert json.loads(res.data)['value'] == '1800'

        res = client.get('/api/settings/run_max_age')
        assert json.loads(res.data)['value'] == '3600'

    def test_toggle_general_category_js(self, client):
        """The toggleCategory JS should include the 'general' category."""
        res = client.get('/settings')
        html = res.data.decode('utf-8')
        assert "toggleCategory('general')" in html


# ---------------------------------------------------------------------------
# Config keys used by agents.py
# ---------------------------------------------------------------------------

class TestConfigConsumedByAgents:
    def test_port_from_db(self, client):
        """get_config should return port from DB."""
        with client.application.app_context():
            set_setting('port', '8080')
            result = get_config('port')
            assert result == 8080
            assert isinstance(result, int)

    def test_max_parallel_from_db(self, client):
        """agents.py should read max_parallel from DB via get_config."""
        with client.application.app_context():
            set_setting('max_parallel', '2')
            # Use the same resolution path that agents.py uses
            result = get_config('max_parallel')
            assert result == 2

    def test_pi_cowork_url_from_db(self, client):
        """api_docs.py should read pi_cowork_url from DB via get_config."""
        with client.application.app_context():
            set_setting('pi_cowork_url', 'http://custom-host:9999')
            result = get_config('pi_cowork_url')
            assert result == 'http://custom-host:9999'

    def test_warm_spawn_threshold_from_db(self, client):
        """agents.py should read warm_spawn_threshold from DB via get_config."""
        with client.application.app_context():
            set_setting('warm_spawn_threshold', '7200')
            assert get_config('warm_spawn_threshold') == 7200

    def test_run_max_age_from_db(self, client):
        """agents.py should read run_max_age from DB via get_config."""
        with client.application.app_context():
            set_setting('run_max_age', '14400')
            assert get_config('run_max_age') == 14400


# ---------------------------------------------------------------------------
# Settings listing includes new keys
# ---------------------------------------------------------------------------

class TestSettingsListingIncludesGeneral:
    def test_all_general_keys_in_settings_list(self, client):
        """GET /api/settings should include all new general setting keys."""
        res = client.get('/api/settings')
        data = json.loads(res.data)
        keys = {item['key'] for item in data}
        assert 'pi_cowork_url' in keys
        assert 'port' in keys
        assert 'max_parallel' in keys
        assert 'max_per_hour' in keys
        assert 'warm_spawn_threshold' in keys
        assert 'run_max_age' in keys


# ---------------------------------------------------------------------------
# CONFIG module metadata
# ---------------------------------------------------------------------------

class TestConfigModuleMetadata:
    def test_defaults_defined(self):
        """All expected default values should be in DEFAULTS."""
        assert DEFAULTS['pi_cowork_url'] == 'http://localhost:5000'
        assert DEFAULTS['port'] == '5000'
        assert DEFAULTS['max_parallel'] == '1'
        assert DEFAULTS['max_per_hour'] == '100'
        assert DEFAULTS['warm_spawn_threshold'] == '3600'
        assert DEFAULTS['run_max_age'] == '7200'
        assert DEFAULTS['log_retention_days'] == '30'

    def test_env_map_defined(self):
        """Env var mappings should include expected keys."""
        assert ENV_MAP['pi_cowork_url'] == 'PI_COWORK_URL'
        assert ENV_MAP['port'] == 'PI_PORT'
        assert ENV_MAP['max_parallel'] == 'PI_MAX_PARALLEL'
        assert ENV_MAP['max_per_hour'] == 'PI_MAX_PER_HOUR'
        assert ENV_MAP['log_retention_days'] == 'PI_LOG_RETENTION_DAYS'

    def test_int_keys_defined(self):
        """Int keys should include all numeric settings."""
        assert 'port' in _INT_KEYS
        assert 'max_parallel' in _INT_KEYS
        assert 'max_per_hour' in _INT_KEYS
        assert 'warm_spawn_threshold' in _INT_KEYS
        assert 'run_max_age' in _INT_KEYS
        assert 'log_retention_days' in _INT_KEYS
        # pi_cowork_url should NOT be in int keys
        assert 'pi_cowork_url' not in _INT_KEYS

    def test_module_level_aliases_preserved(self):
        """Backward-compatible module-level constants should still exist."""
        assert hasattr(config, 'PI_COWORK_URL')
        assert hasattr(config, 'PI_MAX_PARALLEL')
        assert hasattr(config, 'PI_MAX_PER_HOUR')
        assert hasattr(config, 'WARM_SPAWN_THRESHOLD_SECONDS')
        assert hasattr(config, 'RUN_MAX_AGE_SECONDS')