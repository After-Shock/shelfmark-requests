"""AudiobookBay query normalization and detail-URL validation (upstream #1242, #972)."""

from threading import Event
from unittest.mock import MagicMock, patch

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


def _auto_download_note(releases=None, search_error=False):
    from types import SimpleNamespace
    from shelfmark.core import request_routes

    source = MagicMock()
    if search_error:
        source.search.side_effect = RuntimeError("ABB down")
    else:
        source.search.return_value = [SimpleNamespace(title=t, source="audiobookbay") for t in (releases or [])]
    book = SimpleNamespace(title="The Snow Child", authors=["Eowyn Ivey"])
    calls = []
    with patch("shelfmark.release_sources.list_available_sources", return_value=[
        {"name": "audiobookbay", "enabled": True, "supported_content_types": ["audiobook"]},
        {"name": "direct_download", "enabled": True, "supported_content_types": ["ebook"]},
    ]), patch("shelfmark.release_sources.get_source", return_value=source), patch(
        "shelfmark.metadata_providers.is_provider_registered", return_value=True
    ), patch("shelfmark.metadata_providers.get_provider_kwargs", return_value={}), patch(
        "shelfmark.metadata_providers.get_provider", return_value=MagicMock(get_book=MagicMock(return_value=book))
    ), patch("shelfmark.core.search_plan.build_release_search_plan"), patch.object(
        request_routes, "_set_request_status", side_effect=lambda *a, **k: calls.append((a[3], k))
    ):
        request_routes._auto_download_request(
            MagicMock(), MagicMock(), 362,
            {"provider": "googlebooks", "provider_id": "x", "content_type": "audiobook"},
        )
    assert calls and calls[-1][0] == "failed"
    return calls[-1][1]["admin_note"]


def test_audiobook_with_no_matching_release_reports_no_automation_resources():
    note = _auto_download_note(releases=["Black Woods, Blue Sky"])
    assert note == "No automation resources found: no AudiobookBay release matches 'The Snow Child'."


def test_audiobook_search_failure_is_not_reported_as_unavailable():
    note = _auto_download_note(search_error=True)
    assert note == "Search failed on AudiobookBay. Try again later."
