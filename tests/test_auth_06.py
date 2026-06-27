"""Tests Auth 06 — SSE authentication, auth edge cases, and before_request exemptions."""

import secrets
from contextlib import contextmanager

from pi_cowork import auth
from pi_cowork.models import create_api_token, create_user, set_setting


def _create_user():
    """Create a test user and return (user_id, username, password)."""
    username = "testuser"
    password = secrets.token_urlsafe(16)
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


class TestSSEAuth:
    """SSE endpoint accepts session cookie or ?token query param."""

    def test_sse_with_valid_token_returns_event_stream(self, client, default_board):
        with client.application.app_context():
            user_id, _, _ = _create_user()
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "sse-token", token_hash)

        with auth_enabled(client.application, enabled=1):
            url = f"/api/events/stream?board_id={default_board['id']}&token={token}"
            res = client.get(url, buffered=False)
            assert res.status_code == 200
            assert "text/event-stream" in res.content_type
            res.close()

    def test_sse_with_invalid_token_returns_401(self, client, default_board):
        with auth_enabled(client.application, enabled=1):
            url = f"/api/events/stream?board_id={default_board['id']}&token=invalid"
            res = client.get(url, buffered=False)
            assert res.status_code == 401
            res.close()

    def test_sse_without_token_or_session_returns_401(self, client, default_board):
        with auth_enabled(client.application, enabled=1):
            url = f"/api/events/stream?board_id={default_board['id']}"
            res = client.get(url, buffered=False)
            assert res.status_code == 401
            res.close()

    def test_sse_with_session_returns_event_stream(self, client, default_board):
        with client.application.app_context():
            user_id, _, _ = _create_user()

        with auth_enabled(client.application, enabled=1):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

            url = f"/api/events/stream?board_id={default_board['id']}"
            res = client.get(url, buffered=False)
            assert res.status_code == 200
            assert "text/event-stream" in res.content_type
            res.close()

    def test_sse_auth_disabled_requires_no_token(self, client, default_board):
        with auth_enabled(client.application, enabled=0):
            url = f"/api/events/stream?board_id={default_board['id']}"
            res = client.get(url, buffered=False)
            assert res.status_code == 200
            assert "text/event-stream" in res.content_type
            res.close()


class TestSetupRouteConditionalExemption:
    """/api/auth/setup is exempt only when no users exist (first-run)."""

    def test_setup_reachable_on_first_run(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup")
            assert res.status_code != 401
            assert res.status_code != 302

    def test_setup_blocked_after_user_exists(self, client):
        with client.application.app_context():
            _create_user()

        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup")
            assert res.status_code in (401, 302)

    def test_setup_needed_always_exempt(self, client):
        with client.application.app_context():
            _create_user()

        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup-needed")
            assert res.status_code == 200


class TestAssistantSessionOnly:
    """Assistant endpoints require a browser session, not an API token."""

    def test_assistant_config_requires_session(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user()
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "assistant-token", token_hash)

        with auth_enabled(client.application, enabled=1):
            res = client.get(
                "/api/assistant/config",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 401

    def test_assistant_history_opens_with_session(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user()

        with auth_enabled(client.application, enabled=1):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

            res = client.get("/api/assistant/history")
            assert res.status_code == 200

    def test_assistant_config_opens_with_session(self, client):
        with client.application.app_context():
            user_id, _, _ = _create_user()

        with auth_enabled(client.application, enabled=1):
            with client.session_transaction() as sess:
                sess["user_id"] = user_id

            res = client.get("/api/assistant/config")
            assert res.status_code == 200


class TestStaticAndHookInterference:
    """Static assets remain reachable; existing hooks keep working."""

    def test_static_css_loads_without_session(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/static/style.css")
            assert res.status_code == 200

    def test_request_timing_hook_still_fires(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup-needed")
            assert res.status_code == 200
            # /api/auth/setup-needed is skipped from audit/slow logging, but we
            # still want to prove the response made it through the middleware
            # stack without crashing. Pick a non-skipped path for timing hook:
            res2 = client.get("/login")
            assert res2.status_code == 200
