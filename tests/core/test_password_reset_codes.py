"""Tests for admin-generated password reset codes."""

import os
import tempfile
from unittest.mock import patch

from flask import Flask
from werkzeug.security import check_password_hash

from shelfmark.core.user_db import UserDB


def _db():
    tmp = tempfile.TemporaryDirectory()
    db = UserDB(os.path.join(tmp.name, "users.db"))
    db.initialize()
    return tmp, db


def test_password_reset_code_lifecycle():
    tmp, db = _db()
    try:
        user = db.create_user("alice", password_hash="old")
        reset = db.create_password_reset_code(user["id"], "reset123", None, "2999-01-01 00:00:00")
        assert reset["username"] == "alice"
        consumed = db.consume_password_reset_code("alice", "reset123")
        assert consumed and consumed["id"] == user["id"]
        assert db.consume_password_reset_code("alice", "reset123") is None
    finally:
        tmp.cleanup()


def test_public_reset_endpoint_updates_password(monkeypatch):
    tmp, db = _db()
    try:
        user = db.create_user("alice", password_hash="old")
        db.create_password_reset_code(user["id"], "reset123", None, "2999-01-01 00:00:00")
        import shelfmark.main as main

        monkeypatch.setattr(main, "user_db", db)
        app = main.app
        app.config["TESTING"] = True
        client = app.test_client()
        resp = client.post(
            "/api/auth/reset-password",
            json={"username": "alice", "code": "reset123", "password": "newpass"},
        )
        assert resp.status_code == 200
        updated = db.get_user(username="alice")
        assert check_password_hash(updated["password_hash"], "newpass")
    finally:
        tmp.cleanup()


def test_admin_reset_api_generates_code():
    tmp, db = _db()
    try:
        user = db.create_user("alice", password_hash="old")
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret"
        app.config["TESTING"] = True
        from shelfmark.core.admin_routes import register_admin_routes

        register_admin_routes(app, db)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["is_admin"] = True
        with patch("shelfmark.core.admin_routes._get_auth_mode", return_value="builtin"):
            resp = client.post("/api/admin/password-resets", json={"user_id": user["id"], "expires_in_hours": 1})
            assert resp.status_code == 201
            data = resp.get_json()
            assert data["username"] == "alice"
            assert data["code"]
    finally:
        tmp.cleanup()
