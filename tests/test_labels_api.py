import json


def test_create_label(client, new_workflow):
    res = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#ef4444",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert "id" in data


def test_create_label_duplicate_per_workflow(client, new_workflow):
    res = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#ef4444",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res.status_code == 201
    res2 = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#991b1b",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res2.status_code == 409


def test_create_label_same_name_different_workflow(client, new_workflow):
    # Create a second workflow
    wf2 = client.post("/api/workflows", json={"name": "Other WF"})
    wf2_id = json.loads(wf2.data)["id"]
    res = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#ef4444",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res.status_code == 201
    res2 = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#ef4444",
            "workflow_id": wf2_id,
        },
    )
    assert res2.status_code == 201


def test_list_labels_by_workflow(client, new_workflow):
    client.post("/api/labels", json={"name": "A", "color": "#000", "workflow_id": new_workflow["id"]})
    client.post("/api/labels", json={"name": "B", "color": "#fff", "workflow_id": new_workflow["id"]})
    res = client.get(f"/api/labels?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 2
    assert data[0]["name"] == "A"
    assert data[1]["name"] == "B"


def test_update_label(client, new_workflow):
    res = client.post(
        "/api/labels",
        json={
            "name": "Old",
            "color": "#000",
            "workflow_id": new_workflow["id"],
        },
    )
    lid = json.loads(res.data)["id"]
    res = client.put(f"/api/labels/{lid}", json={"name": "New", "color": "#fff"})
    assert res.status_code == 200
    res = client.get(f"/api/labels/{lid}")
    data = json.loads(res.data)
    assert data["name"] == "New"
    assert data["color"] == "#fff"


def test_delete_label_cascades_from_ticket_labels(client, default_board):
    wf_id = default_board["workflow_id"]
    # Create label
    lbl = client.post(
        "/api/labels",
        json={
            "name": "ToDelete",
            "color": "#000",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    # Create ticket and attach label
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
            "labels": [lid],
        },
    )
    tid = json.loads(ticket.data)["id"]
    # Verify attached
    res = client.get(f"/api/tickets/{tid}/labels")
    assert len(json.loads(res.data)) == 1
    # Delete label
    res = client.delete(f"/api/labels/{lid}")
    assert res.status_code == 200
    # Verify detached
    res = client.get(f"/api/tickets/{tid}/labels")
    assert len(json.loads(res.data)) == 0


def test_attach_label_to_ticket(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "Feature",
            "color": "#10b981",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]
    res = client.post(f"/api/tickets/{tid}/labels", json={"label_ids": [lid]})
    assert res.status_code == 201
    res = client.get(f"/api/tickets/{tid}/labels")
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["name"] == "Feature"


def test_attach_invalid_label_to_ticket(client, default_board):
    # Create another workflow and label there
    wf2 = client.post("/api/workflows", json={"name": "Other"})
    wf2_id = json.loads(wf2.data)["id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "External",
            "color": "#000",
            "workflow_id": wf2_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]
    res = client.post(f"/api/tickets/{tid}/labels", json={"label_ids": [lid]})
    assert res.status_code == 400


def test_detach_label_from_ticket(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "Bug",
            "color": "#ef4444",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
            "labels": [lid],
        },
    )
    tid = json.loads(ticket.data)["id"]
    res = client.delete(f"/api/tickets/{tid}/labels?label_id={lid}")
    assert res.status_code == 200
    res = client.get(f"/api/tickets/{tid}/labels")
    assert len(json.loads(res.data)) == 0


def test_ticket_api_returns_labels(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "Docs",
            "color": "#3b82f6",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
            "labels": [lid],
        },
    )
    tid = json.loads(ticket.data)["id"]
    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert "labels" in data
    assert len(data["labels"]) == 1
    assert data["labels"][0]["name"] == "Docs"


def test_ticket_list_returns_labels(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl = client.post(
        "/api/labels",
        json={
            "name": "Urgent",
            "color": "#f59e0b",
            "workflow_id": wf_id,
        },
    )
    lid = json.loads(lbl.data)["id"]
    client.post(
        "/api/tickets",
        json={
            "title": "T1",
            "board_id": default_board["id"],
            "labels": [lid],
        },
    )
    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    data = json.loads(res.data)
    assert len(data) == 1
    assert len(data[0]["labels"]) == 1
    assert data[0]["labels"][0]["name"] == "Urgent"


def test_ticket_update_replaces_labels(client, default_board):
    wf_id = default_board["workflow_id"]
    lbl1 = client.post("/api/labels", json={"name": "A", "color": "#000", "workflow_id": wf_id})
    lid1 = json.loads(lbl1.data)["id"]
    lbl2 = client.post("/api/labels", json={"name": "B", "color": "#fff", "workflow_id": wf_id})
    lid2 = json.loads(lbl2.data)["id"]
    ticket = client.post(
        "/api/tickets",
        json={
            "title": "T",
            "board_id": default_board["id"],
            "labels": [lid1],
        },
    )
    tid = json.loads(ticket.data)["id"]
    res = client.put(f"/api/tickets/{tid}", json={"labels": [lid2]})
    assert res.status_code == 200
    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert len(data["labels"]) == 1
    assert data["labels"][0]["name"] == "B"


def test_import_export_roundtrips_labels(client, default_workflow):
    # Export the default workflow (has everything)
    res = client.get(f"/api/workflows/{default_workflow['id']}/export")
    payload = json.loads(res.data)
    # It should include labels (possibly empty if no labels seeded)
    assert "labels" in payload
    # Add a label to the payload for round-trip verification
    payload["labels"].append({"name": "Roundtrip", "color": "#abcdef"})
    # Import
    res = client.post("/api/workflows/import", json=payload)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["labels"] >= 1
    new_wf_id = data["workflow_id"]
    res = client.get(f"/api/labels?workflow_id={new_wf_id}")
    imported = json.loads(res.data)
    names = {label["name"] for label in imported}
    assert "Roundtrip" in names
