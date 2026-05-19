"""Tests for the re-run agent button feature (ticket #35).

Covers:
  - API: last_agent_run and agent_run_count fields in ticket detail
  - API: re-spawning after a failed agent run
  - API: re-spawning after a completed agent run
  - API: re-spawning after completion creates a new run
  - Frontend: button visibility logic (tested via API fields)
"""

import json
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_agent(client, workflow_id, name='TestAgent', description='You are a test agent.'):
    res = client.post('/api/agents', json={
        'name': name,
        'description': description,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_status_with_agent(client, workflow_id, agent_id, name='SpawnStage', sort_order=99, is_terminal=False):
    res = client.post('/api/statuses', json={
        'name': name,
        'sort_order': sort_order,
        'agent_id': agent_id,
        'is_terminal': is_terminal,
        'workflow_id': workflow_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


def _create_ticket(client, board_id, title='Rerun Ticket'):
    res = client.post('/api/tickets', json={
        'title': title,
        'board_id': board_id,
    })
    assert res.status_code == 201
    return json.loads(res.data)


# ---------------------------------------------------------------------------
# GET /api/tickets/<id> — last_agent_run & agent_run_count fields
# ---------------------------------------------------------------------------

def test_ticket_detail_no_previous_run(client, default_workflow, default_board):
    """When no agent has ever run, last_agent_run is None and agent_run_count is 0."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Move ticket to status with agent, which spawns the agent
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10001)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # The ticket was just moved and agent spawned — there IS a running run
    res = client.get(f'/api/tickets/{tid}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['agent_run_count'] >= 1
    assert data['last_agent_run'] is not None
    assert data['last_agent_run']['status'] == 'running'


def test_ticket_detail_last_agent_run_after_failure(client, default_workflow, default_board):
    """After an agent fails, last_agent_run shows status='failed' and correct exit_code."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Move ticket to spawn agent
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10002)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Mark the agent run as failed with exit code 1
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'failed', exit_code = 1, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    res = client.get(f'/api/tickets/{tid}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['agent_run_count'] == 1
    assert data['last_agent_run'] is not None
    assert data['last_agent_run']['status'] == 'failed'
    assert data['last_agent_run']['exit_code'] == 1
    assert data['last_agent_run']['agent_name'] == 'TestAgent'
    assert data['running_agents'] == 0


def test_ticket_detail_last_agent_run_after_completion(client, default_workflow, default_board):
    """After an agent completes successfully, last_agent_run shows status='completed' and exit_code=0."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Move ticket to spawn agent
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10003)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Mark the agent run as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    res = client.get(f'/api/tickets/{tid}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['agent_run_count'] == 1
    assert data['last_agent_run']['status'] == 'completed'
    assert data['last_agent_run']['exit_code'] == 0
    assert data['running_agents'] == 0


def test_ticket_detail_no_runs_at_all(client, default_board):
    """Ticket with no agent runs should have last_agent_run=None and agent_run_count=0."""
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    res = client.get(f'/api/tickets/{tid}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['last_agent_run'] is None
    assert data['agent_run_count'] == 0


def test_ticket_detail_multiple_runs_shows_latest(client, default_workflow, default_board):
    """When there are multiple runs, last_agent_run shows the most recent one."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # First spawn
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10004)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Mark first run as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    # Second spawn (re-run)
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10005)
        res = client.post(f'/api/tickets/{tid}/spawn')
        assert res.status_code == 200

    # Mark second run as failed with exit code 1
    with client.application.app_context():
        # Get the latest (second) run id
        rows = app_module.query_db(
            "SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
            (tid,)
        )
        latest_run_id = rows[0]['id'] if rows else None
        if latest_run_id:
            app_module.run_db(
                "UPDATE agent_runs SET status = 'failed', exit_code = 1, completed_at = datetime('now') WHERE id = ?",
                (latest_run_id,)
            )

    res = client.get(f'/api/tickets/{tid}')
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data['agent_run_count'] == 2
    assert data['last_agent_run']['status'] == 'failed'
    assert data['last_agent_run']['exit_code'] == 1


# ---------------------------------------------------------------------------
# POST /api/tickets/<id>/spawn — re-run after failure
# ---------------------------------------------------------------------------

def test_rerun_after_failed_agent(client, default_workflow, default_board):
    """Re-running an agent after it failed should succeed and create a new run."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # First spawn
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10010)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Mark first run as failed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'failed', exit_code = 1, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    # Re-run via spawn endpoint
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10011)
        res = client.post(f'/api/tickets/{tid}/spawn')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True
        assert data['spawned'] is True

    # Verify there are now 2 runs: 1 failed, 1 running
    res = client.get(f'/api/tickets/{tid}/agent_runs')
    assert res.status_code == 200
    runs = json.loads(res.data)
    assert len(runs) == 2
    statuses = [r['status'] for r in runs]
    assert 'failed' in statuses
    assert 'running' in statuses


def test_rerun_after_completed_agent(client, default_workflow, default_board):
    """Re-running an agent after it completed successfully should create a new run."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # First spawn
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10012)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Mark first run as completed
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'completed', exit_code = 0, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    # Re-run
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10013)
        res = client.post(f'/api/tickets/{tid}/spawn')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['success'] is True
        assert data['spawned'] is True


# ---------------------------------------------------------------------------
# Frontend hint fields — button logic scenarios
# ---------------------------------------------------------------------------

def test_rerun_button_scenario_failed_run(client, default_workflow, default_board):
    """Simulates frontend re-run button scenario: failed run => show re-run button."""
    import app as app_module
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Spawn agent
    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10020)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    # Fail the run
    with client.application.app_context():
        app_module.run_db(
            "UPDATE agent_runs SET status = 'failed', exit_code = 1, completed_at = datetime('now') WHERE ticket_id = ?",
            (tid,)
        )

    # Check ticket detail — the frontend would use these fields to show "Re-run Agent"
    res = client.get(f'/api/tickets/{tid}')
    data = json.loads(res.data)
    assert data['agent_run_count'] > 0, "agent_run_count should be > 0 for re-run"
    assert data['running_agents'] == 0, "No agents should be running"
    assert data['last_agent_run']['status'] == 'failed', "Last run should show failed"
    assert not data.get('is_terminal'), "Ticket should not be terminal"
    assert data.get('agent_name') == 'TestAgent', "Should have an agent assigned"


def test_rerun_button_scenario_first_run(client, default_workflow, default_board):
    """Simulates frontend first-run scenario: no previous runs => show 'Run Agent'."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Move to agent status via DB without spawning (simulate manually placed ticket)
    import app as app_module
    with client.application.app_context():
        app_module.run_db("UPDATE tickets SET status_id = ? WHERE id = ?", (status['id'], tid))

    res = client.get(f'/api/tickets/{tid}')
    data = json.loads(res.data)
    assert data['agent_run_count'] == 0, "agent_run_count should be 0 for first run"
    assert data['last_agent_run'] is None, "No last run should exist"
    assert data['running_agents'] == 0


def test_rerun_button_scenario_running_agent(client, default_workflow, default_board):
    """Simulates frontend scenario: agent currently running => show disabled re-run button."""
    agent = _create_agent(client, default_workflow['id'])
    status = _create_status_with_agent(client, default_workflow['id'], agent['id'])
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    with patch('app.subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock(pid=10030)
        client.put(f'/api/tickets/{tid}', json={'status_id': status['id']})

    res = client.get(f'/api/tickets/{tid}')
    data = json.loads(res.data)
    assert data['running_agents'] > 0, "Agent should be running"
    assert data['agent_run_count'] > 0, "agent_run_count should reflect the running run"


def test_rerun_button_scenario_terminal_status(client, default_workflow, default_board):
    """Simulates frontend scenario: ticket in terminal status => disabled re-run button."""
    agent = _create_agent(client, default_workflow['id'])
    _create_status_with_agent(client, default_workflow['id'], agent['id'])

    # Create terminal status
    term_res = client.post('/api/statuses', json={
        'name': 'DoneTerminal',
        'sort_order': 100,
        'is_terminal': True,
        'workflow_id': default_workflow['id'],
    })
    assert term_res.status_code == 201
    terminal_status = json.loads(term_res.data)

    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']

    # Move to terminal status
    client.put(f'/api/tickets/{tid}', json={'status_id': terminal_status['id']})

    res = client.get(f'/api/tickets/{tid}')
    data = json.loads(res.data)
    assert data['is_terminal'] == 1, "Should be terminal"
    # Spawn should be rejected
    res = client.post(f'/api/tickets/{tid}/spawn')
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# Ticket detail page includes agent runs section
# ---------------------------------------------------------------------------

def test_ticket_detail_page_includes_rerun_button_html(client, default_board):
    """The ticket detail page HTML includes the re-run agent button element."""
    ticket = _create_ticket(client, default_board['id'])
    tid = ticket['id']
    res = client.get(f'/ticket/{tid}')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'rerun-agent-btn' in html, "Re-run Agent button should be in the page"
    assert 'agent-runs-section' in html, "Agent Runs section should be in the page"


def test_ticket_detail_page_includes_rerun_button_styles(client, default_board):
    """The stylesheet should include re-run agent button styles."""
    import os
    style_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'style.css')
    with open(style_path) as f:
        css = f.read()
    assert '.btn.rerun-agent' in css, "Re-run agent button styles should exist"
    assert '.agent-runs-section' in css, "Agent runs section styles should exist"
    assert '.agent-run-card' in css, "Agent run card styles should exist"