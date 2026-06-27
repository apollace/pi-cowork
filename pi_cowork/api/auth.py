"""Authentication API endpoints."""

from flask import Blueprint, jsonify, request

from pi_cowork import auth
from pi_cowork.db import query_db
from pi_cowork.models import (
    create_api_token,
    create_user,
    get_user_by_username,
    list_api_tokens,
    revoke_api_token,
    update_user_password,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _request_json():
    """Safely parse JSON body, returning empty dict on failure."""
    return request.get_json(silent=True) or {}


def _user_response(user):
    """Return a serializable user payload (no password hash)."""
    return {"id": user["id"], "username": user["username"]}


@auth_bp.route("/setup-needed", methods=["GET"])
def api_setup_needed():
    """Return whether an initial user account still needs to be created."""
    count = query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    return jsonify({"setup_needed": count == 0}), 200


@auth_bp.route("/setup", methods=["POST"])
def api_setup():
    """Create the very first user. Only works if zero users exist."""
    data = _request_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    existing = query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    if existing > 0:
        return jsonify({"error": "A user already exists. Use login instead."}), 409

    password_hash = auth.hash_password(password)
    user_id = create_user(username, password_hash)
    user = get_user_by_username(username)
    auth.create_session(user_id)
    return jsonify(_user_response(user)), 201


@auth_bp.route("/login", methods=["POST"])
def api_login():
    """Validate credentials and start a session."""
    data = _request_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    user = get_user_by_username(username)
    if user and auth.verify_password(password, user["password_hash"]):
        auth.create_session(user["id"])
        return jsonify(_user_response(user)), 200

    return jsonify({"error": "Invalid username or password"}), 401


@auth_bp.route("/logout", methods=["POST"])
def api_logout():
    """Clear the current browser session."""
    auth.clear_session()
    return jsonify({"ok": True}), 200


@auth_bp.route("/me", methods=["GET"])
def api_me():
    """Return the currently logged-in user."""
    user = auth.current_user()
    if user:
        return jsonify(_user_response(user)), 200
    return jsonify({"error": "Authentication required"}), 401


@auth_bp.route("/password", methods=["PUT"])
def api_change_password():
    """Change the current user's password.

    Requires an active browser session (tokens are not accepted). Validates the
    current password, then updates the stored hash.
    """
    session_check = auth.require_session()
    if session_check is not True:
        return session_check

    data = _request_json()
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        return jsonify({"error": "current_password and new_password are required"}), 400
    if len(new_password) < 8:
        return jsonify({"error": "new_password must be at least 8 characters"}), 400

    user = auth.current_user()
    if not auth.verify_password(current_password, user["password_hash"]):
        return jsonify({"error": "Current password is incorrect"}), 401

    update_user_password(user["id"], auth.hash_password(new_password))
    return jsonify({"success": True}), 200


@auth_bp.route("/tokens", methods=["GET"])
def api_list_tokens():
    """List API tokens belonging to the current session user."""
    session_check = auth.require_session()
    if session_check is not True:
        return session_check

    user = auth.current_user()
    tokens = list_api_tokens(user["id"])
    return jsonify(
        [
            {
                "id": t["id"],
                "name": t["name"],
                "created_at": t["created_at"],
                "last_used_at": t["last_used_at"],
            }
            for t in tokens
        ]
    ), 200


@auth_bp.route("/tokens", methods=["POST"])
def api_create_token():
    """Create a new API token for the current session user.

    The plaintext token is returned exactly once. Only its SHA-256 hash is
    stored in the database.
    """
    session_check = auth.require_session()
    if session_check is not True:
        return session_check

    data = _request_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    user = auth.current_user()
    token, token_hash = auth.generate_api_token()
    token_id = create_api_token(user["id"], name, token_hash)
    return jsonify({"id": token_id, "token": token}), 201


@auth_bp.route("/tokens/<int:token_id>", methods=["DELETE"])
def api_revoke_token(token_id):
    """Revoke an API token belonging to the current session user."""
    session_check = auth.require_session()
    if session_check is not True:
        return session_check

    user = auth.current_user()
    tokens = list_api_tokens(user["id"])
    if not any(t["id"] == token_id for t in tokens):
        return jsonify({"error": "Token not found"}), 404

    revoke_api_token(token_id)
    return jsonify({"success": True}), 200
