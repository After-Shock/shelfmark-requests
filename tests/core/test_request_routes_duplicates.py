"""Route integration tests for shared duplicate requests."""

import sqlite3
from threading import Barrier, Thread
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


@pytest.fixture
def grouped_requests(request_db):
    canonical, _ = request_db.create_or_join_request(
        user_id=1, title="Dune", author="Frank Herbert", content_type="ebook"
    )
    linked, _ = request_db.create_or_join_request(
        user_id=2, title="Dune", author="Frank Herbert", content_type="ebook"
    )
    return canonical, linked


@pytest.fixture
def user_db():
    users = {
        1: {"id": 1, "email": "first@example.com"},
        2: {"id": 2, "email": "second@example.com"},
    }
    db = MagicMock()
    db.get_user.side_effect = lambda *, user_id: users.get(user_id)
    return db


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


def test_provider_audiobook_joins_existing_manual_request(app):
    with patch("shelfmark.core.request_routes.abs_client.find_match", return_value=None), \
         patch("shelfmark.core.request_routes._send_discord_new_request"), \
         patch("shelfmark.core.request_routes._send_pushover_new_request"):
        with app.test_client() as client:
            login(client, 1)
            manual = client.post(
                "/api/requests",
                json={
                    "title": "The Eye of the Bedlam Bride",
                    "author": "Matt Dinniman",
                    "content_type": "audiobook",
                    "is_manual_request": True,
                },
            )
            login(client, 2)
            provider = client.post(
                "/api/requests",
                json={
                    "title": "the eye of the bedlam bride",
                    "author": "matt dinniman",
                    "content_type": "audiobook",
                    "provider": "googlebooks",
                    "provider_id": "gc_H0QEACAAJ",
                },
            )

    assert manual.status_code == 201
    assert provider.status_code == 200
    assert provider.get_json()["joined_existing"] is True
    assert provider.get_json()["canonical_request_id"] == manual.get_json()["id"]


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


def test_fulfilling_linked_request_notifies_discord_once_with_canonical(app):
    canonical, linked = _group(app)

    with patch("shelfmark.core.request_routes._send_group_status_notifications"), \
         patch("shelfmark.core.request_routes._send_discord_book_available") as discord:
        with app.test_client() as client:
            login(client, 1, is_admin=True)
            response = client.put(
                f"/api/requests/{linked['id']}/status", json={"status": "fulfilled"}
            )

    assert response.status_code == 200
    assert app.request_db.get_request(canonical["id"])["status"] == "fulfilled"
    assert app.request_db.get_request(linked["id"])["status"] == "fulfilled"
    discord.assert_called_once_with(app.request_db.get_request(canonical["id"]))


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


def test_cancelled_request_retry_is_rejected_without_starting_work(app):
    canonical, linked = _group(app, status="cancelled")

    with patch("shelfmark.core.request_routes._acquire_download_slot") as acquire_slot, \
         patch("shelfmark.core.request_routes.threading.Thread") as thread_cls, \
         patch.object(app.request_db, "update_request_metadata") as update_metadata, \
         patch.object(app.request_db, "update_request_status") as update_status:
        response = _admin_post(app, f"/api/requests/{linked['id']}/retry")

    assert response.status_code == 409
    assert "cancelled" in response.get_json()["error"].lower()
    acquire_slot.assert_not_called()
    thread_cls.assert_not_called()
    update_metadata.assert_not_called()
    update_status.assert_not_called()
    assert app.request_db.get_request(canonical["id"])["status"] == "cancelled"


def test_linked_and_canonical_retry_share_one_download_slot(app):
    canonical, linked = _group(app, status="failed")

    from shelfmark.core import request_routes
    request_routes._in_flight_downloads.clear()
    try:
        with patch(
            "shelfmark.core.request_routes._backfill_missing_metadata",
            side_effect=lambda _db, _request_id, req: req,
        ), patch("shelfmark.core.request_routes.threading.Thread") as thread_cls:
            linked_response = _admin_post(app, f"/api/requests/{linked['id']}/retry")
            canonical_response = _admin_post(app, f"/api/requests/{canonical['id']}/retry")

        assert linked_response.status_code == 200
        assert canonical_response.status_code == 200
        assert thread_cls.call_count == 1
        assert thread_cls.call_args.kwargs["args"][2] == canonical["id"]
        assert request_routes._in_flight_downloads == {canonical["id"]}
    finally:
        request_routes._in_flight_downloads.clear()


def _simultaneous_admin_posts(app, paths):
    start = Barrier(len(paths))
    responses = []

    def post(path):
        with app.test_client() as client:
            login(client, 1, is_admin=True)
            start.wait()
            responses.append(client.post(path, json={}))

    threads = [Thread(target=post, args=(path,)) for path in paths]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return responses


@pytest.mark.parametrize("route", ["retry", "approve"])
def test_simultaneous_canonical_and_linked_routes_start_one_worker(app, route):
    initial_status = "failed" if route == "retry" else "pending"
    canonical, linked = _group(app, status=initial_status)
    paths = [
        f"/api/requests/{canonical['id']}/{route}",
        f"/api/requests/{linked['id']}/{route}",
    ]
    original_get_request = app.request_db.get_request
    initial_reads = Barrier(2)

    def synchronized_initial_read(request_id):
        initial_reads.wait()
        return original_get_request(request_id)

    from shelfmark.core import request_routes
    request_routes._in_flight_downloads.clear()
    created_threads = []

    def make_thread(*args, **kwargs):
        worker = MagicMock()
        created_threads.append((args, kwargs, worker))
        return worker

    try:
        with patch.object(app.request_db, "get_request", side_effect=synchronized_initial_read), \
             patch(
                 "shelfmark.core.request_routes._backfill_missing_metadata",
                 side_effect=lambda _db, _request_id, req: req,
             ), patch(
                 "shelfmark.core.request_routes.threading.Thread",
                 side_effect=make_thread,
             ):
            responses = _simultaneous_admin_posts(app, paths)

        download_workers = [
            (kwargs, worker) for _, kwargs, worker in created_threads
            if kwargs.get("target") is request_routes._auto_download_request
        ]
        assert {response.status_code for response in responses} == {200}
        assert len(download_workers) == 1
        assert download_workers[0][0]["args"][2] == canonical["id"]
        assert download_workers[0][1].start.call_count == 1
        assert request_routes._in_flight_downloads == {canonical["id"]}
    finally:
        request_routes._in_flight_downloads.clear()


def test_status_notification_fans_out_to_all_active_users(request_db, user_db, grouped_requests):
    from shelfmark.core.request_routes import _send_group_status_notifications

    canonical, _ = grouped_requests
    with patch("shelfmark.core.request_routes.send_request_notification") as send:
        _send_group_status_notifications(request_db, user_db, canonical["id"], "fulfilled")

    assert {call.args[0] for call in send.call_args_list} == {
        "first@example.com",
        "second@example.com",
    }


def test_removed_user_does_not_receive_group_notification(request_db, user_db, grouped_requests):
    from shelfmark.core.request_routes import _send_group_status_notifications

    canonical, linked = grouped_requests
    request_db.delete_user_request(linked["id"], linked["user_id"])
    with patch("shelfmark.core.request_routes.send_request_notification") as send:
        _send_group_status_notifications(request_db, user_db, canonical["id"], "fulfilled")

    assert [call.args[0] for call in send.call_args_list] == ["first@example.com"]


def test_cancelled_linked_member_does_not_receive_group_notification(
    request_db, user_db, grouped_requests
):
    from shelfmark.core.request_routes import _send_group_status_notifications

    canonical, linked = grouped_requests
    with request_db._connect() as conn:
        conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = ?", (linked["id"],))
        conn.commit()

    with patch("shelfmark.core.request_routes.send_request_notification") as send:
        _send_group_status_notifications(request_db, user_db, canonical["id"], "fulfilled")

    assert [call.args[0] for call in send.call_args_list] == ["first@example.com"]


def test_failed_group_recipient_notification_does_not_stop_other_recipients(
    request_db, user_db, grouped_requests
):
    from shelfmark.core.request_routes import _send_group_status_notifications

    canonical, _ = grouped_requests
    with patch(
        "shelfmark.core.request_routes.send_request_notification",
        side_effect=[RuntimeError("SMTP unavailable"), None],
    ) as send:
        _send_group_status_notifications(request_db, user_db, canonical["id"], "fulfilled")

    assert [call.args[0] for call in send.call_args_list] == [
        "first@example.com",
        "second@example.com",
    ]


@pytest.mark.parametrize("target", ["canonical", "linked"])
def test_admin_non_owner_delete_hides_entire_group_and_broadcasts_canonical(app, target):
    canonical, linked = _group(app)
    target_id = canonical["id"] if target == "canonical" else linked["id"]

    with patch("shelfmark.core.request_routes._broadcast_request_update") as broadcast:
        with app.test_client() as client:
            login(client, 3, is_admin=True)
            response = client.delete(f"/api/requests/{target_id}")

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "action": "hidden"}
    assert {app.request_db.get_request(row["id"])["hidden_from_admin"] for row in (canonical, linked)} == {1}
    broadcast.assert_called_once_with(app.request_db.get_request(canonical["id"]))

    with app.test_client() as client:
        login(client, canonical["user_id"])
        deleted = client.delete(f"/api/requests/{canonical['id']}")
        login(client, 3, is_admin=True)
        admin_rows = client.get("/api/requests").get_json()["requests"]

    assert deleted.status_code == 200
    promoted = app.request_db.get_request(linked["id"])
    assert promoted["canonical_request_id"] is None
    assert promoted["hidden_from_admin"] == 1
    assert linked["id"] not in [row["id"] for row in admin_rows]
