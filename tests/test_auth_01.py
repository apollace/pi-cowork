"""Tests for the auth foundation data model (Ticket #202).

Covers users, api_tokens tables and the auth_enabled config setting.
"""

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
from pi_cowork.config import get_config
from pi_cowork.db import get_db
from pi_cowork.models import (
    create_api_token,
    create_user,
    get_api_token,
    get_user_by_username,
    list_api_tokens,
    revoke_api_token,
    set_setting,
    touch_api_token,
)


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
def client(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    flask_app.config["TESTING"] = True
    flask_app.config["DATABASE"] = db_path

    with flask_app.test_client() as client:
        with flask_app.app_context():
            init_db(flask_app)
        agents_module._drain_app = flask_app
        yield client
        agents_module._drain_app = None

    os.close(db_fd)
    os.unlink(db_path)


class TestUserHelpers:
    def test_create_and_get_user(self, client):
        with client.application.app_context():
            user_id = create_user("alice", "hashed-password")
            row = get_user_by_username("alice")
            assert row is not None
            assert row["id"] == user_id
            assert row["username"] == "alice"
            assert row["password_hash"] == "hashed-password"

    def test_get_user_missing_returns_none(self, client):
        with client.application.app_context():
            assert get_user_by_username("nobody") is None

    def test_duplicate_username_raises_integrity_error(self, client):
        with client.application.app_context():
            create_user("bob", "hash1")
            with pytest.raises(Exception):
                create_user("bob", "hash2")


class TestApiTokenHelpers:
    def test_create_get_list_revoke_token(self, client):
        with client.application.app_context():
            user_id = create_user("token-user", "hash")
            token_id = create_api_token(user_id, "laptop", "sha256-of-token")
            row = get_api_token("sha256-of-token")
            assert row is not None
            assert row["id"] == token_id
            assert row["user_id"] == user_id
            assert row["name"] == "laptop"

            tokens = list_api_tokens(user_id)
            assert len(tokens) == 1
            assert tokens[0]["token_hash"] == "sha256-of-token"

            revoke_api_token(token_id)
            assert get_api_token("sha256-of-token") is None
            assert list_api_tokens(user_id) == []

    def test_touch_api_token_updates_last_used_at(self, client):
        with client.application.app_context():
            user_id = create_user("touch-user", "hash")
            token_id = create_api_token(user_id, "phone", "token-hash")
            before = get_api_token("token-hash")["last_used_at"]
            assert before is None
            touch_api_token(token_id)
            after = get_api_token("token-hash")["last_used_at"]
            assert after is not None

    def test_cascade_deletes_tokens_when_user_deleted(self, client):
        with client.application.app_context():
            user_id = create_user("cascade-user", "hash")
            create_api_token(user_id, "watch", "watch-token")
            db = get_db()
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            assert get_api_token("watch-token") is None


class TestAuthEnabledConfig:
    def test_auth_enabled_defaults_to_zero_int(self, client):
        with client.application.app_context():
            assert get_config("auth_enabled") == 0
            assert isinstance(get_config("auth_enabled"), int)

    def test_auth_enabled_respects_env_var(self, client, monkeypatch):
        monkeypatch.setenv("PI_AUTH_ENABLED", "1")
        with client.application.app_context():
            assert get_config("auth_enabled") == 1

    def test_auth_enabled_respects_db_override(self, client):
        with client.application.app_context():
            set_setting("auth_enabled", "1")
            assert get_config("auth_enabled") == 1

    def test_auth_enabled_invalid_db_value_falls_back_to_env(self, client, monkeypatch):
        monkeypatch.setenv("PI_AUTH_ENABLED", "1")
        with client.application.app_context():
            set_setting("auth_enabled", "not-a-number")
            assert get_config("auth_enabled") == 1
