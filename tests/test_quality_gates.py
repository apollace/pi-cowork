import json
from unittest.mock import MagicMock, patch

from conftest import HUMAN_ACTION_SECRET_FOR_TESTS

HUMAN_HEADERS = {"Content-Type": "application/json", "X-Human-Action": HUMAN_ACTION_SECRET_FOR_TESTS}


def _create_workflow_with_statuses(client, n_statuses=2):
    """Helper: create a workflow with n_statuses statuses and return ids."""
    res = client.post("/api/workflows", json={"name": "Gate Test WF"})
    wf = json.loads(res.data)
    wf_id = wf["id"]
    status_ids = []
    for i in range(n_statuses):
        res = client.post(
            "/api/statuses",
            json={
                "name": f"Status {i}",
                "sort_order": i,
                "is_default": 1 if i == 0 else 0,
                "is_terminal": 1 if i == n_statuses - 1 else 0,
                "workflow_id": wf_id,
            },
        )
        status_ids.append(json.loads(res.data)["id"])
    return wf_id, status_ids


def _create_board_with_ticket(client, wf_id, status_id):
    """Helper: create a board and a ticket, return board_id, ticket_id."""
    res = client.post(
        "/api/boards",
        json={
            "name": "Gate Test Board",
            "workflow_id": wf_id,
            "working_directory": "/tmp",  # noqa: S108
        },
    )
    board_id = json.loads(res.data)["id"]
    res = client.post(
        "/api/tickets",
        json={
            "title": "Test Ticket",
            "board_id": board_id,
        },
    )
    ticket_id = json.loads(res.data)["id"]
    return board_id, ticket_id


# 1. Test creating a quality gate on a (from, to) pair
def test_create_quality_gate(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Human Approval",
            "workflow_id": wf_id,
            "sort_order": 0,
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["id"]

    # Verify it's retrievable
    res = client.get(f"/api/quality_gates?from_status_id={status_ids[0]}&to_status_id={status_ids[1]}")
    gates = json.loads(res.data)
    assert len(gates) == 1
    assert gates[0]["gate_type"] == "manual"
    assert gates[0]["name"] == "Human Approval"


# 2. Test that moving a ticket to a status with a manual gate creates a pending review
#    and does NOT move the ticket
def test_manual_gate_blocks_transition(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Add manual gate on (from, to) pair
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is True

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Should have pending gate reviews
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1
    assert reviews[0]["status"] == "pending"
    assert reviews[0]["gate_type"] == "manual"


# 3. Test that approving a manual gate moves the ticket
def test_approve_manual_gate_moves_ticket(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id = reviews[0]["id"]

    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id}",
            json={
                "status": "approved",
            },
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200

    # Ticket should now be in the new status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1]


# 4. Test that rejecting a manual gate keeps the ticket in old status and adds a comment
def test_reject_manual_gate_stays_old_status(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id = reviews[0]["id"]

    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id}",
            json={
                "status": "rejected",
                "comment": "Needs more work",
            },
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Rejection comment should be added
    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    rejection_comments = [c for c in comments if "rejected" in c["body"].lower()]
    assert len(rejection_comments) >= 1


# 5. Test CLI gate: exit 0 → passed, ticket moves
def test_cli_gate_pass_moves_ticket(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Test Suite",
            "config": json.dumps({"command": "true"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen") as _, patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All tests passed"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is not True

    # Ticket should now be in new status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1]


# 6. Test CLI gate: exit non-zero → failed, ticket stays, comment added
def test_cli_gate_fail_blocks_ticket(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Test Suite",
            "config": json.dumps({"command": "false"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "1 test failed"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Comment about failure should be added
    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    fail_comments = [c for c in comments if "failed" in c["body"].lower()]
    assert len(fail_comments) >= 1


# 7. Test multiple gates: first CLI fails → whole transition rejected
def test_multiple_gates_first_fails_rejects_all(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Add CLI gate that will fail
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "false"}),
            "workflow_id": wf_id,
            "sort_order": 0,
        },
    )
    # Add manual gate (should never be reached)
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
            "sort_order": 1,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "lint error"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # No pending gate reviews — all were cleaned up on rejection
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    pending = [r for r in reviews if r["status"] == "pending"]
    assert len(pending) == 0


# 8. Test that agent is not spawned while gate is pending
def test_agent_not_spawned_while_gate_pending(client):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1
    res = client.post(
        "/api/agents",
        json={
            "name": "Worker",
            "description": "Does work",
            "workflow_id": wf_id,
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    # Add manual gate on (status 0 → status 1) pair
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen") as mock_popen:
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Popen should NOT have been called (gate is pending)
    assert not mock_popen.called

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]


# 9. Test that agent IS re-triggered after rejection (with the feedback comment)
def test_agent_retriggered_after_rejection(client):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to the current (old) status
    res = client.post(
        "/api/agents",
        json={
            "name": "Worker",
            "description": "Does work",
            "workflow_id": wf_id,
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[0]}", json={"agent_id": agent_id})

    # Add manual gate on destination
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id = reviews[0]["id"]

    # Reject the gate — this should re-trigger agent for old status
    with patch("app.subprocess.Popen") as mock_popen:
        res = client.put(
            f"/api/gate_reviews/{review_id}",
            json={
                "status": "rejected",
                "comment": "Fix the thing",
            },
            headers=HUMAN_HEADERS,
        )

    # Agent should have been re-triggered for the old status
    assert mock_popen.called


# 10. Test gate_pending flag on ticket API responses
def test_gate_pending_flag_on_tickets(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Before any gate — no pending
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["gate_pending"] is False

    tickets = json.loads(client.get(f"/api/tickets?board_id={board_id}").data)
    assert tickets[0]["gate_pending"] is False

    # Add a manual gate
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Now pending
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["gate_pending"] is True

    tickets = json.loads(client.get(f"/api/tickets?board_id={board_id}").data)
    assert tickets[0]["gate_pending"] is True


# 11. Test deleting a quality gate cascades reviews
def test_delete_gate_cascades_reviews(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )
    gate_id = json.loads(res.data)["id"]

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Verify review exists
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1

    # Delete the gate
    client.delete(f"/api/quality_gates/{gate_id}")

    # Reviews should be gone (cascade)
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 0


# 12. Test deleting a status cascades gates and reviews
def test_delete_status_cascades_gates_and_reviews(client):
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create another status just for the gate (not used by any ticket directly)
    res = client.post(
        "/api/statuses",
        json={
            "name": "Gate Status",
            "sort_order": 99,
            "is_default": 0,
            "is_terminal": 0,
            "workflow_id": wf_id,
        },
    )
    gate_status_id = json.loads(res.data)["id"]

    # Add gate on the separate status
    res = client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": gate_status_id,
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )
    _ = json.loads(res.data)["id"]

    # Create a gate review by attempting a transition
    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": gate_status_id})

    # Verify gate and review exist
    gates = json.loads(
        client.get(f"/api/quality_gates?from_status_id={status_ids[0]}&to_status_id={gate_status_id}").data
    )
    assert len(gates) == 1
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) >= 1

    # Delete transitions referencing gate_status_id
    transitions = json.loads(client.get(f"/api/transitions?workflow_id={wf_id}").data)
    for t in transitions:
        if t.get("from_status_id") == gate_status_id or t.get("to_status_id") == gate_status_id:
            client.delete(f"/api/transitions/{t['id']}")

    # Delete the gate status — should cascade gates and reviews
    res = client.delete(f"/api/statuses/{gate_status_id}")
    assert res.status_code == 200

    # Gate should be gone
    gates = json.loads(
        client.get(f"/api/quality_gates?from_status_id={status_ids[0]}&to_status_id={gate_status_id}").data
    )
    assert len(gates) == 0

    # Reviews should be gone (cascaded through gate deletion)
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    pending_reviews = [r for r in reviews if r["status"] == "pending"]
    assert len(pending_reviews) == 0


# 13. Test deleting a board cleans up gate_reviews
def test_delete_board_cleans_up_gate_reviews(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Verify review exists
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1

    # Delete the board
    res = client.delete(f"/api/boards/{board_id}")
    assert res.status_code == 200

    # Reviews for that ticket should be gone
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 0


# 14. Test export/import includes quality_gates
def test_export_import_includes_quality_gates(client, default_workflow):
    wf_id = default_workflow["id"]

    # Get a status to attach a gate to
    statuses = json.loads(client.get(f"/api/statuses?workflow_id={wf_id}").data)
    if not statuses:
        return  # No statuses to test with

    # Create a quality gate
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": statuses[0]["id"],
            "to_status_id": statuses[1]["id"] if len(statuses) > 1 else statuses[0]["id"],
            "gate_type": "manual",
            "name": "Test Gate",
            "workflow_id": wf_id,
            "sort_order": 0,
        },
    )

    # Export
    res = client.get(f"/api/workflows/{wf_id}/export")
    export_data = json.loads(res.data)

    assert "quality_gates" in export_data
    assert len(export_data["quality_gates"]) == 1
    assert export_data["quality_gates"][0]["name"] == "Test Gate"
    assert "from_status_name" in export_data["quality_gates"][0]
    assert "to_status_name" in export_data["quality_gates"][0]

    # Import as new workflow
    res = client.post("/api/workflows/import", json=export_data)
    assert res.status_code == 200
    import_data = json.loads(res.data)
    assert import_data["quality_gates"] == 1

    # Verify gate was recreated
    new_wf_id = import_data["workflow_id"]
    new_gates = json.loads(client.get(f"/api/quality_gates?workflow_id={new_wf_id}").data)
    assert len(new_gates) == 1
    assert new_gates[0]["name"] == "Test Gate"


# 15. Regression: duplicate gate review creation should not block manual approval
def test_duplicate_gate_reviews_cannot_block_approval(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    # First transition attempt creates a pending review
    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is True

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1
    review_id = reviews[0]["id"]

    # Second transition attempt for the same direction — must NOT create a second pending review
    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is True

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1, f"Expected 1 pending review, got {len(reviews)}"

    # The review may have been recreated, fetch the current one
    review_id = reviews[0]["id"]

    # Approve the single review — ticket must move
    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/gate_reviews/{review_id}", json={"status": "approved"}, headers=HUMAN_HEADERS)
    assert res.status_code == 200

    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1]


# 16. Regression: agent prompt includes quality gate annotations for gated transitions
def test_agent_prompt_includes_gate_annotations(client):
    """When a transition target has quality gates, the agent's context message
    must annotate the transition and include gate_pending API docs."""
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1 (the destination status)
    res = client.post(
        "/api/agents",
        json={
            "name": "GateAware",
            "description": "You are a gate-aware agent.",
            "workflow_id": wf_id,
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    # Create a transition FROM status 1 TO status 2 (which will be gated)
    client.post(
        "/api/transitions",
        json={
            "from_status_id": status_ids[1],
            "to_status_id": status_ids[2],
            "instructions": "Move when ready",
            "workflow_id": wf_id,
        },
    )

    # Add manual gate on (status 1 → status 2) pair
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[1],
            "to_status_id": status_ids[2],
            "gate_type": "manual",
            "name": "Human Signoff",
            "workflow_id": wf_id,
        },
    )

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    # Move ticket to status 1 (agent's status) — agent should be spawned
    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert captured_cmd, "Agent should have been spawned"
    context_msg = captured_cmd[-1]

    # The transition line for status 2 should mention the quality gate
    assert "⚠️ Gate required; stop if blocked." in context_msg

    # The API docs should mention gate_pending
    assert "gate_pending" in context_msg
    assert "blocked for human approval" in context_msg


# 17. Regression: agent prompt does NOT mention gates when no gated transitions exist
def test_agent_prompt_no_gates_no_mention(client):
    """When no transitions have quality gates, the agent context should not mention gates."""
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to status 1 — no gates anywhere
    res = client.post(
        "/api/agents",
        json={
            "name": "NoGate",
            "description": "You are a gateless agent.",
            "workflow_id": wf_id,
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[1]}", json={"agent_id": agent_id})

    # Create a transition FROM status 1 TO status 2 (no gates)
    client.post(
        "/api/transitions",
        json={
            "from_status_id": status_ids[1],
            "to_status_id": status_ids[2],
            "instructions": "Move when ready",
            "workflow_id": wf_id,
        },
    )

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    # Move ticket to status 1 (agent's status) — no gates
    with patch("app.subprocess.Popen", side_effect=capture_popen):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert captured_cmd, "Agent should have been spawned"
    context_msg = captured_cmd[-1]

    # No gate-related content should appear
    assert "⚠️ Gate required; stop if blocked." not in context_msg
    # The extra gate warning should not appear
    assert "blocked for human approval" not in context_msg
    # Note: 'gate_pending' MAY appear in the PUT endpoint docs (it's part of the API schema),
    # but the gate-specific warning should not be present
    assert "Some transitions require quality gate approval" not in context_msg


# 18. Regression: CLI gate failure DOES re-trigger the agent in the current (old) status,
# mirroring the manual gate rejection behaviour. The agent receives the failure comment
# in its warm-spawn context so it can fix the root cause before retrying the same
# transition.
def test_cli_gate_failure_retriggers_agent_in_current_status(client):
    """When a CLI gate fails, the agent for the current (old) status must be
    re-triggered with the failure comment as context. This mirrors the
    manual gate rejection path in pi_cowork/api/gate_reviews.py."""
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Create an agent and assign it to the current (old) status
    res = client.post(
        "/api/agents",
        json={
            "name": "RetryOnFail",
            "description": "Does work",
            "workflow_id": wf_id,
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.put(f"/api/statuses/{status_ids[0]}", json={"agent_id": agent_id})

    # Add CLI gate on (from, to) pair that will fail
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "false"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen") as mock_popen, patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "lint error"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    # The agent for the old status MUST have been re-triggered after the CLI failure
    assert mock_popen.called, "Agent should be re-triggered in the current status after CLI gate failure"

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Failure comments should be present (CLI failure + transition rejection)
    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    fail_comments = [c for c in comments if "failed" in c["body"].lower()]
    assert len(fail_comments) >= 1
    reject_comments = [c for c in comments if "rejected" in c["body"].lower()]
    assert len(reject_comments) >= 1

    # No pending gate reviews remain
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    pending = [r for r in reviews if r["status"] == "pending"]
    assert len(pending) == 0


# 19. Regression: orphaned gate reviews from different transitions are cleaned up
def test_orphaned_gate_reviews_cleaned_on_unrelated_move(client):
    """When a ticket has pending gate reviews for transition A→B and is then
    manually moved to C (no gate), the orphaned A→B reviews must be cleaned up."""
    wf_id, status_ids = _create_workflow_with_statuses(client, n_statuses=3)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    # Add manual gate on (status 0 → status 1) pair
    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    # Attempt transition to gated status 1 — creates pending review
    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    # Verify pending review exists
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    pending = [r for r in reviews if r["status"] == "pending"]
    assert len(pending) >= 1

    # Now move ticket to status 2 (no gate, unrelated to the pending review)
    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[2]})

    # Ticket should be in status 2
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[2]

    # Orphaned pending reviews from A→B should be cleaned up
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    pending = [r for r in reviews if r["status"] == "pending"]
    assert len(pending) == 0, f"Expected 0 pending reviews, got {len(pending)}"


# 20. Regression: rejecting then re-approving a manual gate must allow the move
# Bug: old 'rejected' gate review is not deleted, so on re-attempt after approval
# the any_rejected query still sees the stale rejected record and blocks the move.
def test_reject_then_approve_manual_gate_allows_move(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    # 1) First transition attempt — blocked by gate
    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})
    assert res.status_code == 200
    assert json.loads(res.data).get("gate_pending") is True

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id_1 = reviews[0]["id"]

    # 2) Reject the gate
    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id_1}",
            json={
                "status": "rejected",
                "comment": "Needs more work",
            },
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200

    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # 3) Re-attempt the same transition — new pending review created
    with patch("app.subprocess.Popen"):
        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})
    assert res.status_code == 200
    assert json.loads(res.data).get("gate_pending") is True

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    # There should be a new pending review (old rejected one stays in history)
    pending = [r for r in reviews if r["status"] == "pending"]
    assert len(pending) == 1
    review_id_2 = pending[0]["id"]

    # 4) Approve the new review — ticket MUST move
    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id_2}",
            json={
                "status": "approved",
            },
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200

    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1], (
        f"Bug: ticket stayed in status {ticket['status_id']} after gate approval. "
        f"Stale rejected review is blocking the move."
    )


# 21. Security: agent cannot self-approve a manual gate without the X-Human-Action header
def test_gate_review_approval_requires_human_action_header(client):
    """A request to approve a gate review without the X-Human-Action header
    must be rejected with 403. This prevents AI agents from bypassing
    manual quality gates by calling the gate review API directly."""
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Human Approval",
            "workflow_id": wf_id,
        },
    )

    # Create a pending gate review by attempting the transition
    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert len(reviews) == 1
    review_id = reviews[0]["id"]

    # Attempt to approve WITHOUT the X-Human-Action header — must fail
    res = client.put(
        f"/api/gate_reviews/{review_id}",
        json={
            "status": "approved",
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.data}"
    data = json.loads(res.data)
    assert "human" in data["error"].lower() or "authentication" in data["error"].lower()

    # Verify the review is still pending (not approved)
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert reviews[0]["status"] == "pending"

    # Verify the ticket is still in the old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Attempt with a WRONG secret — must also fail
    res = client.put(
        f"/api/gate_reviews/{review_id}",
        json={
            "status": "approved",
        },
        headers={"Content-Type": "application/json", "X-Human-Action": "wrong-secret"},
    )
    assert res.status_code == 403

    # Attempt with the CORRECT secret — must succeed
    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/gate_reviews/{review_id}",
            json={
                "status": "approved",
            },
            headers=HUMAN_HEADERS,
        )
    assert res.status_code == 200

    # Ticket should now be in the new status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1]


# 22. Security: gate review rejection also requires the X-Human-Action header
def test_gate_review_rejection_requires_human_action_header(client):
    """Rejection of a gate review also requires the X-Human-Action header."""
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Human Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    review_id = reviews[0]["id"]

    # Attempt rejection WITHOUT header — must fail
    res = client.put(
        f"/api/gate_reviews/{review_id}",
        json={
            "status": "rejected",
            "comment": "Not good enough",
        },
    )
    assert res.status_code == 403

    # Review should still be pending
    reviews = json.loads(client.get(f"/api/gate_reviews?ticket_id={ticket_id}").data)
    assert reviews[0]["status"] == "pending"


# 23. Regression: priority update must be persisted even when a manual gate is pending
def test_priority_update_persisted_with_pending_manual_gate(client):
    """When a PUT includes both priority and a status transition that hits a
    pending manual gate, the priority change must be saved alongside title/body.
    Previously priority was extracted after the gate early-return, so it was
    silently dropped."""
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "manual",
            "name": "Approval",
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"):
        res = client.put(
            f"/api/tickets/{ticket_id}",
            json={
                "status_id": status_ids[1],
                "priority": "Critical",
            },
        )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is True

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]
    # Priority must have been saved despite the pending gate
    assert ticket.get("priority") == "Critical"


# 24. Regression: CLI gate failure must include stdout in output and comment
# Bug: run_cli_gate dropped stdout on non-zero exit, so lint.sh diagnostics were lost.
def test_cli_gate_failure_includes_stdout(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Lint",
            "config": json.dumps({"command": "scripts/lint.sh"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "diagnostic on stdout"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    # Ticket should still be in old status
    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[0]

    # Ticket comment must contain the stdout diagnostic
    # (Gate reviews are cleaned up on failure, so we inspect the comment.)
    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    fail_comments = [c for c in comments if "❌ Gate 'Lint' (CLI) failed" in c["body"]]
    assert len(fail_comments) == 1
    assert "diagnostic on stdout" in fail_comments[0]["body"]
    assert "Exit code: 1" in fail_comments[0]["body"]


# 25. Regression: CLI gate failure with both stdout and stderr shows both
def test_cli_gate_failure_shows_stdout_and_stderr(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Build",
            "config": json.dumps({"command": "make"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = "compiling main.c"
        mock_result.stderr = "error: undefined symbol"
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    fail_comments = [c for c in comments if "❌ Gate 'Build' (CLI) failed" in c["body"]]
    assert len(fail_comments) == 1
    body = fail_comments[0]["body"]
    assert "--- stdout ---" in body
    assert "compiling main.c" in body
    assert "--- stderr ---" in body
    assert "error: undefined symbol" in body
    assert "Exit code: 2" in body


# 26. Regression: CLI gate success path still captures stdout
def test_cli_gate_success_captures_stdout(client):
    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Test Suite",
            "config": json.dumps({"command": "pytest"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All tests passed\n42 tests, 0 failures"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data.get("gate_pending") is not True

    ticket = json.loads(client.get(f"/api/tickets/{ticket_id}").data)
    assert ticket["status_id"] == status_ids[1]

    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    pass_comments = [c for c in comments if "✅ Gate 'Test Suite' (CLI) passed" in c["body"]]
    assert len(pass_comments) == 1
    assert "All tests passed" in pass_comments[0]["body"]


# 27. Regression: CLI gate timeout includes stderr if available
def test_cli_gate_timeout_includes_stderr(client):
    import subprocess as _subprocess

    wf_id, status_ids = _create_workflow_with_statuses(client)
    _board_id, ticket_id = _create_board_with_ticket(client, wf_id, status_ids[0])

    client.post(
        "/api/quality_gates",
        json={
            "from_status_id": status_ids[0],
            "to_status_id": status_ids[1],
            "gate_type": "cli",
            "name": "Slow Check",
            "config": json.dumps({"command": "sleep 999"}),
            "workflow_id": wf_id,
        },
    )

    with patch("app.subprocess.Popen"), patch("app.subprocess.run") as mock_run:
        mock_run.side_effect = _subprocess.TimeoutExpired(
            cmd="sleep 999", timeout=60, output="partial stdout", stderr="partial stderr"
        )

        res = client.put(f"/api/tickets/{ticket_id}", json={"status_id": status_ids[1]})

    assert res.status_code == 200

    comments = json.loads(client.get(f"/api/tickets/{ticket_id}/comments").data)
    fail_comments = [c for c in comments if "❌ Gate 'Slow Check' (CLI) failed" in c["body"]]
    assert len(fail_comments) == 1
    body = fail_comments[0]["body"]
    assert "timed out" in body.lower()
    assert "partial stderr" in body
