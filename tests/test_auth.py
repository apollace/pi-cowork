"""Tests for the opt-in authentication subsystem."""

import contextlib
import json


def _close_sse(response):
    """Consume the first SSE chunk and close the response cleanly."""
    with contextlib.suppress(Exception):
        next(response.response)
    with contextlib.suppress(Exception):
        response.close()


def test_auth_disabled_default_routes_open(client):
    """When auth is disabled (default), HTML and API routes are public."""
    assert client.get("/board").status_code == 200
    assert client.get("/api/boards").status_code == 200


def test_auth_enabled_no_session_html_redirects(client, auth_enabled):
    """With auth enabled and no session, HTML routes redirect to /login."""
    resp = client.get("/board")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login?next=")


def test_auth_enabled_no_session_api_401(client, auth_enabled):
    """With auth enabled and no session, API routes return 401 JSON."""
    resp = client.get("/api/boards")
    assert resp.status_code == 401
    data = json.loads(resp.data)
    assert "error" in data


def test_auth_enabled_valid_session(client, auth_enabled):
    """A valid browser session can access both HTML and API routes."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    assert client.get("/board").status_code == 200
    assert client.get("/api/boards").status_code == 200


def test_auth_enabled_invalid_password(client, auth_enabled):
    """Login with the wrong password returns 401."""
    resp = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_auth_enabled_bearer_token_api(client, auth_enabled):
    """API routes accept a valid bearer token; HTML routes still need a session."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    token_resp = client.post("/api/auth/tokens", json={"name": "api-token"})
    assert token_resp.status_code == 201
    token = json.loads(token_resp.data)["token"]

    # API access with bearer token works
    api_resp = client.get("/api/boards", headers={"Authorization": f"Bearer {token}"})
    assert api_resp.status_code == 200

    # HTML access still requires a browser session; a token alone is not enough.
    client.post("/api/auth/logout")
    html_resp = client.get("/board", headers={"Authorization": f"Bearer {token}"})
    assert html_resp.status_code == 302


def test_revoked_token_returns_401(client, auth_enabled):
    """After revoking a token, requests using it are rejected."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    token_resp = client.post("/api/auth/tokens", json={"name": "revoked-token"})
    assert token_resp.status_code == 201
    token_data = json.loads(token_resp.data)
    token = token_data["token"]

    # Token works before revocation
    assert client.get("/api/boards", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    revoke = client.delete(f"/api/auth/tokens/{token_data['id']}")
    assert revoke.status_code == 200

    # Token is rejected after revocation
    assert client.get("/api/boards", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_first_run_setup(client):
    """Setup creates the first user; subsequent setup attempts return 409."""
    resp = client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
    assert resp.status_code == 201
    data = json.loads(resp.data)
    assert data["username"] == "admin"

    # The first run also establishes a session
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert json.loads(me.data)["username"] == "admin"

    second = client.post("/api/auth/setup", json={"username": "other", "password": "password123"})
    assert second.status_code == 409


def test_password_change(client, auth_enabled):
    """Password change requires the current password and updates the hash."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    change = client.put(
        "/api/auth/password",
        json={"current_password": auth_enabled["password"], "new_password": "newpass123"},
    )
    assert change.status_code == 200

    # Old password no longer works
    old_login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert old_login.status_code == 401

    # New password works
    new_login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": "newpass123"},
    )
    assert new_login.status_code == 200


def test_token_lifecycle(client, auth_enabled):
    """Generate a token, use it, list it, and revoke it."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    create = client.post("/api/auth/tokens", json={"name": "lifecycle-token"})
    assert create.status_code == 201
    token = json.loads(create.data)["token"]

    list_resp = client.get("/api/auth/tokens")
    assert list_resp.status_code == 200
    tokens = json.loads(list_resp.data)
    assert any(t["name"] == "lifecycle-token" for t in tokens)

    assert client.get("/api/boards", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    token_id = json.loads(create.data)["id"]
    revoke = client.delete(f"/api/auth/tokens/{token_id}")
    assert revoke.status_code == 200

    assert client.get("/api/boards", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_settings_toggle(client):
    """Enabling auth is guarded when no user exists; disabling reopens routes."""
    # Default state: auth disabled and no users
    assert client.get("/api/auth/setup-needed").status_code == 200

    # Enabling auth with no user should return a clear 400 (not a 401)
    enable_guard = client.put("/api/settings/auth_enabled", json={"value": "1"})
    assert enable_guard.status_code == 400

    # Create the first user
    setup = client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
    assert setup.status_code == 201

    # Now enabling auth succeeds
    enable = client.put("/api/settings/auth_enabled", json={"value": "1"})
    assert enable.status_code == 200

    # Routes are now protected (use a fresh anonymous context)
    client.post("/api/auth/logout")
    assert client.get("/api/boards").status_code == 401
    assert client.get("/board").status_code == 302

    # Disabling auth reopens everything
    re_login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    assert re_login.status_code == 200
    disable = client.put("/api/settings/auth_enabled", json={"value": "0"})
    assert disable.status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/boards").status_code == 200
    assert client.get("/board").status_code == 200


def test_sse_with_token(client, auth_enabled):
    """SSE opens with a valid query-param token and rejects invalid tokens."""
    login = client.post(
        "/api/auth/login",
        json={"username": auth_enabled["username"], "password": auth_enabled["password"]},
    )
    assert login.status_code == 200

    token_resp = client.post("/api/auth/tokens", json={"name": "sse-token"})
    assert token_resp.status_code == 201
    token = json.loads(token_resp.data)["token"]

    # Logout so the requests below rely purely on the token, not a session cookie.
    client.post("/api/auth/logout")

    valid = client.get(f"/api/events/stream?token={token}")
    assert valid.status_code == 200
    _close_sse(valid)

    invalid = client.get("/api/events/stream?token=not-a-real-token")
    assert invalid.status_code == 401
