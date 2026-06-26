"""Tests for Auth 02 — authentication backend logic and middleware."""

import json
from contextlib import contextmanager

from pi_cowork import auth
from pi_cowork.models import create_api_token, create_user, set_setting


def _create_user(password):
    """Create a test user and return (user_id, username, password)."""
    username = "testuser"
    user_id = create_user(username, auth.hash_password(password))
    return user_id, username, password


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


class TestPasswordHashing:
    def test_hash_password_returns_verifiable_hash(self):
        plain = "correct horse battery staple"
        hash_ = auth.hash_password(plain)
        assert hash_ != plain
        assert auth.verify_password(plain, hash_)
        assert not auth.verify_password("wrong", hash_)


class TestSessionHelpers:
    def test_create_session_sets_user_id(self, client):
        with client.application.test_request_context():
            auth.create_session(42)
            assert __import__("flask").session.get("user_id") == 42

    def test_clear_session_removes_user_id(self, client):
        with client.application.test_request_context():
            auth.create_session(42)
            auth.clear_session()
            assert "user_id" not in __import__("flask").session


class TestApiTokenHelpers:
    def test_generate_api_token_returns_token_and_hash(self):
        token, hash_ = auth.generate_api_token()
        assert token
        assert hash_
        assert hash_ != token
        import hashlib

        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert hash_ == expected

    def test_validate_api_token_returns_user(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")
            token, token_hash = auth.generate_api_token()
            _ = create_api_token(user_id, "agent-key", token_hash)

        with client.application.app_context():
            user = auth.validate_api_token(token)

        assert user is not None
        assert user["id"] == user_id
        assert user["username"] == "testuser"

    def test_validate_api_token_invalid_returns_none(self, client):
        with client.application.app_context():
            assert auth.validate_api_token("not-a-real-token") is None

    def test_validate_api_token_updates_last_used_at(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")
            token, token_hash = auth.generate_api_token()
            _ = create_api_token(user_id, "agent-key", token_hash)

        with client.application.app_context():
            auth.validate_api_token(token)
            row = auth.get_api_token(token_hash)
            assert row["last_used_at"] is not None


class TestMiddlewareDisabledAuth:
    """Auth middleware must be transparent when auth_enabled=0."""

    def test_api_routes_accessible_without_session(self, client, default_board):
        res = client.get("/api/boards")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data

    def test_html_routes_accessible_without_session(self, client):
        res = client.get("/board")
        assert res.status_code == 200

    def test_static_routes_accessible(self, client):
        res = client.get("/static/style.css")
        assert res.status_code == 200


class TestMiddlewareEnabledAuth:
    """Auth middleware blocks unauthenticated traffic when auth_enabled=1."""

    def test_api_route_returns_401_without_session_or_token(self, client, default_board):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/boards")
            assert res.status_code == 401
            data = json.loads(res.data)
            assert data["error"] == "Authentication required"

    def test_html_route_redirects_to_login(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/board")
            assert res.status_code == 302
            assert res.headers["Location"] == "/login?next=%2Fboard"

    def test_root_redirects_to_login(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/")
            assert res.status_code == 302
            assert res.headers["Location"] == "/login?next=%2F"

    def test_exempt_auth_setup_route_not_blocked(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup")
            assert res.status_code != 401

    def test_exempt_login_route_not_blocked(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/login")
            assert res.status_code == 200

    def test_exempt_static_route_not_blocked(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/static/style.css")
            assert res.status_code == 200


class TestMiddlewareSessionAccess:
    """Valid browser session opens both API and HTML routes."""

    def test_session_opens_api_route(self, client, default_board):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")

        with auth_enabled(client.application, enabled=1):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

            res = client.get("/api/boards")
            assert res.status_code == 200

    def test_session_opens_html_route(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")

        with auth_enabled(client.application, enabled=1):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

            res = client.get("/board")
            assert res.status_code == 200


class TestMiddlewareTokenAccess:
    """Bearer tokens satisfy API routes but not HTML routes."""

    def test_valid_bearer_token_opens_api_route(self, client, default_board):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "agent-key", token_hash)

        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/boards", headers={"Authorization": f"Bearer {token}"})
            assert res.status_code == 200

    def test_bearer_token_does_not_open_html_route(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "agent-key", token_hash)

        with auth_enabled(client.application, enabled=1):
            res = client.get("/board", headers={"Authorization": f"Bearer {token}"})
            assert res.status_code == 302
            assert res.headers["Location"].startswith("/login?next=")

    def test_invalid_bearer_token_returns_401(self, client, default_board):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/boards", headers={"Authorization": "Bearer invalid-token"})
            assert res.status_code == 401

    def test_missing_bearer_prefix_falls_back_to_session_check(self, client, default_board):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/boards", headers={"Authorization": "not-bearer-token"})
            assert res.status_code == 401


class TestCurrentUser:
    def test_current_user_returns_none_without_session(self, client):
        with client.application.test_request_context():
            assert auth.current_user() is None

    def test_current_user_resolves_from_session(self, client):
        with client.application.app_context():
            user_id, username, _ = _create_user("secret123")

        with client.application.test_request_context():
            __import__("flask").session["user_id"] = user_id
            user = auth.current_user()
            assert user is not None
            assert user["id"] == user_id
            assert user["username"] == username

    def test_current_user_cached_on_g(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")

        with client.application.test_request_context():
            from flask import g

            __import__("flask").session["user_id"] = user_id
            assert not hasattr(g, "current_user")
            u1 = auth.current_user()
            u2 = auth.current_user()
            assert u1 is u2
            assert g.current_user is u1


class TestContextProcessor:
    def test_current_user_injected_into_template_context(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user("secret123")

        with auth_enabled(client.application, enabled=1), client.application.test_request_context("/board"):
            flask = __import__("flask")
            flask.session["user_id"] = user_id
            processors = client.application.template_context_processors[None]
            context = {}
            for processor in processors:
                context.update(processor())
            assert context.get("current_user") is not None
            assert context["current_user"]["id"] == user_id

    def test_current_user_none_in_template_context_when_not_logged_in(self, client):
        with auth_enabled(client.application, enabled=0), client.application.test_request_context("/board"):
            processors = client.application.template_context_processors[None]
            context = {}
            for processor in processors:
                context.update(processor())
            assert context.get("current_user") is None
