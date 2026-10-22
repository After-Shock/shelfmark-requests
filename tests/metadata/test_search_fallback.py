"""A failing or empty metadata provider falls back to the next enabled one."""

import pytest

import shelfmark.metadata_providers as mp


class _Fake:
    display_name = "Fake"

    def __init__(self, name, books=(), error=False):
        self.name, self.books, self.error, self.calls = name, list(books), error, []

    def is_available(self):
        return True

    def search_paginated(self, options):
        self.calls.append(options)
        if self.error:
            raise RuntimeError("503")
        return mp.SearchResult(books=self.books, page=options.page, total_found=len(self.books), has_more=False)


@pytest.fixture
def providers(monkeypatch):
    fakes = {"hardcover": _Fake("hardcover", books=["hc-book"]), "openlibrary": _Fake("openlibrary", books=["ol-book"])}
    monkeypatch.setattr(mp, "_PROVIDERS", {"googlebooks": object, **{n: object for n in fakes}})
    monkeypatch.setattr(mp, "is_provider_enabled", lambda name: name != "openlibrary")
    monkeypatch.setattr(mp, "get_provider", lambda name, **kw: fakes[name])
    monkeypatch.setattr(mp, "get_provider_kwargs", lambda name: {})
    return fakes


@pytest.mark.parametrize("primary", [_Fake("googlebooks"), _Fake("googlebooks", error=True)])
def test_empty_or_failing_primary_uses_next_enabled_provider(providers, primary):
    options = mp.MetadataSearchOptions(query="Fourth Wing", fields={"series": "x"})
    used, result = mp.search_with_fallback(primary, options)
    assert used.name == "hardcover" and result.books == ["hc-book"]
    assert providers["hardcover"].calls[0].fields == {}  # provider-specific fields dropped
    assert providers["openlibrary"].calls == []  # disabled


def test_primary_results_are_kept(providers):
    primary = _Fake("googlebooks", books=["gb-book"])
    used, result = mp.search_with_fallback(primary, mp.MetadataSearchOptions(query="x"))
    assert used is primary and providers["hardcover"].calls == []


def test_nothing_anywhere(providers):
    providers["hardcover"].books = []
    primary = _Fake("googlebooks")
    used, result = mp.search_with_fallback(primary, mp.MetadataSearchOptions(query="zzz"))
    assert used is primary and result.books == []
    with pytest.raises(RuntimeError):
        mp.search_with_fallback(_Fake("googlebooks", error=True), mp.MetadataSearchOptions(query="zzz"))
