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


def _normalize(s: str) -> str:
    """Lowercase and strip punctuation for fuzzy comparison."""
    return re.sub(r'[^\w\s]', '', s.lower()).strip()


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
                    params={'minified': 1, 'limit': 0},
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
        """Return first ABS item fuzzy-matching title+author, or None (fail open)."""
        with self._cache_lock:
            cache = list(self._cache)

        if not cache:
            if not self.is_configured():
                return None
            self.refresh()
            with self._cache_lock:
                cache = list(self._cache)

        norm_title = _normalize(title)
        norm_author = _normalize(author or '')

        for item in cache:
            item_title = _normalize(item.get('title', ''))
            item_author = _normalize(item.get('author', ''))

            title_ratio = difflib.SequenceMatcher(None, norm_title, item_title).ratio()
            # Also accept when the query title is a leading substring of the stored title
            # (e.g. "The Hobbit" matching "The Hobbit A Novel")
            title_prefix_match = item_title.startswith(norm_title) or norm_title.startswith(item_title)
            if title_ratio < 0.85 and not title_prefix_match:
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
