"""Dedicated API-token management for spawned agents.

When authentication is enabled, every (agent, ticket) pair gets its own API
token named ``agent-<agent_id>-ticket-<ticket_id>``.  The plaintext token is
cached in the agent's session directory so that warm spawns reuse the same
token.  All dedicated agent tokens are revoked when authentication is disabled.
"""

import hashlib
from pathlib import Path

from pi_cowork.auth import generate_api_token, is_auth_enabled, store_api_token
from pi_cowork.db import query_db, run_db
from pi_cowork.models import get_api_token


def _get_first_user_id():
    """Return the id of the first user, or None if no users exist."""
    row = query_db("SELECT id FROM users ORDER BY id LIMIT 1", one=True)
    return row["id"] if row else None


def _token_cache_path(session_dir):
    return Path(session_dir) / "agent_api_token"


def get_or_create_agent_api_token(agent_id, ticket_id, session_dir):
    """Return a dedicated API token for this agent/ticket pair.

    * If auth is disabled, returns ``None``.
    * Reuses a cached plaintext token in ``session_dir/agent_api_token`` when
      its SHA-256 hash is still present in ``api_tokens``.
    * Otherwise generates a new token, deletes any older row with the same
      token name, stores the new hash, writes the plaintext to the session
      cache, and returns the plaintext token.
    """
    if not is_auth_enabled():
        return None

    token_name = f"agent-{agent_id}-ticket-{ticket_id}"
    cache_path = _token_cache_path(session_dir)

    # Try to reuse a cached token.
    if cache_path.exists():
        cached = cache_path.read_text().strip()
        if cached:
            cached_hash = hashlib.sha256(cached.encode("utf-8")).hexdigest()
            row = get_api_token(cached_hash)
            if row and row["name"] == token_name:
                return cached

    user_id = _get_first_user_id()
    if user_id is None:
        return None

    token, token_hash = generate_api_token()

    # Delete any previous token with the same name before inserting.
    run_db("DELETE FROM api_tokens WHERE name = ?", (token_name,))
    store_api_token(user_id, token_name, token_hash)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(token)
    return token


def revoke_agent_api_tokens():
    """Delete all dedicated agent API tokens from the database."""
    run_db("DELETE FROM api_tokens WHERE name LIKE 'agent-%-ticket-%'")
