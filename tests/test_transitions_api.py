import json


def test_create_transition(client, default_workflow):
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
    res = client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "Move when done",
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["id"]


def test_create_transition_duplicate(client, default_workflow):
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "C",
            "sort_order": 3,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "D",
            "sort_order": 4,
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
            "instructions": "x",
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "y",
            "workflow_id": default_workflow["id"],
        },
    )
    assert res.status_code == 409


def test_list_transitions(client, default_workflow):
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "E",
            "sort_order": 95,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "F",
            "sort_order": 96,
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
            "instructions": "go",
            "workflow_id": default_workflow["id"],
        },
    )
    res = client.get(f"/api/transitions?workflow_id={default_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    ours = [t for t in data if t["from_status_name"] == "E" and t["to_status_name"] == "F"]
    assert len(ours) == 1
    assert ours[0]["instructions"] == "go"


def test_update_transition(client, default_workflow):
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "I",
            "sort_order": 97,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "J",
            "sort_order": 98,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]
    tr = client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "old",
            "workflow_id": default_workflow["id"],
        },
    )
    tr_id = json.loads(tr.data)["id"]
    res = client.put(f"/api/transitions/{tr_id}", json={"instructions": "new text"})
    assert res.status_code == 200
    res = client.get(f"/api/transitions/{tr_id}")
    data = json.loads(res.data)
    assert data["instructions"] == "new text"


def test_delete_transition(client, default_workflow):
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "G",
            "sort_order": 91,
            "workflow_id": default_workflow["id"],
        },
    )
    s2 = client.post(
        "/api/statuses",
        json={
            "name": "H",
            "sort_order": 92,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]
    id2 = json.loads(s2.data)["id"]
    tr = client.post(
        "/api/transitions",
        json={
            "from_status_id": id1,
            "to_status_id": id2,
            "instructions": "z",
            "workflow_id": default_workflow["id"],
        },
    )
    tr_id = json.loads(tr.data)["id"]
    # Verify it exists before deletion
    res = client.get(f"/api/transitions/{tr_id}")
    assert res.status_code == 200
    # Delete it
    res = client.delete(f"/api/transitions/{tr_id}")
    assert res.status_code == 200
    # Verify it's gone
    res = client.get(f"/api/transitions/{tr_id}")
    assert res.status_code == 404


def test_list_transitions_requires_workflow_id(client):
    res = client.get("/api/transitions")
    assert res.status_code == 400
    assert b"workflow_id" in res.data
