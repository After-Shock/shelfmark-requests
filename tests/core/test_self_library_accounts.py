"""Account page: add an Audiobookshelf / Calibre-Web account with your Shelfmark password."""

from flask import Flask
from werkzeug.security import generate_password_hash

import shelfmark.core.self_user_routes as self_routes
import shelfmark.core.signup_provisioning as signup_provisioning
from shelfmark.core.user_db import UserDB


def test_add_library_account_needs_the_users_password(tmp_path, monkeypatch):
    user_db = UserDB(str(tmp_path / "users.db"))
    user_db.initialize()
    user = user_db.create_user(username="dave", password_hash=generate_password_hash("pw1234"), role="user")

    app = Flask(__name__)
    app.secret_key = "test"
    self_routes.register_self_user_routes(app, user_db)
    monkeypatch.setattr(self_routes, "_get_auth_mode", lambda: "builtin")
    monkeypatch.setattr(
        signup_provisioning,
        "library_account_status",
        lambda username: {"audiobookshelf": {"offered": True, "has_account": False},
                          "calibre_web": {"offered": False, "has_account": False}},
    )
    created = []
    monkeypatch.setattr(
        signup_provisioning,
        "provision_signup_accounts",
        lambda username, password, **k: created.append((username, password, k["services"]))
        or {"audiobookshelf": {"status": "created", "message": "ok"}},
    )

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"], sess["db_user_id"] = "dave", user["id"]
    post = lambda body: client.post("/api/users/me/library-accounts", json=body)

    assert post({"service": "audiobookshelf", "password": "nope"}).status_code == 403
    assert post({"service": "calibre_web", "password": "pw1234"}).status_code == 400  # not offered
    assert created == []

    assert post({"service": "audiobookshelf", "password": "pw1234"}).status_code == 200
    assert created == [("dave", "pw1234", {"audiobookshelf": True})]
    assert user_db.get_user(username="dave")["provisioned_services"] == "audiobookshelf"
