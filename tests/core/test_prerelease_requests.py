from datetime import datetime, timezone
import sqlite3
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from shelfmark.core.request_db import RequestDB
from shelfmark.core.prerelease_requests import promote_due_prerelease_requests


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "requests.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, role TEXT)")
        conn.executemany("INSERT INTO users VALUES (?, ?, ?, 'user')", [(1, 'first', 'First'), (2, 'second', 'Second')])
    db = RequestDB(str(path))
    db.initialize()
    return db


@pytest.fixture
def user_db():
    users = MagicMock()
    users.get_user.side_effect = lambda *, user_id: {"username": f"reader-{user_id}", "email": f"reader-{user_id}@example.com"}
    return users


@pytest.fixture(autouse=True)
def notifications():
    with patch("shelfmark.core.prerelease_requests.send_request_notification") as email, \
         patch("shelfmark.core.prerelease_requests.send_new_request_pushover") as push:
        yield email, push


def prerelease(db, release_date="2026-11-17"):
    row = db.create_request(user_id=1, title="Due Book", author="Author")
    db.update_request_metadata(row["id"], expected_release_date=release_date, is_released=False)
    db.update_request_status(row["id"], "prerelease_requested")
    return row["id"]


@pytest.mark.parametrize("release_date,utc_hour", [("2026-11-17", 14), ("2026-05-05", 13)])
def test_auto_approval_waits_until_nine_eastern(db, user_db, notifications, release_date, utc_hour):
    request_id = prerelease(db, release_date)
    year, month, day = map(int, release_date.split('-'))
    before = datetime(year, month, day, utc_hour - 1, 59, 59, tzinfo=timezone.utc)
    at_nine = datetime(year, month, day, utc_hour, 0, tzinfo=timezone.utc)
    assert promote_due_prerelease_requests(db, user_db, now=before) == []
    assert db.get_request(request_id)["status"] == "prerelease_requested"
    notifications[0].assert_not_called()
    notifications[1].assert_not_called()
    promoted = promote_due_prerelease_requests(db, user_db, now=at_nine)
    assert [row["id"] for row in promoted] == [request_id]
    assert db.get_request(request_id)["status"] == "approved"
    assert db.get_request(request_id)["is_released"] == 1
    assert db.get_request(request_id)["expected_release_date"] is None
    notifications[1].assert_called_once()
    assert notifications[1].call_args.kwargs["heading"] == "Pre-release Auto-approved"
    assert "approved" in notifications[1].call_args.kwargs["note"].lower()
    assert notifications[0].call_args.kwargs["new_status"] == "approved"


def test_due_group_downloads_and_notifies_once_across_repeated_scans(db, user_db, notifications):
    request_id = prerelease(db)
    linked = db.create_request(user_id=2, title="Due Book", canonical_request_id=request_id)
    db.update_request_status(request_id, "prerelease_requested")
    download = MagicMock()
    updates = MagicMock()
    now = datetime(2026, 11, 17, 9, tzinfo=ZoneInfo("America/New_York"))
    first = promote_due_prerelease_requests(db, user_db, now=now, on_request_approved=download, on_request_update=updates)
    assert len(first) == 1
    assert promote_due_prerelease_requests(db, user_db, now=now, on_request_approved=download, on_request_update=updates) == []
    download.assert_called_once_with(first[0])
    updates.assert_called_once_with(first[0])
    assert db.get_request(linked["id"])["status"] == "approved"
    assert db.get_request(linked["id"])["expected_release_date"] is None
    assert {call.kwargs["user_email"] for call in notifications[0].call_args_list} == {"reader-1@example.com", "reader-2@example.com"}
    notifications[1].assert_called_once()


@pytest.mark.parametrize("release_date", ["2099-01-01", "not-a-date", ""])
def test_future_or_invalid_dates_do_not_approve(db, user_db, notifications, release_date):
    request_id = prerelease(db, release_date)
    assert promote_due_prerelease_requests(db, user_db) == []
    assert db.get_request(request_id)["status"] == "prerelease_requested"
    notifications[0].assert_not_called()
    notifications[1].assert_not_called()


def test_due_request_catches_up_after_missed_release_time(db, user_db):
    request_id = prerelease(db, "2000-01-01")
    assert promote_due_prerelease_requests(db, user_db)[0]["status"] == "approved"
    assert db.get_request(request_id)["status"] == "approved"


def test_rescheduled_request_is_not_approved_from_stale_scan(db, user_db, notifications):
    request_id = prerelease(db, '2000-01-01')
    stale_rows = db.list_requests(status='prerelease_requested')
    db.update_request_metadata(request_id, expected_release_date='2099-01-01')
    with patch.object(db, 'list_requests', return_value=stale_rows):
        assert promote_due_prerelease_requests(db, user_db) == []
    assert db.get_request(request_id)['status'] == 'prerelease_requested'
    notifications[1].assert_not_called()


def test_download_callback_is_forwarded_by_loop(db, user_db):
    from shelfmark.core.prerelease_requests import run_prerelease_request_loop
    callback = MagicMock()
    with patch('shelfmark.core.prerelease_requests.promote_due_prerelease_requests') as promote, \
         patch('shelfmark.core.prerelease_requests.time.sleep', side_effect=InterruptedError):
        with pytest.raises(InterruptedError):
            run_prerelease_request_loop(db, user_db, on_request_approved=callback)
    promote.assert_called_once_with(db, user_db, on_request_update=None, on_request_approved=callback)


def test_automatic_download_reserves_slot_and_backfills_metadata():
    from shelfmark.core.request_routes import start_prerelease_download
    request_db, user_db = MagicMock(), MagicMock()
    req = {'id': 123456, 'status': 'approved', 'title': 'Manual pre-release'}
    request_db.get_request.return_value = req
    enriched = {**req, 'provider': 'googlebooks', 'provider_id': 'book-id'}
    with patch('shelfmark.core.request_routes.threading.Thread') as thread, \
         patch('shelfmark.core.request_routes._backfill_missing_metadata', return_value=enriched) as backfill, \
         patch('shelfmark.core.request_routes._auto_download_request') as download, \
         patch('shelfmark.core.request_routes._acquire_download_slot', return_value=True) as acquire:
        start_prerelease_download(request_db, user_db, req)
        acquire.assert_called_once_with(req['id'])
        thread.return_value.start.assert_called_once()
        thread.call_args.kwargs['target']()
        backfill.assert_called_once_with(request_db, req['id'], req)
        download.assert_called_once_with(request_db, user_db, req['id'], enriched)


def test_automatic_download_skips_already_reserved_request():
    from shelfmark.core.request_routes import start_prerelease_download
    with patch('shelfmark.core.request_routes._acquire_download_slot', return_value=False), \
         patch('shelfmark.core.request_routes.threading.Thread') as thread:
        start_prerelease_download(MagicMock(), MagicMock(), {'id': 123456})
    thread.assert_not_called()


def test_concurrent_scanners_claim_group_only_once(db, user_db, notifications):
    from concurrent.futures import ThreadPoolExecutor
    request_id = prerelease(db, '2000-01-01')
    second_db = RequestDB(db._db_path)
    snapshots = db.list_requests(status='prerelease_requested')
    download = MagicMock()
    with patch.object(db, 'list_requests', return_value=snapshots), \
         patch.object(second_db, 'list_requests', return_value=snapshots), \
         ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda scan_db: promote_due_prerelease_requests(scan_db, user_db, on_request_approved=download), [db, second_db]))
    assert sorted(map(len, results)) == [0, 1]
    assert db.get_request(request_id)['status'] == 'approved'
    download.assert_called_once()
    notifications[1].assert_called_once()


def test_automatic_download_releases_slot_if_thread_cannot_start():
    from shelfmark.core.request_routes import start_prerelease_download
    with patch('shelfmark.core.request_routes._acquire_download_slot', return_value=True), \
         patch('shelfmark.core.request_routes._release_download_slot') as release, \
         patch('shelfmark.core.request_routes.threading.Thread') as thread:
        thread.return_value.start.side_effect = RuntimeError('cannot start thread')
        with pytest.raises(RuntimeError):
            start_prerelease_download(MagicMock(), MagicMock(), {'id': 123456})
        release.assert_called_once_with(123456)


def test_download_does_not_start_if_admin_changed_status():
    from shelfmark.core.request_routes import start_prerelease_download
    db = MagicMock()
    db.get_request.return_value = {'id': 123456, 'status': 'denied'}
    with patch('shelfmark.core.request_routes._acquire_download_slot', return_value=True), \
         patch('shelfmark.core.request_routes._release_download_slot') as release, \
         patch('shelfmark.core.request_routes.threading.Thread') as thread, \
         patch('shelfmark.core.request_routes._auto_download_request') as download:
        start_prerelease_download(db, MagicMock(), {'id': 123456})
        thread.call_args.kwargs['target']()
        download.assert_not_called()
        release.assert_called_once_with(123456)


def test_approval_notifications_precede_download_status_changes(db, user_db, notifications):
    prerelease(db, '2000-01-01')
    events = []
    notifications[0].side_effect = lambda **kwargs: events.append('email')
    notifications[1].side_effect = lambda **kwargs: events.append('push')
    promote_due_prerelease_requests(db, user_db, on_request_approved=lambda req: events.append('download'))
    assert events == ['email', 'push', 'download']
