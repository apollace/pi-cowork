"""Tests for directory-based skills system (Ticket #143 / #146)."""

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
    res = client.get(f"/api/skills?workflow_id={workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["description"] == "modified"


def test_skill_package_rename_move_dir(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    old_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    assert os.path.isdir(old_dir)
    new_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "renamed-skill")
    os.rename(old_dir, new_dir)
    assert os.path.isdir(new_dir)
    assert not os.path.isdir(old_dir)
    skill_md = os.path.join(new_dir, "SKILL.md")
    with open(skill_md) as f:
        content = f.read()
    assert "name: test-skill" in content


def test_skill_package_update_content(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    skill_md = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md, "w") as f:
        f.write("---\nname: test-skill\ndescription: A test skill\n---\n\nUpdated body.")
    res = client.get(f"/api/skills?workflow_id={workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["description"] == "A test skill"


def test_skill_package_delete_removes_dir(client, sample_skill, temp_skills_folder):
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    assert os.path.isdir(skill_dir)
    res = client.delete(f"/api/skills/test-skill?workflow_id={workflow['id']}")
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
    import pi_cowork.skill_packages as _sp

    original = _sp.get_skills_folder
    _sp.get_skills_folder = lambda: "workspace/skills"
    try:
        assert get_config("skills_folder_path") == "workspace/skills"
    finally:
        _sp.get_skills_folder = original


def test_skill_setting_env_override(monkeypatch, tmp_path):
    from pi_cowork.config import get_config

    test_dir = str(tmp_path / "skills-test")
    monkeypatch.setenv("PI_SKILLS_FOLDER", test_dir)
    assert get_config("skills_folder_path") == test_dir


def test_spawn_agent_copies_skill_directory(client, default_workflow, default_board, temp_skills_folder):
    from unittest.mock import patch

    skill_dir = os.path.join(temp_skills_folder, str(default_workflow["id"]), "dir-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: dir-skill\ndescription: Dir skill\n---\n\n## Dir Skill")
    with open(os.path.join(skill_dir, "examples.txt"), "w") as f:
        f.write("example data")

    agent = client.post(
        "/api/agents",
        json={
            "name": "DirSkillAgent",
            "description": "You are a dir skill agent.",
            "workflow_id": default_workflow["id"],
            "skill_names": ["dir-skill"],
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

    assert "--skill" in captured_cmd
    idx = captured_cmd.index("--skill")
    session_skill_dir = captured_cmd[idx + 1]
    assert session_skill_dir.endswith("dir-skill")
    assert os.path.isfile(os.path.join(session_skill_dir, "SKILL.md"))
    assert os.path.isfile(os.path.join(session_skill_dir, "examples.txt"))
    with open(os.path.join(session_skill_dir, "SKILL.md")) as f:
        data = f.read()
    assert "name: dir-skill" in data


def test_spawn_agent_missing_skill_warning(client, default_workflow, default_board, temp_skills_folder):
    from unittest.mock import patch

    agent = client.post(
        "/api/agents",
        json={
            "name": "MissingSkillAgent",
            "description": "You are a missing skill agent.",
            "workflow_id": default_workflow["id"],
            "skill_names": ["nonexistent-skill"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "MissingSkillStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    sid = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={"title": "Missing Skill Ticket", "board_id": default_board["id"]},
    )
    tid = json.loads(ticket.data)["id"]

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": sid})
        assert res.status_code == 200

    comments = json.loads(client.get(f"/api/tickets/{tid}/comments").data)
    bodies = [c["body"] for c in comments]
    assert any("Missing skill packages" in b for b in bodies)


def test_workflow_delete_cleans_skills_folder(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "wf-skill")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: wf-skill\n---\n\nContent.")
    wf_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]))
    assert os.path.isdir(wf_dir)

    del_res = client.delete(f"/api/workflows/{new_workflow['id']}")
    assert del_res.status_code == 200
    assert not os.path.exists(wf_dir)


def test_parse_frontmatter_with_dashes_in_body(client, sample_skill, temp_skills_folder):
    """--- inside markdown body must not be mistaken for frontmatter delimiter."""
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")
    skill_md = os.path.join(skill_dir, "SKILL.md")
    body_with_dashes = "Some text\n---\nMore text after separator"
    with open(skill_md, "w") as f:
        f.write(f"---\nname: test-skill\ndescription: A test skill\n---\n\n{body_with_dashes}")

    from pi_cowork.skill_packages import read_skill_package

    pkg = read_skill_package(skill_dir)
    assert pkg["name"] == "test-skill"
    assert pkg["description"] == "A test skill"
    assert pkg["content"] == body_with_dashes


def test_write_skill_package_newlines_and_quotes(client, sample_skill, temp_skills_folder):
    """Descriptions with newlines, quotes, and backslashes round-trip correctly."""
    skill, workflow = sample_skill
    skill_dir = os.path.join(temp_skills_folder, str(workflow["id"]), "test-skill")

    from pi_cowork.skill_packages import read_skill_package, write_skill_package

    desc = 'Line one\nLine two\nSay "hello" and \\ backslash'
    write_skill_package(skill_dir, "test-skill", desc, "content")
    pkg = read_skill_package(skill_dir)
    assert pkg["name"] == "test-skill"
    assert pkg["description"] == desc
    assert pkg["content"] == "content"
