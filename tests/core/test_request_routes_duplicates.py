"""Route integration tests for shared duplicate requests."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from shelfmark.core.request_db import RequestDB
from shelfmark.core.request_routes import register_request_routes


@pytest.fixture
def request_db(tmp_path):
    db_path = tmp_path / "requests.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, 'user')",
            [(1, "user-1", "User 1"), (2, "user-2", "User 2")],
        )
    db = RequestDB(str(db_path))
    db.initialize()
    return db


@pytest.fixture
def app(request_db):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    user_db = MagicMock()
    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
        register_request_routes(app, request_db, user_db)
    app.request_db = request_db
    return app


def login(client, user_id, *, is_admin=False):
    with client.session_transaction() as session:
        session["user_id"] = f"user-{user_id}"
        session["db_user_id"] = user_id
        session["is_admin"] = is_admin


def create_request(client, user_id, *, title="Dune", author="Frank Herbert"):
    login(client, user_id)
    return client.post("/api/requests", json={"title": title, "author": author})


def test_second_user_joins_existing_request_and_only_creation_notifies(app):
    with patch("shelfmark.core.request_routes._send_discord_new_request") as discord, \
         patch("shelfmark.core.request_routes._send_pushover_new_request") as pushover:
        with app.test_client() as client:
            first = create_request(client, 1)
            second = create_request(client, 2, title="dune", author="frank herbert")

    assert first.status_code == 201
    assert first.get_json()["joined_existing"] is False
    assert second.status_code == 200
    assert second.get_json()["joined_existing"] is True
    assert second.get_json()["canonical_request_id"] == first.get_json()["id"]
    assert discord.call_count == 1
    assert pushover.call_count == 1

    with app.test_client() as client:
        login(client, 1, is_admin=True)
        admin_rows = client.get("/api/requests").get_json()["requests"]
        login(client, 1)
        first_user_rows = client.get("/api/requests").get_json()["requests"]
        login(client, 2)
        second_user_rows = client.get("/api/requests").get_json()["requests"]

    assert [row["id"] for row in admin_rows] == [first.get_json()["id"]]
    assert len(first_user_rows) == len(second_user_rows) == 1
    assert admin_rows[0]["requester_count"] == 2


def test_same_user_repeat_returns_existing_row(app):
    with app.test_client() as client:
        first = create_request(client, 1)
        second = create_request(client, 1)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["already_joined"] is True
    assert second.get_json()["id"] == first.get_json()["id"]
    assert len(app.request_db.list_requests(user_id=1)) == 1


def test_owner_delete_uses_user_scoped_deletion_and_broadcasts_promotion(app):
    with app.test_client() as client:
        canonical = create_request(client, 1).get_json()
        linked = create_request(client, 2).get_json()

    with patch.object(app.request_db, "delete_user_request", wraps=app.request_db.delete_user_request) as delete_user, \
         patch("shelfmark.core.request_routes._broadcast_request_update") as broadcast:
        with app.test_client() as client:
            login(client, 1)
            response = client.delete(f"/api/requests/{canonical['id']}")

    assert response.status_code == 200
    delete_user.assert_called_once_with(canonical["id"], 1)
    assert app.request_db.get_request(linked["id"])["canonical_request_id"] is None
    broadcast.assert_any_call({"id": canonical["id"], "deleted": True})
    broadcast.assert_any_call(app.request_db.get_request(linked["id"]))


def _group(app, *, content_type="ebook", status="pending"):
    canonical, _ = app.request_db.create_or_join_request(
        user_id=1, title="Dune", author="Frank Herbert", content_type=content_type
    )
    linked, _ = app.request_db.create_or_join_request(
        user_id=2, title="Dune", author="Frank Herbert", content_type=content_type
    )
    if status != "pending":
        app.request_db.update_request_status(canonical["id"], status, approved_by=1)
    return canonical, linked


def _admin_post(app, path, *, json=None):
    with app.test_client() as client:
        login(client, 1, is_admin=True)
        return client.post(path, json={} if json is None else json)


def test_approve_updates_the_entire_request_group(app):
    canonical, linked = _group(app, content_type="audiobook")

    response = _admin_post(app, f"/api/requests/{canonical['id']}/approve")

    assert response.status_code == 200
    assert app.request_db.get_request(canonical["id"])["status"] == "approved"
    assert app.request_db.get_request(linked["id"])["status"] == "approved"


def test_denying_a_linked_id_returns_and_updates_the_canonical_group(app):
    canonical, linked = _group(app)

    response = _admin_post(app, f"/api/requests/{linked['id']}/deny")

    assert response.status_code == 200
    assert response.get_json()["id"] == canonical["id"]
    assert app.request_db.get_request(canonical["id"])["status"] == "denied"
    assert app.request_db.get_request(linked["id"])["status"] == "denied"


def test_generic_status_update_updates_the_entire_request_group(app):
    canonical, linked = _group(app)

    with app.test_client() as client:
        login(client, 1, is_admin=True)
        response = client.put(
            f"/api/requests/{canonical['id']}/status", json={"status": "approved"}
        )

    assert response.status_code == 200
    assert {app.request_db.get_request(row["id"])["status"] for row in (canonical, linked)} == {"approved"}


def test_activate_updates_linked_prerelease_member(app):
    canonical, linked = _group(app, status="prerelease_requested")

    response = _admin_post(app, f"/api/requests/{canonical['id']}/activate")

    assert response.status_code == 200
    assert {app.request_db.get_request(row["id"])["status"] for row in (canonical, linked)} == {"pending"}


def test_move_to_prerelease_updates_the_entire_request_group(app):
    canonical, linked = _group(app)

    response = _admin_post(
        app,
        f"/api/requests/{canonical['id']}/move-to-prerelease",
        json={"expected_release_date": "2099-01-01"},
    )

    assert response.status_code == 200
    assert {app.request_db.get_request(row["id"])["status"] for row in (canonical, linked)} == {"prerelease_requested"}


def test_retry_updates_the_entire_request_group(app):
    canonical, linked = _group(app, status="failed")

    with patch("shelfmark.core.request_routes._acquire_download_slot", return_value=False):
        response = _admin_post(app, f"/api/requests/{canonical['id']}/retry")

    assert response.status_code == 200
    assert {app.request_db.get_request(row["id"])["status"] for row in (canonical, linked)} == {"approved"}
