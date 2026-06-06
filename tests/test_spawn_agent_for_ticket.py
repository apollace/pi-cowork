"""Tests for spawn_agent_for_ticket helper — Ticket #92."""

import json
from unittest.mock import patch

from app import app as flask_app


class TestSpawnAgentForTicket:
    """Unit tests for the spawn_agent_for_ticket helper function."""

    def test_no_agent_on_status_no_spawn(self, client, default_workflow, default_board):
        """If the status has no agent_id, spawn_agent_for_ticket should not spawn."""
        # Create a status with no agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "NoAgentHere",
                "sort_order": 1,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        with patch("pi_cowork.agents.try_spawn_or_queue") as mock_spawn:
            with flask_app.app_context():
                from pi_cowork.agents import spawn_agent_for_ticket

                spawn_agent_for_ticket(ticket_id=999, status_id=sid)
            assert not mock_spawn.called, "Should not spawn when status has no agent"

    def test_agent_exists_spawns_correctly(self, client, default_workflow, default_board):
        """If the status has an agent, spawn_agent_for_ticket should call try_spawn_or_queue."""
        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "HelperTestAgent",
                "description": "Agent for spawn_agent_for_ticket test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with that agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "HelperTestStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a ticket in that status (suppress its own spawn)
        with patch("pi_cowork.api.tickets.spawn_agent_for_ticket"):
            ticket = client.post(
                "/api/tickets",
                json={
                    "title": "Helper Test Ticket",
                    "board_id": default_board["id"],
                    "status_id": sid,
                },
            )
        tid = json.loads(ticket.data)["id"]

        with patch("pi_cowork.agents.try_spawn_or_queue") as mock_spawn:
            mock_spawn.return_value = None
            with flask_app.app_context():
                from pi_cowork.agents import spawn_agent_for_ticket

                spawn_agent_for_ticket(ticket_id=tid, status_id=sid)
            assert mock_spawn.called, "Should call try_spawn_or_queue when status has an agent"
            # Verify it was called with the right args
            call_args = mock_spawn.call_args
            ticket_dict = call_args[0][0]
            status_dict = call_args[0][1]
            agent_dict = call_args[0][2]
            assert ticket_dict["id"] == tid
            assert ticket_dict["board_name"] == default_board["name"]
            assert "workflow_id" in ticket_dict
            assert status_dict["id"] == sid
            assert agent_dict["id"] == aid

    def test_missing_ticket_no_spawn(self, client, default_workflow, default_board):
        """If the ticket doesn't exist, spawn_agent_for_ticket should not spawn."""
        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "MissingTicketAgent",
                "description": "Agent for missing-ticket test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with that agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "MissingTicketStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        with patch("pi_cowork.agents.try_spawn_or_queue") as mock_spawn:
            # Use a non-existent ticket ID
            with flask_app.app_context():
                from pi_cowork.agents import spawn_agent_for_ticket

                spawn_agent_for_ticket(ticket_id=99999, status_id=sid)
            assert not mock_spawn.called, "Should not spawn when ticket doesn't exist"

    def test_missing_status_no_spawn(self, client, default_workflow, default_board):
        """If the status doesn't exist, spawn_agent_for_ticket should not spawn."""
        # Create a ticket
        with patch("pi_cowork.api.tickets.spawn_agent_for_ticket"):
            ticket = client.post(
                "/api/tickets",
                json={
                    "title": "Missing Status Ticket",
                    "board_id": default_board["id"],
                },
            )
        tid = json.loads(ticket.data)["id"]

        with patch("pi_cowork.agents.try_spawn_or_queue") as mock_spawn:
            # Use a non-existent status ID — get_status returns None
            with flask_app.app_context():
                from pi_cowork.agents import spawn_agent_for_ticket

                spawn_agent_for_ticket(ticket_id=tid, status_id=99999)
            assert not mock_spawn.called, "Should not spawn when status doesn't exist"

    def test_integration_create_ticket_uses_helper(self, client, default_workflow, default_board):
        """api_create_ticket should call spawn_agent_for_ticket, not duplicate the logic."""
        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "IntegrationTestAgent",
                "description": "Agent for integration test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with that agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "IntegrationTestStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Patch spawn_agent_for_ticket at the import site in tickets.py
        with patch("pi_cowork.api.tickets.spawn_agent_for_ticket") as mock_helper:
            mock_helper.return_value = None
            res = client.post(
                "/api/tickets",
                json={
                    "title": "Integration Test Ticket",
                    "board_id": default_board["id"],
                    "status_id": sid,
                },
            )
            assert res.status_code == 201
            assert mock_helper.called, "api_create_ticket should call spawn_agent_for_ticket"
            # Verify it passes the right arguments
            call_args = mock_helper.call_args
            # spawn_agent_for_ticket(ticket_id, status_id)
            assert call_args[0][1] == sid  # status_id

    def test_integration_recurring_trigger_uses_helper(self, client, default_workflow, default_board):
        """api_trigger_recurring should call spawn_agent_for_ticket, not duplicate the logic."""
        # Create an agent
        agent = client.post(
            "/api/agents",
            json={
                "name": "RecurringHelperAgent",
                "description": "Agent for recurring helper test.",
                "workflow_id": default_workflow["id"],
            },
        )
        aid = json.loads(agent.data)["id"]

        # Create a status with that agent
        s1 = client.post(
            "/api/statuses",
            json={
                "name": "RecurringHelperStatus",
                "sort_order": 1,
                "agent_id": aid,
                "workflow_id": default_workflow["id"],
            },
        )
        sid = json.loads(s1.data)["id"]

        # Create a recurring task
        task = client.post(
            "/api/recurring",
            json={
                "board_id": default_board["id"],
                "title": "Recurring Helper Test",
                "status_id": sid,
                "cron_expression": "0 9 * * *",
            },
        )
        task_id = json.loads(task.data)["id"]

        # Patch spawn_agent_for_ticket in the module where it's defined
        # (recurring.py uses an inline import, so patching at recurring module won't work)
        with patch("pi_cowork.agents.spawn_agent_for_ticket") as mock_helper:
            mock_helper.return_value = None
            res = client.post(f"/api/recurring/{task_id}/trigger")
            assert res.status_code == 200
            assert mock_helper.called, "api_trigger_recurring should call spawn_agent_for_ticket"
            call_args = mock_helper.call_args
            # spawn_agent_for_ticket(ticket_id, status_id)
            assert call_args[0][1] == sid  # status_id
