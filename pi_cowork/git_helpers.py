"""Git helpers for agent workspace branch management.

Ensures every ticket gets its own branch checked out before the agent spawns,
saving LLM tokens by handling git boilerplate in Python rather than in the prompt.

Git operations are only performed when the workflow has ``git_enabled=True``.
When disabled, the branch field is hidden from API responses and no git
operations are attempted during agent spawning.
"""

import logging
import os
import re
import subprocess

from pi_cowork.db import run_db

logger = logging.getLogger(__name__)


def _git(cmd, cwd, check=False):
    """Run a git command and return CompletedProcess."""
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)
    except Exception as e:
        class _FakeResult:
            returncode = -1
            stdout = ''
            stderr = str(e)
        return _FakeResult()


def is_git_repo(path):
    """Check if a directory is inside a git repository."""
    return os.path.isdir(os.path.join(path, '.git'))


def _get_default_remote_branch(cwd):
    """Determine the default remote branch (e.g. origin/main).

    Uses ``git symbolic-ref refs/remotes/origin/HEAD``, falling back to
    probing ``origin/main`` and ``origin/master``.
    """
    result = _git(['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'], cwd=cwd)
    if result.returncode == 0 and result.stdout.strip():
        ref = result.stdout.strip()
        return ref.replace('refs/remotes/', '')
    # Fallback: try main, then master
    for fb in ['main', 'master']:
        r = _git(['git', 'rev-parse', '--verify', f'origin/{fb}'], cwd=cwd)
        if r.returncode == 0:
            return f'origin/{fb}'
    return None


def get_current_branch(cwd):
    """Return the currently checked-out branch name, or None."""
    result = _git(['git', 'branch', '--show-current'], cwd=cwd)
    if result.returncode == 0:
        return result.stdout.strip() or None
    return None


def make_branch_name(ticket_id, title):
    """Generate a kebab-case branch name from a ticket id and title.

    Format: ``ticket-<id>-<kebab-case-slug>``
    - Lowercased, non-alphanumeric replaced with hyphens
    - Consecutive hyphens collapsed
    - Slug portion truncated to 60 characters
    """
    slug = re.sub(r'[^\w\s-]', '', (title or 'untitled').lower())
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    if len(slug) > 60:
        slug = slug[:60]
    return f"ticket-{ticket_id}-{slug}"


def branch_exists(working_directory, branch_name):
    """Check if a branch exists locally or on the remote."""
    local = _git(['git', 'rev-parse', '--verify', branch_name], cwd=working_directory)
    if local.returncode == 0:
        return True
    remote = _git(['git', 'rev-parse', '--verify', f'origin/{branch_name}'], cwd=working_directory)
    return remote.returncode == 0


def ensure_ticket_branch(working_directory, ticket_id, ticket_title, existing_branch=None):
    """Ensure the ticket's branch exists and is checked out.

    Returns the branch name on success, or None if the directory is not a
    git repo or no remote default branch can be determined.
    """
    if not working_directory or not is_git_repo(working_directory):
        return None

    branch = existing_branch or make_branch_name(ticket_id, ticket_title)

    default_remote = _get_default_remote_branch(working_directory)
    if not default_remote:
        logger.warning("Could not determine default remote branch in %s", working_directory)
        return None

    # Stash any dirty working tree before branch operations so that
    # checkout / rebase cannot fail because of uncommitted files.
    stashed = False
    status_res = _git(['git', 'status', '--porcelain'], cwd=working_directory)
    if status_res.returncode == 0 and status_res.stdout.strip():
        stash_res = _git(['git', 'stash', 'push', '-m', 'pi-cowork auto-stash'], cwd=working_directory)
        if stash_res.returncode == 0:
            stashed = True
        else:
            logger.warning("git stash failed in %s: %s", working_directory, stash_res.stderr.strip())

    # Fetch quietly
    fetch_res = _git(['git', 'fetch', 'origin'], cwd=working_directory)
    if fetch_res.returncode != 0:
        logger.warning("git fetch failed in %s: %s", working_directory, fetch_res.stderr.strip())

    # Check if branch already exists locally
    verify = _git(['git', 'rev-parse', '--verify', branch], cwd=working_directory)
    if verify.returncode == 0:
        # Exists: checkout and rebase onto latest default so the agent works
        # from the most up-to-date base, reducing merge conflicts later.
        checkout_res = _git(['git', 'checkout', branch], cwd=working_directory)
        if checkout_res.returncode != 0:
            logger.error("git checkout %s failed: %s", branch, checkout_res.stderr.strip())
            if stashed:
                _git(['git', 'stash', 'pop'], cwd=working_directory)
            return None
        rebase_res = _git(['git', 'rebase', default_remote], cwd=working_directory)
        if rebase_res.returncode != 0:
            logger.warning(
                "git rebase %s onto %s failed: %s; aborting rebase",
                branch, default_remote, rebase_res.stderr.strip()
            )
            _git(['git', 'rebase', '--abort'], cwd=working_directory)
    else:
        create_res = _git(['git', 'checkout', '-b', branch, default_remote], cwd=working_directory)
        if create_res.returncode != 0:
            logger.error(
                "Failed to create branch %s from %s: %s",
                branch, default_remote, create_res.stderr.strip()
            )
            if stashed:
                _git(['git', 'stash', 'pop'], cwd=working_directory)
            return None

    # Restore stashed changes so the agent can continue interrupted work.
    if stashed:
        pop_res = _git(['git', 'stash', 'pop'], cwd=working_directory)
        if pop_res.returncode != 0:
            logger.warning(
                "git stash pop failed in %s after switching to %s: %s",
                working_directory, branch, pop_res.stderr.strip()
            )

    # Persist branch on ticket if it changed or was generated
    if existing_branch != branch:
        run_db("UPDATE tickets SET branch = ? WHERE id = ?", (branch, ticket_id))

    return branch