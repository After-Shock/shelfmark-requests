"""Torrent hand-off mode and AudiobookBay registration."""

import subprocess
import sys
from threading import Event
from unittest.mock import MagicMock, patch

from shelfmark.core.config import config
from shelfmark.core.models import DownloadTask
from shelfmark.release_sources import HANDOFF_COMPLETE
from shelfmark.release_sources.audiobookbay.handler import AudiobookBayHandler

MAGNET = "magnet:?xt=urn:btih:ABCDEF0123456789ABCDEF0123456789ABCDEF01"


def _run(handoff_only: bool, existing=None):
    client = MagicMock()
    client.name = "qbittorrent"
    client.find_existing.return_value = existing
    client.add_download.return_value = "abcdef0123456789abcdef0123456789abcdef01"
    settings = {"TORRENT_HANDOFF_ONLY": handoff_only, "ABB_HOSTNAME": "audiobookbay.lu"}
    statuses = []

    with patch.object(config, "get", side_effect=lambda k, d=None: settings.get(k, d)), patch(
        "shelfmark.release_sources.audiobookbay.handler.scraper.extract_magnet_link",
        return_value=MAGNET,
    ), patch(
        "shelfmark.release_sources.audiobookbay.handler.get_client", return_value=client
    ), patch.object(AudiobookBayHandler, "_poll_and_complete", return_value="/polled") as poll:
        task = DownloadTask(
            task_id="t1",
            source="audiobookbay",
            title="Some Audiobook",
            source_url="https://audiobookbay.lu/abss/some-audiobook/",
            content_type="audiobook",
        )
        result = AudiobookBayHandler().download(
            task, Event(), lambda p: None, lambda s, m=None: statuses.append((s, m))
        )
    return result, statuses, client, poll


def test_handoff_sends_magnet_and_completes_without_polling():
    result, statuses, client, poll = _run(handoff_only=True)

    assert result == HANDOFF_COMPLETE
    assert client.add_download.call_args.kwargs["url"] == MAGNET
    poll.assert_not_called()
    assert statuses[-1] == ("complete", "Sent to qbittorrent (abcdef0123456789abcdef0123456789abcdef01)")


def test_handoff_completes_when_torrent_already_in_client():
    result, _, client, poll = _run(handoff_only=True, existing=("abc", MagicMock(complete=False)))

    assert result == HANDOFF_COMPLETE
    client.add_download.assert_not_called()
    poll.assert_not_called()


def test_without_handoff_still_polls_for_import():
    result, _, _, poll = _run(handoff_only=False)

    assert result == "/polled"
    poll.assert_called_once()


def test_audiobookbay_registers_with_the_source_registry():
    # Fresh interpreter: importing the ABB handler above registers it on its own.
    code = (
        "from shelfmark.release_sources import list_available_sources as l;"
        "assert 'audiobookbay' in {s['name'] for s in l()}"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
