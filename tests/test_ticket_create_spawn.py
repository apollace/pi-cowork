"""Tests for Bug #59: agent spawn on ticket creation and board_id/workflow_id in API docs."""

import json
from unittest.mock import patch, MagicMock


class TestCreateTicketSpawnsAgent:
    """Bug #1: Creating a ticket in a status with an agent should spawn that agent."""

    def test_create_ticket_spawns_agent_when_status_has_agent(self, client, default_workflow, default_board):
        """POST /api/tickets with a status_id that has an agent should trigger agent spawn."""
        # Create an agent
        agent = client.post('/api/agents', json={
            'name': 'CreateSpawnAgent',
            'description': 'Agent that should spawn on ticket creation.',
            'workflow_id': default_workflow['id'],
        })
        aid = json.loads(agent.data)['id']

        # Create a status with that agent
        s1 = client.post('/api/statuses', json={
            'name': 'AutoSpawnStatus',
            'sort_order': 1,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        # Create a ticket directly in that status
        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            res = client.post('/api/tickets', json={
                'title': 'AutoSpawn Ticket',
                'body': 'Should trigger agent on creation',
                'board_id': default_board['id'],
                'status_id': sid,
            })

        assert res.status_code == 201
        assert captured_cmd, "Agent should have been spawned on ticket creation"

        context_msg = captured_cmd[-1]
        assert 'AutoSpawn Ticket' in context_msg
        assert 'AutoSpawnStatus' in context_msg

    def test_create_ticket_no_spawn_when_status_has_no_agent(self, client, default_board, default_workflow):
        """POST /api/tickets in a status with no agent should NOT trigger spawn."""
        # Create a status with no agent
        s1 = client.post('/api/statuses', json={
            'name': 'NoAgentStatus',
            'sort_order': 1,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        with patch('app.subprocess.Popen') as mock_popen:
            res = client.post('/api/tickets', json={
                'title': 'NoSpawn Ticket',
                'board_id': default_board['id'],
                'status_id': sid,
            })

        assert res.status_code == 201
        assert not mock_popen.called, "No agent should be spawned when status has no agent"

    def test_create_ticket_default_status_no_agent_no_spawn(self, client, default_board):
        """POST /api/tickets without status_id goes to default (Backlog, no agent) — no spawn."""
        with patch('app.subprocess.Popen') as mock_popen:
            res = client.post('/api/tickets', json={
                'title': 'Default Status Ticket',
                'board_id': default_board['id'],
            })

        assert res.status_code == 201
        assert not mock_popen.called, "No agent should be spawned for default Backlog status"

    def test_create_ticket_with_agent_in_default_status(self, client, default_workflow, default_board):
        """POST /api/tickets with default status that has an agent should spawn."""
        # Create an agent
        agent = client.post('/api/agents', json={
            'name': 'DefaultSpawnAgent',
            'description': 'Agent in default status.',
            'workflow_id': default_workflow['id'],
        })
        aid = json.loads(agent.data)['id']

        # Update Backlog (the default status) to have this agent
        statuses = json.loads(client.get(f'/api/statuses?workflow_id={default_workflow["id"]}').data)
        backlog = next(s for s in statuses if s.get('is_default'))
        backlog_id = backlog['id']

        client.put(f'/api/statuses/{backlog_id}', json={
            'agent_id': aid,
        })

        # Create ticket without specifying status_id (defaults to Backlog)
        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            res = client.post('/api/tickets', json={
                'title': 'Default Agent Ticket',
                'board_id': default_board['id'],
            })

        assert res.status_code == 201
        assert captured_cmd, "Agent should be spawned even with default status"

    def test_create_ticket_spawn_uses_full_context(self, client, default_workflow, default_board):
        """The spawned agent on create should get a full ticket context (board_name, workflow_id)."""
        agent = client.post('/api/agents', json={
            'name': 'ContextCheckAgent',
            'description': 'Check context.',
            'workflow_id': default_workflow['id'],
        })
        aid = json.loads(agent.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'ContextCheckStatus',
            'sort_order': 1,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            res = client.post('/api/tickets', json={
                'title': 'Context Ticket',
                'body': 'Check the context details',
                'board_id': default_board['id'],
                'status_id': sid,
            })

        assert res.status_code == 201
        context_msg = captured_cmd[-1]
        # Should include board context like update path does
        assert f'board_id={default_board["id"]}' in context_msg
        assert default_board['name'] in context_msg

    def test_create_ticket_spawn_with_labels(self, client, default_workflow, default_board):
        """Creating a ticket with labels and an agent should spawn and return labels."""
        agent = client.post('/api/agents', json={
            'name': 'LabelSpawnAgent',
            'description': 'Agent with labels.',
            'workflow_id': default_workflow['id'],
        })
        aid = json.loads(agent.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'LabelSpawnStatus',
            'sort_order': 1,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        # Create a label
        label = client.post('/api/labels', json={
            'name': 'TestLabel',
            'color': '#ff0000',
            'workflow_id': default_workflow['id'],
        })
        label_id = json.loads(label.data)['id']

        captured_cmd = []
        def capture_popen(cmd, **kwargs):
            class FakeProc:
                pid = 9999
            captured_cmd[:] = cmd
            return FakeProc()

        with patch('app.subprocess.Popen', side_effect=capture_popen):
            res = client.post('/api/tickets', json={
                'title': 'Label Ticket',
                'board_id': default_board['id'],
                'status_id': sid,
                'labels': [label_id],
            })

        assert res.status_code == 201
        data = json.loads(res.data)
        assert len(data['labels']) == 1
        assert data['labels'][0]['id'] == label_id


class TestBuildApiDocsBoardWorkflowSubstitution:
    """Bug #2: build_api_docs should substitute {board_id} and {workflow_id}."""

    def test_board_id_substitution_in_docs(self):
        """board_id parameter should replace {board_id} in endpoint URLs."""
        from pi_cowork.api_docs import build_api_docs
        result = build_api_docs(
            ['tickets_list', 'board_get', 'recurring_list'],
            ticket_id=5,
            base_url='http://localhost:5000',
            board_id=3,
        )
        assert 'board_id=3' in result
        assert '/api/boards/3' in result
        assert '{board_id}' not in result

    def test_workflow_id_substitution_in_docs(self):
        """workflow_id parameter should replace {workflow_id} in endpoint URLs."""
        from pi_cowork.api_docs import build_api_docs
        result = build_api_docs(
            ['workflow_get', 'statuses_list', 'transitions_list', 'agents_list', 'labels_list'],
            ticket_id=5,
            base_url='http://localhost:5000',
            workflow_id=7,
        )
        assert '/api/workflows/7' in result
        assert 'workflow_id=7' in result
        assert '{workflow_id}' not in result

    def test_both_board_and_workflow_substitution(self):
        """When both board_id and workflow_id provided, both should be substituted."""
        from pi_cowork.api_docs import build_api_docs
        result = build_api_docs(
            ['tickets_list', 'board_get', 'workflow_get', 'statuses_list'],
            ticket_id=10,
            base_url='http://localhost:5000',
            board_id=3,
            workflow_id=7,
        )
        assert 'board_id=3' in result
        assert '/api/boards/3' in result
        assert '/api/workflows/7' in result
        assert 'workflow_id=7' in result
        assert '{board_id}' not in result
        assert '{workflow_id}' not in result

    def test_none_board_and_workflow_leaves_empty_string(self):
        """When board_id and workflow_id are None, template vars are replaced with empty string."""
        from pi_cowork.api_docs import build_api_docs
        # This matches pre-fix behavior: the template vars would remain literal
        # Now they should be replaced with empty string
        result = build_api_docs(
            ['tickets_list', 'board_get'],
            ticket_id=5,
            base_url='http://localhost:5000',
            board_id=None,
            workflow_id=None,
        )
        # {board_id} should be replaced with empty string, not left as literal
        assert '{board_id}' not in result
        # The URLs will have empty values (e.g., ?board_id= and /api/boards/)
        # which is acceptable for the default 3 endpoints that don't use these vars

    def test_default_endpoints_unaffected_by_missing_params(self):
        """Default 3 endpoints don't use {board_id} or {workflow_id}, so missing params don't matter."""
        from pi_cowork.api_docs import build_api_docs, DEFAULT_ENDPOINT_KEYS
        result = build_api_docs(
            DEFAULT_ENDPOINT_KEYS,
            ticket_id=42,
            base_url='http://localhost:5000',
        )
        # Default endpoints only have {base_url} and {ticket_id}, not {board_id}/{workflow_id}
        assert '/api/tickets/42' in result
        assert '{board_id}' not in result
        assert '{workflow_id}' not in result

    def test_spawn_agent_passes_board_and_workflow(self, client, default_workflow, default_board):
        """When an agent is spawned, build_api_docs should receive board_id and workflow_id."""
        agent = client.post('/api/agents', json={
            'name': 'BoardWorkflowAgent',
            'description': 'Agent with board/workflow docs.',
            'workflow_id': default_workflow['id'],
            'api_endpoints': ['ticket_put', 'tickets_list', 'board_get', 'statuses_list'],
        })
        aid = json.loads(agent.data)['id']

        s1 = client.post('/api/statuses', json={
            'name': 'DocsStatus',
            'sort_order': 1,
            'agent_id': aid,
            'workflow_id': default_workflow['id'],
        })
        sid = json.loads(s1.data)['id']

        ticket = client.post('/api/tickets', json={
            'title': 'Docs Ticket',
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
        context_msg = captured_cmd[-1]
        # The endpoint URLs should have actual board_id and workflow_id substituted
        assert f'board_id={default_board["id"]}' in context_msg
        assert f'/api/boards/{default_board["id"]}' in context_msg or '/api/boards/' in context_msg
        assert '{board_id}' not in context_msg
        assert '{workflow_id}' not in context_msg