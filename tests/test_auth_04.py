"""Tests for Auth 04 — Security settings UI backend.

Covers password change, API token management, and session-only enforcement.
"""

import hashlib
import json
from contextlib import contextmanager

from pi_cowork import auth
from pi_cowork.models import create_api_token, create_user, set_setting


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


class TestSetupNeededEndpoint:
    """GET /api/auth/setup-needed — unauthenticated first-run check."""

    def test_setup_needed_true_when_no_users(self, client):
        res = client.get("/api/auth/setup-needed")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["setup_needed"] is True

    def test_setup_needed_false_after_user_created(self, client):
        _create_user(client, "first", "secret123")
        res = client.get("/api/auth/setup-needed")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["setup_needed"] is False

    def test_setup_needed_works_when_auth_enabled(self, client):
        with auth_enabled(client.application, enabled=1):
            res = client.get("/api/auth/setup-needed")
            assert res.status_code == 200


class TestChangePasswordEndpoint:
    """PUT /api/auth/password — session-only password change."""

    def test_change_password_success(self, client):
        user = _create_user(client, "alice", "oldpass123")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put(
            "/api/auth/password",
            json={"current_password": "oldpass123", "new_password": "newpass123"},
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

        # Old password no longer works
        me = client.get("/api/auth/me")
        assert me.status_code == 200

        with client.application.app_context():
            row = auth.get_user_by_id(user["id"])
        assert auth.verify_password("newpass123", row["password_hash"])
        assert not auth.verify_password("oldpass123", row["password_hash"])

    def test_change_password_wrong_current(self, client):
        user = _create_user(client, "bob", "right123")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put(
            "/api/auth/password",
            json={"current_password": "wrong123", "new_password": "newpass123"},
        )
        assert res.status_code == 401
        assert "incorrect" in json.loads(res.data)["error"].lower()

    def test_change_password_too_short(self, client):
        user = _create_user(client, "carol", "oldpass123")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put(
            "/api/auth/password",
            json={"current_password": "oldpass123", "new_password": "short"},
        )
        assert res.status_code == 400
        assert "8" in json.loads(res.data)["error"]

    def test_change_password_requires_session(self, client):
        res = client.put(
            "/api/auth/password",
            json={"current_password": "x", "new_password": "y"},
        )
        assert res.status_code == 401

    def test_change_password_rejects_bearer_token(self, client):
        with client.application.app_context():
            user_id, _, _ = ("dummy", "dummy", "dummy")
            user_id = create_user("token-user", auth.hash_password("secret123"))
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "agent-key", token_hash)

        with auth_enabled(client.application, enabled=1):
            res = client.put(
                "/api/auth/password",
                json={"current_password": "secret123", "new_password": "newpass123"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 401


class TestTokenEndpoints:
    """GET/POST/DELETE /api/auth/tokens — session-only token management."""

    def test_list_tokens_empty(self, client):
        user = _create_user(client, "alice", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.get("/api/auth/tokens")
        assert res.status_code == 200
        assert json.loads(res.data) == []

    def test_create_and_list_token(self, client):
        user = _create_user(client, "bob", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.post("/api/auth/tokens", json={"name": "laptop"})
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["id"]
        assert data["token"]
        plaintext = data["token"]

        # Verify hash stored, not plaintext
        with client.application.app_context():
            row = auth.get_api_token(hashlib.sha256(plaintext.encode("utf-8")).hexdigest())
        assert row is not None
        assert row["user_id"] == user["id"]

        # List returns metadata without hash or plaintext
        res2 = client.get("/api/auth/tokens")
        assert res2.status_code == 200
        tokens = json.loads(res2.data)
        assert len(tokens) == 1
        assert tokens[0]["name"] == "laptop"
        assert "token" not in tokens[0]
        assert "token_hash" not in tokens[0]
        assert tokens[0]["id"] == data["id"]

    def test_create_token_requires_name(self, client):
        user = _create_user(client, "charlie", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.post("/api/auth/tokens", json={})
        assert res.status_code == 400

    def test_revoke_token(self, client):
        user = _create_user(client, "dave", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.post("/api/auth/tokens", json={"name": "phone"})
        token_id = json.loads(res.data)["id"]

        res2 = client.delete(f"/api/auth/tokens/{token_id}")
        assert res2.status_code == 200

        res3 = client.get("/api/auth/tokens")
        assert json.loads(res3.data) == []

    def test_revoke_other_user_token_fails(self, client):
        user_a = _create_user(client, "alice", "pw123456")
        user_b = _create_user(client, "bob", "pw123456")

        with client.application.app_context():
            token_id = create_api_token(user_b["id"], "stolen", "sha256-of-token")

        with client.session_transaction() as sess:
            sess["user_id"] = user_a["id"]

        res = client.delete(f"/api/auth/tokens/{token_id}")
        assert res.status_code == 404

    def test_token_endpoints_require_session(self, client):
        assert client.get("/api/auth/tokens").status_code == 401
        assert client.post("/api/auth/tokens", json={"name": "x"}).status_code == 401
        assert client.delete("/api/auth/tokens/1").status_code == 401

    def test_token_endpoints_reject_bearer_token(self, client):
        with client.application.app_context():
            user_id = create_user("token-user-2", auth.hash_password("secret123"))
            token, token_hash = auth.generate_api_token()
            create_api_token(user_id, "agent-key", token_hash)

        with auth_enabled(client.application, enabled=1):
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/auth/tokens", headers=headers).status_code == 401
            assert client.post("/api/auth/tokens", json={"name": "x"}, headers=headers).status_code == 401
            assert client.delete("/api/auth/tokens/1", headers=headers).status_code == 401


class TestAuthEndpointRegistry:
    """New auth routes are covered by the endpoint registry and restricted."""

    def test_registry_lists_new_auth_endpoints(self, client):
        res = client.get("/api/endpoint-registry")
        assert res.status_code == 200
        keys = {e["key"] for e in json.loads(res.data)["endpoints"]}
        assert "auth_password" in keys
        assert "auth_tokens_list" in keys
        assert "auth_tokens_create" in keys
        assert "auth_tokens_delete" in keys
        assert "auth_setup_needed" in keys

    def test_new_auth_endpoints_are_restricted(self):
        from pi_cowork.api_docs import AGENT_RESTRICTED_KEYS

        assert "auth_password" in AGENT_RESTRICTED_KEYS
        assert "auth_tokens_list" in AGENT_RESTRICTED_KEYS
        assert "auth_tokens_create" in AGENT_RESTRICTED_KEYS
        assert "auth_tokens_delete" in AGENT_RESTRICTED_KEYS
        assert "auth_setup_needed" in AGENT_RESTRICTED_KEYS


class TestAuthEnabledToggle:
    """Auth can be enabled/disabled via settings when a user exists."""

    def test_auth_enabled_setting_persists(self, client):
        user = _create_user(client, "admin", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put("/api/settings/auth_enabled", json={"value": "1"})
        assert res.status_code == 200

        with client.application.app_context():
            from pi_cowork.config import get_config

            assert get_config("auth_enabled") == 1

        res2 = client.put("/api/settings/auth_enabled", json={"value": "0"})
        assert res2.status_code == 200

        with client.application.app_context():
            assert get_config("auth_enabled") == 0

    def test_new_auth_routes_blocked_when_auth_enabled(self, client):
        """The new /api/auth/* routes should require a session even when auth is off,
        because they are no longer blanket-exempt."""
        res = client.put("/api/auth/password", json={"current_password": "x", "new_password": "y"})
        assert res.status_code == 401

        res = client.get("/api/auth/tokens")
        assert res.status_code == 401

        res = client.post("/api/auth/tokens", json={"name": "x"})
        assert res.status_code == 401


class TestAuthEnableGuard:
    """PUT /api/settings/auth_enabled rejects enabling when no user exists."""

    def test_cannot_enable_auth_without_user(self, client):
        res = client.put("/api/settings/auth_enabled", json={"value": "1"})
        assert res.status_code == 400
        data = json.loads(res.data)
        assert "Create an account first" in data["error"]

        with client.application.app_context():
            from pi_cowork.config import get_config

            assert get_config("auth_enabled") == 0

    def test_can_enable_auth_after_user_created(self, client):
        user = _create_user(client, "admin", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put("/api/settings/auth_enabled", json={"value": "1"})
        assert res.status_code == 200

        with client.application.app_context():
            from pi_cowork.config import get_config

            assert get_config("auth_enabled") == 1
