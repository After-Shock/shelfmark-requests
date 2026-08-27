"""Tests for signup invite code storage and admin API."""

import os
import tempfile
from unittest.mock import patch

from flask import Flask

from shelfmark.core.user_db import UserDB


def _db():
    tmp = tempfile.TemporaryDirectory()
    db = UserDB(os.path.join(tmp.name, "users.db"))
    db.initialize()
    return tmp, db


def test_invite_code_lifecycle():
    tmp, db = _db()
    try:
        invite = db.create_invite_code("abc123", created_by=None)
        assert invite["code"] == "abc123"
        assert db.get_invite_code("abc123")["used_at"] is None

        user = db.create_user("alice", password_hash="hash")
        assert db.consume_invite_code("abc123", user["id"]) is True
        assert db.consume_invite_code("abc123", user["id"]) is False
        assert db.get_invite_code("abc123")["used_by"] == user["id"]
    finally:
        tmp.cleanup()


def test_admin_invite_api_generates_and_deletes_unused_invite():
    tmp, db = _db()
    try:
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret"
        app.config["TESTING"] = True
        from shelfmark.core.admin_routes import register_admin_routes

        register_admin_routes(app, db)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = "admin"
            sess["db_user_id"] = 1
            sess["is_admin"] = True

        with patch("shelfmark.core.admin_routes._get_auth_mode", return_value="builtin"):
            resp = client.post("/api/admin/invites", json={"expires_in_hours": 24})
            assert resp.status_code == 201
            invite = resp.get_json()
            assert invite["code"]
            assert invite["expires_at"]

            resp = client.get("/api/admin/invites")
            assert resp.status_code == 200
            assert resp.get_json()[0]["code"] == invite["code"]

            resp = client.delete(f"/api/admin/invites/{invite['id']}")
            assert resp.status_code == 200
            assert db.get_invite_code(invite["code"]) is None
    finally:
        tmp.cleanup()
