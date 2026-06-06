"""Tests for git integration: git_enabled on workflows, branch on tickets,
conditional visibility, branch write guard, and agent context injection."""

import json

# ── Workflow git_enabled CRUD ──


def test_create_workflow_git_enabled_default_false(client):
    """Creating a workflow without git_enabled defaults to False."""
    res = client.post(
        "/api/workflows",
        json={
            "name": "NoGit Wf",
            "description": "No git",
        },
    )
    assert res.status_code == 201
    wf_id = json.loads(res.data)["id"]
    res = client.get(f"/api/workflows/{wf_id}")
    wf = json.loads(res.data)
    assert wf["git_enabled"] == 0 or wf["git_enabled"] is False


def test_create_workflow_git_enabled_true(client):
    """Creating a workflow with git_enabled=True stores it."""
    res = client.post(
        "/api/workflows",
        json={
            "name": "GitEnabled Wf",
            "description": "With git",
            "git_enabled": True,
        },
    )
    assert res.status_code == 201
    wf_id = json.loads(res.data)["id"]
    res = client.get(f"/api/workflows/{wf_id}")
    wf = json.loads(res.data)
    assert wf["git_enabled"] in (1, True)


def test_update_workflow_git_enabled(client):
    """Updating git_enabled on a workflow works."""
    res = client.post(
        "/api/workflows",
        json={
            "name": "Toggle Wf",
            "description": "Toggle git",
        },
    )
    assert res.status_code == 201
    wf_id = json.loads(res.data)["id"]
    # Enable git
    res = client.put(f"/api/workflows/{wf_id}", json={"git_enabled": True})
    assert res.status_code == 200
    res = client.get(f"/api/workflows/{wf_id}")
    wf = json.loads(res.data)
    assert wf["git_enabled"] in (1, True)
    # Disable git
    res = client.put(f"/api/workflows/{wf_id}", json={"git_enabled": False})
    assert res.status_code == 200
    res = client.get(f"/api/workflows/{wf_id}")
    wf = json.loads(res.data)
    assert wf["git_enabled"] in (0, False)


def test_list_workflows_includes_git_enabled(client):
    """Listing workflows includes git_enabled."""
    client.post("/api/workflows", json={"name": "GitList Wf", "git_enabled": True})
    res = client.get("/api/workflows")
    assert res.status_code == 200
    data = json.loads(res.data)
    wf = [w for w in data if w["name"] == "GitList Wf"][0]
    assert wf["git_enabled"] in (1, True)


# ── Board git_enabled exposure ──


def test_board_includes_git_enabled(client, default_board):
    """Board detail response includes git_enabled from its workflow."""
    board = default_board
    res = client.get(f"/api/boards/{board['id']}")
    data = json.loads(res.data)
    assert "git_enabled" in data
    assert data["git_enabled"] in (False, 0)


def test_board_git_enabled_reflects_workflow(client, default_workflow):
    """Board git_enabled reflects workflow's git_enabled."""
    # Enable git on the default workflow
    client.put(f"/api/workflows/{default_workflow['id']}", json={"git_enabled": True})
    boards = json.loads(client.get("/api/boards").data)
    board = boards[0]
    res = client.get(f"/api/boards/{board['id']}")
    data = json.loads(res.data)
    assert data["git_enabled"] in (True, 1)


def test_boards_list_includes_git_enabled(client, default_workflow):
    """Board list responses include git_enabled."""
    boards = json.loads(client.get("/api/boards").data)
    assert "git_enabled" in boards[0]


# ── Ticket branch visibility ──


def test_ticket_no_branch_when_git_disabled(client, default_board):
    """When git is disabled, ticket API responses don't include branch."""
    # default_workflow has git_enabled=False
    res = client.post(
        "/api/tickets",
        json={
            "title": "No Branch",
            "board_id": default_board["id"],
        },
    )
    assert res.status_code == 201
    tid = json.loads(res.data)["id"]

    # GET single ticket
    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert "branch" not in data

    # GET ticket list
    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    data = json.loads(res.data)
    ticket = [t for t in data if t["id"] == tid][0]
    assert "branch" not in ticket


def test_ticket_has_branch_when_git_enabled(client, default_board, default_workflow):
    """When git is enabled, ticket API responses include branch field."""
    client.put(f"/api/workflows/{default_workflow['id']}", json={"git_enabled": True})

    res = client.post(
        "/api/tickets",
        json={
            "title": "With Branch",
            "board_id": default_board["id"],
        },
    )
    assert res.status_code == 201
    tid = json.loads(res.data)["id"]

    # GET single ticket
    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert "branch" in data
    # branch should be None/empty since no git repo
    assert data["branch"] is None or data["branch"] == ""

    # GET ticket list
    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    data = json.loads(res.data)
    ticket = [t for t in data if t["id"] == tid][0]
    assert "branch" in ticket


# ── Branch write guard ──


def test_cannot_set_branch_when_git_disabled(client, default_board):
    """PUT /api/tickets/:id with branch returns 400 when git is disabled."""
    res = client.post(
        "/api/tickets",
        json={
            "title": "Branch Guard Test",
            "board_id": default_board["id"],
        },
    )
    assert res.status_code == 201
    tid = json.loads(res.data)["id"]

    res = client.put(f"/api/tickets/{tid}", json={"branch": "ticket-1-branch"})
    assert res.status_code == 400
    assert b"git is not enabled" in res.data


def test_can_set_branch_when_git_enabled(client, default_board, default_workflow):
    """PUT /api/tickets/:id with branch succeeds when git is enabled."""
    client.put(f"/api/workflows/{default_workflow['id']}", json={"git_enabled": True})

    res = client.post(
        "/api/tickets",
        json={
            "title": "Branch Set Test",
            "board_id": default_board["id"],
        },
    )
    assert res.status_code == 201
    tid = json.loads(res.data)["id"]

    res = client.put(f"/api/tickets/{tid}", json={"branch": "ticket-42-my-feature"})
    assert res.status_code == 200

    # Verify branch was set
    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert data["branch"] == "ticket-42-my-feature"


def test_can_clear_branch_when_git_enabled(client, default_board, default_workflow):
    """PUT /api/tickets/:id with branch=null clears the branch."""
    client.put(f"/api/workflows/{default_workflow['id']}", json={"git_enabled": True})

    res = client.post(
        "/api/tickets",
        json={
            "title": "Branch Clear Test",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    # Set a branch
    client.put(f"/api/tickets/{tid}", json={"branch": "my-branch"})
    # Clear it
    res = client.put(f"/api/tickets/{tid}", json={"branch": ""})
    assert res.status_code == 200


# ── Schema and migrations ──


def test_schema_has_git_enabled_on_workflows(client):
    """The schema includes git_enabled on workflows table."""
    from app import app

    with app.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        cols = db.execute("PRAGMA table_info(workflows)").fetchall()
        col_names = [c[1] for c in cols]
        assert "git_enabled" in col_names


def test_schema_has_branch_on_tickets(client):
    """The schema includes branch on tickets table."""
    from app import app

    with app.app_context():
        from pi_cowork.db import get_db

        db = get_db()
        cols = db.execute("PRAGMA table_info(tickets)").fetchall()
        col_names = [c[1] for c in cols]
        assert "branch" in col_names


# ── git_enabled on board list ──


def test_board_list_git_enabled_from_workflow(client, default_workflow, new_workflow):
    """Each board in the list includes git_enabled from its workflow."""
    # Create a board with git-enabled workflow
    client.put(f"/api/workflows/{new_workflow['id']}", json={"git_enabled": True})
    res = client.post(
        "/api/boards",
        json={
            "name": "Git Board",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res.status_code == 201
    board_id = json.loads(res.data)["id"]

    boards = json.loads(client.get("/api/boards").data)
    git_board = [b for b in boards if b["id"] == board_id][0]
    assert git_board["git_enabled"] in (True, 1)

    # The default board should have git_enabled=False
    default_board = [b for b in boards if b["id"] != board_id][0]
    assert default_board["git_enabled"] in (False, 0)
