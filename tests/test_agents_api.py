import json


def test_create_agent(client, default_workflow):
    res = client.post(
        "/api/agents",
        json={
            "name": "TestAgent",
            "description": "A test agent",
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["id"]


def test_create_agent_duplicate(client, default_workflow):
    client.post(
        "/api/agents",
        json={
            "name": "DupAgent",
            "description": "d1",
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.post(
        "/api/agents",
        json={
            "name": "DupAgent",
            "description": "d2",
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 409


def test_list_agents(client, default_workflow):
    client.post(
        "/api/agents",
        json={
            "name": "A1",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.get(f"/api/agents?workflow_id={default_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [a["name"] for a in data]
    assert "A1" in names
    assert len(data) >= 8  # 8 pre-built agents + A1


def test_delete_agent_blocked_by_status(client, default_workflow):
    res = client.post(
        "/api/agents",
        json={
            "name": "LinkedAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    agent_id = json.loads(res.data)["id"]
    client.post(
        "/api/statuses",
        json={
            "name": "S1",
            "sort_order": 1,
            "agent_id": agent_id,
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.delete(f"/api/agents/{agent_id}")
    assert res.status_code == 409


def test_delete_agent_ok(client, default_workflow):
    res = client.post(
        "/api/agents",
        json={
            "name": "OrphanAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    agent_id = json.loads(res.data)["id"]
    res = client.delete(f"/api/agents/{agent_id}")
    assert res.status_code == 200


def test_create_agent_same_name_different_workflow(client, default_workflow, new_workflow):
    """Agent names should only be unique within a single workflow."""
    res = client.post(
        "/api/agents",
        json={
            "name": "SharedAgent",
            "description": "First workflow",
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 201
    res2 = client.post(
        "/api/agents",
        json={
            "name": "SharedAgent",
            "description": "Second workflow",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res2.status_code == 201


def test_create_agent_with_excluded_skill_names(client, default_workflow):
    res = client.post(
        "/api/agents",
        json={
            "name": "ExcludedAgent",
            "description": "An agent with exclusions",
            "workflow_id": default_workflow["id"],
            "excluded_skill_names": ["ux-design", "some-skill"],
        },
    )
    assert res.status_code == 201
    agent_id = json.loads(res.data)["id"]
    get_res = client.get(f"/api/agents/{agent_id}")
    data = json.loads(get_res.data)
    assert data["excluded_skill_names"] == ["ux-design", "some-skill"]


def test_update_agent_excluded_skill_names(client, default_workflow):
    res = client.post(
        "/api/agents",
        json={
            "name": "UpdateExcludedAgent",
            "description": "Before update",
            "workflow_id": default_workflow["id"],
        },
    )
    agent_id = json.loads(res.data)["id"]
    put_res = client.put(
        f"/api/agents/{agent_id}",
        json={"excluded_skill_names": ["ux-design"]},
    )
    assert put_res.status_code == 200
    get_res = client.get(f"/api/agents/{agent_id}")
    data = json.loads(get_res.data)
    assert data["excluded_skill_names"] == ["ux-design"]


def test_list_agents_includes_excluded_skill_names(client, default_workflow):
    client.post(
        "/api/agents",
        json={
            "name": "ListedExcludedAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
            "excluded_skill_names": ["ux-design"],
        },
    )
    res = client.get(f"/api/agents?workflow_id={default_workflow['id']}")
    data = json.loads(res.data)
    agent = next((a for a in data if a["name"] == "ListedExcludedAgent"), None)
    assert agent is not None
    assert agent["excluded_skill_names"] == ["ux-design"]
