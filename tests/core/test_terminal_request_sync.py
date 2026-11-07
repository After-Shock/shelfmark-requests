"""One terminal download event must drive a request group exactly once."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock, patch

import pytest

from shelfmark.core.models import QueueStatus


@pytest.fixture(scope="module")
def main_module():
    fake_bs4 = types.ModuleType("bs4")
    fake_bs4.BeautifulSoup = object
    fake_bs4.NavigableString = object
    fake_bs4.Tag = object
    sys.modules.setdefault("bs4", fake_bs4)

    import shelfmark.download.orchestrator as orchestrator

    with patch.object(orchestrator, "start"):
        sys.modules.pop("shelfmark.main", None)
        import shelfmark.main as main

        importlib.reload(main)
        return main


def _group_db():
    db = Mock()
    db.get_requests_by_download_task.return_value = [
        {"id": 1, "canonical_request_id": None},
        {"id": 2, "canonical_request_id": 1},
    ]
    db.get_request.return_value = {"title": "Dune"}
    return db


def test_error_with_retry_does_not_fail_group_via_linked_row(main_module):
    from shelfmark.core import request_routes

    db = _group_db()
    with patch.object(main_module, "request_db", db), \
            patch.object(request_routes, "retry_next_release", side_effect=lambda _db, rid: rid == 1) as retry:
        main_module._sync_request_db_on_terminal("T1", QueueStatus.ERROR)

    retry.assert_called_once_with(db, 1)
    db.update_request_status.assert_not_called()


def test_complete_notifies_discord_once_per_group(main_module):
    db = _group_db()
    with patch.object(main_module, "request_db", db), \
            patch("shelfmark.core.discord_notifications.send_discord_book_available") as discord:
        main_module._sync_request_db_on_terminal("T1", QueueStatus.COMPLETE)

    db.update_request_status.assert_called_once_with(1, status="fulfilled", admin_note="")
    discord.assert_called_once()


def test_superseded_attempt_is_dropped_not_recorded(main_module):
    task = Mock(user_id=5, status_message="Download stalled (no activity for 300s)")
    with patch.object(main_module, "_sync_request_db_on_terminal", return_value=True), \
            patch.object(main_module.backend.book_queue, "forget") as forget, \
            patch.object(main_module, "_notify_admin_for_terminal_download_status") as notify, \
            patch.object(main_module, "activity_service") as activity:
        main_module._record_download_terminal_snapshot("T1", QueueStatus.CANCELLED, task)

    forget.assert_called_once_with("T1")
    notify.assert_not_called()
    activity.record_terminal_snapshot.assert_not_called()
