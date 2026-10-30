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


def test_release_must_be_by_one_of_the_books_authors():
    from types import SimpleNamespace
    from shelfmark.core.request_routes import _release_matches_author

    def abb(raw):
        title, _, author = raw.rpartition(" - ")
        return SimpleNamespace(extra={"author": author, "title_raw": raw})

    authors = ["Rebecca Stead", "Wendy Mass"]
    assert not _release_matches_author(authors, abb("The Lost Library - A.M. Dean"))
    assert _release_matches_author(authors, abb("The Lost Library - Rebecca Stead, Wendy Mass"))
    # Narrator last: the author is still in the raw title.
    assert _release_matches_author(["H. D. Carlton"], abb("Haunting Adeline - H.D. Carlton - Teddy Hamilton"))
    assert _release_matches_author(["Kate Quinn"], abb("The Astral Library - ate Quinn"))
    # Nothing to compare against: don't reject.
    assert _release_matches_author(authors, SimpleNamespace(extra={}))
    assert _release_matches_author([], abb("The Lost Library - A.M. Dean"))


def _auto_download_note(releases=None, search_error=False):
    from types import SimpleNamespace
    from shelfmark.core import request_routes

    source = MagicMock()
    if search_error:
        source.search.side_effect = RuntimeError("ABB down")
    else:
        source.search.return_value = [
            SimpleNamespace(title=t, source="audiobookbay", extra={}) for t in (releases or [])
        ]
    book = SimpleNamespace(title="The Snow Child", authors=["Eowyn Ivey"], series_position=None)
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


def test_search_pages_are_fetched_without_the_session_cookie():
    # ABB leaves some new uploads out of search results when PHPSESSID is sent (2026-10-27).
    from shelfmark.release_sources.audiobookbay import scraper

    post = '<div class="post"><div class="postTitle"><h2><a href="/abss/book/">Book - Author</a></h2></div></div>'
    cookies_at_search = []

    def fake_get(url, *, session, **kwargs):
        if "?s=" in url:
            cookies_at_search.append(dict(session.cookies))
        session.cookies.set("PHPSESSID", "abc")  # every ABB response sets one
        return f"<html>{post}</html>", url

    with patch.object(scraper.downloader, "html_get_page", side_effect=fake_get), \
            patch.object(config, "get", side_effect=lambda k, d=None: 0 if k == "ABB_RATE_LIMIT_DELAY" else d):
        results = scraper.search_audiobookbay("book", max_pages=2)

    assert cookies_at_search == [{}, {}]
    assert [r["title"] for r in results] == ["Book - Author", "Book - Author"]


def test_release_subtitle_is_ignored_unless_it_names_another_book():
    from shelfmark.core.request_routes import _release_matches_title

    # ABB titles for "He Who Fights with Monsters" (book 1) on 2026-10-27, author already split off.
    abb_results = [
        "He Who Fights With Monsters, Books 1-12",
        "He Who Fights with Monsters 12",
        "He Who Fights with Monsters 9 [updated]",
        "He Who Fights with Monsters book 3 A LitRPG Adventure",
        "He Who Fights with Monsters - A LitRPG Adventure, Book 1",
        "Doctor Who: The War Doctor Begins: He Who Fights With Monsters",
    ]
    assert [t for t in abb_results if _release_matches_title("He Who Fights with Monsters", t, 1)] == [
        "He Who Fights with Monsters - A LitRPG Adventure, Book 1",
    ]
    assert not _release_matches_title("He Who Fights with Monsters", "He Who Fights with Monsters - Book 5", 1)
    assert _release_matches_title("Sing You Home", "Sing You Home: A Novel")


def test_junk_only_results_fall_through_to_the_next_query():
    from shelfmark.core.search_plan import ReleaseSearchPlan, ReleaseSearchVariant
    from shelfmark.release_sources.audiobookbay import source

    plan = ReleaseSearchPlan(
        languages=None, isbn_candidates=[], author="Jocko Willink", manual_query=None, indexers=None,
        title_variants=[ReleaseSearchVariant(title="Extreme Ownership: How U.S. Navy SEALs Lead and Win", author="Jocko Willink")],
        grouped_title_variants=[],
    )
    hit = {"title": "Extreme Ownership - Jocko Willink", "link": "https://audiobookbay.lu/abss/eo/"}
    queries = []

    def fake_search(query, **_):
        queries.append(query)
        # The full-title queries only find a homepage "Latest" item, which the relevance check drops.
        return [hit] if query == "extreme ownership jocko willink" else [{"title": "SUSPENSE Radio", "link": "x"}]

    settings = {"ABB_HOSTNAME": "audiobookbay.lu", "ABB_PAGE_LIMIT": 1}
    with patch.object(config, "get", side_effect=lambda k, d=None: settings.get(k, d)), patch.object(
        source.scraper, "search_audiobookbay", side_effect=fake_search
    ):
        releases = source.AudiobookBaySource().search(MagicMock(), plan, content_type="audiobook")

    assert queries == [
        "extreme ownership: how u.s. navy seals lead and win jocko willink",
        "extreme ownership: how u.s. navy seals lead and win",
        "extreme ownership jocko willink",
    ]
    assert [r.title for r in releases] == ["Extreme Ownership"]
