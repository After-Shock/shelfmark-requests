"""AudiobookBay query normalization and detail-URL validation (upstream #1242, #972)."""

from threading import Event
from unittest.mock import patch

from shelfmark.core.config import config
from shelfmark.core.models import DownloadTask
from shelfmark.release_sources.audiobookbay.handler import AudiobookBayHandler
from shelfmark.release_sources.audiobookbay.scraper import _encode_search_query
from shelfmark.release_sources.audiobookbay.utils import normalize_search_punctuation


def test_typographic_punctuation_maps_to_ascii():
    assert normalize_search_punctuation("The Stranger’s Wife — “Part”…") == (
        "The Stranger's Wife - \"Part\"..."
    )


def test_query_encoding_keeps_ampersand_inside_the_search():
    assert _encode_search_query("books 1 & 2", exact_phrase=False) == "books+1+%26+2"
    assert _encode_search_query("a b", exact_phrase=True) == "%22a+b%22"


def _resolve(detail_url):
    statuses = []
    task = DownloadTask(task_id="t", source="audiobookbay", title="X", source_url=detail_url)
    with patch.object(config, "get", side_effect=lambda k, d=None: {"ABB_HOSTNAME": "audiobookbay.lu"}.get(k, d)), patch(
        "shelfmark.release_sources.audiobookbay.handler.scraper.extract_magnet_link",
        return_value="magnet:?xt=urn:btih:abc",
    ) as extract:
        result = AudiobookBayHandler()._resolve_download(task, lambda s, m=None: statuses.append((s, m)))
    return result, statuses, extract


def test_detail_url_on_configured_host_is_resolved():
    result, _, extract = _resolve("https://audiobookbay.lu/abss/some-book/")
    assert result.url == "magnet:?xt=urn:btih:abc"
    extract.assert_called_once()


def test_detail_url_on_other_host_or_scheme_is_rejected():
    for url in ("https://evil.example/abss/x/", "http://audiobookbay.lu/abss/x/", "file:///etc/passwd"):
        result, statuses, extract = _resolve(url)
        assert result is None, url
        assert statuses[-1] == ("error", "Invalid AudiobookBay details URL")
        extract.assert_not_called()


def test_auto_download_only_keeps_releases_of_the_requested_title():
    from shelfmark.core.request_routes import _release_matches_title

    abb_results = [
        "Black Woods, Blue Sky",
        "The Snow Child",
        "To the Bright Edge of the World",
        "The Snow Child (Unabridged)",
    ]
    assert [t for t in abb_results if _release_matches_title("The Snow Child", t)] == [
        "The Snow Child",
        "The Snow Child (Unabridged)",
    ]
    assert _release_matches_title("The Snow Child: A Novel", "The Snow Child")
    assert not _release_matches_title("Dune", "Dune Messiah")
    assert not _release_matches_title(None, "Dune")
