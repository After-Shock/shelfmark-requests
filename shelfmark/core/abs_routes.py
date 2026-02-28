"""ABS duplicate-check and cache-refresh API routes."""

from functools import wraps

from flask import Flask, jsonify, request, session

from shelfmark.core.audiobookshelf import abs_client
from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)


def _get_auth_mode() -> str:
    try:
        from shelfmark.core.settings_registry import load_config_file
        return load_config_file("security").get("AUTH_METHOD", "none")
    except Exception:
        return "none"


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _get_auth_mode() != "none" and "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def _require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_mode = _get_auth_mode()
        if auth_mode != "none":
            if "user_id" not in session:
                return jsonify({"error": "Authentication required"}), 401
            if not session.get("is_admin", False):
                return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def register_abs_routes(app: Flask) -> None:
    """Register /api/abs/* routes."""

    @app.route("/api/abs/check", methods=["GET"])
    @_require_auth
    def abs_check():
        title = (request.args.get("title") or "").strip()
        author = (request.args.get("author") or "").strip()

        if not title:
            return jsonify({"owned": False, "match": None})

        match = abs_client.find_match(title, author)
        if match:
            return jsonify({
                "owned": True,
                "match": {"title": match["title"], "author": match["author"]},
            })
        return jsonify({"owned": False, "match": None})

    @app.route("/api/abs/refresh", methods=["POST"])
    @_require_admin
    def abs_refresh():
        count = abs_client.refresh()
        return jsonify({"ok": True, "count": count})
