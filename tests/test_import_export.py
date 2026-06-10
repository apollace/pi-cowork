import json


def test_export_workflow(client, default_workflow):
    res = client.get(f"/api/workflows/{default_workflow['id']}/export")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["version"] == "1.0"
    assert data["name"] == default_workflow["name"]
    assert isinstance(data["agents"], list)
    assert isinstance(data["statuses"], list)
    assert isinstance(data["transitions"], list)
    # Skills no longer included in export
    assert "skills" not in data
    agent_names = [a["name"] for a in data["agents"]]
    assert "Researcher" in agent_names
    assert "Developer" in agent_names


def test_import_workflow_with_skill_names(client):
    workflow_json = {
        "version": "1.0",
        "name": "Skills Import Workflow",
        "description": "Testing skills import",
        "agents": [{"name": "SkilledAgent", "description": "d", "skill_names": ["pytest-skill"]}],
        "statuses": [
            {
                "name": "Start",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": None,
                "goal": None,
            },
            {
                "name": "End",
                "sort_order": 2,
                "is_default": False,
                "is_terminal": True,
                "agent_name": None,
                "goal": None,
            },
        ],
        "transitions": [{"from_status_name": "Start", "to_status_name": "End", "instructions": ""}],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["agents"] == 1

    wf_id = data["workflow_id"]
    agents = json.loads(client.get(f"/api/agents?workflow_id={wf_id}").data)
    assert agents[0]["skill_names"] == ["pytest-skill"]


def test_export_nonexistent_workflow(client):
    res = client.get("/api/workflows/99999/export")
    assert res.status_code == 404


def test_import_workflow(client):
    workflow_json = {
        "version": "1.0",
        "name": "Imported Test Workflow",
        "description": "A test import",
        "agents": [{"name": "Tester", "description": "Test agent", "working_directory": "/tmp/test"}],  # noqa: S108
        "statuses": [
            {
                "name": "Start",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": None,
                "goal": None,
            },
            {
                "name": "End",
                "sort_order": 2,
                "is_default": False,
                "is_terminal": True,
                "agent_name": None,
                "goal": None,
            },
        ],
        "transitions": [{"from_status_name": "Start", "to_status_name": "End", "instructions": "Finish the task"}],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["workflow_id"]
    assert data["agents"] == 1
    assert data["statuses"] == 2
    assert data["transitions"] == 1

    wf_res = client.get(f"/api/workflows/{data['workflow_id']}")
    wf = json.loads(wf_res.data)
    assert wf["name"] == "Imported Test Workflow"


def test_import_workflow_duplicate_name(client):
    workflow_json = {
        "version": "1.0",
        "name": "Duplicate Workflow",
        "agents": [{"name": "Agent1", "description": "d1", "working_directory": "/tmp/d1"}],  # noqa: S108
        "statuses": [
            {"name": "S1", "sort_order": 1, "is_default": True, "is_terminal": False, "agent_name": None, "goal": None}
        ],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["workflow_id"]

    wf_list = json.loads(client.get("/api/workflows").data)
    names = [w["name"] for w in wf_list]
    assert any("Duplicate Workflow" in n for n in names)


def test_import_workflow_invalid_version(client):
    res = client.post("/api/workflows/import", json={"version": "2.0"})
    assert res.status_code == 400


def test_import_workflow_missing_default_status(client):
    workflow_json = {
        "version": "1.0",
        "name": "Bad Workflow",
        "agents": [],
        "statuses": [{"name": "S1", "sort_order": 1, "is_default": False, "is_terminal": False}],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 400
    assert b"Exactly one status" in res.data


def test_import_workflow_invalid_agent_ref(client):
    workflow_json = {
        "version": "1.0",
        "name": "Bad Workflow",
        "agents": [],
        "statuses": [
            {"name": "S1", "sort_order": 1, "is_default": True, "is_terminal": False, "agent_name": "NonExistent"}
        ],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 400
    assert b"unknown agent" in res.data


def test_import_workflow_invalid_status_ref(client):
    workflow_json = {
        "version": "1.0",
        "name": "Bad Workflow",
        "agents": [],
        "statuses": [{"name": "S1", "sort_order": 1, "is_default": True, "is_terminal": False}],
        "transitions": [{"from_status_name": "S1", "to_status_name": "NonExistent", "instructions": "go"}],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 400
    assert b"unknown to_status" in res.data


def test_import_export_roundtrip(client):
    workflow_json = {
        "version": "1.0",
        "name": "Roundtrip Workflow",
        "description": "Testing roundtrip",
        "agents": [
            {
                "name": "RTAgent",
                "description": "Roundtrip agent",
                "working_directory": "/tmp/rt",  # noqa: S108
                "skill_names": ["my-skill"],
            }
        ],  # noqa: S108
        "statuses": [
            {
                "name": "Open",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": "RTAgent",
                "goal": "Get stuff done",
            },
            {
                "name": "Done",
                "sort_order": 2,
                "is_default": False,
                "is_terminal": True,
                "agent_name": None,
                "goal": None,
            },
        ],
        "transitions": [{"from_status_name": "Open", "to_status_name": "Done", "instructions": "When complete"}],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    wf_id = json.loads(res.data)["workflow_id"]

    res = client.get(f"/api/workflows/{wf_id}/export")
    exported = json.loads(res.data)

    assert exported["name"] == "Roundtrip Workflow"
    assert exported["description"] == "Testing roundtrip"
    assert len(exported["agents"]) == 1
    assert exported["agents"][0]["name"] == "RTAgent"
    assert exported["agents"][0]["skill_names"] == ["my-skill"]
    assert len(exported["statuses"]) == 2
    assert exported["statuses"][0]["name"] == "Open"
    assert exported["statuses"][0]["agent_name"] == "RTAgent"
    assert len(exported["transitions"]) == 1
    assert exported["transitions"][0]["from_status_name"] == "Open"

    # Re-import from exported JSON
    exported["name"] = "Roundtrip Workflow Reimport"
    res2 = client.post("/api/workflows/import", json=exported)
    assert res2.status_code == 200
    wf_id2 = json.loads(res2.data)["workflow_id"]

    agents = json.loads(client.get(f"/api/agents?workflow_id={wf_id2}").data)
    assert agents[0]["skill_names"] == ["my-skill"]


# ---------------------------------------------------------------------------
# Status model/thinking in import/export (Ticket #69)
# ---------------------------------------------------------------------------


def test_export_includes_status_model_and_thinking(client, default_workflow):
    agent = client.post(
        "/api/agents",
        json={
            "name": "StatusMTAgent",
            "description": "d",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    res = client.post(
        "/api/statuses",
        json={
            "name": "StatusMT",
            "sort_order": 99,
            "workflow_id": default_workflow["id"],
            "agent_id": aid,
            "model": "gpt-4o",
            "thinking": "high",
        },
    )
    assert res.status_code == 201

    res = client.get(f"/api/workflows/{default_workflow['id']}/export")
    assert res.status_code == 200
    data = json.loads(res.data)

    status = next(s for s in data["statuses"] if s["name"] == "StatusMT")
    assert status["model"] == "gpt-4o"
    assert status["thinking"] == "high"

    backlog = next(s for s in data["statuses"] if s["name"] == "Backlog")
    assert backlog["model"] is None
    assert backlog["thinking"] is None


def test_import_with_status_model_and_thinking(client):
    workflow_json = {
        "version": "1.0",
        "name": "Import Status MT",
        "agents": [{"name": "A1", "description": "d"}],
        "statuses": [
            {
                "name": "S1",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": "A1",
                "model": "gpt-4o",
                "thinking": "high",
            },
            {
                "name": "S2",
                "sort_order": 2,
                "is_default": False,
                "is_terminal": False,
                "agent_name": None,
                "model": None,
                "thinking": None,
            },
        ],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    wf_id = json.loads(res.data)["workflow_id"]

    statuses = json.loads(client.get(f"/api/statuses?workflow_id={wf_id}").data)
    s1 = next(s for s in statuses if s["name"] == "S1")
    assert s1["model"] == "gpt-4o"
    assert s1["thinking"] == "high"
    s2 = next(s for s in statuses if s["name"] == "S2")
    assert s2["model"] is None
    assert s2["thinking"] is None


def test_import_export_roundtrip_with_status_model_thinking(client):
    """Roundtrip: import → export → re-import preserves status model/thinking."""
    workflow_json = {
        "version": "1.0",
        "name": "Status MT Roundtrip",
        "agents": [{"name": "A1", "description": "d"}],
        "statuses": [
            {
                "name": "S1",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": "A1",
                "model": "claude-3",
                "thinking": "xhigh",
            },
            {"name": "S2", "sort_order": 2, "is_default": False, "is_terminal": False, "agent_name": None},
        ],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    wf_id = json.loads(res.data)["workflow_id"]

    res = client.get(f"/api/workflows/{wf_id}/export")
    exported = json.loads(res.data)
    s1 = next(s for s in exported["statuses"] if s["name"] == "S1")
    assert s1["model"] == "claude-3"
    assert s1["thinking"] == "xhigh"
    s2 = next(s for s in exported["statuses"] if s["name"] == "S2")
    assert s2["model"] is None
    assert s2["thinking"] is None

    exported["name"] = "Status MT Roundtrip Reimport"
    res2 = client.post("/api/workflows/import", json=exported)
    assert res2.status_code == 200
    wf_id2 = json.loads(res2.data)["workflow_id"]

    statuses = json.loads(client.get(f"/api/statuses?workflow_id={wf_id2}").data)
    s1_re = next(s for s in statuses if s["name"] == "S1")
    assert s1_re["model"] == "claude-3"
    assert s1_re["thinking"] == "xhigh"
    s2_re = next(s for s in statuses if s["name"] == "S2")
    assert s2_re["model"] is None
    assert s2_re["thinking"] is None
