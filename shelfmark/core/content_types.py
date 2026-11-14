"""Content-type helpers for releases and release sources."""

from __future__ import annotations

from typing import Any, Sequence

DEFAULT_SUPPORTED_CONTENT_TYPES = ("ebook", "audiobook")


def normalize_content_type(content_type: Any) -> str:
    """Normalize arbitrary content type values to `ebook` or `audiobook`."""
    if not isinstance(content_type, str):
        return "ebook"

    value = content_type.strip().lower()
    if not value:
        return "ebook"

    if value in {"audiobook", "audiobooks", "audio", "book (audiobook)"}:
        return "audiobook"

    return "ebook"


def normalize_source(source: Any) -> str:
    """Normalize a source name for lookups."""
    if not isinstance(source, str):
        return "*"

    value = source.strip().lower()
    return value or "*"


def _normalize_rule_content_type(content_type: Any) -> str | None:
    if not isinstance(content_type, str):
        return None
    value = content_type.strip().lower()
    if not value:
        return None
    if value in {"*", "any"}:
        return "*"
    if value in {"ebook", "book", "books", "book (fiction)"}:
        return "ebook"
    if value in {"audiobook", "audiobooks", "audio", "book (audiobook)"}:
        return "audiobook"
    return None


def get_source_content_type_capabilities() -> dict[str, set[str]]:
    """Return source -> supported content type map from registered sources."""
    try:
        from shelfmark.release_sources import list_available_sources
    except Exception:
        return {}

    capabilities: dict[str, set[str]] = {}
    for source in list_available_sources():
        raw_name = source.get("name")
        name = normalize_source(raw_name)
        if not name or name == "*":
            continue

        raw_types = source.get("supported_content_types", DEFAULT_SUPPORTED_CONTENT_TYPES)
        if isinstance(raw_types, str) or not isinstance(raw_types, Sequence):
            raw_types = DEFAULT_SUPPORTED_CONTENT_TYPES

        normalized_types: set[str] = set()
        for content_type in raw_types:
            normalized_type = _normalize_rule_content_type(content_type)
            if normalized_type and normalized_type != "*":
                normalized_types.add(normalized_type)

        if not normalized_types:
            normalized_types = set(DEFAULT_SUPPORTED_CONTENT_TYPES)
        capabilities[name] = normalized_types
    return capabilities
