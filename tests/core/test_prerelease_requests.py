from datetime import datetime
import sqlite3
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from shelfmark.core.request_db import RequestDB


def test_promote_due_prerelease_requests_moves_due_rows_to_pending():
    from shelfmark.core.prerelease_requests import promote_due_prerelease_requests

    request_db = MagicMock()
    user_db = MagicMock()
    request_db.list_requests.return_value = [
        {
            "id": 10,
            "status": "prerelease_requested",
            "title": "Due Book",
            "user_id": 3,
            "expected_release_date": "2000-01-01",
        }
    ]
    request_db.update_request_status.return_value = {
        "id": 10,
        "status": "pending",
        "title": "Due Book",
        "user_id": 3,
        "expected_release_date": None,
        "is_released": True,
    }
    user_db.get_user.return_value = {"id": 3, "email": "reader@example.com"}
    request_db.get_request_group.return_value = [request_db.update_request_status.return_value]

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db)

    assert [row["id"] for row in promoted] == [10]
    request_db.update_request_metadata.assert_called_once_with(
        10,
        is_released=True,
        clear_expected_release_date=True,
    )
    request_db.update_request_status.assert_called_once_with(10, "pending")
    mock_notify.assert_called_once()


def test_promote_due_prerelease_requests_waits_until_9am_eastern():
    from shelfmark.core.prerelease_requests import promote_due_prerelease_requests

    request_db = MagicMock()
    user_db = MagicMock()
    request_db.list_requests.return_value = [
        {
            "id": 13,
            "status": "prerelease_requested",
            "title": "Morning Book",
            "user_id": 3,
            "expected_release_date": "2026-05-05",
        }
    ]

    before_nine = datetime(2026, 5, 5, 8, 59, tzinfo=ZoneInfo("America/New_York"))
    at_nine = datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("America/New_York"))

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db, now=before_nine)

    assert promoted == []
    request_db.update_request_status.assert_not_called()
    mock_notify.assert_not_called()

    request_db.update_request_status.reset_mock()
    request_db.update_request_metadata.reset_mock()
    request_db.update_request_status.return_value = {
        "id": 13,
        "status": "pending",
        "title": "Morning Book",
        "user_id": 3,
        "expected_release_date": None,
        "is_released": True,
    }
    user_db.get_user.return_value = {"id": 3, "email": "reader@example.com"}
    request_db.get_request_group.return_value = [request_db.update_request_status.return_value]

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db, now=at_nine)

    assert [row["id"] for row in promoted] == [13]
    request_db.update_request_status.assert_called_once_with(13, "pending")
    mock_notify.assert_called_once()


def test_promote_due_prerelease_requests_processes_only_canonical_group_member(tmp_path):
    from shelfmark.core.prerelease_requests import promote_due_prerelease_requests

    db_path = tmp_path / "requests.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, role TEXT)"
        )
        conn.executemany(
            "INSERT INTO users (id, username, display_name, role) VALUES (?, ?, ?, 'user')",
            [(1, "first", "First"), (2, "second", "Second")],
        )
    request_db = RequestDB(str(db_path))
    request_db.initialize()
    canonical, _ = request_db.create_or_join_request(
        user_id=1, title="Due Book", author="Author", content_type="ebook"
    )
    linked, _ = request_db.create_or_join_request(
        user_id=2, title="Due Book", author="Author", content_type="ebook"
    )
    request_db.update_request_metadata(canonical["id"], expected_release_date="2000-01-01")
    request_db.update_request_status(canonical["id"], "prerelease_requested")
    user_db = MagicMock()
    user_db.get_user.side_effect = lambda *, user_id: {
        1: {"email": "first@example.com"},
        2: {"email": "second@example.com"},
    }.get(user_id)

    with patch.object(request_db, "update_request_status", wraps=request_db.update_request_status) as update_status, \
         patch("shelfmark.core.prerelease_requests.send_request_notification") as notify:
        promoted = promote_due_prerelease_requests(request_db, user_db)

    assert [row["id"] for row in promoted] == [canonical["id"]]
    update_status.assert_called_once_with(canonical["id"], "pending")
    assert request_db.get_request(linked["id"])["status"] == "pending"
    assert {call.kwargs["user_email"] for call in notify.call_args_list} == {
        "first@example.com",
        "second@example.com",
    }


def test_promote_due_prerelease_requests_ignores_future_rows():
    from shelfmark.core.prerelease_requests import promote_due_prerelease_requests

    request_db = MagicMock()
    user_db = MagicMock()
    request_db.list_requests.return_value = [
        {
            "id": 11,
            "status": "prerelease_requested",
            "title": "Future Book",
            "user_id": 4,
            "expected_release_date": "2099-01-01",
        }
    ]

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db)

    assert promoted == []
    request_db.update_request_status.assert_not_called()
    mock_notify.assert_not_called()


def test_promote_due_prerelease_requests_skips_invalid_dates():
    from shelfmark.core.prerelease_requests import promote_due_prerelease_requests

    request_db = MagicMock()
    user_db = MagicMock()
    request_db.list_requests.return_value = [
        {
            "id": 12,
            "status": "prerelease_requested",
            "title": "Broken Date Book",
            "user_id": 5,
            "expected_release_date": "not-a-date",
        }
    ]

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db)

    assert promoted == []
    request_db.update_request_status.assert_not_called()
    mock_notify.assert_not_called()
