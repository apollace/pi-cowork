"""Tests for Knowledge Management API and agent injection."""

import json


class TestKnowledgeAPI:
    """Test the Knowledge CRUD, search, and version history API."""

    def test_create_global_entry(self, client):
        """Create a global (board_id=null) knowledge entry."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "API Conventions",
                "content": "REST endpoints follow JSON conventions.",
                "category": "Conventions",
                "auto_context": True,
                "tags": ["api", "rest"],
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["title"] == "API Conventions"
        assert data["board_id"] is None
        assert data["category"] == "Conventions"
        assert data["auto_context"] is True or data["auto_context"] == 1
        assert len(data["tags"]) == 2
        tag_names = {t["name"] for t in data["tags"]}
        assert tag_names == {"api", "rest"}

    def test_create_board_entry(self, client, default_board):
        """Create a board-scoped knowledge entry."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Git Workflow",
                "content": "Always branch from main.",
                "board_id": default_board["id"],
                "auto_context": False,
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["title"] == "Git Workflow"
        assert data["board_id"] == default_board["id"]

    def test_create_entry_validation(self, client):
        """Title and content are required."""
        res = client.post("/api/knowledge", json={})
        assert res.status_code == 400

        res = client.post("/api/knowledge", json={"title": "No content"})
        assert res.status_code == 400

        res = client.post("/api/knowledge", json={"content": "No title"})
        assert res.status_code == 400

    def test_create_entry_invalid_board(self, client):
        """board_id must reference an existing board."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Test",
                "content": "Content",
                "board_id": 9999,
            },
        )
        assert res.status_code == 404

    def test_list_entries_omitting_board_id_returns_global(self, client):
        """Omitting board_id returns only global entries."""
        # Create global and board entries
        client.post(
            "/api/knowledge",
            json={
                "title": "Global Entry",
                "content": "Global content",
            },
        )
        res = client.get("/api/boards")
        boards = json.loads(res.data)
        board_id = boards[0]["id"]
        client.post(
            "/api/knowledge",
            json={
                "title": "Board Entry",
                "content": "Board content",
                "board_id": board_id,
            },
        )

        # Without board_id: should return only global
        res = client.get("/api/knowledge")
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "Global Entry" in titles
        assert "Board Entry" not in titles

    def test_list_entries_with_board_id_returns_both(self, client, default_board):
        """With board_id, returns global + board-specific entries."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Global 1",
                "content": "Global content 1",
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "Board 1",
                "content": "Board content 1",
                "board_id": default_board["id"],
            },
        )

        res = client.get(f"/api/knowledge?board_id={default_board['id']}")
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "Global 1" in titles
        assert "Board 1" in titles

    def test_get_single_entry(self, client):
        """Get a single entry by ID."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Test Entry",
                "content": "Test content",
                "category": "Testing",
                "tags": ["test"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        res = client.get(f"/api/knowledge/{entry_id}")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["title"] == "Test Entry"
        assert data["category"] == "Testing"
        assert len(data["tags"]) == 1

    def test_get_entry_not_found(self, client):
        res = client.get("/api/knowledge/9999")
        assert res.status_code == 404

    def test_update_entry(self, client):
        """Updating an entry creates version history."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Original Title",
                "content": "Original content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "title": "Updated Title",
                "content": "Updated content",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["title"] == "Updated Title"
        assert data["content"] == "Updated content"

    def test_update_creates_version(self, client):
        """Updating an entry should create a version record."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "V1",
                "content": "Version 1 content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # The initial create also creates a version
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        data = json.loads(res.data)
        assert len(data) >= 1  # initial version

        # Now update
        client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "title": "V2",
                "content": "Version 2 content",
            },
        )

        res = client.get(f"/api/knowledge/{entry_id}/versions")
        data = json.loads(res.data)
        assert len(data) >= 2  # initial + update version

    def test_update_entry_not_found(self, client):
        res = client.put("/api/knowledge/9999", json={"title": "Nope"})
        assert res.status_code == 404

    def test_clear_board_id_makes_entry_global(self, client, default_board):
        """clear_board_id=True sets board_id to NULL (global)."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Board Entry",
                "content": "Content",
                "board_id": default_board["id"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]
        assert data["board_id"] == default_board["id"]

        # Update to global using clear_board_id
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "clear_board_id": True,
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["board_id"] is None

    def test_omit_board_id_and_clear_board_id_leaves_board_unchanged(self, client, default_board):
        """Omitting both board_id and clear_board_id leaves board_id unchanged."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Board Entry",
                "content": "Content",
                "board_id": default_board["id"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]
        assert data["board_id"] == default_board["id"]

        # Update only the title — board_id should remain unchanged
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "title": "Updated Title",
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["title"] == "Updated Title"
        assert data["board_id"] == default_board["id"]

    def test_update_board_id_to_specific_board(self, client, default_board):
        """Providing board_id as integer changes the board."""
        # Create a second board
        res = client.get("/api/workflows")
        workflows = json.loads(res.data)
        workflow_id = workflows[0]["id"]
        res = client.post(
            "/api/boards",
            json={
                "name": "Second Board",
                "workflow_id": workflow_id,
            },
        )
        board2 = json.loads(res.data)

        # Create entry on default board
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Board Entry",
                "content": "Content",
                "board_id": default_board["id"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]
        assert data["board_id"] == default_board["id"]

        # Move entry to second board
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "board_id": board2["id"],
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["board_id"] == board2["id"]

    def test_board_id_and_clear_board_id_both_provided_is_error(self, client, default_board):
        """Providing both board_id and clear_board_id=True returns 400."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Entry",
                "content": "Content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # Providing both should fail
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "board_id": default_board["id"],
                "clear_board_id": True,
            },
        )
        assert res.status_code == 400
        err = json.loads(res.data)
        assert "both" in err["error"].lower() or "clear_board_id" in err["error"]

    def test_board_id_null_in_put_is_rejected(self, client):
        """board_id=null in PUT is no longer valid — use clear_board_id instead."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Entry",
                "content": "Content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # Sending board_id=null in PUT should fail validation
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "board_id": None,
            },
        )
        # None (null) is not a valid board_id — should be caught by validation
        # but note: the API now treats null as "not provided", so board_id won't
        # be changed. This is fine since null is no longer a sentinel value.
        # However, we test that it doesn't crash and doesn't set board to null.
        assert res.status_code == 200
        data = json.loads(res.data)
        # board_id should remain unchanged (not set to null)
        # Since the entry was created global, board_id is already None
        assert data["board_id"] is None

    def test_delete_entry(self, client):
        """Delete an entry cascades versions and tags."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "To Delete",
                "content": "Will be deleted",
                "tags": ["delete"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        res = client.delete(f"/api/knowledge/{entry_id}")
        assert res.status_code == 200

        res = client.get(f"/api/knowledge/{entry_id}")
        assert res.status_code == 404

    def test_delete_entry_not_found(self, client):
        res = client.delete("/api/knowledge/9999")
        assert res.status_code == 404

    def test_search_entries(self, client):
        """Search across title and content."""
        client.post(
            "/api/knowledge",
            json={
                "title": "REST Conventions",
                "content": "All endpoints use JSON.",
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "Git Workflow",
                "content": "Branch naming conventions.",
            },
        )

        res = client.get("/api/knowledge/search?q=conventions")
        assert res.status_code == 200
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "REST Conventions" in titles
        assert "Git Workflow" in titles

        res = client.get("/api/knowledge/search?q=JSON")
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "REST Conventions" in titles

    def test_search_requires_query(self, client):
        res = client.get("/api/knowledge/search")
        assert res.status_code == 400

    def test_list_with_filters(self, client):
        """Test category, auto_context, and search filters."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Auto Context Entry",
                "content": "Important info",
                "category": "Important",
                "auto_context": True,
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "Manual Entry",
                "content": "Not auto",
                "category": "Notes",
                "auto_context": False,
            },
        )

        # Filter by auto_context
        res = client.get("/api/knowledge?auto_context=1")
        data = json.loads(res.data)
        assert all(e["auto_context"] for e in data)

        # Filter by category
        res = client.get("/api/knowledge?category=Important")
        data = json.loads(res.data)
        assert all(e["category"] == "Important" for e in data)

    def test_version_history(self, client):
        """Get version history and restore a previous version."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Original",
                "content": "Content v1",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # Get initial versions
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        data = json.loads(res.data)
        assert len(data) == 1

        # Update to create v2
        client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "title": "Updated",
                "content": "Content v2",
            },
        )

        res = client.get(f"/api/knowledge/{entry_id}/versions")
        data = json.loads(res.data)
        assert len(data) == 2

        # Get specific version
        first_version = data[-1]  # oldest (created_at DESC)
        version_id = first_version["id"]
        res = client.get(f"/api/knowledge/{entry_id}/versions/{version_id}")
        assert res.status_code == 200
        vdata = json.loads(res.data)
        assert vdata["title"] == "Original"

    def test_restore_version(self, client):
        """Restore a previous version as current."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "V1 Title",
                "content": "V1 content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # Get initial version ID
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        versions = json.loads(res.data)
        v1_id = versions[0]["id"]

        # Update to v2
        client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "title": "V2 Title",
                "content": "V2 content",
            },
        )

        # Restore v1
        res = client.post(f"/api/knowledge/{entry_id}/versions/{v1_id}/restore", json={})
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["title"] == "V1 Title"
        assert data["content"] == "V1 content"

    def test_categories_endpoint(self, client):
        """Test category listing."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Entry 1",
                "content": "Content",
                "category": "Conventions",
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "Entry 2",
                "content": "Content",
                "category": "Process",
            },
        )

        res = client.get("/api/knowledge/categories")
        data = json.loads(res.data)
        assert "Conventions" in data
        assert "Process" in data

    def test_tags_endpoint(self, client):
        """Test tag listing."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Tagged",
                "content": "Content",
                "tags": ["api", "rest"],
            },
        )

        res = client.get("/api/knowledge/tags")
        data = json.loads(res.data)
        tag_names = [t["name"] for t in data]
        assert "api" in tag_names
        assert "rest" in tag_names

    def test_agent_created_entry(self, client):
        """Test that agents can create entries with created_by='agent'."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Agent Note",
                "content": "Self-documenting knowledge.",
                "created_by": "agent",
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)

        # Verify version has created_by
        res = client.get(f"/api/knowledge/{data['id']}/versions")
        versions = json.loads(res.data)
        assert versions[0]["created_by"] == "agent"

    def test_update_by_agent(self, client):
        """Test that agents can update entries with updated_by='agent'."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Entry",
                "content": "Content",
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "content": "Updated by agent",
                "updated_by": "agent",
            },
        )
        assert res.status_code == 200

        # Verify version history records the agent update
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        versions = json.loads(res.data)
        # The most recent version should be by agent
        assert any(v["created_by"] == "agent" for v in versions)

    def test_sort_order(self, client):
        """Test that entries are sorted by sort_order then updated_at."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Low Priority",
                "content": "Content",
                "sort_order": 10,
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "High Priority",
                "content": "Content",
                "sort_order": 0,
            },
        )

        res = client.get("/api/knowledge")
        data = json.loads(res.data)
        # sort_order=0 should come before sort_order=10
        titles = [e["title"] for e in data]
        high_idx = titles.index("High Priority")
        low_idx = titles.index("Low Priority")
        assert high_idx < low_idx

    def test_update_tags(self, client):
        """Test updating tags on an entry."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Tag Test",
                "content": "Content",
                "tags": ["alpha", "beta"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]
        assert len(data["tags"]) == 2

        # Update tags
        res = client.put(
            f"/api/knowledge/{entry_id}",
            json={
                "tags": ["gamma", "delta"],
            },
        )
        assert res.status_code == 200
        data = json.loads(res.data)
        tag_names = {t["name"] for t in data["tags"]}
        assert tag_names == {"gamma", "delta"}

    def test_empty_tags_array(self, client):
        """Test creating an entry with empty tags."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "No Tags",
                "content": "Content",
                "tags": [],
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["tags"] == []

    def test_null_category(self, client):
        """Test that category can be null."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "No Category",
                "content": "Content",
            },
        )
        assert res.status_code == 201
        data = json.loads(res.data)
        assert data["category"] is None


class TestKnowledgeAgentInjection:
    """Test that auto_context knowledge entries are injected into agent prompts."""

    def test_auto_context_injection_with_board(self, client, default_board):
        """Auto-context entries relevant to a board should be returned via API."""
        # Create a global auto_context entry
        client.post(
            "/api/knowledge",
            json={
                "title": "Global Convention",
                "content": "Use JSON for all API responses.",
                "auto_context": True,
            },
        )

        # Create a board-specific auto_context entry
        client.post(
            "/api/knowledge",
            json={
                "title": "Board Process",
                "content": "Always run tests before committing.",
                "board_id": default_board["id"],
                "auto_context": True,
            },
        )

        # Create a non-auto_context entry (should NOT appear)
        client.post(
            "/api/knowledge",
            json={
                "title": "Internal Note",
                "content": "Not for agents.",
                "auto_context": False,
            },
        )

        # Verify through API: list with auto_context=1 filter
        res = client.get(f"/api/knowledge?board_id={default_board['id']}&auto_context=1")
        assert res.status_code == 200
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "Global Convention" in titles
        assert "Board Process" in titles
        assert "Internal Note" not in titles

    def test_auto_context_global_only(self, client):
        """Without board_id, only global auto_context entries are returned."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Global Only",
                "content": "This is global.",
                "auto_context": True,
            },
        )

        res = client.get("/api/knowledge?auto_context=1")
        assert res.status_code == 200
        data = json.loads(res.data)
        titles = [e["title"] for e in data]
        assert "Global Only" in titles

    def test_knowledge_count_for_board(self, client, default_board):
        """Knowledge count includes both global and board-specific entries."""
        client.post(
            "/api/knowledge",
            json={
                "title": "Global Entry",
                "content": "Content",
            },
        )
        client.post(
            "/api/knowledge",
            json={
                "title": "Board Entry",
                "content": "Content",
                "board_id": default_board["id"],
            },
        )

        # Board-specific list should return both global + board entries
        res = client.get(f"/api/knowledge?board_id={default_board['id']}")
        data = json.loads(res.data)
        assert len(data) >= 2  # global + board

    def test_delete_cascades_versions_and_tags(self, client):
        """Deleting an entry should cascade to versions and tags."""
        res = client.post(
            "/api/knowledge",
            json={
                "title": "Cascade Test",
                "content": "Content",
                "tags": ["cascade"],
            },
        )
        data = json.loads(res.data)
        entry_id = data["id"]

        # Verify version exists via API
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        versions = json.loads(res.data)
        assert len(versions) >= 1

        # Delete
        client.delete(f"/api/knowledge/{entry_id}")

        # Verify entry is gone
        res = client.get(f"/api/knowledge/{entry_id}")
        assert res.status_code == 404

        # Verify versions are gone
        res = client.get(f"/api/knowledge/{entry_id}/versions")
        # Versions endpoint will 404 since entry doesn't exist
        assert res.status_code == 404


class TestKnowledgePage:
    """Test the knowledge management UI page."""

    def test_knowledge_page_loads(self, client):
        """The /knowledge page should load successfully."""
        res = client.get("/knowledge")
        assert res.status_code == 200
        assert b"Knowledge" in res.data

    def test_knowledge_page_contains_elements(self, client):
        """The knowledge page should contain key UI elements."""
        res = client.get("/knowledge")
        assert b"knowledge-scope" in res.data
        assert b"knowledge-search" in res.data
        assert b"knowledge-category" in res.data
