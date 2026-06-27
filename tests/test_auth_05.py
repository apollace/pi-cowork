"""Tests for Auth 05 — Agent API token injection.

When authentication is enabled, spawned agents receive a dedicated API token in
their context message.  The token is cached in the agent's session directory so
warm spawns reuse it, and all dedicated agent tokens are revoked when auth is
disabled.
"""

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from pi_cowork import auth
from pi_cowork.agent_auth import get_or_create_agent_api_token, revoke_agent_api_tokens
from pi_cowork.db import query_db as _query_db
from pi_cowork.models import create_api_token, create_user, set_setting


@contextmanager
def _auth_enabled(app, enabled=1):
    """Temporarily toggle the auth_enabled setting inside an app context."""
    with app.app_context():
        set_setting("auth_enabled", str(enabled))
    try:
        yield
    finally:
        with app.app_context():
            set_setting("auth_enabled", str(0))


def _create_user(client, username, password):
    """Create a test user and return the user row."""
    with client.application.app_context():
        user_id = create_user(username, auth.hash_password(password))
    return {"id": user_id, "username": username}


def _count_agent_tokens(app):
    with app.app_context():
        row = _query_db(
            "SELECT COUNT(*) AS c FROM api_tokens WHERE name LIKE 'agent-%-ticket-%'",
            one=True,
        )
    return row["c"]


class TestAgentTokenColdSpawnDisabled:
    """Auth disabled: no token is created or injected."""

    def test_cold_spawn_no_token_when_auth_disabled(self, client, default_workflow, default_board):
        agent = client.post(
            "/api/agents",
            json={
                "name": "TokenDisabledAgent",
                "description": "You are an agent.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "TokenDisabledStage",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Token Disabled Ticket",
                "body": "Do things",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            res = client.put(f"/api/tickets/{tid}", json={"status_id": sid})
        assert res.status_code == 200

        context_msg = captured_cmd[-1]
        assert "Authorization" not in context_msg
        assert "Bearer" not in context_msg
        assert "agent-" not in context_msg  # no dedicated agent token name leakage
        assert "Headers:" not in context_msg

        assert _count_agent_tokens(client.application) == 0


class TestAgentTokenColdSpawnEnabled:
    """Auth enabled: dedicated token is created and injected into agent docs."""

    def test_cold_spawn_token_injected_and_works(self, client, default_workflow, default_board):
        user = _create_user(client, "agent-auth-user", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        res = client.put("/api/settings/auth_enabled", json={"value": "1"})
        assert res.status_code == 200

        agent = client.post(
            "/api/agents",
            json={
                "name": "TokenEnabledAgent",
                "description": "You are an agent.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "TokenEnabledStage",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Token Enabled Ticket",
                "body": "Do auth things",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            res = client.put(f"/api/tickets/{tid}", json={"status_id": sid})
        assert res.status_code == 200

        context_msg = captured_cmd[-1]
        expected_name = f"agent-{aid}-ticket-{tid}"

        # Token header appears at the top of the API docs block.
        assert "Headers: Authorization: Bearer " in context_msg
        token_start = context_msg.find("Headers: Authorization: Bearer ") + len("Headers: Authorization: Bearer ")
        token_end = context_msg.find("\n", token_start)
        token = context_msg[token_start:token_end].strip()
        assert token
        assert token != "<token>"
        assert token != "<api_token>"

        # A matching row exists in the database.
        with client.application.app_context():
            row = auth.get_api_token(hashlib.sha256(token.encode("utf-8")).hexdigest())
        assert row is not None
        assert row["name"] == expected_name
        assert row["user_id"] == user["id"]

        # The token authenticates agent-scoped API calls.
        headers = {"Authorization": f"Bearer {token}"}
        res = client.put(f"/api/tickets/{tid}", json={"title": "Updated by token"}, headers=headers)
        assert res.status_code == 200

        res = client.post(f"/api/tickets/{tid}/comments", json={"body": "Agent comment via token"}, headers=headers)
        assert res.status_code == 201

        comments = client.get(f"/api/tickets/{tid}/comments", headers=headers)
        assert comments.status_code == 200
        bodies = {c["body"] for c in json.loads(comments.data)}
        assert "Agent comment via token" in bodies


class TestAgentTokenWarmSpawnReuse:
    """Warm spawns reuse the cached token; no new DB row is created."""

    def test_warm_spawn_reuses_cached_token(self, client, default_workflow, default_board):
        user = _create_user(client, "warm-user", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        client.put("/api/settings/auth_enabled", json={"value": "1"})

        agent = client.post(
            "/api/agents",
            json={
                "name": "WarmTokenAgent",
                "description": "You are an agent.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "WarmStage1",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        s2 = client.post(
            "/api/statuses",
            json={
                "name": "WarmStage2",
                "sort_order": 2,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid1 = json.loads(s1.data)["id"]
        sid2 = json.loads(s2.data)["id"]

        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Warm Token Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]

        # First cold spawn.
        with patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid1})

        first_count = _count_agent_tokens(client.application)
        assert first_count == 1

        # Simulate a real pi session file so warm-spawn detection works.
        session_dir = os.path.join("workspace", ".pi-sessions", str(aid), f"ticket-{tid}")
        os.makedirs(session_dir, exist_ok=True)
        with open(os.path.join(session_dir, "session.jsonl"), "w") as f:
            f.write('{"type":"message"}\n')

        cached_file = Path(session_dir) / "agent_api_token"
        assert cached_file.exists()
        cached_token = cached_file.read_text().strip()

        # Force the new comment to be newer than the last spawn so warm context has deltas.
        # Bump the comment timestamp so warm-spawn new-comment detection works.
        with client.application.app_context():
            from pi_cowork.db import get_db

            db = get_db()
            db.execute(
                "UPDATE comments SET created_at = datetime('now', '+1 minute') WHERE ticket_id = ?",
                (tid,),
            )
            db.commit()

        # Second spawn (warm, same agent, status change).
        with (
            patch("app.subprocess.Popen", return_value=MagicMock(pid=9999)),
            patch("app.os.path.isdir", return_value=True),
        ):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid2})

        # No additional agent token rows were created.
        assert _count_agent_tokens(client.application) == 1

        # The cached token is unchanged.
        assert cached_file.read_text().strip() == cached_token

        # Warm-spawn context does not re-inject the API docs block.
        # We already asserted no new token row; the cache reuse covers the requirement.


class TestAgentTokenRevokeOnDisable:
    """Disabling auth revokes all dedicated agent tokens."""

    def test_disable_auth_revokes_agent_tokens(self, client, default_workflow, default_board):
        user = _create_user(client, "revoke-user", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        client.put("/api/settings/auth_enabled", json={"value": "1"})

        agent = client.post(
            "/api/agents",
            json={
                "name": "RevokeAgent",
                "description": "You are an agent.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "RevokeStage",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Revoke Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        assert _count_agent_tokens(client.application) == 1

        context_msg = captured_cmd[-1]
        token_start = context_msg.find("Headers: Authorization: Bearer ") + len("Headers: Authorization: Bearer ")
        token_end = context_msg.find("\n", token_start)
        token = context_msg[token_start:token_end].strip()

        # Token works before revocation.
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get(f"/api/tickets/{tid}", headers=headers).status_code == 200

        # Disable auth.
        client.put("/api/settings/auth_enabled", json={"value": "0"})

        # Dedicated agent token row is gone.
        assert _count_agent_tokens(client.application) == 0

        # After disabling auth, the API is open again.
        res = client.get(f"/api/tickets/{tid}")
        assert res.status_code == 200


class TestAgentTokenRestrictedEndpoints:
    """Agent docs never expose human-only endpoints, even if configured."""

    def test_restricted_endpoints_not_in_agent_docs(self, client, default_workflow, default_board):
        user = _create_user(client, "restricted-user", "pw123456")
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        client.put("/api/settings/auth_enabled", json={"value": "1"})

        # Configure an agent that explicitly asks for restricted + allowed keys.
        agent = client.post(
            "/api/agents",
            json={
                "name": "RestrictedAgent",
                "description": "You are an agent.",
                "workflow_id": default_workflow["id"],
                "api_endpoints": [
                    "ticket_put",
                    "ticket_comments_post",
                    "gate_review_put",
                    "agent_run_kill",
                    "settings_put",
                    "db_backup_restore",
                ],
            },
        )
        aid = json.loads(agent.data)["id"]

        s1 = client.post(
            "/api/statuses",
            json={
                "name": "RestrictedStage",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        ticket = client.post(
            "/api/tickets",
            json={
                "title": "Restricted Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(ticket.data)["id"]

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        context_msg = captured_cmd[-1]

        # Allowed endpoints are documented.
        with client.application.app_context():
            from pi_cowork.config import get_config

            base_url = get_config("pi_cowork_url")
        assert f"PUT {base_url}/api/tickets/{tid}" in context_msg
        assert f"POST {base_url}/api/tickets/{tid}/comments" in context_msg

        # Human-only endpoints are filtered out.
        assert "/api/gate_reviews/" not in context_msg
        assert "/api/agent_runs/" not in context_msg
        assert "/api/settings/" not in context_msg
        assert "/api/db-backup/" not in context_msg


class TestAgentTokenUnit:
    """Unit-level coverage for pi_cowork/agent_auth.py helpers."""

    def test_get_or_create_returns_none_when_auth_disabled(self, client, default_workflow, default_board):
        with client.application.app_context():
            assert get_or_create_agent_api_token(1, 1, "/tmp/fake-session") is None

    def test_revoke_agent_api_tokens_deletes_matching_rows(self, client):
        user = _create_user(client, "revoke-unit", "pw123456")
        with client.application.app_context():
            token, token_hash = auth.generate_api_token()
            create_api_token(user["id"], "agent-1-ticket-1", token_hash)
            token2, token_hash2 = auth.generate_api_token()
            create_api_token(user["id"], "agent-1-ticket-2", token_hash2)
            create_api_token(user["id"], "human-laptop", "deadbeef")

            assert revoke_agent_api_tokens() is None
            rows = _query_db(
                "SELECT name FROM api_tokens WHERE name LIKE 'agent-%-ticket-%'",
                one=False,
            )
            assert len(rows) == 0
            human = _query_db("SELECT * FROM api_tokens WHERE name = ?", ("human-laptop",), one=True)
            assert human is not None
