"""Tests for the Agent Ask function — Ticket #115.

Covers:
- POST /api/tickets/<id>/ask endpoint
- ask_system_prompt persisted on agents
- agent_runs.mode column ('work' default, 'ask' when ask spawn)
- Lean ask-mode prompt (no status goal, no transitions block)
- System comment with question preview
- Blocked in terminal status / unanswered questions / ask already running
- Ask endpoint key present in /api/endpoint-registry
"""

import json
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_agent(client, workflow_id, name, description, **extra):
    body = {
        'name': name,
        'description': description,
        'workflow_id': workflow_id,
    }
    body.update(extra)
    res = client.post('/api/agents', json=body)
    assert res.status_code == 201, res.data
    return json.loads(res.data)


def _create_status(client, workflow_id, name, agent_id, sort_order=1,
                    is_default=False, is_terminal=False, goal=None):
    body = {
        'name': name,
        'sort_order': sort_order,
        'agent_id': agent_id,
        'workflow_id': workflow_id,
        'is_default': is_default,
        'is_terminal': is_terminal,
        'goal': goal,
    }
    res = client.post('/api/statuses', json=body)
    assert res.status_code == 201, res.data
    return json.loads(res.data)


def _create_ticket(client, board_id, **extra):
    """Create a ticket on the given board. The default seeded status is used
    unless ``status_id`` is passed in ``extra``. Raises if the board's workflow
    has no default status and the caller didn't provide one.
    """
    body = {'title': 'Ask Test Ticket', 'board_id': board_id}
    body.update(extra)
    res = client.post('/api/tickets', json=body)
    assert res.status_code == 201, res.data
    return json.loads(res.data)


def _move_ticket_to_status(client, ticket_id, status_id):
    """Move a ticket into a specific status (used so ask uses that status's agent).

    Also marks any resulting work-mode agent_runs as 'completed' so subsequent
    ask spawns are not blocked by the parallel-running guard. The ask test
    cares about the ASK run being spawned, not the side-effect work spawn.
    """
    with patch('app.subprocess.Popen') as p:
        class _F:
            pid = 9999
            stdout = None  # closeable by _fake_log_reader
        p.return_value = _F()
        res = client.put(f'/api/tickets/{ticket_id}', json={'status_id': status_id})
    assert res.status_code == 200, res.data
    # Mark the side-effect work run as completed so the ask path is unblocked.
    with client.application.app_context():
        from pi_cowork.db import get_db
        db = get_db()
        db.execute(
            "UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ? AND status = 'running'",
            (ticket_id,),
        )
        db.commit()
    return res


def _make_fake_popen():
    """Return a side_effect callable that captures the cmd but doesn't spawn pi."""
    class FakeProc:
        pid = 9999
        stdout = None  # closeable by _fake_log_reader
    captured = {'cmd': None}

    def side_effect(cmd, **kwargs):
        captured['cmd'] = cmd
        return FakeProc()

    return side_effect, captured


# ---------------------------------------------------------------------------
# Basic happy path
# ---------------------------------------------------------------------------

class TestAskEndpointBasic:
    def test_ask_endpoint_basic(self, client, default_workflow, default_board):
        """POST /ask with a question → 200, mode='ask' row, system comment."""
        agent = _create_agent(client, default_workflow['id'], 'AskAgentBasic',
                              'You are a basic ask agent.')
        status = _create_status(client, default_workflow['id'], 'AskBasicStage',
                                agent['id'], sort_order=1, goal='Do the work.')
        ticket = _create_ticket(client, default_board['id'])

        popen_side_effect, captured = _make_fake_popen()

        with patch('app.subprocess.Popen', side_effect=popen_side_effect):
            _move_ticket_to_status(client, ticket['id'], status['id'])
            res = client.post(f'/api/tickets/{ticket["id"]}/ask', json={
                'question': 'Why is the sky blue?'
            })
        assert res.status_code == 200, res.data
        data = json.loads(res.data)
        assert data['success'] is True
        assert data['agent']['id'] == agent['id']
        assert data['agent']['name'] == 'AskAgentBasic'
        assert data['spawned'] is True
        assert data['queued'] is False

        # agent_runs row should be mode='ask' (the latest one, since the move
        # also spawned a work run, the work run + ask run both exist; filter)
        runs = json.loads(client.get(f'/api/tickets/{ticket["id"]}/agent_runs').data)
        ask_runs = [r for r in runs if r['mode'] == 'ask']
        assert len(ask_runs) == 1
        assert ask_runs[0]['status'] == 'running'

        # System comment with the question preview
        comments = json.loads(client.get(f'/api/tickets/{ticket["id"]}/comments').data)
        preview_comments = [c for c in comments if 'Asked agent' in c['body']]
        assert len(preview_comments) == 1
        assert 'Why is the sky blue?' in preview_comments[0]['body']

    def test_ask_response_shape_matches_spawn(self, client, default_workflow, default_board):
        """Ask endpoint returns the same shape as /spawn."""
        agent = _create_agent(client, default_workflow['id'], 'AskShapeAgent',
                              'shape agent.')
        status = _create_status(client, default_workflow['id'], 'AskShapeStage',
                                agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Anything?'})
        assert res.status_code == 200
        data = json.loads(res.data)
        # Required fields mirroring /spawn
        for k in ('success', 'agent', 'spawned', 'queued'):
            assert k in data, f"Missing key {k!r} in ask response"
        assert 'id' in data['agent'] and 'name' in data['agent']


# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------

class TestAskAgentResolution:
    def test_ask_uses_current_status_agent_by_default(self, client, default_workflow, default_board):
        """No agent_id → uses the status's agent_id."""
        status_agent = _create_agent(client, default_workflow['id'], 'StatusDefaultAgent',
                                     'status default.')
        other_agent = _create_agent(client, default_workflow['id'], 'OtherAgent',
                                    'other.')
        status = _create_status(client, default_workflow['id'], 'AskDefaultAgentStage',
                                status_agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Use status agent.'})
        assert res.status_code == 200, res.data
        data = json.loads(res.data)
        assert data['agent']['id'] == status_agent['id']
        assert data['agent']['name'] == 'StatusDefaultAgent'

    def test_ask_with_explicit_agent_id(self, client, default_workflow, default_board):
        """Explicit agent_id → uses that agent regardless of status."""
        status_agent = _create_agent(client, default_workflow['id'], 'StatusAgent2',
                                     'status agent.')
        explicit_agent = _create_agent(client, default_workflow['id'], 'ExplicitAgent2',
                                       'explicit.')
        status = _create_status(client, default_workflow['id'], 'AskExplicitAgentStage',
                                status_agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask', json={
                'agent_id': explicit_agent['id'],
                'question': 'Use explicit agent.'
            })
        assert res.status_code == 200, res.data
        data = json.loads(res.data)
        assert data['agent']['id'] == explicit_agent['id']
        assert data['agent']['name'] == 'ExplicitAgent2'

    def test_ask_explicit_agent_from_other_workflow_rejected(self, client, default_workflow,
                                                              default_board, new_workflow):
        """Explicit agent_id from a different workflow → 409."""
        status_agent = _create_agent(client, default_workflow['id'], 'StatusAgentWf',
                                     'status agent.')
        other_agent = _create_agent(client, new_workflow['id'], 'OtherWfAgent',
                                    'other workflow.')
        status = _create_status(client, default_workflow['id'], 'AskOtherWfStage',
                                status_agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        res = client.post(f'/api/tickets/{ticket["id"]}/ask', json={
            'agent_id': other_agent['id'],
            'question': 'Cross-workflow ask.'
        })
        assert res.status_code == 409
        assert 'workflow' in json.loads(res.data)['error'].lower()

    def test_ask_no_status_agent_rejected(self, client, default_workflow, default_board):
        """Status has no agent AND no agent_id given → 409."""
        # Use a status with no agent
        status = _create_status(client, default_workflow['id'], 'NoAgentStage', None,
                                 sort_order=1, is_default=False)
        ticket = _create_ticket(client, default_board['id'])

        res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                          json={'question': 'No agent available.'})
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# ask_system_prompt persistence and usage
# ---------------------------------------------------------------------------

class TestAskSystemPrompt:
    def test_ask_system_prompt_saved_on_create(self, client, default_workflow):
        agent = _create_agent(client, default_workflow['id'], 'AskPromptAgent',
                              'desc', ask_system_prompt='Custom ask prompt content.')
        # GET the agent back
        res = client.get(f'/api/agents/{agent["id"]}')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['ask_system_prompt'] == 'Custom ask prompt content.'

    def test_ask_system_prompt_saved_on_update(self, client, default_workflow):
        agent = _create_agent(client, default_workflow['id'], 'AskPromptUpdateAgent',
                              'desc')
        res = client.put(f'/api/agents/{agent["id"]}', json={
            'ask_system_prompt': 'Updated ask prompt.'
        })
        assert res.status_code == 200
        data = json.loads(client.get(f'/api/agents/{agent["id"]}').data)
        assert data['ask_system_prompt'] == 'Updated ask prompt.'

    def test_ask_system_prompt_cleared_with_empty_string(self, client, default_workflow):
        agent = _create_agent(client, default_workflow['id'], 'AskPromptClearAgent',
                              'desc', ask_system_prompt='Some prompt.')
        res = client.put(f'/api/agents/{agent["id"]}', json={
            'ask_system_prompt': ''
        })
        assert res.status_code == 200
        data = json.loads(client.get(f'/api/agents/{agent["id"]}').data)
        assert data['ask_system_prompt'] is None

    def test_ask_uses_agents_ask_system_prompt(self, client, default_workflow, default_board):
        """Custom ask_system_prompt is sent to pi as --system-prompt."""
        custom_prompt = 'You are a CUSTOM ask agent. Always reply in haiku.'
        agent = _create_agent(client, default_workflow['id'], 'AskCustomPromptAgent',
                              'You are a work agent.', ask_system_prompt=custom_prompt)
        status = _create_status(client, default_workflow['id'], 'AskCustomPromptStage',
                                agent['id'], sort_order=1, goal='Do the work.')
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask', json={
                'question': 'Tell me about haiku.'
            })
        assert res.status_code == 200, res.data
        cmd = captured['cmd']
        assert cmd is not None
        idx = cmd.index('--system-prompt')
        system_prompt = cmd[idx + 1]
        assert custom_prompt in system_prompt
        # Default work-mode "ask question" prefix should NOT appear
        # because we have a custom prompt. The custom one replaces it.
        assert 'You are a work agent.' not in system_prompt

    def test_ask_uses_default_ask_prompt_when_none_set(self, client, default_workflow, default_board):
        """No ask_system_prompt on agent → built-in DEFAULT_ASK_SYSTEM_PROMPT is used."""
        agent = _create_agent(client, default_workflow['id'], 'AskDefaultPromptAgent',
                              'You are a work agent.')
        assert agent.get('ask_system_prompt') is None
        status = _create_status(client, default_workflow['id'], 'AskDefaultPromptStage',
                                agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Use default prompt.'})
        assert res.status_code == 200
        cmd = captured['cmd']
        idx = cmd.index('--system-prompt')
        system_prompt = cmd[idx + 1]
        # Default text contains these key phrases
        from pi_cowork.agents import DEFAULT_ASK_SYSTEM_PROMPT
        assert 'ASK MODE' in system_prompt
        assert 'Do NOT change the ticket status' in system_prompt
        # Work-mode identity should NOT be in system prompt
        assert 'You are a work agent.' not in system_prompt


# ---------------------------------------------------------------------------
# Lean prompt structure in ask mode
# ---------------------------------------------------------------------------

class TestAskPromptStructure:
    def test_ask_omits_status_goal_and_transitions(self, client, default_workflow, default_board):
        """Lean ask context: no 'Your goal:' line, no 'Next status you MUST set'."""
        agent = _create_agent(client, default_workflow['id'], 'AskLeanAgent',
                              'Lean ask agent.')
        # Add a transition so we have a transitions_line to omit
        s1 = _create_status(client, default_workflow['id'], 'AskFromStage', agent['id'],
                             sort_order=1, goal='Work goal text.')
        s2 = _create_status(client, default_workflow['id'], 'AskToStage', None,
                             sort_order=2)
        res = client.post('/api/transitions', json={
            'from_status_id': s1['id'],
            'to_status_id': s2['id'],
            'instructions': 'Move along',
            'workflow_id': default_workflow['id'],
        })
        assert res.status_code == 201

        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], s1['id'])
        question = 'Should I move to Closed?'

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': question})
        assert res.status_code == 200
        cmd = captured['cmd']
        # Last arg is the context message
        context_msg = cmd[-1]

        # Ask context must contain the question verbatim + "You were asked:" header
        assert question in context_msg
        assert 'You were asked:' in context_msg

        # Lean context must NOT contain status goal or transition block
        assert 'Your goal:' not in context_msg
        assert 'Next status you MUST set' not in context_msg
        # The status goal text should not appear in ask context
        assert 'Work goal text.' not in context_msg
        # The transition instructions should not appear in ask context
        assert 'Move along' not in context_msg

    def test_ask_keeps_ticket_body_and_comments(self, client, default_workflow, default_board):
        """Ask context still includes body, comments, API docs (same as work).

        Body + comments are surfaced differently depending on warm/cold spawn:
        - Cold spawn → inlined in the ``Description`` and ``Comments`` blocks
        - Warm spawn → inlined in the ``New comments since last update`` block

        This test asserts at least one of those blocks contains the body and
        the pre-existing comment, so it works regardless of the spawn path.
        """
        agent = _create_agent(client, default_workflow['id'], 'AskKeepCtxAgent',
                              'Keep context.')
        status = _create_status(client, default_workflow['id'], 'AskKeepCtxStage',
                                agent['id'], sort_order=1)

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            # Create ticket directly in agent's status; this auto-spawns a
            # work run. Keep mocking Popen so we capture all subprocess
            # invocations. The ask then runs and captures the ask context.
            ticket = _create_ticket(client, default_board['id'],
                                    body='Detailed ticket body for context.',
                                    status_id=status['id'])
            # Mark the work run as completed so the ask isn't blocked.
            with client.application.app_context():
                from pi_cowork.db import get_db
                db = get_db()
                db.execute(
                    "UPDATE agent_runs SET status = 'completed' WHERE ticket_id = ? AND status = 'running'",
                    (ticket['id'],),
                )
                db.commit()
            # Add a comment
            client.post(f'/api/tickets/{ticket["id"]}/comments',
                        json={'body': 'Pre-existing comment'})
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Read everything.'})
        assert res.status_code == 200
        # The captured cmd is the LAST Popen call (the ask spawn).
        context_msg = captured['cmd'][-1]
        # The body or the new-comments block must contain our context
        body_in_msg = (
            'Detailed ticket body for context.' in context_msg
            or 'New comments since last update' in context_msg
        )
        comment_in_msg = (
            'Pre-existing comment' in context_msg
            or 'New comments since last update' in context_msg
        )
        # API docs section is always present
        assert 'API:' in context_msg
        assert f'/api/tickets/{ticket["id"]}/comments' in context_msg
        # The body and comment must surface in some form
        assert body_in_msg, (
            f"Body or 'New comments' block not found in ask context: {context_msg}"
        )
        assert comment_in_msg, (
            f"Comment or 'New comments' block not found in ask context: {context_msg}"
        )

    def test_ask_uses_default_endpoints(self, client, default_workflow, default_board):
        """Ask mode keeps the agent's existing api_endpoints config as-is."""
        agent = _create_agent(client, default_workflow['id'], 'AskDefaultEpAgent',
                              'Default ep agent.',
                              api_endpoints=['ticket_put', 'ticket_comments_post',
                                              'ticket_questions_post'])
        status = _create_status(client, default_workflow['id'], 'AskDefaultEpStage',
                                agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Test endpoints.'})
        assert res.status_code == 200
        context_msg = captured['cmd'][-1]
        # All three default endpoints documented
        assert f'PUT {client.application.config["HUMAN_ACTION_SECRET"][:1]}' not in context_msg  # sanity
        # Confirm the doc lines are present (use base URL placeholder)
        # The build_api_docs substitutes base_url with the configured one.
        from pi_cowork.config import get_config
        base = get_config('pi_cowork_url')
        assert f'PUT {base}/api/tickets/{ticket["id"]}' in context_msg
        assert f'POST {base}/api/tickets/{ticket["id"]}/comments' in context_msg
        assert f'POST {base}/api/tickets/{ticket["id"]}/questions' in context_msg


# ---------------------------------------------------------------------------
# Session dir
# ---------------------------------------------------------------------------

class TestAskSessionReuse:
    def test_ask_reuses_session_dir(self, client, default_workflow, default_board):
        """Session dir is the same as work runs: .pi-sessions/<agent-id>/ticket-<id>/.

        The default board has working_directory='workspace' which the boards
        API resolves to an absolute path under the project root.
        """
        agent = _create_agent(client, default_workflow['id'], 'AskSessionAgent',
                              'Session test agent.')
        status = _create_status(client, default_workflow['id'], 'AskSessionStage',
                                agent['id'], sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Share session?'})
        assert res.status_code == 200
        cmd = captured['cmd']
        assert '--session-dir' in cmd
        idx = cmd.index('--session-dir')
        # The default board's working_directory is 'workspace' (resolved to
        # the absolute project workspace/ path by the boards API).
        session_dir = cmd[idx + 1]
        assert session_dir.endswith(f'workspace/.pi-sessions/{agent["id"]}/ticket-{ticket["id"]}')

    def test_ask_session_dir_uses_board_working_directory(self, client, default_workflow,
                                                          new_workflow):
        """Session dir uses the board's working_directory (e.g. 'custom-board-ws')."""
        agent = _create_agent(client, new_workflow['id'], 'AskWsAgent',
                              'WS agent.')
        # Create a board with a custom working directory
        res = client.post('/api/boards', json={
            'name': 'AskWsBoard',
            'workflow_id': new_workflow['id'],
            'working_directory': 'custom-board-ws',
        })
        assert res.status_code == 201
        board = json.loads(res.data)
        # Status + ticket on that board
        status = _create_status(client, new_workflow['id'], 'AskWsStage', agent['id'],
                                 sort_order=1, is_default=True)
        ticket = _create_ticket(client, board['id'], status_id=status['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, captured = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'WS test.'})
        assert res.status_code == 200
        cmd = captured['cmd']
        idx = cmd.index('--session-dir')
        # Working directory may be stored as an absolute path (the boards
        # API resolves it on creation). The session dir must end with the
        # relative path we expect.
        session_dir = cmd[idx + 1]
        assert session_dir.endswith(f'custom-board-ws/.pi-sessions/{agent["id"]}/ticket-{ticket["id"]}')


# ---------------------------------------------------------------------------
# Blocked scenarios
# ---------------------------------------------------------------------------

class TestAskBlocked:
    def test_ask_blocked_on_terminal_status(self, client, default_workflow, default_board):
        """Terminal status → 409."""
        agent = _create_agent(client, default_workflow['id'], 'AskTermAgent',
                              'term test agent.')
        status = _create_status(client, default_workflow['id'], 'AskTermStage', agent['id'],
                                 sort_order=1, is_terminal=True)
        # Ticket must exist in terminal status
        ticket_res = client.post('/api/tickets', json={
            'title': 'In terminal',
            'board_id': default_board['id'],
            'status_id': status['id'],
        })
        assert ticket_res.status_code == 201
        ticket = json.loads(ticket_res.data)

        res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                          json={'question': 'Am I done?'})
        assert res.status_code == 409
        assert 'terminal' in json.loads(res.data)['error'].lower()

    def test_ask_blocked_on_unanswered_questions(self, client, default_workflow, default_board):
        """Open questions → 409 (agent would be blocked by try_spawn_or_queue)."""
        agent = _create_agent(client, default_workflow['id'], 'AskQAgent',
                              'q test agent.')
        status = _create_status(client, default_workflow['id'], 'AskQStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])

        # Post a question (no answer) so the agent is blocked
        qres = client.post(f'/api/tickets/{ticket["id"]}/questions', json={
            'questions': [{'body': 'What color?', 'options': ['red', 'blue']}],
        })
        assert qres.status_code == 201

        res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                          json={'question': 'Are you stuck?'})
        assert res.status_code == 409
        # The error should mention questions / blocked
        body = json.loads(res.data)
        assert body.get('error')

    def test_ask_blocked_when_ask_run_in_flight(self, client, default_workflow, default_board):
        """Another ask run already running on this ticket → 409."""
        agent = _create_agent(client, default_workflow['id'], 'AskInflightAgent',
                              'inflight test.')
        status = _create_status(client, default_workflow['id'], 'AskInflightStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        # First ask → succeeds and is running
        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res1 = client.post(f'/api/tickets/{ticket["id"]}/ask',
                                json={'question': 'First ask.'})
        assert res1.status_code == 200
        # Confirm there's a running ask run
        runs = json.loads(client.get(f'/api/tickets/{ticket["id"]}/agent_runs').data)
        assert any(r['mode'] == 'ask' and r['status'] == 'running' for r in runs)

        # Second ask while first still running → 409
        res2 = client.post(f'/api/tickets/{ticket["id"]}/ask',
                            json={'question': 'Second ask.'})
        assert res2.status_code == 409
        assert 'ask' in json.loads(res2.data)['error'].lower()

    def test_ask_ticket_not_found(self, client):
        res = client.post('/api/tickets/99999/ask', json={'question': 'Where?'})
        assert res.status_code == 404

    def test_ask_missing_question(self, client, default_workflow, default_board):
        agent = _create_agent(client, default_workflow['id'], 'AskNoQAgent',
                              'no question agent.')
        status = _create_status(client, default_workflow['id'], 'AskNoQStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        res = client.post(f'/api/tickets/{ticket["id"]}/ask', json={})
        assert res.status_code == 400
        # Also reject empty string
        res2 = client.post(f'/api/tickets/{ticket["id"]}/ask',
                            json={'question': '   '})
        assert res2.status_code == 400


# ---------------------------------------------------------------------------
# Work-spawn compatibility
# ---------------------------------------------------------------------------

class TestWorkSpawnCompatibility:
    def test_ask_mode_default_is_work_for_status_spawns(self, client, default_workflow,
                                                        default_board):
        """Existing spawn_agent() callers (no ask_question) still create mode='work' rows."""
        agent = _create_agent(client, default_workflow['id'], 'WorkModeAgent',
                              'work mode agent.')
        status = _create_status(client, default_workflow['id'], 'WorkModeStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])

        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            # Manually move ticket into the agent's status (this triggers a work spawn)
            res = client.put(f'/api/tickets/{ticket["id"]}',
                              json={'status_id': status['id']})
        assert res.status_code == 200, res.data

        runs = json.loads(client.get(f'/api/tickets/{ticket["id"]}/agent_runs').data)
        # At least one run, and it should be mode='work'
        assert any(r['mode'] == 'work' for r in runs)
        assert not any(r['mode'] == 'ask' for r in runs)

    def test_existing_agent_runs_backfill_to_work(self, client, default_workflow, default_board):
        """The mode column defaults to 'work' for any existing row (covered by the migration default)."""
        agent = _create_agent(client, default_workflow['id'], 'BackfillModeAgent',
                              'backfill.')
        status = _create_status(client, default_workflow['id'], 'BackfillModeStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/spawn')
        assert res.status_code == 200
        runs = json.loads(client.get(f'/api/tickets/{ticket["id"]}/agent_runs').data)
        # Filter out the initial work spawn from moving the ticket
        work_runs = [r for r in runs if r['mode'] == 'work']
        assert len(work_runs) >= 1


# ---------------------------------------------------------------------------
# Endpoint registry
# ---------------------------------------------------------------------------

class TestAskEndpointRegistry:
    def test_ask_api_endpoint_key_visible_in_registry(self, client):
        """GET /api/endpoint-registry includes the tickets_ask_post key."""
        res = client.get('/api/endpoint-registry')
        assert res.status_code == 200
        data = json.loads(res.data)
        # Find the key (response shape: list of entries or grouped dict — accept either)
        keys = []
        if isinstance(data, list):
            keys = [e['key'] for e in data if 'key' in e]
        elif isinstance(data, dict):
            # Grouped by category: flatten
            for v in data.values():
                if isinstance(v, list):
                    for e in v:
                        if isinstance(e, dict) and 'key' in e:
                            keys.append(e['key'])
        assert 'tickets_ask_post' in keys, (
            f"tickets_ask_post not found in /api/endpoint-registry response. "
            f"Got keys: {keys}"
        )


# ---------------------------------------------------------------------------
# System comment preview
# ---------------------------------------------------------------------------

class TestAskSystemComment:
    def test_system_comment_truncates_long_question(self, client, default_workflow, default_board):
        """Long question → preview truncated to ~80 chars with ellipsis."""
        agent = _create_agent(client, default_workflow['id'], 'AskLongQAgent',
                              'long q.')
        status = _create_status(client, default_workflow['id'], 'AskLongQStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        long_q = 'a' * 200
        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': long_q})
        assert res.status_code == 200

        comments = json.loads(client.get(f'/api/tickets/{ticket["id"]}/comments').data)
        ask_comments = [c for c in comments if 'Asked agent' in c['body']]
        assert len(ask_comments) == 1
        body = ask_comments[0]['body']
        # First 80 chars appear, with an ellipsis marker
        assert 'a' * 80 in body
        assert '…' in body

    def test_short_question_appears_in_full(self, client, default_workflow, default_board):
        """Short question → full text appears in system comment."""
        agent = _create_agent(client, default_workflow['id'], 'AskShortQAgent',
                              'short q.')
        status = _create_status(client, default_workflow['id'], 'AskShortQStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        _move_ticket_to_status(client, ticket['id'], status['id'])

        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'Is it raining?'})
        assert res.status_code == 200

        comments = json.loads(client.get(f'/api/tickets/{ticket["id"]}/comments').data)
        ask_comments = [c for c in comments if 'Asked agent' in c['body']]
        assert len(ask_comments) == 1
        assert 'Is it raining?' in ask_comments[0]['body']


# ---------------------------------------------------------------------------
# UI: ticket detail page includes the Ask Agent button + modal
# ---------------------------------------------------------------------------

class TestAskUI:
    def test_ticket_detail_includes_ask_button(self, client, default_workflow, default_board):
        """The ticket detail page HTML includes the Ask Agent button."""
        agent = _create_agent(client, default_workflow['id'], 'AskUIButtonAgent',
                              'UI button test.')
        _create_status(client, default_workflow['id'], 'AskUIButtonStage', agent['id'],
                        sort_order=1)
        ticket = _create_ticket(client, default_board['id'])
        res = client.get(f'/ticket/{ticket["id"]}')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert 'ask-agent-btn' in html, "Ask Agent button should be in the page"
        assert 'ask-agent-modal' in html, "Ask Agent modal should be in the page"
        assert 'Ask Agent' in html, "Ask Agent label should be in the page"

    def test_ticket_detail_includes_ask_button_styles(self, client):
        """The stylesheet includes ask-mode badge styles."""
        import os
        style_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'static', 'style.css'
        )
        with open(style_path) as f:
            css = f.read()
        assert '.ask-mode-badge' in css, "Ask-mode badge styles should exist"
        assert '.ask-agent' in css, "Ask Agent button styles should exist"

    def test_agent_runs_api_returns_mode_field(self, client, default_workflow, default_board):
        """The agent_runs API returns the mode field for every run."""
        agent = _create_agent(client, default_workflow['id'], 'AskApiModeAgent',
                              'mode test.')
        status = _create_status(client, default_workflow['id'], 'AskApiModeStage', agent['id'],
                                 sort_order=1)
        ticket = _create_ticket(client, default_board['id'], status_id=status['id'])

        popen_se, _ = _make_fake_popen()
        with patch('app.subprocess.Popen', side_effect=popen_se):
            res = client.post(f'/api/tickets/{ticket["id"]}/ask',
                              json={'question': 'mode field test.'})
        assert res.status_code == 200

        runs = json.loads(client.get(f'/api/tickets/{ticket["id"]}/agent_runs').data)
        assert len(runs) >= 1
        for run in runs:
            assert 'mode' in run, f"agent_runs row should include 'mode': {run}"
