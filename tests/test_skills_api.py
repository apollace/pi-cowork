"""Tests for skills API (Ticket #146)."""

import io
import json
import os
import zipfile

import pytest


@pytest.fixture
def sample_skill(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "test-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: test-skill\ndescription: A test skill\n---\n\n## Test Skill\n\nThis is a test.")
    return {"name": "test-skill", "workflow_id": new_workflow["id"]}, new_workflow


def test_list_skills_filesystem_scan(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "fs-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: fs-skill\ndescription: Scanned\n---\n\nContent.")
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["name"] == "fs-skill"
    assert data[0]["scope"] == "workflow"
    assert data[0]["description"] == "Scanned"


def test_list_skills_includes_global(client, new_workflow, temp_skills_folder):
    global_dir = os.path.join(temp_skills_folder, "global", "global-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-skill\ndescription: Global\n---\n\nGlobal content.")
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [sk["name"] for sk in data]
    assert "global-skill" in names
    global_skill = next(sk for sk in data if sk["name"] == "global-skill")
    assert global_skill["scope"] == "global"


def test_list_skills_used_by_agents(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "linked-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: linked-skill\ndescription: Linked\n---\n\nContent.")
    agent_res = client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "LinkedAgent",
            "description": "d",
            "skill_names": ["linked-skill"],
        },
    )
    assert agent_res.status_code == 201
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    data = json.loads(res.data)
    sk = next(s for s in data if s["name"] == "linked-skill")
    assert sk["used_by"] == ["LinkedAgent"]


def test_delete_skill_by_name(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "del-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: del-skill\ndescription: Del\n---\n\nContent.")
    res = client.delete(f"/api/skills/del-skill?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    assert not os.path.exists(skill_dir)


def test_delete_skill_missing_workflow(client):
    res = client.delete("/api/skills/foo")
    assert res.status_code == 400
    assert b"workflow_id is required" in res.data


def test_delete_skill_not_found(client, new_workflow):
    res = client.delete(f"/api/skills/missing?workflow_id={new_workflow['id']}")
    assert res.status_code == 404


def test_export_skill(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "exp-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: exp-skill\n---\n\nContent.")
    with open(os.path.join(skill_dir, "extra.txt"), "w") as f:
        f.write("extra")
    res = client.get(f"/api/skills/exp-skill/export?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    assert res.content_type == "application/zip"
    from io import BytesIO

    buf = BytesIO(res.data)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert "SKILL.md" in names
        assert "extra.txt" in names


def test_export_skill_global_fallback(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, "global", "global-exp")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-exp\n---\n\nContent.")
    res = client.get(f"/api/skills/global-exp/export?workflow_id={new_workflow['id']}")
    assert res.status_code == 200


def test_import_skill_zip(client, new_workflow, temp_skills_folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: zip-import-skill\ndescription: Imported\n---\n\nContent.",
        )
    buf.seek(0)
    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "zip-import-skill"
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "zip-import-skill")
    assert os.path.isdir(skill_dir)


def test_import_skill_zip_duplicate(client, sample_skill, new_workflow):
    skill, workflow = sample_skill
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: test-skill\n---\n\nContent.")
    buf.seek(0)
    res = client.post(
        "/api/skills/import",
        data={"workflow_id": workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 409


def test_import_skill_zip_missing_skill_md(client, new_workflow):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "Hello")
    buf.seek(0)
    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    assert b"SKILL.md" in res.data
