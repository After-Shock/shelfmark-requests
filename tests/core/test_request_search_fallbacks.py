"""Requests that failed with 'Not found' / 'Metadata lookup failed' for fixable reasons."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from shelfmark.core.search_plan import (
    ReleaseSearchPlan,
    ReleaseSearchVariant,
    _pick_search_title,
)


def test_series_suffix_is_dropped_from_search_title():
    def title(t):
        return _pick_search_title(SimpleNamespace(search_title=None, title=t))

    assert title("Anathema (The Eating Woods, #1)") == "Anathema"
    assert title("Hexes Go Well with Tequila (The Lost Souls Series, Book 1)") == "Hexes Go Well with Tequila"
    assert title("Notes (Annotated)") == "Notes (Annotated)"
    assert title("The Washwoman at the River's End") == "The Washwoman at the River's End"


def test_metadata_backfill_falls_back_when_configured_provider_is_down():
    from shelfmark.core import request_routes

    google = MagicMock()
    google.name = "googlebooks"
    google.search.return_value = []  # Google Books answering 503
    hardcover = MagicMock()
    hardcover.name = "hardcover"
    hardcover.search.return_value = [SimpleNamespace(provider_id="hc-1", publish_date=None)]
    request_db = MagicMock()
    request_db.update_request_metadata.return_value = {"id": 368, "provider": "hardcover", "provider_id": "hc-1"}

    with patch("shelfmark.metadata_providers.get_configured_provider", return_value=google), patch(
        "shelfmark.metadata_providers.get_enabled_providers", return_value=["googlebooks", "hardcover"]
    ), patch("shelfmark.metadata_providers.get_provider", return_value=hardcover), patch(
        "shelfmark.metadata_providers.get_provider_kwargs", return_value={}
    ):
        result = request_routes._backfill_missing_metadata(
            request_db, 368, {"title": "Death of a Mortal", "author": "Someone", "content_type": "ebook"}
        )

    assert result["provider"] == "hardcover"
    assert request_db.update_request_metadata.call_args.kwargs["provider_id"] == "hc-1"


def test_direct_download_falls_back_to_isbn_when_title_search_is_empty():
    from shelfmark.release_sources import direct_download as dd

    plan = ReleaseSearchPlan(
        languages=None,
        isbn_candidates=["9780000000001"],
        author="Keri Lake",
        title_variants=[],
        grouped_title_variants=[ReleaseSearchVariant(title="Anathema", author="Keri Lake")],
    )
    queries = []

    def fake_search(query, filters):
        queries.append(query)
        return ["hit"] if query == "9780000000001" else []

    with patch.object(dd, "search_books", side_effect=fake_search), patch.object(
        dd, "_book_info_to_release", side_effect=lambda bi: bi
    ):
        releases = dd.DirectDownloadSource().search(MagicMock(), plan, expand_search=True)

    assert queries == ["Anathema Keri Lake", "9780000000001"]
    assert releases == ["hit"]


def test_release_title_with_series_suffix_matches():
    from shelfmark.core.request_routes import _release_matches_title

    assert _release_matches_title("The ice beyond", "The Ice Beyond (The Empress of Thorns Book 1)")
    assert not _release_matches_title("The Ice Beyond", "Ice Cold Player (Beyond the Ice Book 1)")
