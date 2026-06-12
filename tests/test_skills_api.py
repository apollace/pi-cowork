"""Tests for skills API (Ticket #146)."""

import io
import json
import os
import zipfile
from unittest.mock import patch

import pytest

from pi_cowork.skill_packages import (
    import_skill_from_github,
    parse_github_url,
)


def _make_skill_zip_bytes(name="github-skill", description="GitHub skill"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndescription: {description}\n---\n\nContent.",
        )
    buf.seek(0)
    return buf.read()


def _make_github_zipball_bytes(skill_name="github-skill", subpath="", description="GitHub skill"):
    """Create a zipball that mimics GitHub's zipball format (single top-level dir)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        prefix = "owner-repo-abc123/"
        if subpath:
            prefix += subpath.rstrip("/") + "/"
        zf.writestr(
            prefix + "SKILL.md",
            f"---\nname: {skill_name}\ndescription: {description}\n---\n\nContent.",
        )
    buf.seek(0)
    return buf.read()


class FakeHTTPResponse:
    def __init__(self, body_bytes):
        self._body = body_bytes

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestParseGitHubUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("github.com/owner/repo", ("owner", "repo", None)),
            ("https://github.com/owner/repo.git", ("owner", "repo", None)),
            ("https://github.com/owner/repo/tree/main/sub/folder", ("owner", "repo", "sub/folder")),
            ("http://www.github.com/owner/repo/blob/main/sub/folder", ("owner", "repo", "sub/folder")),
            ("github.com/owner/repo/", ("owner", "repo", None)),
        ],
    )
    def test_valid_urls(self, url, expected):
        assert parse_github_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://gitlab.com/owner/repo",
            "not-a-url",
            "github.com/",
            "github.com/owner",
        ],
    )
    def test_invalid_urls(self, url):
        with pytest.raises(ValueError):
            parse_github_url(url)


class TestImportSkillFromGitHub:
    def test_import_skill_from_github_whole_repo(self, temp_skills_folder):
        zip_bytes = _make_github_zipball_bytes("gh-skill")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            info, error = import_skill_from_github("https://github.com/owner/repo", workflow_id=None)
        assert error is None
        assert info["name"] == "gh-skill"
        skill_dir = os.path.join(temp_skills_folder, "global", "gh-skill")
        assert os.path.isdir(skill_dir)

    def test_import_skill_from_github_subpath(self, temp_skills_folder):
        zip_bytes = _make_github_zipball_bytes("gh-sub-skill", subpath="skills/my-skill")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            info, error = import_skill_from_github(
                "https://github.com/owner/repo/tree/main/skills/my-skill",
                workflow_id=None,
            )
        assert error is None
        assert info["name"] == "gh-sub-skill"
        skill_dir = os.path.join(temp_skills_folder, "global", "gh-sub-skill")
        assert os.path.isdir(skill_dir)

    @pytest.mark.parametrize("subpath", ["../..", "foo/../../etc", "foo/../..", "../foo"])
    def test_import_skill_from_github_traversal_subpath(self, subpath):
        zip_bytes = _make_github_zipball_bytes("gh-skill")
        url = f"https://github.com/owner/repo/tree/main/{subpath}"
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            info, error = import_skill_from_github(url, workflow_id=None)
        assert info is None
        assert "Invalid subpath" in error

    def test_import_skill_from_github_404(self):
        from urllib.error import HTTPError

        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 404, "Not Found", None, None)):
            info, error = import_skill_from_github("https://github.com/owner/repo", workflow_id=None)
        assert info is None
        assert "not found" in error.lower()

    def test_import_skill_from_github_403(self):
        from urllib.error import HTTPError

        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 403, "Forbidden", None, None)):
            info, error = import_skill_from_github("https://github.com/owner/repo", workflow_id=None)
        assert info is None
        assert "rate limit" in error.lower() or "denied" in error.lower()

    def test_import_skill_from_github_missing_skill_md(self, temp_skills_folder):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("owner-repo-abc123/sub/README.md", "Hello")
        zip_bytes = buf.getvalue()
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            info, error = import_skill_from_github("https://github.com/owner/repo/tree/main/sub", workflow_id=None)
        assert info is None
        assert "SKILL.md" in error

    def test_import_skill_from_github_duplicate(self, temp_skills_folder):
        skill_dir = os.path.join(temp_skills_folder, "global", "dup-gh-skill")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: dup-gh-skill\n---\n\nContent.")
        zip_bytes = _make_github_zipball_bytes("dup-gh-skill")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            info, error = import_skill_from_github("https://github.com/owner/repo", workflow_id=None)
        assert info is None
        assert "already exists" in error.lower()

    def test_import_skill_from_github_invalid_url(self):
        info, error = import_skill_from_github("https://gitlab.com/owner/repo", workflow_id=None)
        assert info is None
        assert "Invalid GitHub URL" in error


class TestImportSkillGitHubAPI:
    def test_api_import_skill_github_global(self, client, temp_skills_folder):
        zip_bytes = _make_github_zipball_bytes("api-gh-skill")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            res = client.post("/api/skills/import-github", json={"url": "https://github.com/owner/repo"})
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["name"] == "api-gh-skill"
        skill_dir = os.path.join(temp_skills_folder, "global", "api-gh-skill")
        assert os.path.isdir(skill_dir)

    def test_api_import_skill_github_workflow(self, client, new_workflow, temp_skills_folder):
        zip_bytes = _make_github_zipball_bytes("api-gh-wf-skill")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            res = client.post(
                "/api/skills/import-github",
                json={"url": "https://github.com/owner/repo", "workflow_id": new_workflow["id"]},
            )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["name"] == "api-gh-wf-skill"
        skill_dir = os.path.join(temp_skills_folder, str(new_workflow["id"]), "api-gh-wf-skill")
        assert os.path.isdir(skill_dir)

    def test_api_import_skill_github_missing_url(self, client):
        res = client.post("/api/skills/import-github", json={})
        assert res.status_code == 400
        assert b"url is required" in res.data

    def test_api_import_skill_github_repo_not_found(self, client):
        from urllib.error import HTTPError

        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 404, "Not Found", None, None)):
            res = client.post("/api/skills/import-github", json={"url": "https://github.com/owner/repo"})
        assert res.status_code == 404
        assert b"not found" in res.data.lower()

    def test_api_import_skill_github_rate_limit(self, client):
        from urllib.error import HTTPError

        with patch("urllib.request.urlopen", side_effect=HTTPError(None, 403, "Forbidden", None, None)):
            res = client.post("/api/skills/import-github", json={"url": "https://github.com/owner/repo"})
        assert res.status_code == 400
        assert b"rate limit" in res.data.lower() or b"denied" in res.data.lower()

    def test_api_import_skill_github_duplicate(self, client, temp_skills_folder):
        skill_dir = os.path.join(temp_skills_folder, "global", "dup-api-gh")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
            f.write("---\nname: dup-api-gh\n---\n\nContent.")
        zip_bytes = _make_github_zipball_bytes("dup-api-gh")
        with patch("urllib.request.urlopen", return_value=FakeHTTPResponse(zip_bytes)):
            res = client.post("/api/skills/import-github", json={"url": "https://github.com/owner/repo"})
        assert res.status_code == 409
        assert b"already exists" in res.data

    def test_api_import_skill_github_invalid_workflow_id(self, client):
        res = client.post(
            "/api/skills/import-github",
            json={"url": "https://github.com/owner/repo", "workflow_id": "not-an-int"},
        )
        assert res.status_code == 400
        assert b"workflow_id must be an integer" in res.data


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
    # Default-enable model: agents automatically use available skills
    client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "LinkedAgent",
            "description": "d",
        },
    )
    # Excluding agent should not appear in used_by
    client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "ExcludedAgent",
            "description": "d",
            "excluded_skill_names": ["linked-skill"],
        },
    )
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


def test_list_skills_global_only(client, temp_skills_folder):
    global_dir = os.path.join(temp_skills_folder, "global", "global-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-skill\ndescription: Global\n---\n\nGlobal content.")
    res = client.get("/api/skills")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["name"] == "global-skill"
    assert data[0]["scope"] == "global"
    assert data[0]["description"] == "Global"


def test_list_skills_global_only_excludes_system(client, temp_skills_folder):
    import pi_cowork.skill_packages as _sp

    global_dir = os.path.join(temp_skills_folder, "global", "global-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-skill\n---\n\nContent.")
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-skill")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-skill\n---\n\nContent.")
    res = client.get("/api/skills")
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [sk["name"] for sk in data]
    assert "global-skill" in names
    assert "bi-skill" not in names


def test_list_skills_include_system_global_only(client, temp_skills_folder):
    import pi_cowork.skill_packages as _sp

    global_dir = os.path.join(temp_skills_folder, "global", "global-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-skill\ndescription: Global\n---\n\nContent.")
    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-skill")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-skill\ndescription: Built-in\n---\n\nContent.")
    res = client.get("/api/skills?include_system=true")
    assert res.status_code == 200
    data = json.loads(res.data)
    names = [sk["name"] for sk in data]
    assert "global-skill" in names
    assert "bi-skill" in names
    global_skill = next(sk for sk in data if sk["name"] == "global-skill")
    assert global_skill["scope"] == "global"
    bi_skill = next(sk for sk in data if sk["name"] == "bi-skill")
    assert bi_skill["scope"] == "system"


def test_list_skills_global_only_used_by_all_workflows(client, new_workflow, temp_skills_folder):
    global_dir = os.path.join(temp_skills_folder, "global", "shared-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: shared-skill\ndescription: Shared\n---\n\nContent.")
    # Create two workflows, each with an agent (default-enable: no skill_names needed)
    wf2_res = client.post("/api/workflows", json={"name": "WF2", "description": "d"})
    assert wf2_res.status_code == 201
    wf2 = json.loads(wf2_res.data)
    client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "Agent1",
            "description": "d",
        },
    )
    client.post(
        "/api/agents",
        json={
            "workflow_id": wf2["id"],
            "name": "Agent2",
            "description": "d",
        },
    )
    # Excluding agent should not appear in used_by
    client.post(
        "/api/agents",
        json={
            "workflow_id": new_workflow["id"],
            "name": "ExcludedAgent",
            "description": "d",
            "excluded_skill_names": ["shared-skill"],
        },
    )
    res = client.get("/api/skills")
    assert res.status_code == 200
    data = json.loads(res.data)
    sk = next(s for s in data if s["name"] == "shared-skill")
    used = sk["used_by"]
    assert "Agent1" in used
    assert "Agent2" in used
    assert "ExcludedAgent" not in used


def test_delete_skill_missing_workflow_targets_global(client, temp_skills_folder):
    global_dir = os.path.join(temp_skills_folder, "global", "global-del")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: global-del\n---\n\nContent.")
    res = client.delete("/api/skills/global-del")
    assert res.status_code == 200
    assert not os.path.exists(global_dir)


def test_delete_skill_global_built_in_rejected(client, temp_skills_folder):
    import pi_cowork.skill_packages as _sp

    built_in_dir = os.path.join(_sp.get_built_in_skills_folder(), "bi-global-del")
    os.makedirs(built_in_dir, exist_ok=True)
    with open(os.path.join(built_in_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: bi-global-del\n---\n\nContent.")
    res = client.delete("/api/skills/bi-global-del")
    assert res.status_code == 403
    assert b"System skills cannot be deleted" in res.data
    assert os.path.isdir(built_in_dir)


def test_import_skill_zip_global(client, temp_skills_folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: zip-global-skill\ndescription: Global imported\n---\n\nContent.",
        )
    buf.seek(0)
    res = client.post(
        "/api/skills/import",
        data={"file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert data["name"] == "zip-global-skill"
    skill_dir = os.path.join(temp_skills_folder, "global", "zip-global-skill")
    assert os.path.isdir(skill_dir)


def test_import_skill_zip_global_duplicate(client, temp_skills_folder):
    global_dir = os.path.join(temp_skills_folder, "global", "dup-global-skill")
    os.makedirs(global_dir, exist_ok=True)
    with open(os.path.join(global_dir, "SKILL.md"), "w") as f:
        f.write("---\nname: dup-global-skill\n---\n\nContent.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: dup-global-skill\n---\n\nContent.")
    buf.seek(0)
    res = client.post(
        "/api/skills/import",
        data={"file": (buf, "skill.zip")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 409
    assert b"already exists" in res.data


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
