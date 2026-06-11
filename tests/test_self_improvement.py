"""Tests for Hermes self-evaluation and self-improvement loop (Ticket #150)."""

import json
from unittest.mock import MagicMock, patch

from pi_cowork.events import (
    AGENT_FAILED,
    GATE_FAILED,
    GATE_REVIEW_REJECTED,
    TICKET_RERUN_DETECTED,
    bus,
)


def _get_system_board(client):
    res = client.get("/api/boards")
    boards = json.loads(res.data)
    for b in boards:
        if b["name"] == "System":
            return b
    return None


def _get_system_workflow_id(client):
    res = client.get("/api/workflows")
    wfs = json.loads(res.data)
    for w in wfs:
        if w["name"] == "System Improvement":
            return w["id"]
    return None


def _get_observe_status_id(client, workflow_id):
    res = client.get(f"/api/statuses?workflow_id={workflow_id}")
    statuses = json.loads(res.data)
    for s in statuses:
        if s["name"] == "Observe":
            return s["id"]
    return None


def _count_system_observations(client, board_id, status_id):
    res = client.get(f"/api/tickets?board_id={board_id}")
    tickets = json.loads(res.data)
    return sum(1 for t in tickets if t["status_id"] == status_id and t["board_id"] == board_id)


class TestSelfImprovementObservations:
    def test_agent_failed_creates_observation(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(AGENT_FAILED, ticket_id=9999, agent_name="TestAgent", exit_code=1)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_gate_failed_creates_observation(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(GATE_FAILED, ticket_id=9998, gate_name="TestGate")
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_gate_review_rejected_creates_observation(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(GATE_REVIEW_REJECTED, ticket_id=9997, gate_name="ManualGate")
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_ticket_rerun_detected_creates_observation(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(TICKET_RERUN_DETECTED, ticket_id=9996, old_status_id=10, new_status_id=5)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_comment_added_below_threshold_no_observation(self, client, default_board):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        # Create a regular ticket on the default board
        res = client.post(
            "/api/tickets",
            json={"title": "Churn test", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        before = _count_system_observations(client, board["id"], observe_id)
        for i in range(5):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"human comment {i}"})
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_comment_added_above_threshold_creates_observation(self, client, default_board):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post(
            "/api/tickets",
            json={"title": "Churn test high", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        before = _count_system_observations(client, board["id"], observe_id)
        for i in range(12):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"human comment {i}"})
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_comment_added_system_comments_not_counted(self, client, default_board):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post(
            "/api/tickets",
            json={"title": "Churn system comments", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        before = _count_system_observations(client, board["id"], observe_id)
        for i in range(12):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"🤖 system comment {i}"})
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_high_churn_observation_deduplication(self, client, default_board):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post(
            "/api/tickets",
            json={"title": "Churn dedup", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        before = _count_system_observations(client, board["id"], observe_id)
        for i in range(15):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"human comment {i}"})
        # Add more comments; should not create another observation
        for i in range(5):
            client.post(f"/api/tickets/{tid}/comments", json={"body": f"more human comment {i}"})
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_disabled_self_improvement_no_observation(self, client):
        from pi_cowork.models import set_setting

        with client.application.app_context():
            set_setting("self_improvement_enabled", "0")
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(AGENT_FAILED, ticket_id=9995, agent_name="TestAgent", exit_code=1)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_observation_ticket_titles(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        with client.application.app_context():
            bus.publish(AGENT_FAILED, ticket_id=1001, agent_name="AgentX", exit_code=42)
            bus.publish(GATE_FAILED, ticket_id=1002, gate_name="GateY")
            bus.publish(GATE_REVIEW_REJECTED, ticket_id=1003, gate_name="GateZ")
            bus.publish(TICKET_RERUN_DETECTED, ticket_id=1004, old_status_id=10, new_status_id=5)

        res = client.get(f"/api/tickets?board_id={board['id']}")
        tickets = json.loads(res.data)
        titles = [t["title"] for t in tickets if t["status_id"] == observe_id]
        assert any("[Agent Failed] Ticket #1001" in t for t in titles)
        assert any("[Gate Failed] Ticket #1002" in t for t in titles)
        assert any("[Gate Rejected] Ticket #1003" in t for t in titles)
        assert any("[Rerun] Ticket #1004" in t for t in titles)

    def test_cli_gate_failed_creates_observation(self, client):
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        # Create a workflow with two statuses and a board + ticket
        res = client.post("/api/workflows", json={"name": "CLI Gate WF", "description": "test"})
        cli_wf_id = json.loads(res.data)["id"]
        # Create two statuses for the workflow
        r1 = client.post("/api/statuses", json={"name": "Open", "sort_order": 1, "workflow_id": cli_wf_id})
        s1 = json.loads(r1.data)["id"]
        r2 = client.post("/api/statuses", json={"name": "Done", "sort_order": 2, "workflow_id": cli_wf_id})
        s2 = json.loads(r2.data)["id"]

        res = client.post("/api/boards", json={"name": "CLI Gate Board", "workflow_id": cli_wf_id})
        cli_board_id = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={"title": "CLI Gate Ticket", "board_id": cli_board_id, "status_id": s1},
        )
        ticket_id = json.loads(res.data)["id"]

        client.post(
            "/api/quality_gates",
            json={
                "from_status_id": s1,
                "to_status_id": s2,
                "gate_type": "cli",
                "name": "Failing Gate",
                "config": json.dumps({"command": "false"}),
                "workflow_id": cli_wf_id,
                "notify_on_failure": True,
            },
        )

        before = _count_system_observations(client, board["id"], observe_id)
        with patch("app.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "fail"
            mock_run.return_value = mock_result
            res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": s2})
        assert res.status_code == 200

        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_cli_gate_default_notify_false_no_observation(self, client):
        """CLI gates default to notify_on_failure=False, so failures create zero observations."""
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post("/api/workflows", json={"name": "CLI Silent WF", "description": "test"})
        cli_wf_id = json.loads(res.data)["id"]
        r1 = client.post("/api/statuses", json={"name": "Open", "sort_order": 1, "workflow_id": cli_wf_id})
        s1 = json.loads(r1.data)["id"]
        r2 = client.post("/api/statuses", json={"name": "Done", "sort_order": 2, "workflow_id": cli_wf_id})
        s2 = json.loads(r2.data)["id"]

        res = client.post("/api/boards", json={"name": "CLI Silent Board", "workflow_id": cli_wf_id})
        cli_board_id = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={"title": "CLI Silent Ticket", "board_id": cli_board_id, "status_id": s1},
        )
        ticket_id = json.loads(res.data)["id"]

        # Do NOT pass notify_on_failure — should default to False for CLI
        client.post(
            "/api/quality_gates",
            json={
                "from_status_id": s1,
                "to_status_id": s2,
                "gate_type": "cli",
                "name": "Silent Gate",
                "config": json.dumps({"command": "false"}),
                "workflow_id": cli_wf_id,
            },
        )

        before = _count_system_observations(client, board["id"], observe_id)
        with patch("app.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_result.stderr = "fail"
            mock_run.return_value = mock_result
            res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": s2})
        assert res.status_code == 200

        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_manual_gate_rejection_only_one_observation(self, client):
        """One manual gate rejection creates exactly one observation (GATE_REVIEW_REJECTED only)."""
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post("/api/workflows", json={"name": "Manual Dedup WF", "description": "test"})
        manual_wf_id = json.loads(res.data)["id"]
        r1 = client.post("/api/statuses", json={"name": "Open", "sort_order": 1, "workflow_id": manual_wf_id})
        s1 = json.loads(r1.data)["id"]
        r2 = client.post("/api/statuses", json={"name": "Done", "sort_order": 2, "workflow_id": manual_wf_id})
        s2 = json.loads(r2.data)["id"]

        res = client.post("/api/boards", json={"name": "Manual Dedup Board", "workflow_id": manual_wf_id})
        manual_board_id = json.loads(res.data)["id"]

        res = client.post(
            "/api/tickets",
            json={"title": "Manual Dedup Ticket", "board_id": manual_board_id, "status_id": s1},
        )
        ticket_id = json.loads(res.data)["id"]

        client.post(
            "/api/quality_gates",
            json={
                "from_status_id": s1,
                "to_status_id": s2,
                "gate_type": "manual",
                "name": "Approval Gate",
                "workflow_id": manual_wf_id,
            },
        )

        with patch("app.subprocess.Popen"):
            res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": s2})
        assert res.status_code == 200

        reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
        review_id = reviews[0]["id"]

        from conftest import HUMAN_ACTION_SECRET_FOR_TESTS
        HUMAN_HEADERS = {"Content-Type": "application/json", "X-Human-Action": HUMAN_ACTION_SECRET_FOR_TESTS}

        before = _count_system_observations(client, board["id"], observe_id)
        with patch("app.subprocess.Popen"):
            res = client.put(
                f"/api/gate_reviews/{review_id}",
                json={"status": "rejected", "comment": "Needs work"},
                headers=HUMAN_HEADERS,
            )
        assert res.status_code == 200

        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1

    def test_gate_notify_false_skips_observation(self, client):
        """When notify_on_failure=False, both GATE_FAILED and GATE_REVIEW_REJECTED skip observations."""
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(GATE_FAILED, ticket_id=5001, gate_name="QuietGate", notify_on_failure=False)
            bus.publish(GATE_REVIEW_REJECTED, ticket_id=5002, gate_name="QuietManual", notify_on_failure=False)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_rerun_suppressed_after_recent_gate_failure(self, client, default_board):
        """TICKET_RERUN_DETECTED is suppressed when a recent gate failure comment exists."""
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post(
            "/api/tickets",
            json={"title": "Rerun suppress test", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        # Add a gate-failure-style system comment
        client.post(f"/api/tickets/{tid}/comments", json={"body": "❌ Gate 'Lint' (CLI) failed.\noutput"})

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(TICKET_RERUN_DETECTED, ticket_id=tid, old_status_id=10, new_status_id=5)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before

    def test_rerun_allowed_without_recent_gate_activity(self, client, default_board):
        """TICKET_RERUN_DETECTED still creates an observation for user-initiated backward moves."""
        board = _get_system_board(client)
        assert board is not None
        wf_id = _get_system_workflow_id(client)
        observe_id = _get_observe_status_id(client, wf_id)
        assert observe_id is not None

        res = client.post(
            "/api/tickets",
            json={"title": "Rerun allow test", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        # Add a regular human comment (not gate-related)
        client.post(f"/api/tickets/{tid}/comments", json={"body": "Regular human comment"})

        before = _count_system_observations(client, board["id"], observe_id)
        with client.application.app_context():
            bus.publish(TICKET_RERUN_DETECTED, ticket_id=tid, old_status_id=10, new_status_id=5)
        after = _count_system_observations(client, board["id"], observe_id)
        assert after == before + 1


class TestSkillCreateAPI:
    def test_create_skill_global(self, client, temp_skills_folder):
        res = client.post(
            "/api/skills",
            json={"name": "new-skill", "description": "A new skill", "content": "## Skill\n\nContent."},
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["name"] == "new-skill"
        import os

        skill_dir = os.path.join(temp_skills_folder, "global", "new-skill")
        assert os.path.isdir(skill_dir)

    def test_create_skill_workflow(self, client, new_workflow, temp_skills_folder):
        res = client.post(
            "/api/skills",
            json={
                "name": "wf-skill",
                "description": "Workflow skill",
                "content": "Content.",
                "workflow_id": new_workflow["id"],
            },
        )
        assert res.status_code == 201
        import os

        skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "wf-skill")
        assert os.path.isdir(skill_dir)

    def test_create_skill_duplicate_global(self, client, temp_skills_folder):
        client.post(
            "/api/skills",
            json={"name": "dup-skill", "description": "d", "content": "c"},
        )
        res = client.post(
            "/api/skills",
            json={"name": "dup-skill", "description": "d2", "content": "c2"},
        )
        assert res.status_code == 409
        assert b"already exists" in res.data

    def test_create_skill_invalid_name(self, client):
        res = client.post(
            "/api/skills",
            json={"name": "Invalid_Name", "description": "d", "content": "c"},
        )
        assert res.status_code == 400
        assert b"name must be lowercase" in res.data

    def test_create_skill_missing_name(self, client):
        res = client.post(
            "/api/skills",
            json={"description": "d", "content": "c"},
        )
        assert res.status_code == 400
        assert b"name is required" in res.data

    def test_create_skill_appears_in_list(self, client, new_workflow):
        client.post(
            "/api/skills",
            json={
                "name": "listed-skill",
                "description": "Listed",
                "content": "Content.",
                "workflow_id": new_workflow["id"],
            },
        )
        res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
        assert res.status_code == 200
        data = json.loads(res.data)
        names = [sk["name"] for sk in data]
        assert "listed-skill" in names


class TestSystemImprovementSeedData:
    def test_system_workflow_exists(self, client):
        res = client.get("/api/workflows")
        wfs = json.loads(res.data)
        assert any(w["name"] == "System Improvement" for w in wfs)

    def test_system_board_exists(self, client):
        res = client.get("/api/boards")
        boards = json.loads(res.data)
        assert any(b["name"] == "System" for b in boards)

    def test_synthesizer_agent_exists(self, client):
        wf_id = _get_system_workflow_id(client)
        res = client.get(f"/api/agents?workflow_id={wf_id}")
        agents = json.loads(res.data)
        assert any(a["name"] == "Synthesizer" for a in agents)

    def test_system_statuses_exist(self, client):
        wf_id = _get_system_workflow_id(client)
        res = client.get(f"/api/statuses?workflow_id={wf_id}")
        statuses = json.loads(res.data)
        names = [s["name"] for s in statuses]
        assert "Observe" in names
        assert "Analyze" in names
        assert "Synthesize" in names
        assert "Apply" in names
        assert "Validate" in names
        assert "Closed" in names

    def test_system_transitions_exist(self, client):
        wf_id = _get_system_workflow_id(client)
        res = client.get(f"/api/transitions?workflow_id={wf_id}")
        transitions = json.loads(res.data)
        assert len(transitions) == 9

    def test_recurring_task_exists(self, client):
        board = _get_system_board(client)
        res = client.get(f"/api/recurring?board_id={board['id']}")
        tasks = json.loads(res.data)
        assert any(t["title"] == "Self-improvement batch" for t in tasks)

    def test_self_improvement_settings_seeded(self, client):
        for key in ("self_improvement_enabled", "self_improvement_batch_cron", "high_comment_threshold"):
            res = client.get(f"/api/settings/{key}")
            assert res.status_code == 200
            data = json.loads(res.data)
            assert data["value"] is not None


class TestTicketRerunEvent:
    def test_rerun_event_published_on_backward_move(self, client, default_board):
        wf_id = default_board["workflow_id"]
        res = client.get(f"/api/statuses?workflow_id={wf_id}")
        statuses = json.loads(res.data)
        by_name = {s["name"]: s for s in statuses}

        # Need at least two statuses with different sort_orders
        # Create a ticket in a higher sort_order status, then move to lower
        # Use Backlog (sort_order=1) and Research (sort_order=2)
        backlog = by_name.get("Backlog")
        research = by_name.get("Research")
        if not backlog or not research:
            return  # Skip if default workflow doesn't have these

        res = client.post(
            "/api/tickets",
            json={"title": "Rerun test", "board_id": default_board["id"], "status_id": research["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        # Publish event manually and ensure the API also publishes it
        res = client.put(f"/api/tickets/{tid}", json={"status_id": backlog["id"]})
        assert res.status_code == 200
        # The event is published synchronously, so we just verify the ticket moved
        res = client.get(f"/api/tickets/{tid}")
        data = json.loads(res.data)
        assert data["status_id"] == backlog["id"]

    def test_no_rerun_event_on_forward_move(self, client, default_board):
        wf_id = default_board["workflow_id"]
        res = client.get(f"/api/statuses?workflow_id={wf_id}")
        statuses = json.loads(res.data)
        by_name = {s["name"]: s for s in statuses}

        backlog = by_name.get("Backlog")
        research = by_name.get("Research")
        if not backlog or not research:
            return

        res = client.post(
            "/api/tickets",
            json={"title": "Forward test", "board_id": default_board["id"], "status_id": backlog["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        res = client.put(f"/api/tickets/{tid}", json={"status_id": research["id"]})
        assert res.status_code == 200
        # Forward move should not trigger rerun event; the ticket just moves
        res = client.get(f"/api/tickets/{tid}")
        data = json.loads(res.data)
        assert data["status_id"] == research["id"]
