"""Requests must not stay 'approved'/'downloading' after a cancel or a restart."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shelfmark.core import request_routes
from shelfmark.core.models import QueueStatus


def test_restart_resumes_approved_and_downloading_requests(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(request_routes, "_resume_lock", None)
    request_db = MagicMock()
    request_db.list_requests.side_effect = lambda status, **kw: {
        "approved": [{"id": 365, "approved_by": 1}],
        "downloading": [{"id": 367, "approved_by": 1}, {"id": 999, "canonical_request_id": 367}],
    }[status]
    user_db = MagicMock()
    user_db.get_user.return_value = {"username": "admin"}

    with patch.object(request_routes, "_auto_download_request") as auto, \
         patch.object(request_routes, "_acquire_download_slot", return_value=True):
        request_routes.resume_interrupted_requests(request_db, user_db)

    assert [c.args[2] for c in auto.call_args_list] == [365, 367]  # linked row 999 skipped
    assert auto.call_args_list[0].args[4:] == (1, "admin")

    # A second process (or a script importing shelfmark.main) must not resume again.
    with patch.object(request_routes, "_auto_download_request") as auto_again, \
         patch.object(request_routes, "_acquire_download_slot", return_value=True):
        request_routes.resume_interrupted_requests(request_db, user_db)
    auto_again.assert_not_called()


def _sync(status_message, retry_ok):
    import shelfmark.main as main

    request_db = MagicMock()
    request_db.get_requests_by_download_task.return_value = [{"id": 367}]
    task = SimpleNamespace(status_message=status_message)
    with patch.object(main, "request_db", request_db), \
         patch.object(main.backend.book_queue, "get_task", return_value=task), \
         patch.object(request_routes, "retry_next_release", return_value=retry_ok) as retry:
        main._sync_request_db_on_terminal("0e75", QueueStatus.CANCELLED)
    return request_db, retry


def test_stalled_download_moves_to_next_release():
    request_db, retry = _sync("Download stalled (no activity for 300s)", retry_ok=True)
    retry.assert_called_once_with(request_db, 367)
    request_db.update_request_status.assert_not_called()


def test_stalled_download_with_nothing_left_fails_with_note():
    request_db, _ = _sync("Download stalled (no activity for 300s)", retry_ok=False)
    request_db.update_request_status.assert_called_once_with(
        367, status="failed", admin_note="Download stalled and no other releases were left to try."
    )


def test_user_cancel_fails_request_without_retrying():
    request_db, retry = _sync("Cancelled", retry_ok=True)
    retry.assert_not_called()
    request_db.update_request_status.assert_called_once_with(
        367, status="failed", admin_note="Download was cancelled. Retry to search again."
    )
