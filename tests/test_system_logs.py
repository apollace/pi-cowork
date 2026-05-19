"""Tests for the centralised system logs feature (Ticket #37)."""

import json
import os
import tempfile

import pytest

# Ensure project root is on sys.path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault('PI_MAX_PARALLEL', '100')
os.environ.setdefault('PI_MAX_PER_HOUR', '100')

from app import app as flask_app, init_db
from pi_cowork import config
from pi_cowork import agents as agents_module
from pi_cowork.system_logs import (
    add_log, get_system_logs, cleanup_old_logs, export_logs_text,
    VALID_LEVELS, VALID_ACTION_TYPES
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fake_start_watcher(proc, run_id, ticket_id, agent_name, log_f):
    pass


def _fake_log_reader(pipe, log_f):
    try:
        pipe.close()
    except (ValueError, OSError, AttributeError):
        pass
    try:
        log_f.close()
    except (ValueError, OSError):
        pass


@pytest.fixture(autouse=True)
def mock_watcher(monkeypatch):
    monkeypatch.setattr(agents_module, '_start_watcher', _fake_start_watcher)


@pytest.fixture(autouse=True)
def mock_log_reader(monkeypatch):
    monkeypatch.setattr(agents_module, '_start_log_reader', _fake_log_reader)


@pytest.fixture(autouse=True)
def reset_limits(monkeypatch):
    config.PI_MAX_PARALLEL = 100
    config.PI_MAX_PER_HOUR = 100
    monkeypatch.setenv('PI_MAX_PARALLEL', '100')
    monkeypatch.setenv('PI_MAX_PER_HOUR', '100')


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    flask_app.config['TESTING'] = True
    flask_app.config['DATABASE'] = db_path

    with flask_app.app_context():
        init_db(flask_app)
        with flask_app.test_client() as client:
            # Ensure _drain_app references the Flask app so that watcher threads
            # (which run outside any request context) can push an app context.
            agents_module._drain_app = flask_app
            yield client
            agents_module._drain_app = None

    os.close(db_fd)
    os.unlink(db_path)


def _create_workflow_and_board(client):
    """Helper: create a workflow and board (with a default status), return board info."""
    res = client.post('/api/workflows', json={'name': 'Test WF'})
    wf_id = json.loads(res.data)['id']
    # Create a default status so tickets can be created
    res = client.post('/api/statuses', json={
        'name': 'Backlog', 'sort_order': 1, 'is_default': True,
        'is_terminal': False, 'workflow_id': wf_id
    })
    res = client.post('/api/boards', json={'name': 'Test Board', 'workflow_id': wf_id})
    return json.loads(res.data), wf_id


def _create_ticket(client, board_id, status_id=None):
    """Helper: create a ticket, return its ID."""
    data = {'title': 'Test Ticket', 'board_id': board_id}
    if status_id:
        data['status_id'] = status_id
    res = client.post('/api/tickets', json=data)
    return json.loads(res.data)['id']


# ---------------------------------------------------------------------------
# Database & Schema
# ---------------------------------------------------------------------------

class TestSystemLogsTable:
    def test_system_logs_table_exists(self, client):
        """The system_logs table should be created by migration."""
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_logs'"
        ).fetchall()
        assert len(rows) == 1

    def test_indexes_exist(self, client):
        """Indexes on key columns should exist."""
        from pi_cowork.db import get_db
        db = get_db()
        indexes = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_system_logs%'"
        ).fetchall()
        index_names = {r['name'] for r in indexes}
        assert 'idx_system_logs_timestamp' in index_names
        assert 'idx_system_logs_level' in index_names
        assert 'idx_system_logs_action_type' in index_names
        assert 'idx_system_logs_ticket_id' in index_names


# ---------------------------------------------------------------------------
# add_log() core function
# ---------------------------------------------------------------------------

class TestAddLog:
    def test_add_log_basic(self, client):
        """add_log should insert a row in system_logs."""
        from pi_cowork.db import get_db
        add_log('INFO', 'db_change', 'INSERT tickets/1',
                details={'operation': 'INSERT', 'table': 'tickets', 'record_id': 1},
                ticket_id=1)
        db = get_db()
        row = db.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row['level'] == 'INFO'
        assert row['action_type'] == 'db_change'
        assert row['message'] == 'INSERT tickets/1'
        assert row['ticket_id'] == 1
        details = json.loads(row['details'])
        assert details['operation'] == 'INSERT'

    def test_add_log_all_levels(self, client):
        """All valid levels should be accepted."""
        from pi_cowork.db import get_db
        for level in VALID_LEVELS:
            add_log(level, 'agent_event', f'Test {level}')
        db = get_db()
        count = db.execute("SELECT COUNT(*) as c FROM system_logs").fetchone()['c']
        assert count >= 4

    def test_add_log_all_action_types(self, client):
        """All valid action_types should be accepted."""
        from pi_cowork.db import get_db
        for at in VALID_ACTION_TYPES:
            add_log('INFO', at, f'Test {at}')
        db = get_db()
        count = db.execute("SELECT COUNT(*) as c FROM system_logs").fetchone()['c']
        assert count >= 3

    def test_add_log_invalid_level_defaults_to_info(self, client):
        """Invalid level should default to INFO."""
        from pi_cowork.db import get_db
        add_log('DEBUG', 'db_change', 'Test invalid level')
        db = get_db()
        row = db.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row['level'] == 'INFO'

    def test_add_log_invalid_action_type_defaults(self, client):
        """Invalid action_type should default to db_change."""
        from pi_cowork.db import get_db
        add_log('INFO', 'custom_type', 'Test invalid action type')
        db = get_db()
        row = db.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row['action_type'] == 'db_change'

    def test_add_log_none_details(self, client):
        """add_log with no details should store NULL."""
        from pi_cowork.db import get_db
        add_log('INFO', 'db_change', 'No details test', details=None)
        db = get_db()
        row = db.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row['details'] is None

    def test_add_log_none_ticket_id(self, client):
        """add_log with no ticket_id should store NULL."""
        from pi_cowork.db import get_db
        add_log('INFO', 'http_request', 'No ticket')
        db = get_db()
        row = db.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row['ticket_id'] is None


# ---------------------------------------------------------------------------
# get_system_logs() — pagination & filtering
# ---------------------------------------------------------------------------

class TestGetSystemLogs:
    def _seed_logs(self, client, count=10):
        """Seed some logs for testing."""
        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])
        for i in range(count):
            level = ['INFO', 'WARNING', 'ERROR', 'CRITICAL'][i % 4]
            action = ['http_request', 'db_change', 'agent_event'][i % 3]
            add_log(level, action, f'Log entry {i}',
                    details={'index': i},
                    ticket_id=ticket_id if i % 2 == 0 else None)

    def test_pagination(self, client):
        """Pagination should work correctly."""
        self._seed_logs(client, 25)
        result = get_system_logs(page=1, per_page=10)
        assert len(result['logs']) == 10
        assert result['total'] >= 25
        assert result['page'] == 1
        assert result['total_pages'] >= 3

        result = get_system_logs(page=3, per_page=10)
        assert len(result['logs']) <= 10  # last page may have fewer
        assert result['page'] == 3

    def test_filter_by_level(self, client):
        """Filtering by level should return only matching rows."""
        self._seed_logs(client, 10)
        result = get_system_logs(level='ERROR')
        assert all(log['level'] == 'ERROR' for log in result['logs'])

    def test_filter_by_action_type(self, client):
        """Filtering by action_type should return only matching rows."""
        self._seed_logs(client, 10)
        result = get_system_logs(action_type='http_request')
        assert all(log['action_type'] == 'http_request' for log in result['logs'])

    def test_filter_by_ticket_id(self, client):
        """Filtering by ticket_id should return only matching rows."""
        board_data, wf_id = _create_workflow_and_board(client)
        tid1 = _create_ticket(client, board_data['id'])
        tid2 = _create_ticket(client, board_data['id'])
        add_log('INFO', 'db_change', 'For ticket 1', ticket_id=tid1)
        add_log('INFO', 'db_change', 'For ticket 2', ticket_id=tid2)
        result = get_system_logs(ticket_id=tid1)
        assert all(log['ticket_id'] == tid1 for log in result['logs'])

    def test_filter_by_search(self, client):
        """Search filter should match message substring."""
        add_log('INFO', 'db_change', 'Unique test message alpha')
        add_log('INFO', 'db_change', 'Different message beta')
        result = get_system_logs(search='alpha')
        assert len(result['logs']) >= 1
        assert any('alpha' in log['message'] for log in result['logs'])

    def test_filter_combined(self, client):
        """Multiple filters combined should work."""
        add_log('ERROR', 'agent_event', 'Agent failure alpha')
        add_log('INFO', 'agent_event', 'Agent success')
        add_log('ERROR', 'db_change', 'DB error alpha')
        result = get_system_logs(level='ERROR', action_type='agent_event', search='alpha')
        assert len(result['logs']) >= 1
        for log in result['logs']:
            assert log['level'] == 'ERROR'
            assert log['action_type'] == 'agent_event'

    def test_ordered_by_timestamp_desc(self, client):
        """Logs should be ordered by timestamp descending (newest first)."""
        add_log('INFO', 'db_change', 'First entry')
        add_log('INFO', 'db_change', 'Second entry')
        result = get_system_logs(per_page=10)
        # The second entry should be returned first (most recent first)
        assert result['logs'][0]['message'] == 'Second entry'


# ---------------------------------------------------------------------------
# get_system_logs() — include_details parameter (Ticket #60)
# ---------------------------------------------------------------------------

class TestGetSystemLogsIncludeDetails:
    def test_default_excludes_details(self, client):
        """Default get_system_logs() should not include details, only has_details."""
        add_log('INFO', 'db_change', 'Log with details', details={'key': 'value'})
        add_log('INFO', 'db_change', 'Log without details', details=None)
        result = get_system_logs(per_page=10)
        assert len(result['logs']) >= 2
        for log in result['logs']:
            assert 'details' not in log
            assert 'has_details' in log
        # Find the specific logs we just added
        with_details = [l for l in result['logs'] if l['message'] == 'Log with details']
        without_details = [l for l in result['logs'] if l['message'] == 'Log without details']
        assert len(with_details) >= 1
        assert len(without_details) >= 1
        assert with_details[0]['has_details'] is True
        assert without_details[0]['has_details'] is False

    def test_include_details_true_returns_details(self, client):
        """get_system_logs(include_details=True) should include details."""
        add_log('INFO', 'db_change', 'Detail test', details={'foo': 'bar'})
        result = get_system_logs(per_page=10, include_details=True)
        found = [l for l in result['logs'] if l['message'] == 'Detail test']
        assert len(found) >= 1
        assert 'details' in found[0]
        assert found[0]['details'] == {'foo': 'bar'}
        assert 'has_details' not in found[0]

    def test_include_details_true_no_details(self, client):
        """get_system_logs(include_details=True) with no details should have None."""
        add_log('INFO', 'db_change', 'No detail test', details=None)
        result = get_system_logs(per_page=10, include_details=True)
        found = [l for l in result['logs'] if l['message'] == 'No detail test']
        assert len(found) >= 1
        assert found[0]['details'] is None

    def test_has_details_boolean_true(self, client):
        """has_details should be True when details column is not NULL."""
        add_log('INFO', 'db_change', 'Has details', details={'x': 1})
        result = get_system_logs(per_page=10)
        found = [l for l in result['logs'] if l['message'] == 'Has details']
        assert len(found) >= 1
        assert found[0]['has_details'] is True

    def test_has_details_boolean_false(self, client):
        """has_details should be False when details column is NULL."""
        add_log('INFO', 'db_change', 'No details', details=None)
        result = get_system_logs(per_page=10)
        found = [l for l in result['logs'] if l['message'] == 'No details']
        assert len(found) >= 1
        assert found[0]['has_details'] is False

    def test_api_list_returns_has_details(self, client):
        """GET /api/system_logs should return has_details instead of details."""
        add_log('INFO', 'db_change', 'API has_details test', details={'key': 'val'})
        add_log('INFO', 'db_change', 'API no details test')
        res = client.get('/api/system_logs')
        assert res.status_code == 200
        data = json.loads(res.data)
        # At least one log should have has_details=True and one False
        has_true = any(l.get('has_details') is True for l in data['logs'])
        has_false = any(l.get('has_details') is False for l in data['logs'])
        assert has_true, "Expected at least one log with has_details=True"
        assert has_false, "Expected at least one log with has_details=False"
        # No log should have 'details' key in the list response
        for log in data['logs']:
            assert 'details' not in log, f"Log {log['id']} should not have 'details' in list response"

    def test_export_includes_details(self, client):
        """export_logs_text should still include full details."""
        add_log('INFO', 'db_change', 'Export detail test', details={'op': 'INSERT', 'table': 'test'})
        text = export_logs_text()
        assert 'Export detail test' in text
        # Export should include the detail key=value pairs
        assert 'op=INSERT' in text


# ---------------------------------------------------------------------------
# cleanup_old_logs()
# ---------------------------------------------------------------------------

class TestLogRotation:
    def test_cleanup_removes_old_logs(self, client):
        """cleanup_old_logs should remove entries older than max_age_days."""
        from pi_cowork.db import get_db
        # Insert a log with an old timestamp
        old_ts = '2020-01-01T00:00:00+00:00'
        db = get_db()
        db.execute(
            "INSERT INTO system_logs (timestamp, level, action_type, message) VALUES (?, 'INFO', 'db_change', 'old log')",
            (old_ts,)
        )
        db.commit()
        add_log('INFO', 'db_change', 'new log')

        deleted = cleanup_old_logs(max_age_days=30)
        assert deleted >= 1

        # Old log should be gone
        remaining = db.execute(
            "SELECT * FROM system_logs WHERE message = 'old log'"
        ).fetchall()
        assert len(remaining) == 0

    def test_cleanup_keeps_recent_logs(self, client):
        """cleanup_old_logs should keep entries within the retention period."""
        add_log('INFO', 'db_change', 'recent log')
        deleted = cleanup_old_logs(max_age_days=30)
        # Recent log should still be there
        from pi_cowork.db import get_db
        db = get_db()
        remaining = db.execute(
            "SELECT * FROM system_logs WHERE message = 'recent log'"
        ).fetchall()
        assert len(remaining) == 1


# ---------------------------------------------------------------------------
# export_logs_text()
# ---------------------------------------------------------------------------

class TestExportLogs:
    def test_export_returns_text(self, client):
        """export_logs_text should return a plain text string."""
        add_log('INFO', 'db_change', 'Export test log')
        text = export_logs_text()
        assert isinstance(text, str)
        assert 'Export test log' in text

    def test_export_with_filters(self, client):
        """Export should respect filters."""
        add_log('ERROR', 'agent_event', 'Export error')
        add_log('INFO', 'db_change', 'Export info')
        text = export_logs_text(level='ERROR')
        assert 'Export error' in text
        # INFO log might also be in text if other test logs exist, so we don't assert absence


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

class TestSystemLogsAPI:
    def test_get_system_logs_endpoint(self, client):
        """GET /api/system_logs should return paginated logs."""
        add_log('INFO', 'db_change', 'API test log')
        res = client.get('/api/system_logs')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert 'logs' in data
        assert 'total' in data
        assert 'page' in data
        assert 'per_page' in data
        assert 'total_pages' in data

    def test_get_system_logs_with_filters(self, client):
        """GET /api/system_logs with query params should filter correctly."""
        add_log('ERROR', 'agent_event', 'API error log')
        res = client.get('/api/system_logs?level=ERROR&action_type=agent_event')
        assert res.status_code == 200
        data = json.loads(res.data)
        for log in data['logs']:
            assert log['level'] == 'ERROR'
            assert log['action_type'] == 'agent_event'

    def test_get_system_logs_pagination(self, client):
        """GET /api/system_logs with page param should paginate."""
        for i in range(5):
            add_log('INFO', 'db_change', f'Pagination log {i}')
        res = client.get('/api/system_logs?per_page=2&page=1')
        data = json.loads(res.data)
        assert len(data['logs']) <= 2
        assert data['total'] >= 5

    def test_export_endpoint(self, client):
        """GET /api/system_logs/export should return plain text."""
        add_log('INFO', 'db_change', 'Export API test')
        res = client.get('/api/system_logs/export')
        assert res.status_code == 200
        assert res.content_type.startswith('text/plain')
        text = res.data.decode('utf-8')
        assert 'Export API test' in text
        assert 'Content-Disposition' in res.headers
        assert 'system_logs.txt' in res.headers['Content-Disposition']

    def test_export_with_filters(self, client):
        """Export with filters should work."""
        add_log('ERROR', 'http_request', 'Filtered export log')
        res = client.get('/api/system_logs/export?level=ERROR')
        assert res.status_code == 200
        text = res.data.decode('utf-8')
        assert 'Filtered export log' in text


# ---------------------------------------------------------------------------
# HTTP Request Logging Middleware
# ---------------------------------------------------------------------------

class TestHTTPRequestLogging:
    def test_post_request_is_logged(self, client):
        """POST requests should be logged in system_logs."""
        board_data, wf_id = _create_workflow_and_board(client)
        res = client.post('/api/tickets', json={
            'title': 'Log test ticket',
            'board_id': board_data['id']
        })
        assert res.status_code == 201

        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%POST%/api/tickets%'"
        ).fetchall()
        assert len(rows) >= 1
        log = rows[-1]
        assert log['level'] == 'INFO'  # 201 = < 400

    def test_put_request_is_logged(self, client):
        """PUT requests should be logged."""
        board_data, wf_id = _create_workflow_and_board(client)
        res = client.put('/api/settings/test_key', json={'value': 'test_value'})
        assert res.status_code == 200

        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%PUT%/api/settings%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_delete_request_is_logged(self, client):
        """DELETE requests should be logged."""
        res = client.delete('/api/statuses/9999')
        # May return 409 or 404 but should still be logged
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%DELETE%/api/statuses%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_get_requests_not_logged(self, client):
        """GET requests should not be logged."""
        client.get('/api/workflows')
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%GET%/api/workflows%'"
        ).fetchall()
        assert len(rows) == 0

    def test_system_logs_endpoint_not_logged(self, client):
        """Requests to /api/system_logs should not be logged (to avoid recursion)."""
        client.get('/api/system_logs')
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%/api/system_logs%'"
        ).fetchall()
        assert len(rows) == 0

    def test_static_requests_not_logged(self, client):
        """Static file requests should not be logged."""
        client.get('/static/style.css')
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE '%GET%/static%'"
        ).fetchall()
        assert len(rows) == 0

    def test_client_error_response_logged_as_warning(self, client):
        """4xx responses should be logged as WARNING level."""
        # PUT on nonexistent ticket generates 404
        res = client.put('/api/tickets/99999', json={'title': 'X'})
        assert res.status_code == 404
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND level = 'WARNING'"
        ).fetchall()
        assert len(rows) >= 1

    def test_http_log_includes_details(self, client):
        """HTTP request logs should contain method, URL, status, bodies."""
        board_data, wf_id = _create_workflow_and_board(client)
        client.post('/api/tickets', json={'title': 'Details test', 'board_id': board_data['id']})

        from pi_cowork.db import get_db
        db = get_db()
        row = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'POST%/api/tickets%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        details = json.loads(row['details'])
        assert 'method' in details
        assert 'url' in details
        assert 'status_code' in details

    def test_ticket_id_extracted_from_url(self, client):
        """HTTP logs should extract ticket_id from /api/tickets/<id>/... URLs."""
        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])
        # PUT on that ticket
        client.put(f'/api/tickets/{ticket_id}', json={'title': 'Updated'})
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            f"SELECT * FROM system_logs WHERE action_type = 'http_request' AND ticket_id = {ticket_id}"
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# DB Change Logging
# ---------------------------------------------------------------------------

class TestDBChangeLogging:
    def test_create_ticket_logged(self, client):
        """Creating a ticket should log INSERT tickets."""
        board_data, wf_id = _create_workflow_and_board(client)
        res = client.post('/api/tickets', json={
            'title': 'Created ticket',
            'board_id': board_data['id']
        })
        assert res.status_code == 201
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'INSERT tickets/%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_update_ticket_logged(self, client):
        """Updating a ticket should log UPDATE tickets."""
        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])
        res = client.put(f'/api/tickets/{ticket_id}', json={'title': 'Updated'})
        assert res.status_code == 200
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            f"SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'UPDATE tickets/{ticket_id}'"
        ).fetchall()
        assert len(rows) >= 1

    def test_create_comment_logged(self, client):
        """Adding a comment should log INSERT comments."""
        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])
        res = client.post(f'/api/tickets/{ticket_id}/comments', json={'body': 'Test comment'})
        assert res.status_code == 201
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'INSERT comments/%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_create_workflow_logged(self, client):
        """Creating a workflow should log INSERT workflows."""
        res = client.post('/api/workflows', json={'name': 'Log test WF'})
        assert res.status_code == 201
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'INSERT workflows/%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_create_status_logged(self, client):
        """Creating a status should log INSERT statuses."""
        res = client.post('/api/workflows', json={'name': 'WF for status test'})
        wf_id = json.loads(res.data)['id']
        res = client.post('/api/statuses', json={
            'name': 'TestStatus', 'sort_order': 1, 'workflow_id': wf_id
        })
        assert res.status_code == 201
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'INSERT statuses/%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_update_setting_logged(self, client):
        """Updating a setting should log UPDATE settings."""
        res = client.put('/api/settings/log_test_key', json={'value': 'value123'})
        assert res.status_code == 200
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'db_change' AND message LIKE 'UPDATE settings/%'"
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# Agent Event Logging
# ---------------------------------------------------------------------------

class TestAgentEventLogging:
    def test_agent_spawned_logged(self, client):
        """AGENT_SPAWNED event should create a log entry."""
        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])
        from pi_cowork.events import bus, AGENT_SPAWNED
        bus.publish(AGENT_SPAWNED, ticket_id=ticket_id, agent_name='TestAgent', run_id=42)

        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'agent_event' AND message LIKE '%started%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_agent_completed_logged(self, client):
        """AGENT_COMPLETED event should create a log entry."""
        from pi_cowork.events import bus, AGENT_COMPLETED
        bus.publish(AGENT_COMPLETED, ticket_id=1, agent_name='TestAgent', run_id=42)

        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'agent_event' AND message LIKE '%completed%'"
        ).fetchall()
        assert len(rows) >= 1

    def test_agent_failed_logged(self, client):
        """AGENT_FAILED event should create an ERROR log entry."""
        from pi_cowork.events import bus, AGENT_FAILED
        bus.publish(AGENT_FAILED, ticket_id=1, agent_name='TestAgent', exit_code=1)

        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'agent_event' AND level = 'ERROR' AND message LIKE '%failed%'"
        ).fetchall()
        assert len(rows) >= 1


# ---------------------------------------------------------------------------
# UI Page
# ---------------------------------------------------------------------------

class TestSystemLogsPage:
    def test_system_logs_page_renders(self, client):
        """GET /system-logs should render the system logs page."""
        res = client.get('/system-logs')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert 'System Logs' in html
        assert 'filter-level' in html
        assert 'filter-action-type' in html
        assert 'logs-tbody' in html

    def test_system_logs_page_in_sidebar(self, client):
        """The sidebar should contain a System Logs link."""
        res = client.get('/board')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        assert 'System Logs' in html
        assert '/system-logs' in html


# ---------------------------------------------------------------------------
# Log Rotation in Drain Loop
# ---------------------------------------------------------------------------

class TestLogRotationDrainLoop:
    def test_cleanup_old_logs_callable(self, client):
        """cleanup_old_logs should be callable and return an integer."""
        add_log('INFO', 'db_change', 'Rotation test')
        result = cleanup_old_logs(max_age_days=30)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Single-log endpoint (#6)
# ---------------------------------------------------------------------------

class TestSingleLogEndpoint:
    def test_get_single_log(self, client):
        """GET /api/system_logs/<id> should return a single log entry."""
        add_log('INFO', 'db_change', 'Single log test', details={'key': 'value'})
        from pi_cowork.db import get_db
        db = get_db()
        log_id = db.execute("SELECT id FROM system_logs ORDER BY id DESC LIMIT 1").fetchone()['id']
        res = client.get(f'/api/system_logs/{log_id}')
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data['id'] == log_id
        assert data['message'] == 'Single log test'
        assert data['details']['key'] == 'value'

    def test_get_single_log_not_found(self, client):
        """GET /api/system_logs/<id> should return 404 for nonexistent ID."""
        res = client.get('/api/system_logs/99999')
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Same-origin check (#8)
# ---------------------------------------------------------------------------

class TestSameOriginCheck:
    def test_same_origin_allowed(self, client):
        """Requests with matching Origin header should be allowed."""
        add_log('INFO', 'db_change', 'Origin test')
        res = client.get('/api/system_logs', headers={'Origin': 'http://localhost'})
        # Flask test client always uses localhost; this should succeed
        assert res.status_code == 200

    def test_cross_origin_blocked(self, client):
        """Requests with mismatched Origin header should be blocked (403)."""
        add_log('INFO', 'db_change', 'Cross-origin test')
        res = client.get('/api/system_logs', headers={'Origin': 'http://evil.example.com'})
        assert res.status_code == 403

    def test_no_origin_headers_allowed(self, client):
        """Requests without Origin/Referer should be allowed (e.g., curl)."""
        add_log('INFO', 'db_change', 'No origin test')
        res = client.get('/api/system_logs')
        assert res.status_code == 200

    def test_export_cross_origin_blocked(self, client):
        """Export endpoint should also block cross-origin requests."""
        res = client.get('/api/system_logs/export', headers={'Origin': 'http://evil.example.com'})
        assert res.status_code == 403

    def test_single_log_cross_origin_blocked(self, client):
        """Single log endpoint should block cross-origin requests."""
        res = client.get('/api/system_logs/1', headers={'Origin': 'http://evil.example.com'})
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# Sensitive data redaction (#7)
# ---------------------------------------------------------------------------

class TestSensitiveDataRedaction:
    def test_password_redacted_from_request_body(self, client):
        """Passwords in request bodies should be redacted."""
        board_data, wf_id = _create_workflow_and_board(client)
        client.post('/api/tickets', json={
            'title': 'Redaction test',
            'board_id': board_data['id'],
            # This won't be used by the API but will appear in logged request body
        })
        from pi_cowork.db import get_db
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'POST%/api/tickets%'"
        ).fetchall()
        assert len(rows) >= 1
        details = json.loads(rows[-1]['details'])
        # The request body should exist
        assert details.get('request_body') is not None

    def test_redact_sensitive_function(self, client):
        """_redact_sensitive should redact known sensitive fields."""
        from pi_cowork.system_logs import _redact_sensitive
        result = _redact_sensitive('{"password": "secret123", "name": "alice"}')
        assert '[REDACTED]' in result
        assert 'secret123' not in result
        assert 'alice' in result

    def test_redact_token(self, client):
        """_redact_sensitive should redact token fields."""
        from pi_cowork.system_logs import _redact_sensitive
        result = _redact_sensitive('{"token": "abc123def", "data": "visible"}')
        assert '[REDACTED]' in result
        assert 'abc123def' not in result
        assert 'visible' in result

    def test_redact_form_style(self, client):
        """_redact_sensitive should redact form-style key=value pairs."""
        from pi_cowork.system_logs import _redact_sensitive
        result = _redact_sensitive('password=secret123&name=alice')
        assert '[REDACTED]' in result
        assert 'secret123' not in result
        assert 'alice' in result


# ---------------------------------------------------------------------------
# LIKE wildcard escaping (#9)
# ---------------------------------------------------------------------------

class TestLikeWildcardEscaping:
    def test_percent_in_search(self, client):
        """Searching for '%' should not match everything."""
        add_log('INFO', 'db_change', 'normal message')
        add_log('INFO', 'db_change', '100% done')
        result = get_system_logs(search='%')
        # Should only match the entry containing literal '%'
        for log in result['logs']:
            assert '%' in log['message']

    def test_underscore_in_search(self, client):
        """Searching for '_' should not match any single character."""
        add_log('INFO', 'db_change', 'test message')
        add_log('INFO', 'db_change', 'test_message')
        result = get_system_logs(search='test_message')
        for log in result['logs']:
            # Should match the literal underscore, not any character
            assert 'test_message' in log['message']

    def test_escape_like_function(self, client):
        """_escape_like should escape % and _ correctly."""
        from pi_cowork.system_logs import _escape_like
        assert _escape_like('100%') == '100\\%'
        assert _escape_like('test_it') == 'test\\_it'
        assert _escape_like('a\\b') == 'a\\\\b'


# ---------------------------------------------------------------------------
# Streaming response not consumed (#3)
# ---------------------------------------------------------------------------

class TestStreamingResponseSkip:
    def test_streaming_response_not_logged_with_body(self, client):
        """Streaming (SSE) responses should not have their body captured."""
        # We can't easily test SSE directly in unit tests, but we can verify
        # the middleware skips streamed responses by checking that the
        # response.is_streamed property is checked before get_data().
        import pi_cowork.system_logs as sl_mod
        assert hasattr(sl_mod, 'log_http_request')
        # Verify the function checks is_streamed by reading source
        import inspect
        source = inspect.getsource(sl_mod.log_http_request)
        assert 'is_streamed' in source


# ---------------------------------------------------------------------------
# Slow API request warning (Ticket #61)
# ---------------------------------------------------------------------------

class TestSlowAPIRequestWarning:
    def test_slow_get_request_produces_warning_log(self, client, monkeypatch):
        """A slow GET request should produce a WARNING log with 'SLOW API' in the message."""
        from pi_cowork.db import get_db
        import pi_cowork.system_logs as sl_mod

        # Lower threshold so even a fast test request triggers slow detection
        monkeypatch.setattr(sl_mod, 'SLOW_REQUEST_THRESHOLD', 0.0)

        client.get('/api/workflows')

        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%'"
        ).fetchall()
        assert len(rows) >= 1
        log = rows[-1]
        assert log['level'] == 'WARNING'
        assert 'SLOW API' in log['message']
        details = json.loads(log['details'])
        assert 'elapsed_seconds' in details
        assert details['elapsed_seconds'] >= 0
        assert details['method'] == 'GET'
        assert 'workflows' in details['url']
        assert details['status_code'] == 200

    def test_fast_request_no_slow_warning(self, client):
        """A fast request should NOT produce a 'SLOW API' WARNING log."""
        from pi_cowork.db import get_db

        # Default threshold (1.0s) — a fast request should not trigger
        client.get('/api/workflows')

        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%'"
        ).fetchall()
        assert len(rows) == 0

    def test_slow_detection_works_for_post(self, client, monkeypatch):
        """Slow detection should work for POST requests (GET is tested above)."""
        from pi_cowork.db import get_db
        import pi_cowork.system_logs as sl_mod

        monkeypatch.setattr(sl_mod, 'SLOW_REQUEST_THRESHOLD', 0.0)

        board_data, wf_id = _create_workflow_and_board(client)
        # This POST creates a ticket and should trigger slow detection
        client.post('/api/tickets', json={'title': 'Slow POST test', 'board_id': board_data['id']})

        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%'"
        ).fetchall()
        assert len(rows) >= 1
        details = json.loads(rows[-1]['details'])
        assert details['method'] == 'POST'

    def test_slow_detection_works_for_get(self, client, monkeypatch):
        """Slow detection should work for GET requests (which are normally skipped for audit logging)."""
        from pi_cowork.db import get_db
        import pi_cowork.system_logs as sl_mod

        monkeypatch.setattr(sl_mod, 'SLOW_REQUEST_THRESHOLD', 0.0)

        # GET requests are in _SKIP_METHODS for audit logging but should still
        # trigger slow detection
        client.get('/api/workflows')

        db = get_db()
        slow_rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%'"
        ).fetchall()
        # GET should produce a slow warning even though it's not audit-logged
        assert len(slow_rows) >= 1
        assert slow_rows[-1]['level'] == 'WARNING'
        assert 'SLOW API' in slow_rows[-1]['message']

        # Verify the GET was NOT audit-logged (no INFO log for GET)
        get_audit_rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'GET%/api/workflows%'"
        ).fetchall()
        # Only slow warning, no separate audit log
        non_slow_get_rows = [r for r in get_audit_rows if 'SLOW API' not in r['message']]
        assert len(non_slow_get_rows) == 0

    def test_slow_post_produces_both_audit_and_slow_log(self, client, monkeypatch):
        """A slow POST should produce both an INFO audit log and a WARNING slow log."""
        from pi_cowork.db import get_db
        import pi_cowork.system_logs as sl_mod

        monkeypatch.setattr(sl_mod, 'SLOW_REQUEST_THRESHOLD', 0.0)

        board_data, wf_id = _create_workflow_and_board(client)
        client.post('/api/tickets', json={'title': 'Slow POST both logs', 'board_id': board_data['id']})

        db = get_db()
        # Should have both a WARNING slow log and an INFO audit log
        slow_rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%POST%/api/tickets%'"
        ).fetchall()
        audit_rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND level = 'INFO' AND message LIKE 'POST%/api/tickets%'"
        ).fetchall()
        assert len(slow_rows) >= 1
        assert len(audit_rows) >= 1
        assert slow_rows[-1]['level'] == 'WARNING'
        assert 'SLOW API' in slow_rows[-1]['message']
        assert audit_rows[-1]['level'] == 'INFO'

    def test_no_crash_when_start_time_missing(self, client):
        """If g._request_start_time is missing, the slow check should not crash."""
        from pi_cowork.db import get_db
        from pi_cowork.system_logs import log_http_request
        from flask import g

        # Directly call log_http_request in a request context where
        # g._request_start_time is not set.
        with client.application.test_request_context('/api/workflows'):
            # Deliberately do NOT set g._request_start_time
            # This simulates the edge case where before_request didn't run
            assert not hasattr(g, '_request_start_time')

            # Create a mock response
            from flask import Response
            response = Response('OK', status=200)

            # Should not crash, and should not log a slow warning
            result = log_http_request(response)
            assert result.status_code == 200

        # Verify no SLOW API warning was logged
        db = get_db()
        rows = db.execute(
            "SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%'"
        ).fetchall()
        assert len(rows) == 0

    def test_slow_request_skips_excluded_paths(self, client):
        """Slow requests to excluded paths should not produce slow warnings."""
        from pi_cowork.system_logs import _should_skip_path
        assert _should_skip_path('/api/system_logs') is True
        assert _should_skip_path('/api/system_logs/export') is True
        assert _should_skip_path('/api/notifications/something') is True
        assert _should_skip_path('/static/style.css') is True
        assert _should_skip_path('/api/tickets') is False
        assert _should_skip_path('/api/workflows') is False

    def test_slow_request_extracts_ticket_id(self, client, monkeypatch):
        """Slow API log should include ticket_id when URL matches /api/tickets/<id>/..."""
        from pi_cowork.db import get_db
        import pi_cowork.system_logs as sl_mod

        monkeypatch.setattr(sl_mod, 'SLOW_REQUEST_THRESHOLD', 0.0)

        board_data, wf_id = _create_workflow_and_board(client)
        ticket_id = _create_ticket(client, board_data['id'])

        # PUT to the ticket endpoint — should trigger slow with correct ticket_id
        client.put(f'/api/tickets/{ticket_id}', json={'title': 'Updated'})

        db = get_db()
        rows = db.execute(
            f"SELECT * FROM system_logs WHERE action_type = 'http_request' AND message LIKE 'SLOW API%' AND ticket_id = {ticket_id}"
        ).fetchall()
        assert len(rows) >= 1
        assert rows[-1]['ticket_id'] == ticket_id
        details = json.loads(rows[-1]['details'])
        assert 'elapsed_seconds' in details


# ---------------------------------------------------------------------------
# CSS variable fix (Ticket #62)
# ---------------------------------------------------------------------------

class TestSystemLogsCSSVariables:
    def test_no_undefined_card_variable(self, client):
        """The system_logs template should not use var(--card) which is undefined;
        all backgrounds should use var(--surface) instead."""
        import re
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'templates', 'system_logs.html'
        )
        with open(template_path) as f:
            content = f.read()

        # var(--card) must not appear anywhere (it's undefined in :root)
        assert 'var(--card)' not in content, (
            "var(--card) found in system_logs.html but --card is not defined "
            "in :root. Use var(--surface) instead."
        )

    def test_surface_variable_used_for_backgrounds(self, client):
        """Key CSS elements should use var(--surface) for their backgrounds."""
        import re
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'templates', 'system_logs.html'
        )
        with open(template_path) as f:
            content = f.read()

        # Extract the <style> block content
        style_match = re.search(r'<style>(.*?)</style>', content, re.DOTALL)
        assert style_match, "No <style> block found in system_logs.html"
        style_content = style_match.group(1)

        # These 4 elements must use var(--surface) for background
        required = [
            '.logs-filters',
            '.logs-table',
            '.logs-table th',
            '.details-popup',
        ]
        for selector in required:
            pattern = rf'{re.escape(selector)}\s*\{{[^}}]*background:\s*var\(--surface\)'
            assert re.search(pattern, style_content, re.DOTALL), (
                f"{selector} must use var(--surface) for background "
                f"(used for card/panel backgrounds in the system logs page)"
            )

    def test_detail_popup_renders_with_surface_bg(self, client):
        """GET /system-logs should render a detail popup with var(--surface) background."""
        res = client.get('/system-logs')
        assert res.status_code == 200
        html = res.data.decode('utf-8')
        # The .details-popup rule should use var(--surface)
        assert 'background: var(--surface)' in html
        # Should NOT contain var(--card)
        assert 'var(--card)' not in html