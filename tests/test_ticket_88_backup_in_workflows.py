"""Ticket #88: Backup & Restore moved to Workflows page.

Tests:
- /backup route returns 404
- Nav sidebar no longer links to /backup
- Workflows page includes Import button
- import/export still works end-to-end via /api/workflows/import
"""

import json

# ── Route removal ──


def test_backup_route_returns_404(client):
    """The /backup page route has been removed entirely."""
    res = client.get("/backup")
    assert res.status_code == 404


# ── Sidebar nav ──


def test_sidebar_no_backup_link(client):
    """The sidebar should not contain a link to /backup."""
    # Any page that uses base.html will include the sidebar
    res = client.get("/workflows")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    # The nav link text and URL should be gone
    assert "/backup" not in html
    assert "Backup &amp; Restore" not in html
    assert "Backup & Restore" not in html


def test_sidebar_has_database_backup_link(client):
    """The Database Backup page link should still be present."""
    res = client.get("/workflows")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "/database-backup" in html


# ── Workflows page Import UI ──


def test_workflows_page_has_import_button(client):
    """The Workflows page should include an Import button."""
    res = client.get("/workflows")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "showImportWorkflow" in html
    assert "import-wf-modal" in html


def test_workflows_page_has_import_modal(client):
    """The Workflows page should include the import modal with file input."""
    res = client.get("/workflows")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "import-wf-modal" in html
    assert "import-file" in html
    assert "import-wf-form" in html
    assert "hideImportWorkflow" in html


def test_workflows_page_still_has_export_button(client, default_workflow):
    """The per-workflow export button (📥) should still exist on the Workflows page."""
    res = client.get("/workflows")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "exportWorkflow" in html


# ── Import API still works ──


def test_import_api_still_works(client):
    """The /api/workflows/import endpoint should still work after removing the backup page."""
    workflow_json = {
        "version": "1.0",
        "name": "Post-Removal Import Test",
        "description": "Import still works",
        "agents": [],
        "statuses": [
            {
                "name": "Start",
                "sort_order": 1,
                "is_default": True,
                "is_terminal": False,
                "agent_name": None,
                "goal": None,
            }
        ],
        "transitions": [],
    }
    res = client.post("/api/workflows/import", json=workflow_json)
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert data["workflow_id"]


def test_export_api_still_works(client, default_workflow):
    """The /api/workflows/<id>/export endpoint should still work."""
    res = client.get(f"/api/workflows/{default_workflow['id']}/export")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["version"] == "1.0"
    assert data["name"] == default_workflow["name"]


# ── Other pages unaffected ──


def test_database_backup_page_still_works(client):
    """The Database Backup page should be unaffected."""
    res = client.get("/database-backup")
    assert res.status_code == 200
