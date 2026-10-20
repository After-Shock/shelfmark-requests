"""Account page: link or add an Audiobookshelf / Calibre-Web account."""

import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

import shelfmark.core.self_user_routes as self_routes
import shelfmark.core.signup_provisioning as signup_provisioning
from shelfmark.core.user_db import UserDB


@pytest.fixture
def account_page(tmp_path, monkeypatch):
    """Logged-in user 'dave' (password pw1234); ABS offered, Calibre-Web not. Returns (post, user_db, status)."""
    user_db = UserDB(str(tmp_path / "users.db"))
    user_db.initialize()
    user = user_db.create_user(username="dave", password_hash=generate_password_hash("pw1234"), role="user")

    app = Flask(__name__)
    app.secret_key = "test"
    self_routes.register_self_user_routes(app, user_db)
    monkeypatch.setattr(self_routes, "_get_auth_mode", lambda: "builtin")
    status = {"audiobookshelf": {"offered": True, "has_account": False, "linked": False},
              "calibre_web": {"offered": False, "has_account": False, "linked": False}}
    monkeypatch.setattr(signup_provisioning, "library_account_status", lambda user: status)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"], sess["db_user_id"] = "dave", user["id"]
    return (lambda body: client.post("/api/users/me/library-accounts", json=body)), user_db, status


def test_add_library_account_needs_the_users_password(account_page, monkeypatch):
    post, user_db, _ = account_page
    created = []
    monkeypatch.setattr(
        signup_provisioning,
        "provision_signup_accounts",
        lambda username, password, **k: created.append((username, password, k["services"]))
        or {"audiobookshelf": {"status": "created", "message": "ok"}},
    )

    assert post({"service": "audiobookshelf", "password": "nope"}).status_code == 403
    assert post({"service": "calibre_web", "password": "pw1234"}).status_code == 400  # not offered
    assert created == []

    assert post({"service": "audiobookshelf", "password": "pw1234"}).status_code == 200
    assert created == [("dave", "pw1234", {"audiobookshelf": True})]
    assert user_db.get_user(username="dave")["provisioned_services"] == "audiobookshelf"


def test_link_existing_account_needs_its_password_then_syncs(account_page, monkeypatch):
    post, user_db, status = account_page
    status["audiobookshelf"]["has_account"] = True
    monkeypatch.setattr(signup_provisioning, "verify_library_login",
                        lambda service, username, password: password == "old-abs-pw")
    pushed = []
    monkeypatch.setattr("shelfmark.core.abs_user_sync.update_abs_password",
                        lambda username, password: pushed.append((username, password)) or {"status": "updated"})

    assert post({"service": "audiobookshelf", "password": "pw1234", "app_password": "wrong"}).status_code == 403
    assert user_db.get_user(username="dave")["provisioned_services"] is None

    assert post({"service": "audiobookshelf", "password": "pw1234", "app_password": "old-abs-pw"}).status_code == 200
    assert user_db.get_user(username="dave")["provisioned_services"] == "audiobookshelf"
    assert pushed == [("dave", "pw1234")]  # ABS now uses the requests-site password
