"""Authentication engine for pi-CoWork.

Provides opt-in password hashing, session management, API token validation,
and a ``before_request`` gate that is transparent when auth is disabled.
"""

import hashlib
import secrets
from urllib.parse import quote

from flask import (
    g,
    jsonify,
    redirect,
    request,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

from pi_cowork.config import get_config
from pi_cowork.db import query_db
from pi_cowork.models import (
    create_api_token as _create_api_token,
)
from pi_cowork.models import (
    get_api_token,
    get_user_by_id,
    touch_api_token,
)

# Routes that are reachable without authentication even when auth is enabled.
_EXEMPT_PATHS = {
    "/login",
    "/api/auth/setup-needed",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/events/stream",
}


def is_auth_enabled():
    """Return True when the auth_enabled setting is on."""
    return bool(get_config("auth_enabled"))


def require_session():
    """Return True if a browser session exists, otherwise an HTTP 401 response.

    For use by human-only /api/auth endpoints that must never accept API tokens.
    """
    if session.get("user_id"):
        return True
    return jsonify({"error": "Authentication required"}), 401


def _setup_is_first_run():
    """Return True only when the users table is empty (first-run setup)."""
    try:
        row = query_db("SELECT COUNT(*) AS c FROM users", one=True)
        return row["c"] == 0 if row else False
    except Exception:
        return False


def hash_password(plain):
    """Hash a plain-text password for storage."""
    return generate_password_hash(plain)


def verify_password(plain, hash_):
    """Verify a plain-text password against a stored hash."""
    return check_password_hash(hash_, plain)


def create_session(user_id):
    """Create a browser session for the given user and rotate the cookie.

    ``session.clear()`` followed by setting ``user_id`` replaces the previous
    session content, which mitigates session fixation attacks for Flask's
    client-side cookie sessions.
    """
    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    session.modified = True


def clear_session():
    """Remove the user id from the browser session."""
    session.pop("user_id", None)
    session.modified = True


def current_user():
    """Return the currently logged-in user dict, or None.

    Looks up ``session["user_id"]`` once per request and caches the result on
    Flask's ``g`` object.
    """
    if hasattr(g, "current_user"):
        return g.current_user

    user_id = session.get("user_id")
    if not user_id:
        g.current_user = None
        return None

    user = get_user_by_id(user_id)
    g.current_user = user
    return user


def generate_api_token():
    """Return ``(token, token_hash)`` for a new API token.

    The token is a URL-safe random string; only its SHA-256 hash is stored in
    the database so a leaked DB cannot be used to impersonate agents.
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, token_hash


def validate_api_token(token):
    """Validate an API token and return its owning user, or None.

    Looks up the stored SHA-256 hash, refreshes ``last_used_at`` on success,
    and returns the associated user row.
    """
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = get_api_token(token_hash)
    if not row:
        return None

    touch_api_token(row["id"])
    return get_user_by_id(row["user_id"])


def store_api_token(user_id, name, token_hash):
    """Persist a token hash and return the new token id."""
    return _create_api_token(user_id, name, token_hash)


def _is_exempt_path(path):
    """Return True if the request path does not require authentication."""
    if path.startswith("/static/"):
        return True
    if path in _EXEMPT_PATHS:
        return True
    # /api/auth/setup is exempt only on first-run; once a user exists it must
    # go through auth like any other protected route.
    if path == "/api/auth/setup":
        return _setup_is_first_run()
    return False


def _authenticate_api():
    """Authenticate an API request.

    API requests accept a ``Authorization: Bearer <token>`` header for agent
    access, then fall back to the browser session. Returns a user dict on
    success or an HTTP response tuple on failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        user = validate_api_token(token)
        if user:
            g.current_user = user
            g.api_token = token
            return user
        return jsonify({"error": "Authentication required"}), 401

    user = current_user()
    if user:
        return user

    return jsonify({"error": "Authentication required"}), 401


def require_auth():
    """``before_request`` gate that is transparent when auth is disabled.

    When ``auth_enabled`` is on:
    * Static assets and auth-subsystem routes are exempt.
    * API routes require either a valid Bearer token or a browser session.
    * HTML routes require a browser session; missing sessions are redirected to
      ``/login?next=<path>``.
    """
    if not is_auth_enabled():
        return None

    path = request.path
    if _is_exempt_path(path):
        return None

    if path.startswith("/api/"):
        # Assistant endpoints are human-facing UI tools and require a browser
        # session; API tokens (agent access) are intentionally rejected.
        if path.startswith("/api/assistant/"):
            user = current_user()
            if user:
                return None
            return jsonify({"error": "Authentication required"}), 401

        result = _authenticate_api()
        if isinstance(result, tuple):
            return result
        return None

    # HTML page routes require a session; tokens are for API access only.
    if current_user():
        return None

    return redirect("/login?next=" + quote(path, safe=""))
