"""Audiobookshelf library client with in-memory cache for duplicate detection."""

import difflib
import logging
import re
import threading
import time
from typing import Any, Optional

import requests as http_requests

from shelfmark.core.config import config

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL = 3600  # 1 hour
_TITLE_STOP_WORDS = {"a", "an", "and", "of", "the"}
_BENIGN_SUFFIX_TOKENS = {
    "adaptation",
    "audio",
    "audiobook",
    "book",
    "dramatized",
    "dramatised",
    "edition",
    "enhanced",
    "novel",
    "unabridged",
}


def _normalize(s: str) -> str:
    """Lowercase and strip punctuation for fuzzy comparison."""
    return re.sub(r'[^\w\s]', '', s.lower()).strip()


def _title_tokens(s: str) -> list[str]:
    """Split a title into normalized tokens, dropping common filler words."""
    return [token for token in _normalize(s).split() if token and token not in _TITLE_STOP_WORDS]


def _is_boundary_prefix_match(query_title: str, item_title: str) -> bool:
    """Return True when the item only adds benign suffix tokens to the query title."""
    norm_query = _normalize(query_title)
    norm_item = _normalize(item_title)
    if not norm_query or not norm_item:
        return False
    if norm_query == norm_item:
        return True
    if not norm_item.startswith(f"{norm_query} "):
        return False

    suffix_tokens = [
        token for token in norm_item[len(norm_query):].strip().split()
        if token and token not in _TITLE_STOP_WORDS
    ]
    return bool(suffix_tokens) and set(suffix_tokens) <= _BENIGN_SUFFIX_TOKENS


def _titles_match(query_title: str, item_title: str) -> bool:
    """Return True when two titles are close enough to represent the same work."""
    norm_query = _normalize(query_title)
    norm_item = _normalize(item_title)
    if not norm_query or not norm_item:
        return False

    if _is_boundary_prefix_match(query_title, item_title):
        return True

    query_tokens = set(_title_tokens(query_title))
    item_tokens = set(_title_tokens(item_title))
    if query_tokens and item_tokens:
        if query_tokens == item_tokens:
            return True

    # Allow small typos only when the titles have the same token structure.
    if len(_normalize(query_title).split()) == len(_normalize(item_title).split()):
        return difflib.SequenceMatcher(None, norm_query, norm_item).ratio() >= 0.92

    return False


class ABSClient:
    """Audiobookshelf API client with in-memory library cache."""

    def __init__(self) -> None:
        self._cache: list[dict[str, Any]] = []
        self._cache_lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None

    def is_configured(self) -> bool:
        """Return True if both URL and API token are set."""
        url = config.get('AUDIOBOOK_LIBRARY_URL', '') or ''
        token = config.get('ABS_API_TOKEN', '') or ''
        return bool(url.strip() and token.strip())

    def _get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        url = (config.get('AUDIOBOOK_LIBRARY_URL', '') or '').rstrip('/')
        token = config.get('ABS_API_TOKEN', '') or ''
        return (url or None, token or None)

    def refresh(self) -> int:
        """Fetch all audiobook items from ABS and update the cache. Returns item count."""
        url, token = self._get_credentials()
        if not url or not token:
            return 0

        headers = {'Authorization': f'Bearer {token}'}
        try:
            resp = http_requests.get(f'{url}/api/libraries', headers=headers, timeout=10)
            resp.raise_for_status()
            libraries = resp.json().get('libraries', [])

            items: list[dict[str, Any]] = []
            for lib in libraries:
                if lib.get('mediaType') != 'book':
                    continue
                lib_id = lib['id']
                resp = http_requests.get(
                    f'{url}/api/libraries/{lib_id}/items',
                    headers=headers,
                    params={'minified': 1, 'limit': 0},  # limit=0 disables pagination in the ABS API
                    timeout=30,
                )
                resp.raise_for_status()
                for item in resp.json().get('results', []):
                    meta = (item.get('media') or {}).get('metadata') or {}
                    title = meta.get('title') or ''
                    author = meta.get('authorName') or ''
                    if title:
                        items.append({
                            'id': item.get('id', ''),
                            'title': title,
                            'author': author,
                        })

            with self._cache_lock:
                self._cache = items
            logger.info("ABS cache refreshed: %d items", len(items))
            return len(items)

        except Exception as exc:
            logger.warning("Failed to refresh ABS library cache: %s", exc)
            return 0

    def find_match(self, title: str, author: str) -> Optional[dict[str, Any]]:
        """Return first ABS item fuzzy-matching title+author, or None (fail open).

        Note: if ABS was previously configured and the cache was populated, then
        the API token is later removed, this method will continue returning matches
        from the stale in-memory cache until the process restarts. This is intentional
        fail-open behavior — it is preferable to allow a duplicate request through
        than to block all requests because credentials are temporarily missing.
        """
        with self._cache_lock:
            cache = list(self._cache)

        if not cache:
            if not self.is_configured():
                return None
            self.refresh()
            with self._cache_lock:
                cache = list(self._cache)

        norm_author = _normalize(author or '')

        for item in cache:
            item_title = item.get('title', '')
            item_author = _normalize(item.get('author', ''))

            if not _titles_match(title, item_title):
                continue

            if not norm_author or not item_author:
                return item

            author_ratio = difflib.SequenceMatcher(None, norm_author, item_author).ratio()
            if author_ratio >= 0.70:
                return item

        return None

    def start_background_refresh(self) -> None:
        """Start a daemon thread that refreshes the cache every hour."""
        if self._refresh_thread and self._refresh_thread.is_alive():
            return

        def _loop() -> None:
            self.refresh()
            while True:
                time.sleep(_REFRESH_INTERVAL)
                self.refresh()

        self._refresh_thread = threading.Thread(
            target=_loop, daemon=True, name='abs-cache-refresh'
        )
        self._refresh_thread.start()


# Module-level singleton
abs_client = ABSClient()
