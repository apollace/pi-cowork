"""Tests for directory-based skills system (Ticket #143)."""

import io
import json
import os
import zipfile

import pytest


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
    data = json.loads(res.data)
    return data, new_workflow


def test_skill_package_filesystem_roundtrip(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    assert os.path.isdir(skill_dir)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    assert os.path.isfile(skill_md)
    with open(skill_md) as f:
        content = f.read()
    assert "name: test-skill" in content
    assert "A test skill" in content
    assert "## Test Skill" in content


def test_skill_package_read_from_disk(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    skill_md = os.path.join(skill_dir, "SKILL.md")
    # Modify on disk
    with open(skill_md, "w") as f:
        f.write("---\nname: test-skill\ndescription: modified\n---\n\nModified content.")
    res = client.get(f"/api/skills/{skill['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["description"] == "modified"
    assert data["content"] == "Modified content."


def test_skill_package_rename_move_dir(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    old_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    assert os.path.isdir(old_dir)
    res = client.put(f"/api/skills/{skill['id']}", json={"name": "renamed-skill"})
    assert res.status_code == 200
    new_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "renamed-skill")
    assert os.path.isdir(new_dir)
    assert not os.path.isdir(old_dir)
    skill_md = os.path.join(new_dir, "SKILL.md")
    with open(skill_md) as f:
        content = f.read()
    assert "name: renamed-skill" in content


def test_skill_package_update_content(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    res = client.put(f"/api/skills/{skill['id']}", json={"content": "Updated body."})
    assert res.status_code == 200
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    skill_md = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md) as f:
        content = f.read()
    assert "Updated body." in content


def test_skill_package_delete_removes_dir(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    assert os.path.isdir(skill_dir)
    res = client.delete(f"/api/skills/{skill['id']}")
    assert res.status_code == 200
    assert not os.path.exists(skill_dir)


def test_skill_package_subdirs(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    os.makedirs(os.path.join(skill_dir, "examples"))
    os.makedirs(os.path.join(skill_dir, "templates"))
    res = client.get(f"/api/skills?workflow_id={workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["subdirs"] == ["examples", "templates"]


def test_skill_import_zip_success(client, new_workflow, temp_skills_folder):
    # Build a ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: zip-skill\ndescription: Imported from ZIP\n---\n\nZIP content here.",
        )
        zf.writestr("examples/demo.py", "print('hello')")
    buf.seek(0)

    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "zip-skill"
    assert data["description"] == "Imported from ZIP"
    assert data["content"] == "ZIP content here."
    assert data["subdirs"] == ["examples"]

    # Verify filesystem
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "zip-skill")
    assert os.path.isdir(skill_dir)
    assert os.path.isfile(os.path.join(skill_dir, "examples", "demo.py"))


def test_skill_import_zip_with_root_dir(client, new_workflow, temp_skills_folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "my-skill/SKILL.md",
            "---\nname: nested-skill\ndescription: Nested\n---\n\nNested content.",
        )
    buf.seek(0)

    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "nested-skill"


def test_skill_import_zip_missing_skill_md(client, new_workflow):
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


def test_skill_import_zip_duplicate_name(client, sample_skill, new_workflow):
    skill, workflow = sample_skill
    # skill is named "test-skill" in workflow
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: test-skill\ndescription: Dup\n---\n\nContent.",
        )
    buf.seek(0)

    res = client.post(
        "/api/skills/import",
        data={"workflow_id": workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 409


def test_skill_import_zip_bad_zip(client, new_workflow):
    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (io.BytesIO(b"not a zip"), "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    assert b"Invalid ZIP" in res.data


def test_skill_import_zip_empty_name(client, new_workflow):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\ndescription: no name\n---\n\nContent.",
        )
    buf.seek(0)

    res = client.post(
        "/api/skills/import",
        data={"workflow_id": new_workflow["id"], "file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    assert b"name field" in res.data


def test_skill_setting_default(monkeypatch):
    from pi_cowork.config import get_config

    monkeypatch.delenv("PI_SKILLS_FOLDER", raising=False)
    # Clear any monkeypatch on get_skills_folder so this test
    # sees the real get_config fallback chain.
    import pi_cowork.skill_packages as _sp

    original = _sp.get_skills_folder
    _sp.get_skills_folder = lambda: "workspace/skills"
    try:
        assert get_config("skills_folder_path") == "workspace/skills"
    finally:
        _sp.get_skills_folder = original


def test_skill_setting_env_override(monkeypatch):
    from pi_cowork.config import get_config

    monkeypatch.setenv("PI_SKILLS_FOLDER", "/tmp/skills-test")
    # get_config reads env dynamically each call
    assert get_config("skills_folder_path") == "/tmp/skills-test"


def test_spawn_agent_copies_skill_directory(client, default_workflow, default_board, temp_skills_folder):
    from unittest.mock import patch

    skill_res = client.post(
        "/api/skills",
        json={
            "workflow_id": default_workflow["id"],
            "name": "dir-skill",
            "description": "Dir skill",
            "content": "## Dir Skill",
        },
    )
    skill_data = json.loads(skill_res.data)

    # Add extra file to the global skill package
    skill_dir = os.path.join(temp_skills_folder, str(default_workflow["id"]), "dir-skill")
    with open(os.path.join(skill_dir, "examples.txt"), "w") as f:
        f.write("example data")

    agent = client.post(
        "/api/agents",
        json={
            "name": "DirSkillAgent",
            "description": "You are a dir skill agent.",
            "workflow_id": default_workflow["id"],
            "skill_ids": [skill_data["id"]],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "DirSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Dir Skill Ticket", "board_id": default_board["id"]},
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

    idx = captured_cmd.index("--skill")
    session_skill_dir = captured_cmd[idx + 1]
    assert session_skill_dir.endswith("dir-skill")
    assert os.path.isfile(os.path.join(session_skill_dir, "SKILL.md"))
    assert os.path.isfile(os.path.join(session_skill_dir, "examples.txt"))
    with open(os.path.join(session_skill_dir, "SKILL.md")) as f:
        data = f.read()
    assert "name: dir-skill" in data


def test_workflow_delete_cleans_skills_folder(client, new_workflow, temp_skills_folder):
    res = client.post(
        "/api/skills",
        json={
            "workflow_id": new_workflow["id"],
            "name": "wf-skill",
            "description": "desc",
            "content": "content",
        },
    )
    assert res.status_code == 201
    wf_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]))
    assert os.path.isdir(wf_dir)

    del_res = client.delete(f"/api/workflows/{new_workflow['id']}")
    assert del_res.status_code == 200
    assert not os.path.exists(wf_dir)
