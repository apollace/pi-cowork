"""Tests for pi_cowork.git_helpers module."""

import os
import subprocess
from unittest.mock import MagicMock, patch


def _init_git_repo(path):
    """Create a minimal git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)
    # Create initial commit
    readme = os.path.join(path, "README.md")
    with open(readme, "w") as f:
        f.write("# Test\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, capture_output=True, check=True)

    # Setup origin remote pointing to self HEAD
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, capture_output=True, check=True)
    # Create a bare repo for origin
    bare_path = path + "-origin.git"
    subprocess.run(["git", "clone", "--bare", ".", bare_path], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "remote", "add", "origin", bare_path], cwd=path, capture_output=True, check=False)
    subprocess.run(["git", "remote", "set-url", "origin", bare_path], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=path, capture_output=True, check=True)
    # Set HEAD so symbolic-ref works
    subprocess.run(
        ["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    return bare_path


# ── make_branch_name ──


def test_make_branch_name_basic():
    from pi_cowork.git_helpers import make_branch_name

    assert make_branch_name(78, "Git option for a workflow") == "ticket-78-git-option-for-a-workflow"


def test_make_branch_name_special_chars():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(1, "Hello, World! (v2.0)")
    assert result == "ticket-1-hello-world-v20"


def test_make_branch_name_unicode():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(5, "Café naïve résumé")
    # Unicode letters should be stripped since \w matches unicode in Python
    # but we use lower() + re.sub for non-word chars
    assert result.startswith("ticket-5-")


def test_make_branch_name_long_title():
    from pi_cowork.git_helpers import make_branch_name

    long_title = "a" * 100
    result = make_branch_name(10, long_title)
    # Slug portion should be at most 60 chars, total: 'ticket-10-' + 60 char slug
    slug_part = result.replace("ticket-10-", "")
    assert len(slug_part) <= 60


def test_make_branch_name_empty_title():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(3, "")
    assert result == "ticket-3-untitled"


def test_make_branch_name_none_title():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(3, None)
    assert result == "ticket-3-untitled"


def test_make_branch_name_collapsed_hyphens():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(1, "foo---bar   baz")
    assert result == "ticket-1-foo-bar-baz"


def test_make_branch_name_leading_trailing_hyphens():
    from pi_cowork.git_helpers import make_branch_name

    result = make_branch_name(1, "  hello world  ")
    # Leading/trailing spaces become hyphens, then stripped
    assert result == "ticket-1-hello-world"


# ── is_git_repo ──


def test_is_git_repo_true(tmp_path):
    from pi_cowork.git_helpers import is_git_repo

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    assert is_git_repo(repo) is True


def test_is_git_repo_false(tmp_path):
    from pi_cowork.git_helpers import is_git_repo

    nongit = str(tmp_path / "notarepo")
    os.makedirs(nongit)
    assert is_git_repo(nongit) is False


# ── get_current_branch ──


def test_get_current_branch(tmp_path):
    from pi_cowork.git_helpers import get_current_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _init_git_repo(repo)
    assert get_current_branch(repo) == "main"


def test_get_current_branch_not_git(tmp_path):
    from pi_cowork.git_helpers import get_current_branch

    nongit = str(tmp_path / "notarepo")
    os.makedirs(nongit)
    assert get_current_branch(nongit) is None


# ── branch_exists ──


def test_branch_exists_local(tmp_path):
    from pi_cowork.git_helpers import branch_exists

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _init_git_repo(repo)
    # Create a branch
    subprocess.run(["git", "checkout", "-b", "test-branch"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)
    assert branch_exists(repo, "test-branch") is True
    assert branch_exists(repo, "nonexistent-branch") is False


# ── ensure_ticket_branch ──


def test_ensure_ticket_branch_creates_branch(tmp_path):
    from pi_cowork.git_helpers import ensure_ticket_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    bare_path = _init_git_repo(repo)

    # Call with no existing branch
    with patch("pi_cowork.git_helpers.run_db"):
        result = ensure_ticket_branch(repo, 42, "My feature task")
    assert result is not None
    assert result == "ticket-42-my-feature-task"
    # Verify branch is checked out
    current = subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True)
    assert current.stdout.strip() == result


def test_ensure_ticket_branch_existing_branch(tmp_path):
    from pi_cowork.git_helpers import ensure_ticket_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    bare_path = _init_git_repo(repo)

    # Create a branch first
    branch_name = "ticket-99-existing-branch"
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)

    # Now call ensure_ticket_branch with the existing branch name
    with patch("pi_cowork.git_helpers.run_db"):
        result = ensure_ticket_branch(repo, 99, "existing branch", existing_branch=branch_name)
    assert result == branch_name


def test_ensure_ticket_branch_not_git_repo(tmp_path):
    from pi_cowork.git_helpers import ensure_ticket_branch

    nongit = str(tmp_path / "notarepo")
    os.makedirs(nongit)
    result = ensure_ticket_branch(nongit, 1, "test")
    assert result is None


def test_ensure_ticket_branch_persists_new_branch(tmp_path):
    from pi_cowork.git_helpers import ensure_ticket_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    bare_path = _init_git_repo(repo)

    mock_run_db = MagicMock()
    with patch("pi_cowork.git_helpers.run_db", mock_run_db):
        result = ensure_ticket_branch(repo, 55, "persist test")

    assert result is not None
    # run_db should have been called to persist the branch
    mock_run_db.assert_called_once_with(
        "UPDATE tickets SET branch = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (result, 55)
    )


def test_ensure_ticket_branch_no_persist_if_existing_match(tmp_path):
    from pi_cowork.git_helpers import ensure_ticket_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    bare_path = _init_git_repo(repo)

    # Create branch first
    branch_name = "ticket-33-my-task"
    subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True, check=True)

    mock_run_db = MagicMock()
    with patch("pi_cowork.git_helpers.run_db", mock_run_db):
        # existing_branch matches the generated name, so no DB update needed
        result = ensure_ticket_branch(repo, 33, "my task", existing_branch=branch_name)

    assert result == branch_name
    # run_db should NOT be called since existing_branch matches
    mock_run_db.assert_not_called()


# ── _get_default_remote_branch ──


def test_get_default_remote_branch(tmp_path):
    from pi_cowork.git_helpers import _get_default_remote_branch

    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    _init_git_repo(repo)
    result = _get_default_remote_branch(repo)
    assert result is not None
    assert "main" in result


def test_get_default_remote_branch_not_git(tmp_path):
    from pi_cowork.git_helpers import _get_default_remote_branch

    nongit = str(tmp_path / "notarepo")
    os.makedirs(nongit)
    result = _get_default_remote_branch(nongit)
    assert result is None
