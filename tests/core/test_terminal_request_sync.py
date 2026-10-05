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

    db.update_request_status.assert_called_once_with(1, status="fulfilled")
    discord.assert_called_once()
