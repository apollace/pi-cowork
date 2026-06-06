"""Tests for ticket-level model & thinking overrides (Ticket #89)."""

import json

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_ticket(client, **kwargs):
    data = {"title": "Test", "board_id": 1, "status_id": 1}
    data.update(kwargs)
    res = client.post("/api/tickets", json=data)
    assert res.status_code == 201
    return json.loads(res.data)["id"]


# ---------------------------------------------------------------------------
# Model layer (via API to stay in request context)
# ---------------------------------------------------------------------------


class TestTicketStatusOverridesModels:
    """Unit tests for the data-access functions — exercised via API endpoints."""

    def test_get_overrides_empty(self, client):
        """Ticket with no overrides returns empty list."""
        ticket_id = _create_ticket(client)
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        assert res.status_code == 200
        assert json.loads(res.data) == []

    def test_set_and_get_override(self, client):
        """Setting an override and retrieving it works."""
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
                "thinking": "high",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] == "agent-model"
        assert data["thinking"] == "high"
        assert data["ticket_id"] == ticket_id
        assert data["status_id"] == 2

        # Retrieve via GET
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 1
        assert overrides[0]["model"] == "agent-model"
        assert overrides[0]["thinking"] == "high"

    def test_set_override_upsert(self, client):
        """Setting an override twice for same (ticket, status) updates it."""
        ticket_id = _create_ticket(client)
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
                "thinking": "high",
            },
        )
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "status-model",
                "thinking": "medium",
            },
        )
        assert res.status_code == 200

        overrides = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        data = json.loads(overrides.data)
        assert len(data) == 1
        assert data[0]["model"] == "status-model"
        assert data[0]["thinking"] == "medium"

    def test_delete_override(self, client):
        """Deleting an override removes it."""
        ticket_id = _create_ticket(client)
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        res = client.delete(f"/api/tickets/{ticket_id}/status_overrides/2")
        assert res.status_code == 200

        overrides = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        assert len(json.loads(overrides.data)) == 0

    def test_delete_nonexistent_override(self, client):
        """Deleting a non-existent override returns 200 without error."""
        ticket_id = _create_ticket(client)
        res = client.delete(f"/api/tickets/{ticket_id}/status_overrides/99")
        assert res.status_code == 200

    def test_get_overrides_for_ticket_returns_multiple(self, client):
        """A ticket can have overrides for multiple statuses."""
        ticket_id = _create_ticket(client)
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 3,
                "thinking": "low",
            },
        )
        overrides = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        data = json.loads(overrides.data)
        assert len(data) == 2

    def test_override_model_only(self, client):
        """Setting only model (no thinking) works."""
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] == "agent-model"
        assert data["thinking"] is None

    def test_override_thinking_only(self, client):
        """Setting only thinking (no model) works."""
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "thinking": "high",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] is None
        assert data["thinking"] == "high"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestTicketStatusOverridesAPI:
    """API tests for the ticket status override endpoints."""

    def test_get_overrides_empty(self, client):
        ticket_id = _create_ticket(client)
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        assert res.status_code == 200
        assert json.loads(res.data) == []

    def test_get_overrides_not_found_ticket(self, client):
        res = client.get("/api/tickets/99999/status_overrides")
        assert res.status_code == 404

    def test_put_override(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
                "thinking": "high",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] == "agent-model"
        assert data["thinking"] == "high"

    def test_put_override_not_found_ticket(self, client):
        res = client.put(
            "/api/tickets/99999/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        assert res.status_code == 404

    def test_put_override_missing_status_id(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "model": "agent-model",
            },
        )
        assert res.status_code == 400

    def test_put_override_invalid_status(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 99999,
                "model": "agent-model",
            },
        )
        assert res.status_code == 404

    def test_put_override_invalid_model(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "nonexistent-model-xyz",
            },
        )
        assert res.status_code == 400

    def test_put_override_invalid_thinking(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "thinking": "superultra",
            },
        )
        assert res.status_code == 400

    def test_put_override_clear_both_deletes(self, client):
        """When both model and thinking are set to empty/null, the override is deleted."""
        ticket_id = _create_ticket(client)
        # Set override first
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        # Clear it
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": None,
                "thinking": None,
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["action"] == "deleted"

        # Verify it's gone
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 0

    def test_put_override_model_only(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] == "agent-model"
        assert data["thinking"] is None

    def test_put_override_thinking_only(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "thinking": "medium",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] is None
        assert data["thinking"] == "medium"

    def test_delete_override(self, client):
        ticket_id = _create_ticket(client)
        # Set override first
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        # Delete it
        res = client.delete(f"/api/tickets/{ticket_id}/status_overrides/2")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["success"] is True

        # Verify it's gone
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        assert len(json.loads(res.data)) == 0

    def test_delete_override_not_found_ticket(self, client):
        res = client.delete("/api/tickets/99999/status_overrides/2")
        assert res.status_code == 404

    def test_get_overrides_includes_cascade_info(self, client):
        """GET overrides returns status_name and effective values with source."""
        ticket_id = _create_ticket(client)
        # Set an override
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 1
        o = overrides[0]
        assert o["status_name"]  # should have status name
        assert o["model_source"] == "ticket"  # override is from ticket
        assert o["effective_model"] == "agent-model"

    def test_upsert_replaces_existing(self, client):
        """PUT for the same (ticket, status) updates the override."""
        ticket_id = _create_ticket(client)
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "status-model",
            },
        )
        assert res.status_code == 200

        # Verify only one override exists with new value
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 1
        assert overrides[0]["model"] == "status-model"

    def test_ticket_get_includes_status_overrides(self, client):
        """Ticket GET includes status_overrides in response."""
        ticket_id = _create_ticket(client)
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        res = client.get(f"/api/tickets/{ticket_id}")
        data = json.loads(res.data)
        assert "status_overrides" in data
        assert len(data["status_overrides"]) == 1
        assert data["status_overrides"][0]["model"] == "agent-model"


# ---------------------------------------------------------------------------
# Spawn logic: resolution cascade
# ---------------------------------------------------------------------------


class TestTicketStatusOverrideCascade:
    """Test that ticket overrides cascade correctly via the API & spawn logic."""

    def test_ticket_override_takes_precedence(self, client):
        """Ticket override should override status and agent settings."""
        ticket_id = _create_ticket(client)

        # Move ticket to Research (status_id=2, agent_id=1)
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": 2})

        # Set a status-level model override
        client.put("/api/statuses/2", json={"model": "status-model"})

        # Set a ticket-level model override
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "plain-model",
            },
        )

        # Check via GET overrides endpoint
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 1
        assert overrides[0]["model"] == "plain-model"
        assert overrides[0]["model_source"] == "ticket"

    def test_clear_ticket_override_falls_back_to_status(self, client):
        """Clearing ticket override falls back to status override."""
        ticket_id = _create_ticket(client)

        # Set status model override
        client.put("/api/statuses/2", json={"model": "status-model"})

        # Set ticket override
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "plain-model",
            },
        )

        # Clear ticket override
        client.delete(f"/api/tickets/{ticket_id}/status_overrides/2")

        # Verify override is gone
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        assert len(json.loads(res.data)) == 0

    def test_model_and_thinking_resolve_independently(self, client):
        """Model and thinking should resolve independently through the cascade."""
        ticket_id = _create_ticket(client)

        # Set status-level model but not thinking
        client.put("/api/statuses/2", json={"model": "status-model"})

        # Set ticket-level thinking but not model
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "thinking": "high",
            },
        )

        # Check override: model should be None in ticket override, thinking should be 'high'
        res = client.get(f"/api/tickets/{ticket_id}/status_overrides")
        overrides = json.loads(res.data)
        assert len(overrides) == 1
        o = overrides[0]
        # Ticket override only has thinking set
        assert o["model"] is None
        assert o["thinking"] == "high"
        # Effective model comes from status (model_source='status')
        assert o["model_source"] == "status"
        assert o["effective_model"] == "status-model"
        # Effective thinking comes from ticket (thinking_source='ticket')
        assert o["thinking_source"] == "ticket"
        assert o["effective_thinking"] == "high"


# ---------------------------------------------------------------------------
# Database: on-delete cascade
# ---------------------------------------------------------------------------


class TestTicketStatusOverridesCascadeDelete:
    """Test that the schema includes ON DELETE CASCADE for foreign keys."""

    def test_schema_has_cascade(self, client):
        """Verify the ticket_status_overrides table has ON DELETE CASCADE on ticket_id FK."""
        # Use the API to trigger model-layer which uses the DB
        ticket_id = _create_ticket(client)

        # Verify the table exists and has cascade by checking via sqlite_master
        # We need an app context for query_db
        from app import app as flask_app

        with flask_app.app_context():
            from pi_cowork.db import query_db

            row = query_db("SELECT sql FROM sqlite_master WHERE name = 'ticket_status_overrides'", one=True)
            assert row is not None
            assert "ON DELETE CASCADE" in row["sql"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestTicketStatusOverridesValidation:
    """Validation tests for invalid model and thinking values."""

    def test_invalid_model_rejected(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "totally-fake-model-12345",
            },
        )
        assert res.status_code == 400
        assert "model" in json.loads(res.data).get("error", "").lower()

    def test_invalid_thinking_rejected(self, client):
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "thinking": "ultra-extreme-not-valid",
            },
        )
        assert res.status_code == 400
        assert "thinking" in json.loads(res.data).get("error", "").lower()

    def test_empty_model_clears_field(self, client):
        """Setting model to empty string while keeping thinking clears model field."""
        ticket_id = _create_ticket(client)
        # Set override with model
        client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "agent-model",
            },
        )
        # Clear model only (keep thinking)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "",
                "thinking": "high",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["model"] is None
        assert data["thinking"] == "high"

    def test_valid_model_accepted(self, client):
        """A valid model from the mock model list is accepted."""
        ticket_id = _create_ticket(client)
        res = client.put(
            f"/api/tickets/{ticket_id}/status_overrides",
            json={
                "status_id": 2,
                "model": "claude-3",
            },
        )
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# Spawn: ticket override affects spawned agent command
# ---------------------------------------------------------------------------


class TestTicketStatusOverrideSpawn:
    """Test that ticket overrides affect the actual spawned agent command."""

    def test_ticket_model_override_in_spawn_command(self, client, default_workflow, default_board):
        """Ticket override for model should be used in the spawn command."""
        from unittest.mock import patch

        # Create an agent with no model/thinking overrides
        res = client.post(
            "/api/agents",
            json={
                "name": "TicketOverrideSpawnAgent",
                "description": "d",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(res.data)["id"]

        res = client.post(
            "/api/statuses",
            json={
                "name": "TicketOverrideStage",
                "sort_order": 100,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={
                "title": "Spawn Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        # Set a ticket-level model override
        client.put(
            f"/api/tickets/{tid}/status_overrides",
            json={
                "status_id": sid,
                "model": "agent-model",
            },
        )

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        assert "--model" in captured_cmd
        idx = captured_cmd.index("--model")
        assert captured_cmd[idx + 1] == "agent-model"

    def test_ticket_thinking_override_in_spawn_command(self, client, default_workflow, default_board):
        """Ticket override for thinking should be used in the spawn command."""
        from unittest.mock import patch

        res = client.post(
            "/api/agents",
            json={
                "name": "ThinkingOverrideAgent",
                "description": "d",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(res.data)["id"]

        res = client.post(
            "/api/statuses",
            json={
                "name": "ThinkingOverrideStage",
                "sort_order": 101,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={
                "title": "Thinking Spawn Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        # Set a ticket-level thinking override
        client.put(
            f"/api/tickets/{tid}/status_overrides",
            json={
                "status_id": sid,
                "thinking": "high",
            },
        )

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        assert "--thinking" in captured_cmd
        idx = captured_cmd.index("--thinking")
        assert captured_cmd[idx + 1] == "high"

    def test_ticket_overrides_status_in_spawn(self, client, default_workflow, default_board):
        """Ticket override should take precedence over status override in spawn."""
        from unittest.mock import patch

        # Create agent with model
        res = client.post(
            "/api/agents",
            json={
                "name": "PrecedenceAgent",
                "description": "d",
                "workflow_id": default_workflow["id"],
                "model": "agent-model",
            },
        )
        aid = json.loads(res.data)["id"]

        res = client.post(
            "/api/statuses",
            json={
                "name": "PrecedenceStage",
                "sort_order": 102,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
                "model": "status-model",
            },
        )
        sid = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={
                "title": "Precedence Ticket",
                "board_id": default_board["id"],
            },
        )
        tid = json.loads(res.data)["id"]

        # Set ticket override that should win over both agent and status
        client.put(
            f"/api/tickets/{tid}/status_overrides",
            json={
                "status_id": sid,
                "model": "plain-model",
            },
        )

        captured_cmd = []

        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999

            captured_cmd[:] = cmd
            return FakeProc()

        with patch("app.subprocess.Popen", side_effect=capture_popen):
            client.put(f"/api/tickets/{tid}", json={"status_id": sid})

        assert "--model" in captured_cmd
        idx = captured_cmd.index("--model")
        assert captured_cmd[idx + 1] == "plain-model"
