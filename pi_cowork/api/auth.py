"""Authentication API endpoints."""

from flask import Blueprint, jsonify, request

from pi_cowork import auth
from pi_cowork.db import query_db
from pi_cowork.models import create_user, get_user_by_username

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _request_json():
    """Safely parse JSON body, returning empty dict on failure."""
    return request.get_json(silent=True) or {}


def _user_response(user):
    """Return a serializable user payload (no password hash)."""
    return {"id": user["id"], "username": user["username"]}


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
