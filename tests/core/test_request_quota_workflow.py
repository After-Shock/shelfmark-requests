"""Auto-approval, the weekly request limit, and the Needs action queue."""

import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from flask import Flask

from shelfmark.core import request_quota, request_routes
from shelfmark.core.request_db import RequestDB, RequestLimitReached
from shelfmark.core.user_db import UserDB


@pytest.fixture
def dbs(tmp_path):
    path = str(tmp_path / "users.db")
    users = UserDB(path)
    users.initialize()
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
            [(1, "reader", "user"), (2, "other", "user"), (9, "boss", "admin")],
        )
    requests = RequestDB(path)
    requests.initialize()
    return requests, users


def _since(users, user_id):
    return request_quota.counting_since(users.get_user(user_id=user_id))


def _create(requests, users, user_id, title, limit=6):
    return requests.create_or_join_request(
        user_id=user_id, title=title, author="Author", content_type="ebook",
        quota_limit=limit, quota_since=_since(users, user_id),
    )


# --- week boundaries ---------------------------------------------------------

def test_week_starts_monday_midnight_eastern():
    sunday_night = datetime(2026, 11, 23, 4, 59, tzinfo=timezone.utc)  # Sun 23:59 EST
    monday = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)          # Mon 00:00 EST
    assert request_quota.week_bounds(sunday_night)[0].isoformat() == "2026-11-16T00:00:00-05:00"
    assert request_quota.week_bounds(monday)[0].isoformat() == "2026-11-23T00:00:00-05:00"
    assert request_quota.week_bounds(sunday_night)[1].isoformat() == "2026-11-23T00:00:00-05:00"


def test_reset_stays_at_midnight_across_daylight_saving_change():
    # DST ends Sun 2026-11-01: the week starts in EDT, the next one in EST.
    start, resets = request_quota.week_bounds(datetime(2026, 10, 28, 12, tzinfo=timezone.utc))
    assert start.isoformat() == "2026-10-26T00:00:00-04:00"
    assert resets.isoformat() == "2026-11-02T00:00:00-05:00"


def test_limits_default_custom_and_admin(dbs):
    _, users = dbs
    with patch.object(request_quota, "default_limit", return_value=6):
        assert request_quota.limit_for(users.get_user(user_id=1)) == 6
        users.update_user(1, weekly_request_limit=10)
        assert request_quota.limit_for(users.get_user(user_id=1)) == 10
        assert request_quota.limit_for(users.get_user(user_id=9)) is None


# --- ledger ------------------------------------------------------------------

def test_new_requests_use_slots_until_the_limit(dbs):
    requests, users = dbs
    for n in range(3):
        _create(requests, users, 1, f"Book {n}", limit=3)
    with pytest.raises(RequestLimitReached):
        _create(requests, users, 1, "One too many", limit=3)
    assert requests.count_quota_usage(1, _since(users, 1)) == 3
    assert [r["title"] for r in requests.list_requests(user_id=1)].count("One too many") == 0


def test_joining_or_rerequesting_is_free_even_at_the_limit(dbs):
    requests, users = dbs
    shared, _ = _create(requests, users, 2, "Shared Book")
    mine, _ = _create(requests, users, 1, "My Book", limit=1)
    requests.update_request_status(mine["id"], "failed")

    joined, outcome = _create(requests, users, 1, "Shared Book", limit=1)
    assert outcome == "joined" and joined["canonical_request_id"] == shared["id"]
    again, outcome = _create(requests, users, 1, "My Book", limit=1)
    assert outcome == "already_joined" and again["id"] == mine["id"]
    assert requests.count_quota_usage(1, _since(users, 1)) == 1


def test_denial_refunds_but_owner_delete_does_not(dbs):
    requests, users = dbs
    denied, _ = _create(requests, users, 1, "Denied Book")
    kept, _ = _create(requests, users, 1, "Kept Book")
    requests.update_request_status(denied["id"], "denied")
    assert requests.count_quota_usage(1, _since(users, 1)) == 1

    requests.update_request_status(kept["id"], "fulfilled")
    requests.delete_user_request(kept["id"], 1)
    assert requests.count_quota_usage(1, _since(users, 1)) == 1


def test_reset_starts_the_count_over(dbs):
    requests, users = dbs
    _create(requests, users, 1, "Before reset")
    _create(requests, users, 2, "Someone else")
    with sqlite3.connect(requests._db_path) as conn:  # make the requests clearly older than the reset
        conn.execute("UPDATE request_quota_usage SET created_at = datetime('now', '-1 minute')")
    users.reset_request_limits(1)
    assert requests.count_quota_usage(1, _since(users, 1)) == 0
    assert requests.count_quota_usage(2, _since(users, 2)) == 1
    users.reset_request_limits()
    assert requests.count_quota_usage(2, _since(users, 2)) == 0


def test_migration_backfills_existing_requests(dbs):
    requests, users = dbs
    counted, _ = requests.create_or_join_request(user_id=1, title="Old", content_type="ebook")
    denied, _ = requests.create_or_join_request(user_id=1, title="Old denied", content_type="ebook")
    requests.update_request_status(denied["id"], "denied")
    requests.create_or_join_request(user_id=2, title="Old", content_type="ebook")  # joins: free
    with sqlite3.connect(requests._db_path) as conn:
        conn.execute("DROP TABLE request_quota_usage")
        conn.execute("UPDATE schema_version SET version = 10")
    requests.initialize()
    with sqlite3.connect(requests._db_path) as conn:
        rows = conn.execute("SELECT request_id, user_id FROM request_quota_usage").fetchall()
    assert rows == [(counted["id"], 1)]


# --- routes ------------------------------------------------------------------

class _SyncThread:
    """Run background work inline so the test sees its effects."""

    def __init__(self, target, args=(), kwargs=None, **_):
        self._run = lambda: target(*args, **(kwargs or {}))

    def start(self):
        self._run()


@pytest.fixture
def client(dbs):
    requests, users = dbs
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    with patch.object(request_routes, "_get_auth_mode", return_value="builtin"):
        request_routes.register_request_routes(app, requests, users)
    with patch.object(request_routes, "_get_auth_mode", return_value="builtin"), \
            patch.object(request_quota, "default_limit", return_value=2), \
            patch.object(request_routes.threading, "Thread", _SyncThread), \
            patch.object(request_routes, "_start_approved_request") as start, \
            patch.object(request_routes, "_send_discord_new_request") as discord, \
            patch.object(request_routes, "_send_pushover") as pushover:
        test_client = app.test_client()
        test_client.start, test_client.discord, test_client.pushover = start, discord, pushover
        yield test_client


def _login(client, user_id, is_admin=False):
    with client.session_transaction() as sess:
        sess["user_id"] = f"user-{user_id}"
        sess["db_user_id"] = user_id
        sess["is_admin"] = is_admin


def _post(client, title):
    with patch.object(request_routes.calibre_library, "find_match", return_value=None):
        return client.post("/api/requests", json={"title": title, "author": "Author"})


def test_request_is_approved_automatically_without_a_push(client):
    _login(client, 1)
    response = _post(client, "First")
    body = response.get_json()
    assert response.status_code == 201
    assert body["status"] == "approved" and body["approved_by"] is None
    assert body["quota"]["remaining"] == 1 and body["quota"]["limit"] == 2
    client.start.assert_called_once()
    client.discord.assert_called_once()
    client.pushover.assert_not_called()


def test_last_slot_pushes_limit_reached_and_next_request_is_refused(client):
    _login(client, 1)
    _post(client, "First")
    _post(client, "Second")
    client.pushover.assert_called_once()
    assert client.pushover.call_args.args[2] == "Weekly Request Limit Reached"
    assert "reader has used all 2" in client.pushover.call_args.args[3]

    refused = _post(client, "Third")
    assert refused.status_code == 429
    assert refused.get_json()["quota"]["remaining"] == 0
    assert "reset on Monday" in refused.get_json()["error"]
    assert client.start.call_count == 2
    assert client.get("/api/requests/counts").get_json()["quota"]["used"] == 2


def test_admins_are_unlimited(client):
    _login(client, 9, is_admin=True)
    for n in range(4):
        assert _post(client, f"Admin book {n}").status_code == 201
    assert _post(client, "Admin book 5").get_json()["quota"] is None
    client.pushover.assert_not_called()


def test_failure_pushes_needs_action_but_series_pack_does_not(dbs):
    requests, users = dbs
    req, _ = requests.create_or_join_request(user_id=1, title="Lost Book", content_type="ebook")
    with patch.object(request_routes, "_send_pushover") as pushover, \
            patch.object(request_routes, "_send_group_status_notifications"):
        request_routes._set_request_status(requests, users, req["id"], "failed", admin_note="Not found")
        pushover.assert_called_once()
        assert pushover.call_args.args[2:] == ("Request Needs Manual Action", "Not found")

        pushover.reset_mock()
        request_routes._set_request_status(requests, users, req["id"], "failed", series_pack_offer="Pack")
        pushover.assert_not_called()


def test_already_owned_audiobook_is_not_pushed():
    with patch("shelfmark.core.pushover_notifications.send_new_request_pushover") as push, \
            patch("shelfmark.core.discord_notifications.send_discord_new_request") as discord:
        request_routes._notify_admin({"title": "T"}, None, "already_exists", "Exists", "note", pushover=False)
    push.assert_not_called()
    discord.assert_called_once()


# --- admin routes -------------------------------------------------------------

@pytest.fixture
def admin(dbs):
    from shelfmark.core.admin_routes import register_admin_routes

    requests, users = dbs
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test")
    register_admin_routes(app, users, requests)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"], sess["is_admin"] = "boss", True
    with patch("shelfmark.core.admin_routes._get_auth_mode", return_value="builtin"):
        yield test_client


def test_admin_sets_and_clears_a_users_limit(admin, dbs):
    assert admin.put("/api/admin/users/1", json={"weekly_request_limit": 9}).get_json()["request_quota"]["limit"] == 9
    for bad in (-1, 101, "lots", 2.5, True):
        assert admin.put("/api/admin/users/1", json={"weekly_request_limit": bad}).status_code == 400
    cleared = admin.put("/api/admin/users/1", json={"weekly_request_limit": None}).get_json()
    assert cleared["weekly_request_limit"] is None and cleared["request_quota"]["is_default"] is True
    users = admin.get("/api/admin/users").get_json()
    assert next(u for u in users if u["id"] == 9)["request_quota"] is None


def test_admin_reset_endpoint(admin, dbs):
    _, users = dbs
    assert admin.post("/api/admin/request-limits/reset", json={"user_id": 1}).status_code == 200
    assert users.get_user(user_id=1)["request_limit_reset_at"] is not None
    assert users.get_user(user_id=2)["request_limit_reset_at"] is None
    assert admin.post("/api/admin/request-limits/reset", json={}).status_code == 200
    assert users.get_user(user_id=2)["request_limit_reset_at"] is not None
    assert admin.post("/api/admin/request-limits/reset", json={"user_id": 404}).status_code == 404


def test_admin_default_limit_validation(admin):
    with patch("shelfmark.core.admin_routes.update_settings", return_value={"success": True}) as save:
        assert admin.put("/api/admin/request-limits", json={"default": 8}).status_code == 200
        save.assert_called_once_with("users", {"WEEKLY_REQUEST_LIMIT": 8})
        assert admin.put("/api/admin/request-limits", json={"default": -2}).status_code == 400
        assert admin.put("/api/admin/request-limits", json={}).status_code == 400


# --- denial wins over a download that was already running --------------------

def test_background_status_changes_do_not_overwrite_a_denial(dbs):
    requests, users = dbs
    req, _ = requests.create_or_join_request(user_id=1, title="Denied Mid-download", content_type="ebook")
    requests.update_request_status(req["id"], "denied", admin_note="No thanks")
    with patch.object(request_routes, "_send_pushover") as pushover, \
            patch.object(request_routes, "_send_group_status_notifications") as emails:
        for status in ("downloading", "fulfilled", "failed"):
            request_routes._set_request_status(requests, users, req["id"], status, admin_note="from worker")
    assert requests.get_request(req["id"])["status"] == "denied"
    assert requests.get_request(req["id"])["admin_note"] == "No thanks"
    pushover.assert_not_called()
    emails.assert_not_called()
