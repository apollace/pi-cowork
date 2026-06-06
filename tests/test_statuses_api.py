import json


def test_create_status(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "Custom",
            "sort_order": 10,
            "is_default": False,
            "is_terminal": False,
            "agent_id": None,
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["id"]


def test_create_status_duplicate(client, default_workflow):
    client.post(
        "/api/statuses",
        json={
            "name": "Dup",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.post(
        "/api/statuses",
        json={
            "name": "Dup",
            "sort_order": 2,
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 409


def test_delete_status_blocked_by_ticket(client, default_workflow, default_board):
    res = client.post(
        "/api/statuses",
        json={
            "name": "S2",
            "sort_order": 2,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]
    client.post(
        "/api/tickets",
        json={
            "title": "T",
            "body": "B",
            "status_id": status_id,
            "board_id": default_board["id"],
        },
    )
    res = client.delete(f"/api/statuses/{status_id}")
    assert res.status_code == 409


def test_delete_status_blocked_by_transition(client, default_workflow):
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "A",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "B",
            "sort_order": 2,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]
    client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "test",
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.delete(f"/api/statuses/{id1}")
    assert res.status_code == 409


def test_delete_status_ok(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "Orphan",
            "sort_order": 99,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]
    res = client.delete(f"/api/statuses/{status_id}")
    assert res.status_code == 200


def test_default_status_new_ticket(client, default_board):
    # Default status is Backlog from seed (in default workflow, which default board uses)
    res = client.post(
        "/api/tickets",
        json={
            "title": "Auto",
            "board_id": default_board["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    ticket = client.get(f"/api/tickets/{data['id']}")
    t = json.loads(ticket.data)
    assert t["status_name"] == "Backlog"


def test_list_statuses_by_workflow(client, default_workflow, new_workflow):
    # Create status in default workflow
    client.post(
        "/api/statuses",
        json={
            "name": "DefaultStatus",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    # Create status in new workflow
    client.post(
        "/api/statuses",
        json={
            "name": "NewStatus",
            "sort_order": 1,
            "workflow_id": new_workflow["id"],
        },
    )

    res = client.get(f"/api/statuses?workflow_id={default_workflow['id']}")
    data = json.loads(res.data)
    names = [s["name"] for s in data]
    assert "DefaultStatus" in names
    assert "NewStatus" not in names

    res = client.get(f"/api/statuses?workflow_id={new_workflow['id']}")
    data = json.loads(res.data)
    names = [s["name"] for s in data]
    assert "NewStatus" in names
    assert "DefaultStatus" not in names


# ---------------------------------------------------------------------------
# Status model/thinking overrides (Ticket #69)
# ---------------------------------------------------------------------------


def test_create_status_with_model_and_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "ModelThink",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
            "model": "gpt-4o",
            "thinking": "high",
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    status_id = data["id"]

    res = client.get(f"/api/statuses/{status_id}")
    assert res.status_code == 200
    status = json.loads(res.data)
    assert status["model"] == "gpt-4o"
    assert status["thinking"] == "high"


def test_create_status_without_model_and_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "PlainStatus",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    status_id = data["id"]

    res = client.get(f"/api/statuses/{status_id}")
    assert res.status_code == 200
    status = json.loads(res.data)
    assert status["model"] is None
    assert status["thinking"] is None


def test_create_status_with_empty_model_and_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "EmptyOverrides",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
            "model": "",
            "thinking": "",
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    status_id = data["id"]

    res = client.get(f"/api/statuses/{status_id}")
    assert res.status_code == 200
    status = json.loads(res.data)
    assert status["model"] is None
    assert status["thinking"] is None


def test_create_status_invalid_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "BadThink",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
            "thinking": "ultra",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "thinking" in data["error"].lower()


def test_update_status_model_and_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "Updatable",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]

    res = client.put(
        f"/api/statuses/{status_id}",
        json={
            "model": "gpt-4o",
            "thinking": "xhigh",
        },
    )
    assert res.status_code == 200

    res = client.get(f"/api/statuses/{status_id}")
    status = json.loads(res.data)
    assert status["model"] == "gpt-4o"
    assert status["thinking"] == "xhigh"


def test_update_status_clears_model_and_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "Clearable",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
            "model": "gpt-4o",
            "thinking": "high",
        },
    )
    status_id = json.loads(res.data)["id"]

    res = client.put(
        f"/api/statuses/{status_id}",
        json={
            "model": "",
            "thinking": "",
        },
    )
    assert res.status_code == 200

    res = client.get(f"/api/statuses/{status_id}")
    status = json.loads(res.data)
    assert status["model"] is None
    assert status["thinking"] is None


def test_update_status_invalid_thinking(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "ThinkCheck",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]

    res = client.put(
        f"/api/statuses/{status_id}",
        json={
            "thinking": "invalid",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "thinking" in data["error"].lower()


def test_create_status_invalid_model(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "BadModel",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
            "model": "not-a-real-model",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "model" in data["error"].lower()


def test_update_status_invalid_model(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "ModelBase",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]

    res = client.put(
        f"/api/statuses/{status_id}",
        json={
            "model": "not-a-real-model",
        },
    )
    assert res.status_code == 400
    data = json.loads(res.data)
    assert "model" in data["error"].lower()


def test_update_status_valid_thinking_values(client, default_workflow):
    res = client.post(
        "/api/statuses",
        json={
            "name": "ThinkVals",
            "sort_order": 1,
            "workflow_id": default_workflow["id"],
        },
    )
    status_id = json.loads(res.data)["id"]

    for val in ("off", "minimal", "low", "medium", "high", "xhigh"):
        res = client.put(f"/api/statuses/{status_id}", json={"thinking": val})
        assert res.status_code == 200
        status = json.loads(client.get(f"/api/statuses/{status_id}").data)
        assert status["thinking"] == val
