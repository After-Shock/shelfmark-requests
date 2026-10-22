"""Self-service password reset by email, and account linking."""

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import shelfmark.core.password_reset as password_reset
import shelfmark.core.signup_provisioning as signup_provisioning
from shelfmark.core.user_db import UserDB


@pytest.fixture
def user_db(tmp_path):
    db = UserDB(str(tmp_path / "users.db"))
    db.initialize()
    db.create_user(username="dave", email="Dave@Example.com", password_hash=generate_password_hash("old"), role="user")
    return db


@pytest.fixture
def libraries(monkeypatch):
    """Both apps offered. dave has a Calibre-Web account on his email and an ABS account on another."""
    accounts = {"calibre_web": {"name": "dave", "email": "dave@example.com"},
                "audiobookshelf": {"name": "dave", "email": "someone-else@example.com"}}
    monkeypatch.setattr(signup_provisioning, "offered_services", lambda: {"calibre_web", "audiobookshelf"})
    monkeypatch.setattr(signup_provisioning, "_find_library_account", lambda service, username: accounts.get(service))
    pushed = []
    monkeypatch.setattr("shelfmark.core.cwa_user_sync.update_cwa_password",
                        lambda u, p: pushed.append(("calibre_web", p)) or {"status": "updated", "message": ""})
    monkeypatch.setattr("shelfmark.core.abs_user_sync.update_abs_password",
                        lambda u, p: pushed.append(("audiobookshelf", p)) or {"status": "updated", "message": ""})
    return pushed


@pytest.fixture
def sent(monkeypatch):
    links = []
    monkeypatch.setattr(password_reset, "_public_url", lambda: "https://books.example.com")
    monkeypatch.setattr(password_reset, "_send_reset_email", lambda user, link: links.append((user["username"], link)))
    return links


def test_reset_link_sets_password_everywhere_linked(user_db, libraries, sent):
    password_reset.request_password_reset(user_db, "  dave@example.COM ")
    [(username, link)] = sent
    assert username == "dave" and link.startswith("https://books.example.com/reset-password?token=")
    token = link.split("token=")[1]

    result = password_reset.complete_password_reset(user_db, token, "new-pw")

    user = user_db.get_user(username="dave")
    assert check_password_hash(user["password_hash"], "new-pw")
    # Calibre-Web is registered to the verified email, so it got linked; ABS wasn't.
    assert user["provisioned_services"] == "calibre_web"
    assert libraries == [("calibre_web", "new-pw")]
    assert result["updated"] == ["Ebooks"]

    with pytest.raises(password_reset.PasswordResetError):  # links work once
        password_reset.complete_password_reset(user_db, token, "again")


def test_unknown_or_repeat_requests_send_nothing(user_db, sent):
    password_reset.request_password_reset(user_db, "nobody")
    assert sent == []
    password_reset.request_password_reset(user_db, "DAVE")
    password_reset.request_password_reset(user_db, "dave")  # within the cooldown
    assert len(sent) == 1
    with pytest.raises(password_reset.PasswordResetError):
        password_reset.complete_password_reset(user_db, "made-up-token", "x1234")
    assert user_db.list_password_reset_codes() == []  # hidden from the admin's reset-code list


def test_email_explains_linked_accounts(user_db, libraries, monkeypatch):
    monkeypatch.setattr(password_reset, "_public_url", lambda: "https://books.example.com")
    monkeypatch.setattr(password_reset, "_app_host",
                        lambda s: {"calibre_web": "ebooks.example.com", "audiobookshelf": "audiobooks.example.com"}[s])
    user = user_db.get_user(username="dave")
    msg = password_reset.compose_reset_email(user, "https://books.example.com/reset-password?token=t",
                                             "admin@example.com", password_reset._app_rows(user))
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    for body in (text, html):
        assert "also set it for your linked accounts on" in body
        assert "ebooks.example.com" in body and "audiobooks.example.com" in body
        assert "Library Access" in body and "reset-password?token=t" in body
    assert "will be linked and updated" in text  # Calibre-Web, by email
    assert "Not linked" in text  # ABS


def test_login_links_accounts_with_the_same_password(user_db, monkeypatch):
    monkeypatch.setattr(signup_provisioning, "offered_services", lambda: {"calibre_web", "audiobookshelf"})
    monkeypatch.setattr(signup_provisioning, "verify_library_login",
                        lambda service, username, password: service == "audiobookshelf" and password == "old")
    user = user_db.get_user(username="dave")

    assert signup_provisioning.link_accounts_with_password(user_db, user, "old") == {"audiobookshelf"}
    assert user_db.get_user(username="dave")["provisioned_services"] == "audiobookshelf"


def test_signup_links_same_password_and_offers_the_rest(user_db, monkeypatch):
    accounts = {"calibre_web": {"name": "dave", "email": None}, "audiobookshelf": {"name": "dave", "email": None}}
    monkeypatch.setattr(signup_provisioning, "offered_services", lambda: {"calibre_web", "audiobookshelf"})
    monkeypatch.setattr(signup_provisioning, "_find_library_account", lambda service, username: accounts.get(service))
    monkeypatch.setattr(signup_provisioning, "verify_library_login",
                        lambda service, username, password: service == "calibre_web" and password == "pw")
    uid = user_db.get_user(username="dave")["id"]

    assert signup_provisioning.link_after_signup(user_db, uid, "pw") == ["audiobookshelf"]
    assert user_db.get_user(user_id=uid)["provisioned_services"] == "calibre_web"


def test_signup_email_already_used_under_another_name(monkeypatch):
    monkeypatch.setattr(signup_provisioning, "offered_services", lambda: {"calibre_web", "audiobookshelf"})
    monkeypatch.setattr("shelfmark.core.cwa_user_sync.find_cwa_names_by_email",
                        lambda email: ["Austin", "austin210286"] if email == "a@example.com" else [])
    monkeypatch.setattr("shelfmark.core.abs_user_sync._get_credentials", lambda: ("http://abs", "t"))
    monkeypatch.setattr("shelfmark.core.abs_user_sync.list_abs_users",
                        lambda url, token: [{"username": "aus", "email": " A@Example.com"}, {"username": "x", "email": None}])

    assert signup_provisioning.accounts_under_other_names(" A@example.com ", "austin210286") == [
        ("audiobookshelf", "aus"), ("calibre_web", "Austin")]
    assert signup_provisioning.accounts_under_other_names("other@example.com", "bob") == []
    assert signup_provisioning.accounts_under_other_names(None, "bob") == []
