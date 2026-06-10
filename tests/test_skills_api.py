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


def test_list_skills_includes_built_in(client, new_workflow, temp_skills_folder):
    import pi_cowork.skill_packages as _sp
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-skill")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-skill\ndescription: Built-in\n---\n\nContent.")
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [sk["name"] for sk in data]
    assert "bi-skill" in names
    bi_skill = next(sk for sk in data if sk["name"] == "bi-skill")
    assert bi_skill["scope"] == "system"
    assert bi_skill["description"] == "Built-in"


def test_list_skills_workflow_overrides_built_in(client, new_workflow, temp_skills_folder):
    import pi_cowork.skill_packages as _sp
    # Create a built-in skill
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "override-skill")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: override-skill\ndescription: Built-in\n---\n\nContent.")
    # Create a workflow-scoped skill with the same name
    wf_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "override-skill")
    os.makedirs(wf_dir, exist_ok=True)
    with open(os.path.join(wf_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: override-skill\ndescription: Workflow\n---\n\nContent.")
    res = client.get(f"/api/skills?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    data = json.loads(res.data)
    skill = next(sk for sk in data if sk["name"] == "override-skill")
    assert skill["scope"] == "workflow"
    assert skill["description"] == "Workflow"


def test_export_skill_built_in_fallback(client, new_workflow, temp_skills_folder):
    import pi_cowork.skill_packages as _sp
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-exp")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-exp\n---\n\nContent.")
    res = client.get(f"/api/skills/bi-exp/export?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    assert res.content_type == "application/zip"


def test_export_skill_global_fallback(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, "global", "global-exp")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-exp\n---\n\nContent.")
    res = client.get(f"/api/skills/global-exp/export?workflow_id={new_workflow['id']}")
    assert res.status_code == 200


def test_delete_skill_built_in_rejected(client, new_workflow, temp_skills_folder):
    import pi_cowork.skill_packages as _sp
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-del")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-del\n---\n\nContent.")
    res = client.delete(f"/api/skills/bi-del?workflow_id={new_workflow['id']}")
    assert res.status_code == 403
    assert b"System skills cannot be deleted" in res.data
    assert os.path.isdir(built_in_dir)


def test_delete_skill_workflow_not_built_in(client, new_workflow, temp_skills_folder):
    skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "del-wf")
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: del-wf\n---\n\nContent.")
    res = client.delete(f"/api/skills/del-wf?workflow_id={new_workflow['id']}")
    assert res.status_code == 200
    assert not os.path.exists(skill_dir)


def test_resolve_skill_dir_built_in_fallback():
    import tempfile
    import pi_cowork.skill_packages as _sp
    from pi_cowork.skill_packages import resolve_skill_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        original_built_in = _sp.get_built_in_skills_folder
        _sp.get_built_in_skills_folder = lambda: tmpdir
        try:
            os.makedirs(os.path.join(tmpdir, "built-in-skill"))
            with open(os.path.join(tmpdir, "built-in-skill", "SKILL.md"), "w") as f:
                f.write("---\nname: built-in-skill\n---\n\nContent.")
            result = resolve_skill_dir(999, "built-in-skill")
            assert result is not None
            assert result.endswith("built-in-skill")
        finally:
            _sp.get_built_in_skills_folder = original_built_in


def test_resolve_skill_dir_workflow_overrides_built_in():
    import tempfile
    import pi_cowork.skill_packages as _sp
    from pi_cowork.skill_packages import resolve_skill_dir

    with tempfile.TemporaryDirectory() as skills_tmp, tempfile.TemporaryDirectory() as built_in_tmp:
        original_skills = _sp.get_skills_folder
        original_built_in = _sp.get_built_in_skills_folder
        _sp.get_skills_folder = lambda: skills_tmp
        _sp.get_built_in_skills_folder = lambda: built_in_tmp
        try:
            wf_dir = os.path.join(skills_tmp, "1", "override-skill")
            bi_dir = os.path.join(built_in_tmp, "override-skill")
            os.makedirs(wf_dir)
            os.makedirs(bi_dir)
            with open(os.path.join(wf_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: override-skill\n---\n\nContent.")
            with open(os.path.join(bi_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: override-skill\n---\n\nContent.")
            result = resolve_skill_dir(1, "override-skill")
            assert result == wf_dir
        finally:
            _sp.get_skills_folder = original_skills
            _sp.get_built_in_skills_folder = original_built_in


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
