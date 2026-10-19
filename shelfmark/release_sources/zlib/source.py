"""Z-Library release source - searches Z-Library's catalogue with a user account."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from shelfmark.core.config import config
from shelfmark.core.logger import setup_logger
from shelfmark.release_sources import (
    Release,
    ReleaseColumnConfig,
    ReleaseProtocol,
    ReleaseSource,
    register_source,
)
from shelfmark.release_sources.libgen.scraper import normalize_language
from shelfmark.release_sources.libgen.source import LibgenSource, _build_query_candidates
from shelfmark.release_sources.zlib import client

if TYPE_CHECKING:
    from shelfmark.core.search_plan import ReleaseSearchPlan
    from shelfmark.metadata_providers import BookMetadata

logger = setup_logger(__name__)

_DEFAULT_MAX_RESULTS = 10


@register_source("zlib")
class ZlibSource(ReleaseSource):
    """Release source backed by the Z-Library EAPI (needs a Z-Library account)."""

    name = "zlib"
    display_name = "Z-Library"
    supported_content_types: ClassVar[list[str]] = ["ebook"]

    def is_available(self) -> bool:
        return (
            config.get("ZLIB_SEARCH_ENABLED", False) is True
            and bool(config.get("ZLIB_EMAIL"))
            and bool(config.get("ZLIB_PASSWORD"))
        )

    def search(
        self,
        book: BookMetadata,
        plan: ReleaseSearchPlan,
        *,
        expand_search: bool = False,
        content_type: str = "ebook",
    ) -> list[Release]:
        if content_type != "ebook" or not self.is_available():
            return []
        limit = int(config.get("ZLIB_SEARCH_MAX_RESULTS", _DEFAULT_MAX_RESULTS) or _DEFAULT_MAX_RESULTS)
        formats = list(config.SUPPORTED_FORMATS or [])
        for query in _build_query_candidates(plan, book):
            logger.info("Searching Z-Library for: %s", query)
            books = client.search(query, formats, limit)
            if books:
                return [self._to_release(b) for b in books if b.get("id") and b.get("hash")]
        return []

    def _to_release(self, book: dict) -> Release:
        language = normalize_language(book.get("language"))
        href = book.get("href") or ""
        return Release(
            source="zlib",
            source_id=f"zlib:{book['id']}:{book['hash']}",
            title=book.get("title") or "Unknown",
            format=(book.get("extension") or "").lower() or None,
            language=language,
            size=book.get("filesizeString"),
            info_url=f"{client._base_url()}{href}" if href.startswith("/") else None,
            protocol=ReleaseProtocol.HTTP,
            indexer="Z-Library",
            content_type="ebook",
            extra={"author": book.get("author"), "year": book.get("year"), "language": language},
        )

    def get_column_config(self) -> ReleaseColumnConfig:
        return LibgenSource.get_column_config(self)

    def search_results_are_releases(self) -> bool:
        return True
