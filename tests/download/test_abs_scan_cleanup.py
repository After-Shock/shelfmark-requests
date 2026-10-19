"""Audiobook torrents: scan Audiobookshelf after import, then remove the torrent."""

from unittest.mock import MagicMock, patch

from shelfmark.core.models import DownloadTask
from shelfmark.release_sources.audiobookbay.handler import AudiobookBayHandler  # loads sources first, as the app does
from shelfmark.download.clients import base_handler

MOD = "shelfmark.download.clients.base_handler"


def _run_scan(match_after_polls: int | None, scan_ok: bool = True, watcher_wait: float = 0):
    client = MagicMock()
    client.name = "qbittorrent"
    abs_client = MagicMock()
    abs_client.scan_libraries.return_value = scan_ok
    results = [None] * (match_after_polls or 0) + [{"title": "The Snow Child"}]
    abs_client.find_match.side_effect = lambda *a: results.pop(0) if match_after_polls is not None and results else None
    with patch(f"{MOD}.abs_client", abs_client), patch(f"{MOD}.ABS_SCAN_POLL_SECONDS", 0), patch(
        f"{MOD}.ABS_SCAN_WAIT_SECONDS", 0.05
    ), patch(f"{MOD}.ABS_WATCHER_WAIT_SECONDS", watcher_wait):
        base_handler._scan_abs_then_remove_torrent(client, "hash1", "The Snow Child", "Eowyn Ivey")
    return client, abs_client


def test_removes_torrent_and_files_once_book_is_in_audiobookshelf():
    client, abs_client = _run_scan(match_after_polls=2)

    abs_client.scan_libraries.assert_called_once()
    client.remove.assert_called_once_with("hash1", delete_files=True)


def test_keeps_torrent_when_book_never_shows_up():
    client, _ = _run_scan(match_after_polls=None)

    client.remove.assert_not_called()


def test_keeps_torrent_when_scan_cannot_start():
    client, abs_client = _run_scan(match_after_polls=None, scan_ok=False)

    abs_client.scan_libraries.assert_called_once()
    client.remove.assert_not_called()


def test_skips_full_scan_when_folder_watcher_already_added_the_book():
    # A full scan racing the watcher added Not My Father's Son twice.
    client, abs_client = _run_scan(match_after_polls=1, watcher_wait=0.05)

    abs_client.scan_libraries.assert_not_called()
    client.remove.assert_called_once_with("hash1", delete_files=True)


def test_cleanup_starts_scan_only_for_imported_audiobook_torrents():
    handler = AudiobookBayHandler()
    client = MagicMock()
    for content_type, success, expected in [("audiobook", True, 1), ("ebook", True, 0), ("audiobook", False, 0)]:
        task = DownloadTask(task_id="t", source="audiobookbay", title="X", author="Y", content_type=content_type)
        handler._cleanup_refs["t"] = (client, "hash1", "torrent")
        with patch(f"{MOD}.abs_client") as abs_client, patch(f"{MOD}.threading.Thread") as thread:
            abs_client.is_configured.return_value = True
            handler.post_process_cleanup(task, success=success)
        assert thread.call_count == expected, (content_type, success)
