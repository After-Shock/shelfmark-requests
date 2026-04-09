from unittest.mock import MagicMock, patch


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
        "expected_release_date": "2000-01-01",
    }
    user_db.get_user.return_value = {"id": 3, "email": "reader@example.com"}

    with patch("shelfmark.core.prerelease_requests.send_request_notification") as mock_notify:
        promoted = promote_due_prerelease_requests(request_db, user_db)

    assert [row["id"] for row in promoted] == [10]
    request_db.update_request_status.assert_called_once_with(10, "pending")
    mock_notify.assert_called_once()


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
