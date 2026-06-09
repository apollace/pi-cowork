import json
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("PI_MAX_PARALLEL", "100")
os.environ.setdefault("PI_MAX_PER_HOUR", "100")

import contextlib

from app import app as flask_app
from app import init_db
from pi_cowork import agents as agents_module
from pi_cowork import config

DEFAULT_MAX_PARALLEL = config.PI_MAX_PARALLEL
DEFAULT_MAX_PER_HOUR = config.PI_MAX_PER_HOUR


def _fake_start_watcher(proc, run_id, ticket_id, agent_name, log_f):
    """In tests, skip the watcher thread. The log reader mock closes log_f."""
    pass


def _fake_log_reader(pipe, log_f):
    """In tests, don't spawn a reader thread; just close log_f safely."""
    with contextlib.suppress(ValueError, OSError, AttributeError):
        pipe.close()
    with contextlib.suppress(ValueError, OSError):
        log_f.close()


HUMAN_ACTION_SECRET_FOR_TESTS = "test-human-action-secret-12345678901234567890123456789012"  # noqa: S105


@pytest.fixture(autouse=True)
def mock_watcher(monkeypatch):
    """Replace _start_watcher with a no-op for all tests."""
    monkeypatch.setattr(agents_module, "_start_watcher", _fake_start_watcher)


@pytest.fixture(autouse=True)
def mock_log_reader(monkeypatch):
    """Replace _start_log_reader with a no-op for all tests."""
    monkeypatch.setattr(agents_module, "_start_log_reader", _fake_log_reader)


@pytest.fixture(autouse=True)
def reset_limits(monkeypatch):
    config.PI_MAX_PARALLEL = DEFAULT_MAX_PARALLEL
    config.PI_MAX_PER_HOUR = DEFAULT_MAX_PER_HOUR
    monkeypatch.setenv("PI_MAX_PARALLEL", str(DEFAULT_MAX_PARALLEL))
    monkeypatch.setenv("PI_MAX_PER_HOUR", str(DEFAULT_MAX_PER_HOUR))


@pytest.fixture
def client():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    flask_app.config["TESTING"] = True
    flask_app.config["DATABASE"] = db_path
    # Set a predictable human-action secret for test assertions
    flask_app.config["HUMAN_ACTION_SECRET"] = HUMAN_ACTION_SECRET_FOR_TESTS

    with flask_app.test_client() as client:
        with flask_app.app_context():
            init_db(flask_app)
        # Ensure _drain_app references the Flask app so that watcher threads
        # (which run outside any request context) can push an app context.
        agents_module._drain_app = flask_app
        yield client
        agents_module._drain_app = None

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def default_workflow(client):
    """The seeded default workflow"""
    res = client.get("/api/workflows")
    data = json.loads(res.data)
    return data[0] if data else None


@pytest.fixture
def default_board(client):
    """The seeded default board"""
    res = client.get("/api/boards")
    data = json.loads(res.data)
    return data[0] if data else None


@pytest.fixture
def new_workflow(client):
    res = client.post(
        "/api/workflows",
        json={
            "name": "Test Workflow",
            "description": "A test workflow",
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)


@pytest.fixture(autouse=True)
def mock_model_ids(monkeypatch):
    """Return a fixed list of valid model ids so tests don't depend on pi CLI."""
    from pi_cowork.api import pi_models

    def fake():
        return (
            "gpt-4o",
            "gpt-4",
            "custom-model",
            "compact-model",
            "claude-3",
            "claude-3-opus",
            "claude-3-opus-20240229",
            "agent-model",
            "status-model",
            "both-model",
            "plain-model",
        )

    monkeypatch.setattr(pi_models, "get_model_ids", fake)
    # Module-level imports in agents_api/statuses/assistant also need patching
    import pi_cowork.api.agents_api as _agents_api
    import pi_cowork.api.statuses as _statuses
    import pi_cowork.api.ticket_status_overrides as _tso
    import pi_cowork.assistant as _assistant

    monkeypatch.setattr(_agents_api, "get_model_ids", fake)
    monkeypatch.setattr(_statuses, "get_model_ids", fake)
    monkeypatch.setattr(_assistant, "get_model_ids", fake)
    monkeypatch.setattr(_tso, "get_model_ids", fake)


@pytest.fixture(autouse=True)
def temp_skills_folder(monkeypatch):
    """Use a temporary directory for skills so tests don't pollute workspace/skills."""
    tmpdir = tempfile.mkdtemp(prefix="pi-cowork-skills-")
    monkeypatch.setenv("PI_SKILLS_FOLDER", tmpdir)
    # Also patch get_config directly since it may cache env reads
    import pi_cowork.skill_packages as _sp

    original_get_skills_folder = _sp.get_skills_folder

    def _fake_get_skills_folder():
        return tmpdir

    monkeypatch.setattr(_sp, "get_skills_folder", _fake_get_skills_folder)
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)
    monkeypatch.setattr(_sp, "get_skills_folder", original_get_skills_folder)


@pytest.fixture
def new_board(client, new_workflow):
    res = client.post(
        "/api/boards",
        json={
            "name": "Test Board",
            "workflow_id": new_workflow["id"],
        },
    )
    assert res.status_code == 201
    return json.loads(res.data)
