import json
import os
from unittest.mock import MagicMock, patch

import app as app_module
from pi_cowork import config


def test_update_page_without_git(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with patch("pi_cowork.update._git_available", return_value=False):
        res = client.get("/update")
        assert res.status_code == 200
        assert b"unknown" in res.data
        assert b"Check for updates" in res.data


def test_update_page_with_git(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._get_git_info", return_value={"branch": "main", "commit": "abc1234"}),
    ):
        res = client.get("/update")
        assert res.status_code == 200
        assert b"main" in res.data
        assert b"abc1234" in res.data


def test_update_check_up_to_date(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["fetch"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "0"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/check", follow_redirects=True)
        assert res.status_code == 200
        assert b"up to date" in res.data


def test_update_check_behind(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["fetch"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "5"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/check", follow_redirects=True)
        assert res.status_code == 200
        assert b"5 new commit" in res.data


def test_update_check_git_fetch_fails(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "fatal: unable to access"
        result.stdout = ""
        mock_git.return_value = result
        res = client.post("/update/check", follow_redirects=True)
        assert res.status_code == 200
        assert b"Git fetch failed" in res.data


def test_update_run_dirty_working_tree(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["status", "--porcelain"]:
                result.stdout = " M app.py\n"
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "3"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200
        assert b"uncommitted changes" in res.data


def test_update_run_no_updates(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["status", "--porcelain"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "0"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200
        assert b"No updates to apply" in res.data


def test_update_run_success(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(app_module, "DATABASE", str(tmp_path / "pi-cowork.db"))
    (tmp_path / "pi-cowork.db").write_text("dummy db")

    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
        patch("pi_cowork.update.os._exit") as mock_exit,
        patch("pi_cowork.update.threading.Thread") as mock_thread,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["status", "--porcelain"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "2"
            elif args == ["pull"]:
                result.stdout = "Updating...\n"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200
        # Pre-restart flash: shows "Installing" message (same PID)
        assert b"Installing update" in res.data or b"Update installed successfully" in res.data
        # Backup should have been created
        backups_dir = tmp_path / "backups"
        assert backups_dir.exists()
        assert any(backups_dir.iterdir())
        # Reload sentinel should exist
        assert (tmp_path / ".reload").exists()
        # Update state file should exist (NOT deleted before restart)
        state_path = tmp_path / ".update-state.json"
        assert state_path.exists()
        mock_thread.assert_called_once()


def test_update_run_git_pull_fails(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(app_module, "DATABASE", str(tmp_path / "pi-cowork.db"))
    (tmp_path / "pi-cowork.db").write_text("dummy db")
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["status", "--porcelain"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "2"
            elif args == ["pull"]:
                result.returncode = 1
                result.stderr = "merge conflict"
                result.stdout = ""
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200
        assert b"Git pull failed" in res.data


def test_update_run_not_a_git_repo(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=False),
    ):
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200
        assert b"Not a git repository" in res.data


def test_shutdown_uses_os_exit(client, monkeypatch, tmp_path):
    """Verify _shutdown uses os._exit(0) for immediate, reliable termination
    (instead of SIGTERM, which hangs due to Werkzeug's server_close joining
    long-lived SSE threads)."""
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr(app_module, "DATABASE", str(tmp_path / "pi-cowork.db"))
    (tmp_path / "pi-cowork.db").write_text("dummy db")

    with (
        patch("pi_cowork.update._git_available", return_value=True),
        patch("pi_cowork.update._git_dir_exists", return_value=True),
        patch("pi_cowork.update._run_git") as mock_git,
        patch("pi_cowork.update.os._exit") as mock_exit,
        patch("pi_cowork.update.threading.Thread") as mock_thread,
    ):

        def side_effect(args, cwd=None):
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if args == ["status", "--porcelain"]:
                result.stdout = ""
            elif args == ["rev-list", "--count", "HEAD..@{u}"]:
                result.stdout = "2"
            elif args == ["pull"]:
                result.stdout = "Updating...\n"
            return result

        mock_git.side_effect = side_effect
        res = client.post("/update/run", follow_redirects=True)
        assert res.status_code == 200

        # Verify Thread was created with _shutdown as target
        mock_thread.assert_called_once()
        assert mock_thread.call_args[1]["target"].__name__ == "_shutdown"
        assert mock_thread.call_args[1]["daemon"] is True

        # Call _shutdown directly to verify it uses os._exit(0)
        _shutdown_fn = mock_thread.call_args[1]["target"]
        _shutdown_fn()
        mock_exit.assert_called_once_with(0)


def test_persistent_flash_pre_restart_same_pid(client, monkeypatch, tmp_path):
    """When the state file PID matches the current process PID (pre-restart),
    the 'installing' message should be shown and the file should NOT be deleted
    so it survives a restart."""
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    state = {
        "level": "success",
        "message": "Update installed successfully. The app has been restarted.",
        "timestamp": "2026-05-14T22:00:00+00:00",
        "pid": os.getpid(),  # same PID = pre-restart
    }
    state_path = tmp_path / ".update-state.json"
    state_path.write_text(json.dumps(state))

    res = client.get("/update")
    assert res.status_code == 200
    # Pre-restart: shows "Installing" message
    assert b"Installing update" in res.data
    # File should NOT be deleted (preserved for post-restart)
    assert state_path.exists()


def test_persistent_flash_post_restart_different_pid(client, monkeypatch, tmp_path):
    """When the state file PID differs from the current process PID (post-restart),
    the 'applied successfully' message should be shown and the file should be deleted."""
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    state = {
        "level": "success",
        "message": "Update installed successfully. The app has been restarted.",
        "timestamp": "2026-05-14T22:00:00+00:00",
        "pid": 99999,  # different PID = post-restart
    }
    state_path = tmp_path / ".update-state.json"
    state_path.write_text(json.dumps(state))

    res = client.get("/update")
    assert res.status_code == 200
    # Post-restart: shows "applied successfully" message
    assert b"Update applied successfully" in res.data
    # File should be deleted after being read
    assert not state_path.exists()


def test_persistent_flash_no_pid_backward_compat(client, monkeypatch, tmp_path):
    """When the state file has no pid field (backwardCompat), treat it as
    pre-restart (show 'installing' message, don't delete the file)."""
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    state = {
        "level": "success",
        "message": "Old-style message.",
        "timestamp": "2026-05-14T22:00:00+00:00",
    }
    state_path = tmp_path / ".update-state.json"
    state_path.write_text(json.dumps(state))

    res = client.get("/update")
    assert res.status_code == 200
    # No PID = pre-restart: shows "Installing" message
    assert b"Installing update" in res.data
    # File should NOT be deleted
    assert state_path.exists()


def test_persistent_flash_on_non_update_page_post_restart(client, monkeypatch, tmp_path):
    """After a restart (different PID), the flash message should appear on
    any page and be cleared after display."""
    monkeypatch.setattr(config, "PROJECT_ROOT", str(tmp_path))
    state = {
        "level": "success",
        "message": "Update installed successfully. The app has been restarted.",
        "timestamp": "2026-05-14T22:00:00+00:00",
        "pid": 99999,  # different PID = post-restart
    }
    state_path = tmp_path / ".update-state.json"
    state_path.write_text(json.dumps(state))

    res = client.get("/")
    assert res.status_code == 302  # index redirects to /board
    # Follow redirect manually
    res = client.get("/board")
    assert res.status_code == 200
    assert b"Update applied successfully" in res.data
    assert not state_path.exists()
