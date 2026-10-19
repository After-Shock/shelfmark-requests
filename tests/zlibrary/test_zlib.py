"""Z-Library source: EAPI results -> Releases, and the download handler."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from shelfmark.core.search_plan import ReleaseSearchPlan, ReleaseSearchVariant
from shelfmark.release_sources.zlib import client
from shelfmark.release_sources.zlib.handler import ZlibHandler
from shelfmark.release_sources.zlib.source import ZlibSource

ENABLED = {"ZLIB_SEARCH_ENABLED": True, "ZLIB_EMAIL": "a@b.c", "ZLIB_PASSWORD": "pw", "ZLIB_SEARCH_MAX_RESULTS": 5}
BOOK = {
    "id": 121001581, "hash": "a1b2c3", "title": "Anathema", "author": "Keri Lake",
    "extension": "EPUB", "filesizeString": "2.20 MB", "year": "2023", "language": "english",
    "href": "/book/121001581/a1b2c3/anathema.html",
}


def _cfg(values):
    return patch("shelfmark.release_sources.zlib.source.config", SimpleNamespace(
        get=lambda k, d=None: values.get(k, d), SUPPORTED_FORMATS=["epub"]))


def _plan():
    variant = ReleaseSearchVariant(title="Anathema", author="Keri Lake")
    return ReleaseSearchPlan(languages=None, isbn_candidates=[], author="Keri Lake",
                             title_variants=[variant], grouped_title_variants=[variant])


def test_disabled_or_missing_login_is_unavailable():
    for values in ({}, {**ENABLED, "ZLIB_PASSWORD": ""}, {**ENABLED, "ZLIB_SEARCH_ENABLED": "true"}):
        with _cfg(values):
            assert not ZlibSource().is_available()


def test_search_maps_eapi_books_to_releases():
    with _cfg(ENABLED), patch.object(client, "search", return_value=[BOOK]) as search, \
         patch.object(client, "_base_url", return_value="https://z-library.sk"):
        releases = ZlibSource().search(SimpleNamespace(title="Anathema"), _plan())
    search.assert_called_once_with("Anathema Keri Lake", ["epub"], 5)
    r = releases[0]
    assert (r.source, r.source_id, r.format, r.language, r.size) == ("zlib", "zlib:121001581:a1b2c3", "epub", "en", "2.20 MB")
    assert r.info_url == "https://z-library.sk/book/121001581/a1b2c3/anathema.html"
    assert r.extra["author"] == "Keri Lake"


def _task(tmp_path):
    return SimpleNamespace(task_id="zlib:121001581:a1b2c3", title="Anathema", author="Keri Lake", year="2023", format="epub")


def test_handler_downloads_file(tmp_path):
    statuses = []

    def fake_download(url, dest, progress, is_cancelled):
        dest.write_bytes(b"PK" + b"x" * 20000)
        return True

    with patch("shelfmark.release_sources.zlib.handler.TMP_DIR", tmp_path), \
         patch.object(client, "download_link", return_value="https://dl/x") as link, \
         patch.object(client, "download", side_effect=fake_download):
        path = ZlibHandler().download(_task(tmp_path), Event(), lambda p: None, lambda s, m=None: statuses.append(s))
    link.assert_called_once_with("121001581", "a1b2c3")
    assert path and path.endswith(".epub")


def test_handler_reports_daily_limit(tmp_path):
    statuses = []
    with patch("shelfmark.release_sources.zlib.handler.TMP_DIR", tmp_path), \
         patch.object(client, "download_link", side_effect=client.ZlibError("Z-Library gave no download link: Daily limit reached")):
        path = ZlibHandler().download(_task(tmp_path), Event(), lambda p: None, lambda s, m=None: statuses.append((s, m)))
    assert path is None
    assert statuses[-1] == ("error", "Z-Library gave no download link: Daily limit reached")


def test_auto_download_drops_other_books_from_loose_sources():
    from shelfmark.core.request_routes import _release_matches_title

    releases = [SimpleNamespace(source="zlib", title="Anathema"), SimpleNamespace(source="libgen", title="Bad Things")]
    kept = [r for r in releases if r.source == "direct_download" or _release_matches_title("Anathema", r.title)]
    assert [r.title for r in kept] == ["Anathema"]
