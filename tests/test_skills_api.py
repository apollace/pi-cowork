"""Tests for skills API (Ticket #133)."""

import json

import pytest


@pytest.fixture
def new_workflow(client):
    res = client.post("/api/workflows", json={"name": "Skill Test WF", "description": "t"})
    assert res.status_code == 201
    return json.loads(res.data)


@pytest.fixture
def sample_skill(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={
            "workflow_id": new_workflow["id"],
            "name": "test-skill",
            "description": "A test skill",
            "content": "## Test Skill\n\nThis is a test.",
            "sort_order": 1,
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)


# ── CRUD ──


def test_create_skill(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={
            "workflow_id": new_workflow["id"],
            "name": "my-skill",
            "description": "desc",
            "content": "content body",
            "sort_order": 5,
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "my-skill"
    assert data["description"] == "desc"
    assert data["content"] == "content body"
    assert data["sort_order"] == 5
    assert data["workflow_id"] == new_workflow["id"]


def test_create_skill_missing_workflow(client):
    res = client.post("/api/skills", json={"name": "n"})
    assert res.status_code == 400
    assert b"workflow_id is required" in res.data


def test_create_skill_missing_name(client, new_workflow):
    res = client.post("/api/skills", json={"workflow_id": new_workflow["id"], "content": "c"})
    assert res.status_code == 400
    assert b"name is required" in res.data


def test_create_skill_invalid_name(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={"workflow_id": new_workflow["id"], "name": "Bad Name!", "content": "c"},
    )
    assert res.status_code == 400
    assert b"lowercase letters" in res.data


def test_create_skill_duplicate_name(client, sample_skill):
    res = client.post(
        "/api/skills",
        json={
            "workflow_id": sample_skill["workflow_id"],
            "name": sample_skill["name"],
            "content": "c",
        },
    )
    assert res.status_code == 409
    assert b"already exists" in res.data


def test_create_skill_name_too_long(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={
            "workflow_id": new_workflow["id"],
            "name": "a" * 65,
            "content": "c",
        },
    )
    assert res.status_code == 400
    assert b"64 characters" in res.data


def test_list_skills(client, new_workflow, sample_skill):
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["name"] == "test-skill"


def test_get_skill(client, sample_skill):
    res = client.get(f"/api/skills/{sample_skill['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["id"] == sample_skill["id"]


def test_get_skill_not_found(client):
    res = client.get("/api/skills/99999")
    assert res.status_code == 404


def test_update_skill(client, sample_skill):
    res = client.put(
        f"/api/skills/{sample_skill['id']}",
        json={"name": "updated-skill", "content": "new content", "description": "new desc", "sort_order": 10},
    )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["name"] == "updated-skill"
    assert data["content"] == "new content"
    assert data["description"] == "new desc"
    assert data["sort_order"] == 10


def test_update_skill_invalid_name(client, sample_skill):
    res = client.put(f"/api/skills/{sample_skill['id']}", json={"name": "--bad"})
    assert res.status_code == 400
    assert b"lowercase letters" in res.data


def test_update_skill_no_fields(client, sample_skill):
    res = client.put(f"/api/skills/{sample_skill['id']}", json={})
    assert res.status_code == 400


def test_delete_skill(client, sample_skill, new_workflow):
    res = client.delete(f"/api/skills/{sample_skill['id']}")
    assert res.status_code == 200
    res2 = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert len(json.loads(res2.data)) == 0


# ── Agent association ──


def test_agent_create_with_skills(client, new_workflow, sample_skill):
    res = client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "SkillAgent",
            "description": "d",
            "skill_ids": [sample_skill["id"]],
        },
    )
    assert res.status_code == 201
    agent_id = json.loads(res.data)["id"]
    agent_res = client.get(f"/api/agents/{agent_id}")
    agent = json.loads(agent_res.data)
    assert len(agent["skills"]) == 1
    assert agent["skills"][0]["id"] == sample_skill["id"]


def test_agent_update_with_skills(client, new_workflow, sample_skill):
    res = client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "SkillAgent",
            "description": "d",
        },
    )
    agent_id = json.loads(res.data)["id"]
    res = client.put(f"/api/agents/{agent_id}", json={"skill_ids": [sample_skill["id"]]})
    assert res.status_code == 200
    agent_res = client.get(f"/api/agents/{agent_id}")
    agent = json.loads(agent_res.data)
    assert len(agent["skills"]) == 1
    assert agent["skills"][0]["id"] == sample_skill["id"]


def test_agent_update_clears_skills(client, new_workflow, sample_skill):
    res = client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "SkillAgent",
            "description": "d",
            "skill_ids": [sample_skill["id"]],
        },
    )
    agent_id = json.loads(res.data)["id"]
    res = client.put(f"/api/agents/{agent_id}", json={"skill_ids": []})
    assert res.status_code == 200
    agent_res = client.get(f"/api/agents/{agent_id}")
    agent = json.loads(agent_res.data)
    assert agent["skills"] == []


def test_agents_list_includes_skills(client, new_workflow, sample_skill):
    res = client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "SkillAgent",
            "description": "d",
            "skill_ids": [sample_skill["id"]],
        },
    )
    assert res.status_code == 201
    res = client.get(f"/api/agents?workflow_id={new_workflow['id']}")
    agents = json.loads(res.data)
    assert len(agents) == 1
    assert len(agents[0]["skills"]) == 1


# ── Agent spawn integration ──


def test_spawn_agent_includes_skill_args(client, default_workflow, default_board):
    from unittest.mock import patch

    # create skill
    skill = client.post(
        "/api/skills",
        json={
            "workflow_id": default_workflow["id"],
            "name": "pytest-skill",
            "description": "A pytest skill",
            "content": "## Pytest Skill\n\nUse pytest.",
        },
    )
    skill_data = json.loads(skill.data)

    # create agent with skill
    agent = client.post(
        "/api/agents",
        json={
            "name": "SkillSpawnAgent",
            "description": "You are a skill agent.",
            "workflow_id": default_workflow["id"],
            "skill_ids": [skill_data["id"]],
        },
    )
    aid = json.loads(agent.data)["id"]

    # create status with agent
    s1 = client.post(
        "/api/statuses",
        json={
            "name": "SkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    # create ticket
    ticket = client.post(
        "/api/tickets",
        json={"title": "Skill Ticket", "board_id": default_board["id"]},
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

    assert "--skill" in captured_cmd
    idx = captured_cmd.index("--skill")
    skill_dir = captured_cmd[idx + 1]
    assert skill_dir.endswith("pytest-skill")

    import os

    skill_md = os.path.join(skill_dir, "SKILL.md")
    assert os.path.exists(skill_md)
    with open(skill_md) as f:
        content = f.read()
    assert "name: pytest-skill" in content
    assert "Use pytest." in content


def test_skill_name_accepts_numbers_and_hyphens(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={"workflow_id": new_workflow["id"], "name": "skill-123", "content": "c"},
    )
    assert res.status_code == 201


def test_skill_name_rejects_leading_hyphen(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={"workflow_id": new_workflow["id"], "name": "-skill", "content": "c"},
    )
    assert res.status_code == 400


def test_skill_name_rejects_trailing_hyphen(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={"workflow_id": new_workflow["id"], "name": "skill-", "content": "c"},
    )
    assert res.status_code == 400


def test_skill_name_rejects_consecutive_hyphens(client, new_workflow):
    res = client.post(
        "/api/skills",
        json={"workflow_id": new_workflow["id"], "name": "skill--name", "content": "c"},
    )
    assert res.status_code == 400


def test_delete_workflow_cascades_skills(client, new_workflow, sample_skill):
    res = client.delete(f"/api/workflows/{new_workflow['id']}")
    assert res.status_code == 200
    res2 = client.get(f"/api/skills/{sample_skill['id']}")
    assert res2.status_code == 404
