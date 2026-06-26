"""Tests for Auth 03 — login/logout UI and first-run setup endpoints."""

import json
from contextlib import contextmanager

import pytest

from app import app as flask_app
from pi_cowork import auth
from pi_cowork.models import create_user, set_setting


def _create_user(client, username, password):
    """Create a test user and return the user row."""
    with client.application.app_context():
        user_id = create_user(username, auth.hash_password(password))
    return {"id": user_id, "username": username}


@contextmanager
def auth_enabled(app, enabled=1):
    """Temporarily toggle the auth_enabled setting inside an app context."""
    with app.app_context():
        set_setting("auth_enabled", str(enabled))
    try:
        yield
    finally:
        with app.app_context():
            set_setting("auth_enabled", str(0))


class TestAuthApiSetup:
    """POST /api/auth/setup — first-run account creation."""

    def test_setup_creates_first_user_and_starts_session(self, client):
        res = client.post(
            "/api/auth/setup",
            json={"username": "first", "password": "secret123"},
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["id"]
        assert data["username"] == "first"

        # User is now logged in
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        me_data = json.loads(me.data)
        assert me_data["username"] == "first"

    def test_setup_requires_username_and_password(self, client):
        res = client.post("/api/auth/setup", json={"username": "first"})
        assert res.status_code == 400
        res2 = client.post("/api/auth/setup", json={"password": "secret123"})
        assert res2.status_code == 400

    def test_setup_rejects_blank_username_or_password(self, client):
        res = client.post("/api/auth/setup", json={"username": "  ", "password": "x"})
        assert res.status_code == 400
        res2 = client.post("/api/auth/setup", json={"username": "x", "password": ""})
        assert res2.status_code == 400

    def test_setup_returns_409_when_user_already_exists(self, client):
        _create_user(client, "first", "secret123")
        res = client.post(
            "/api/auth/setup",
            json={"username": "attacker", "password": "pw"},
        )
        assert res.status_code == 409
        assert "already exists" in json.loads(res.data)["error"]


class TestAuthApiLogin:
    """POST /api/auth/login."""

    def test_login_success(self, client):
        _create_user(client, "alice", "wonderland")
        res = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "wonderland"},
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["username"] == "alice"

    def test_login_starts_session(self, client):
        _create_user(client, "bob", "builder")
        client.post(
            "/api/auth/login",
            json={"username": "bob", "password": "builder"},
        )
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert json.loads(me.data)["username"] == "bob"

    def test_login_invalid_password(self, client):
        _create_user(client, "charlie", "chaplin")
        res = client.post(
            "/api/auth/login",
            json={"username": "charlie", "password": "wrong"},
        )
        assert res.status_code == 401

    def test_login_unknown_user(self, client):
        res = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "pw"},
        )
        assert res.status_code == 401

    def test_login_requires_username_and_password(self, client):
        res = client.post("/api/auth/login", json={"username": "x"})
        assert res.status_code == 400


class TestAuthApiMe:
    """GET /api/auth/me."""

    def test_me_returns_401_when_not_logged_in(self, client):
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_me_returns_current_user(self, client):
        user = _create_user(client, "dave", "password")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]
        res = client.get("/api/auth/me")
        assert res.status_code == 200
        assert json.loads(res.data)["username"] == "dave"


class TestAuthApiLogout:
    """POST /api/auth/logout."""

    def test_logout_clears_session(self, client):
        user = _create_user(client, "eve", "password")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]
        res = client.post("/api/auth/logout")
        assert res.status_code == 200
        assert json.loads(res.data)["ok"] is True
        me = client.get("/api/auth/me")
        assert me.status_code == 401


class TestLoginPage:
    """GET /login page rendering."""

    def test_login_page_setup_mode_when_no_users(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/login")
            assert res.status_code == 200
            text = res.data.decode("utf-8")
            assert "Create account" in text
            # The endpoint path only appears inside inline JS, which is fine
            assert "id=\"auth-submit\"" in text

    def test_login_page_login_mode_when_user_exists(self, client):
        _create_user(client, "frank", "pw")
        with auth_enabled(client.application, enabled=1):
            res = client.get("/login")
            assert res.status_code == 200
            text = res.data.decode("utf-8")
            assert "Sign in" in text
            assert "id=\"auth-submit\"" in text

    def test_login_page_accepts_next_query(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/login?next=%2Fsettings")
            assert res.status_code == 200
            assert "/settings" in res.data.decode("utf-8")


class TestFirstRunRedirect:
    """First-run: when auth is enabled and no user exists, pages redirect to /login."""

    def test_board_redirects_to_login_setup_mode(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/board")
            assert res.status_code == 302
            assert res.headers["Location"].startswith("/login?next=")

    def test_root_redirects_to_login_setup_mode(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/")
            assert res.status_code == 302
            assert res.headers["Location"].startswith("/login?next=")


class TestLoginFlowIntegration:
    """End-to-end: first-run setup then login."""

    def test_setup_then_login_redirect(self, client):
        with auth_enabled(client.application, enabled=1):
            # First request redirects to login/setup
            res = client.get("/board")
            assert res.status_code == 302

            # Create account
            res = client.post(
                "/api/auth/setup",
                json={"username": "admin", "password": "adminpass"},
            )
            assert res.status_code == 201

            # Board is now accessible
            res = client.get("/board")
            assert res.status_code == 200

            # Logout
            client.post("/api/auth/logout")
            res = client.get("/board")
            assert res.status_code == 302

            # Login again
            res = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "adminpass"},
            )
            assert res.status_code == 200
            res = client.get("/board")
            assert res.status_code == 200


class TestAuthEndpointsRequireNoBody:
    """Ensure endpoints tolerate non-JSON input gracefully."""

    def test_setup_with_empty_body_returns_400(self, client):
        res = client.post("/api/auth/setup", content_type="application/json")
        assert res.status_code == 400

    def test_login_with_empty_body_returns_400(self, client):
        res = client.post("/api/auth/login", content_type="application/json")
        assert res.status_code == 400


class TestAuthEndpointRegistry:
    """New auth routes are covered by the endpoint registry."""

    def test_registry_lists_auth_endpoints(self, client):
        res = client.get("/api/endpoint-registry")
        assert res.status_code == 200
        keys = {e["key"] for e in json.loads(res.data)["endpoints"]}
        assert "auth_setup" in keys
        assert "auth_login" in keys
        assert "auth_logout" in keys
        assert "auth_me" in keys

    def test_auth_endpoints_are_restricted(self):
        from pi_cowork.api_docs import AGENT_RESTRICTED_KEYS
        assert "auth_setup" in AGENT_RESTRICTED_KEYS
        assert "auth_login" in AGENT_RESTRICTED_KEYS
        assert "auth_logout" in AGENT_RESTRICTED_KEYS
        assert "auth_me" in AGENT_RESTRICTED_KEYS
