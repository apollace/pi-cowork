"""Tests for the API docs registry, build_api_docs(), and agent API endpoints field."""

import json
from unittest.mock import patch

from pi_cowork.api_docs import (
    ENDPOINT_REGISTRY,
    DEFAULT_ENDPOINT_KEYS,
    build_api_docs,
    build_assistant_api_docs,
    _REGISTRY_MAP,
    AGENT_RESTRICTED_KEYS,
)


# ---------------------------------------------------------------------------
# Registry structural tests
# ---------------------------------------------------------------------------

class TestEndpointRegistry:
    """Validate the ENDPOINT_REGISTRY data structure."""

    def test_registry_is_list_of_dicts(self):
        assert isinstance(ENDPOINT_REGISTRY, list)
        for entry in ENDPOINT_REGISTRY:
            assert isinstance(entry, dict)

    def test_every_entry_has_required_keys(self):
        required = {"key", "category", "method", "path_template", "label", "doc_lines"}
        for entry in ENDPOINT_REGISTRY:
            assert required.issubset(entry.keys()), f"Missing keys in {entry}"

    def test_keys_are_unique(self):
        keys = [e["key"] for e in ENDPOINT_REGISTRY]
        assert len(keys) == len(set(keys)), "Duplicate keys in ENDPOINT_REGISTRY"

    def test_registry_map_matches_registry(self):
        assert set(_REGISTRY_MAP.keys()) == {e["key"] for e in ENDPOINT_REGISTRY}

    def test_default_keys_all_exist_in_registry(self):
        for key in DEFAULT_ENDPOINT_KEYS:
            assert key in _REGISTRY_MAP, f"Default key '{key}' not in registry"

    def test_registry_size(self):
        # The plan says ~30-35 endpoints; we should have at least the default 3
        assert len(ENDPOINT_REGISTRY) >= 3

    def test_doc_lines_are_format_strings(self):
        """doc_lines must contain {base_url} or {ticket_id} placeholders, or be static."""
        for entry in ENDPOINT_REGISTRY:
            for line in entry["doc_lines"]:
                assert isinstance(line, str)


# ---------------------------------------------------------------------------
# build_api_docs() tests
# ---------------------------------------------------------------------------

class TestBuildApiDocs:
    """Test the build_api_docs function."""

    def test_default_keys_produces_docs(self):
        result = build_api_docs(None, ticket_id=42)
        assert "PUT" in result
        assert "/api/tickets/42" in result
        assert "If anything is ambiguous" in result

    def test_empty_list_uses_defaults(self):
        result = build_api_docs([], ticket_id=42)
        # Empty list should fall back to defaults
        assert "PUT" in result
        assert "/api/tickets/42" in result

    def test_custom_endpoint_selection(self):
        result = build_api_docs(["ticket_comments_get", "boards_list"], ticket_id=99)
        assert "GET" in result
        assert "/api/tickets/99/comments" in result
        assert "/api/boards" in result

    def test_has_gates_adds_note(self):
        result_without = build_api_docs(DEFAULT_ENDPOINT_KEYS, ticket_id=1, has_gates=False)
        result_with = build_api_docs(DEFAULT_ENDPOINT_KEYS, ticket_id=1, has_gates=True)
        assert "gate_pending" not in result_without
        assert "gate_pending" in result_with

    def test_has_gates_only_on_ticket_put(self):
        """The gate_pending note should only appear on the PUT ticket line."""
        result = build_api_docs(
            ["ticket_put", "ticket_comments_post", "boards_list"],
            ticket_id=1,
            has_gates=True,
        )
        lines = result.split("\n")
        put_line = [l for l in lines if "PUT" in l and "/api/tickets/1" in l]
        boards_line = [l for l in lines if "/api/boards" in l]
        assert len(put_line) == 1
        assert "gate_pending" in put_line[0]
        assert len(boards_line) == 1
        assert "gate_pending" not in boards_line[0]

    def test_custom_base_url(self):
        result = build_api_docs(["ticket_put"], ticket_id=5, base_url="https://example.com")
        assert "https://example.com/api/tickets/5" in result

    def test_unknown_key_is_skipped(self):
        result = build_api_docs(["ticket_put", "nonexistent_key"], ticket_id=1)
        assert "/api/tickets/1" in result
        # Unknown key should be silently skipped
        assert "nonexistent" not in result

    def test_closing_line_always_present(self):
        result = build_api_docs(["ticket_put"], ticket_id=1)
        assert result.endswith(
            "If anything is ambiguous or missing, ask clarifying questions before proceeding."
        )

    def test_default_three_endpoints(self):
        """Default should include exactly ticket_put, ticket_comments_post, ticket_questions_post."""
        result = build_api_docs(DEFAULT_ENDPOINT_KEYS, ticket_id=10)
        assert "PUT" in result
        assert "/api/tickets/10/comments" in result
        assert "/api/tickets/10/questions" in result
        assert "ALWAYS provide the options field" in result

    def test_ticket_id_substitution(self):
        result = build_api_docs(["ticket_get"], ticket_id=999)
        assert "/api/tickets/999" in result
        assert "{ticket_id}" not in result

    def test_base_url_substitution(self):
        result = build_api_docs(["boards_list"], ticket_id=1, base_url="http://myhost:8080")
        assert "http://myhost:8080/api/boards" in result
        assert "{base_url}" not in result


# ---------------------------------------------------------------------------
# Agent CRUD API tests for api_endpoints field
# ---------------------------------------------------------------------------

class TestAgentApiEndpoints:
    """Test creating and updating agents with the api_endpoints field."""

    def test_create_agent_with_api_endpoints(self, client, default_workflow):
        keys = ["ticket_put", "ticket_comments_get", "boards_list"]
        res = client.post('/api/agents', json={
            'name': 'EpAgent',
            'description': 'Agent with endpoints',
            'workflow_id': default_workflow['id'],
            'api_endpoints': keys,
        })
        assert res.status_code == 201
        data = json.loads(res.data)
        agent_id = data['id']
        # Fetch back and verify
        res2 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res2.data)
        stored = json.loads(agent['api_endpoints'])
        assert set(stored) == set(keys)

    def test_create_agent_with_null_api_endpoints(self, client, default_workflow):
        res = client.post('/api/agents', json={
            'name': 'NullEpAgent',
            'description': 'Agent with null endpoints',
            'workflow_id': default_workflow['id'],
            'api_endpoints': None,
        })
        assert res.status_code == 201
        data = json.loads(res.data)
        agent_id = data['id']
        res2 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res2.data)
        assert agent['api_endpoints'] is None

    def test_create_agent_without_api_endpoints_uses_null(self, client, default_workflow):
        """Omitting api_endpoints should store NULL (defaults)."""
        res = client.post('/api/agents', json={
            'name': 'NoEpAgent',
            'description': 'Agent without endpoints field',
            'workflow_id': default_workflow['id'],
        })
        assert res.status_code == 201
        data = json.loads(res.data)
        agent_id = data['id']
        res2 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res2.data)
        assert agent['api_endpoints'] is None

    def test_create_agent_with_invalid_endpoint_key(self, client, default_workflow):
        res = client.post('/api/agents', json={
            'name': 'BadEpAgent',
            'description': 'Agent with bad endpoint key',
            'workflow_id': default_workflow['id'],
            'api_endpoints': ['ticket_put', 'not_a_real_key'],
        })
        assert res.status_code == 400
        assert 'Unknown endpoint key' in json.loads(res.data)['error']

    def test_create_agent_with_non_list_api_endpoints(self, client, default_workflow):
        res = client.post('/api/agents', json={
            'name': 'BadTypeAgent',
            'description': 'Agent with string endpoints',
            'workflow_id': default_workflow['id'],
            'api_endpoints': 'ticket_put',
        })
        assert res.status_code == 400
        assert 'must be a list' in json.loads(res.data)['error']

    def test_update_agent_api_endpoints(self, client, default_workflow):
        res = client.post('/api/agents', json={
            'name': 'UpdEpAgent',
            'description': 'Agent to update',
            'workflow_id': default_workflow['id'],
        })
        agent_id = json.loads(res.data)['id']

        new_keys = ["ticket_get", "ticket_comments_post"]
        res2 = client.put(f'/api/agents/{agent_id}', json={
            'api_endpoints': new_keys,
        })
        assert res2.status_code == 200

        res3 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res3.data)
        stored = json.loads(agent['api_endpoints'])
        assert stored == new_keys

    def test_update_agent_api_endpoints_to_null(self, client, default_workflow):
        """Setting api_endpoints to null should clear it (use defaults)."""
        res = client.post('/api/agents', json={
            'name': 'ClearEpAgent',
            'description': 'Agent to clear endpoints',
            'workflow_id': default_workflow['id'],
            'api_endpoints': ['ticket_put'],
        })
        agent_id = json.loads(res.data)['id']

        res2 = client.put(f'/api/agents/{agent_id}', json={
            'api_endpoints': None,
        })
        assert res2.status_code == 200

        res3 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res3.data)
        assert agent['api_endpoints'] is None

    def test_update_agent_without_api_endpoints_unchanged(self, client, default_workflow):
        """Updating agent without sending api_endpoints should not change it."""
        res = client.post('/api/agents', json={
            'name': 'PreserveEpAgent',
            'description': 'Agent to preserve endpoints',
            'workflow_id': default_workflow['id'],
            'api_endpoints': ['ticket_put', 'boards_list'],
        })
        agent_id = json.loads(res.data)['id']

        res2 = client.put(f'/api/agents/{agent_id}', json={
            'name': 'PreserveEpAgentRenamed',
        })
        assert res2.status_code == 200

        res3 = client.get(f'/api/agents/{agent_id}')
        agent = json.loads(res3.data)
        stored = json.loads(agent['api_endpoints'])
        assert set(stored) == {'ticket_put', 'boards_list'}


# ---------------------------------------------------------------------------
# Endpoint registry API tests
# ---------------------------------------------------------------------------

class TestEndpointRegistryApi:
    """Test the GET /api/endpoint-registry endpoint."""

    def test_endpoint_registry_returns_ok(self, client):
        res = client.get('/api/endpoint-registry')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert 'endpoints' in data
        assert isinstance(data['endpoints'], list)

    def test_endpoint_registry_has_required_fields(self, client):
        res = client.get('/api/endpoint-registry')
        data = json.loads(res.data)
        required = {"key", "category", "method", "path_template", "label"}
        for entry in data['endpoints']:
            assert required.issubset(entry.keys())

    def test_endpoint_registry_includes_default_keys(self, client):
        res = client.get('/api/endpoint-registry')
        data = json.loads(res.data)
        keys = {e['key'] for e in data['endpoints']}
        for key in DEFAULT_ENDPOINT_KEYS:
            assert key in keys

    def test_endpoint_registry_grouped_correctly(self, client):
        res = client.get('/api/endpoint-registry')
        data = json.loads(res.data)
        # Should have multiple categories
        categories = {e['category'] for e in data['endpoints']}
        assert 'Tickets' in categories
        assert 'Comments' in categories


# ---------------------------------------------------------------------------
# Agent spawn with custom api_endpoints
# ---------------------------------------------------------------------------

class TestAgentSpawnWithApiEndpoints:
    """Test that spawn_agent uses agent's api_endpoints for the API docs section."""

    def test_spawn_with_default_endpoints(self, client, default_workflow, default_board):
        """Agent with NULL api_endpoints uses the default 3 endpoints in prompt."""
        from unittest.mock import patch

        # Create an agent without api_endpoints (NULL -> defaults)
        res = client.post('/api/agents', json={
            'name': 'DefaultEpSpawnAgent',
            'description': 'You are a default agent.',
            'workflow_id': default_workflow['id'],
        })
        assert res.status_code == 201
        aid = json.loads(res.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'DefaultEpStage',
            'sort_order': 900,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        ticket = client.post('/api/tickets', json={
            'title': 'Default EP Ticket',
            'body': 'test default endpoints',
            'board_id': default_board['id'],
        })
        tid = json.loads(ticket.data)['id']

        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            client.put(f'/api/tickets/{tid}', json={'status_id': sid})

        assert captured_cmd
        context = captured_cmd[-1]
        # Should contain default endpoints: PUT ticket, POST comments, POST questions
        assert 'PUT' in context
        assert '/api/tickets/' in context
        assert 'comments' in context
        assert 'questions' in context
        # Should NOT contain non-default endpoints like boards
        assert '/api/boards' not in context

    def test_spawn_with_custom_endpoints(self, client, default_workflow, default_board):
        """Agent with custom api_endpoints only gets those in the prompt."""
        from unittest.mock import patch

        # Create an agent with custom endpoints
        res = client.post('/api/agents', json={
            'name': 'CustomEpSpawnAgent',
            'description': 'You are a custom agent.',
            'workflow_id': default_workflow['id'],
            'api_endpoints': ['ticket_put', 'ticket_get', 'boards_list'],
        })
        assert res.status_code == 201
        aid = json.loads(res.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'CustomEpStage',
            'sort_order': 901,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        ticket = client.post('/api/tickets', json={
            'title': 'Custom EP Ticket',
            'body': 'test custom endpoints',
            'board_id': default_board['id'],
        })
        tid = json.loads(ticket.data)['id']

        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9998
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            client.put(f'/api/tickets/{tid}', json={'status_id': sid})

        assert captured_cmd
        context = captured_cmd[-1]
        # Should contain selected endpoints: PUT ticket, GET ticket, GET boards
        assert '/api/boards' in context
        # Should NOT contain comments or questions (not selected)
        assert '/comments' not in context
        assert '/questions' not in context

    def test_spawn_default_endpoints_include_gate_note(self, client, default_workflow, default_board):
        """When gates exist, the default endpoints prompt includes gate_pending note."""
        from unittest.mock import patch

        res = client.post('/api/agents', json={
            'name': 'GateEpSpawnAgent',
            'description': 'You are a gate agent.',
            'workflow_id': default_workflow['id'],
        })
        aid = json.loads(res.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'GateEpFrom',
            'sort_order': 910,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        from_id = json.loads(s1.data)['id']

        s2 = client.post('/api/statuses', json={
            'name': 'GateEpTo',
            'sort_order': 911,
            'workflow_id': default_workflow['id'],
        })
        to_id = json.loads(s2.data)['id']

        # Create a transition (gates exist on transitions)
        client.post('/api/transitions', json={
            'from_status_id': from_id,
            'to_status_id': to_id,
            'instructions': 'Move when ready.',
            'workflow_id': default_workflow['id'],
        })

        # Add a quality gate on this transition
        client.post('/api/quality_gates', json={
            'name': 'Test Gate',
            'from_status_id': from_id,
            'to_status_id': to_id,
            'gate_type': 'manual',
            'workflow_id': default_workflow['id'],
        })

        ticket = client.post('/api/tickets', json={
            'title': 'Gate EP Ticket',
            'body': 'test gate note',
            'board_id': default_board['id'],
        })
        tid = json.loads(ticket.data)['id']

        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9997
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            client.put(f'/api/tickets/{tid}', json={'status_id': from_id})

        assert captured_cmd
        context = captured_cmd[-1]
        # Should contain gate_pending note in PUT line
        assert 'gate_pending' in context


class TestAgentRestrictedKeys:
    """Ensure that gate review and other restricted endpoints are never exposed to agents."""

    def test_restricted_keys_are_excluded_from_default_docs(self):
        """Default endpoint list should never include restricted keys."""
        docs = build_api_docs(None, ticket_id=1, base_url='http://localhost:5000')
        for key in AGENT_RESTRICTED_KEYS:
            entry = _REGISTRY_MAP.get(key)
            assert entry is not None, f"Restricted key '{key}' not found in registry"
            for line in entry['doc_lines']:
                assert line not in docs, f"Restricted endpoint '{key}' leaked into default docs"

    def test_restricted_keys_filtered_even_if_explicitly_requested(self):
        """Even if someone configures agent with restricted keys, they must be filtered out."""
        # Include a restricted key in the selected list
        all_keys = list(DEFAULT_ENDPOINT_KEYS) + list(AGENT_RESTRICTED_KEYS) + ['ticket_comments_get']
        docs = build_api_docs(all_keys, ticket_id=1, base_url='http://localhost:5000')
        for key in AGENT_RESTRICTED_KEYS:
            entry = _REGISTRY_MAP.get(key)
            for line in entry['doc_lines']:
                assert line not in docs, f"Restricted endpoint '{key}' should be filtered out but appeared in docs"

    def test_gate_reviews_not_in_docs(self):
        """Specifically verify gate_reviews_list is filtered out."""
        docs = build_api_docs(['gate_reviews_list'], ticket_id=1, base_url='http://localhost:5000')
        assert 'gate_reviews' not in docs

    def test_restricted_keys_defined(self):
        """AGENT_RESTRICTED_KEYS should contain at least gate_reviews_list."""
        assert 'gate_reviews_list' in AGENT_RESTRICTED_KEYS


# ---------------------------------------------------------------------------
# build_assistant_api_docs() tests
# ---------------------------------------------------------------------------

class TestBuildAssistantApiDocs:
    """Test the build_assistant_api_docs function."""

    def test_null_uses_all_endpoints(self):
        result = build_assistant_api_docs(None)
        assert result.startswith("## API Documentation")
        # Should contain at least one endpoint from each major category
        assert "PUT" in result
        assert "GET" in result
        assert "/api/tickets/{ticket_id}" in result
        assert "/api/boards" in result

    def test_empty_list_uses_all_endpoints(self):
        result = build_assistant_api_docs([])
        assert "## API Documentation" in result
        assert "/api/tickets/{ticket_id}" in result
        assert "/api/boards" in result

    def test_custom_keys(self):
        result = build_assistant_api_docs(["ticket_put", "boards_list"])
        assert "PUT" in result
        assert "/api/boards" in result
        # Should not contain unselected endpoints
        assert "/api/tickets/{ticket_id}/comments" not in result
        assert "/api/tickets/{ticket_id}/questions" not in result

    def test_literal_template_variables(self):
        """ticket_id, board_id, workflow_id must remain literal placeholders."""
        result = build_assistant_api_docs(["ticket_put", "board_get", "workflow_get"])
        assert "{ticket_id}" in result
        assert "{board_id}" in result
        assert "{workflow_id}" in result

    def test_base_url_substitution(self):
        result = build_assistant_api_docs(["ticket_put"], base_url="https://example.com")
        assert "https://example.com/api/tickets/{ticket_id}" in result
        assert "{base_url}" not in result

    def test_unknown_key_is_skipped(self):
        result = build_assistant_api_docs(["ticket_put", "not_a_real_key"])
        assert "/api/tickets/{ticket_id}" in result
        assert "not_a_real_key" not in result

    def test_no_agent_advisory_lines(self):
        """Assistant docs must not contain the gate_pending or IMPORTANT warnings."""
        result = build_assistant_api_docs(None)
        assert "gate_pending" not in result
        assert "IMPORTANT: You must NOT call any gate review" not in result
        assert "If anything is ambiguous or missing" not in result
