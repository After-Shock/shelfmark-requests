"""Anna's Archive release source - JSON API integration."""

import json
import time
from pathlib import Path
from threading import Event
from typing import Callable, List, Optional
from urllib.parse import quote

import requests

from shelfmark.core.config import config
from shelfmark.core.logger import setup_logger
from shelfmark.core.models import DownloadTask
from shelfmark.metadata_providers import BookMetadata
from shelfmark.release_sources import (
    Release,
    ReleaseProtocol,
    ReleaseSource,
    DownloadHandler,
    register_source,
    register_handler,
    ReleaseColumnConfig,
    ColumnSchema,
    ColumnRenderType,
    ColumnAlign,
    ColumnColorHint,
)
from shelfmark.download import http as downloader

# Import settings to register them
from shelfmark.release_sources.annasarchive import settings  # noqa: F401

logger = setup_logger(__name__)

# Anna's Archive mirrors
ANNASARCHIVE_MIRRORS = [
    "https://annas-archive.li",
    "https://annas-archive.gs",
    "https://annas-archive.se",
]


def _get_base_url() -> str:
    """Get configured base URL or default."""
    custom_url = config.get("ANNASARCHIVE_API_BASE_URL", "").strip()
    if custom_url:
        return custom_url
    return ANNASARCHIVE_MIRRORS[0]


def _get_api_key() -> Optional[str]:
    """Get Anna's Archive API key (donator key)."""
    return config.get("AA_DONATOR_KEY", "").strip() or None


@register_source("annasarchive")
class AnnasArchiveSource(ReleaseSource):
    """Anna's Archive release source using JSON API."""

    name = "annasarchive"
    display_name = "Anna's Archive"
    supported_content_types = ["ebook", "audiobook"]
    can_be_default = True

    def __init__(self):
        """Initialize Anna's Archive source."""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

    def is_available(self) -> bool:
        """Check if Anna's Archive is available."""
        # Check if enabled in settings
        enabled = config.get("ANNASARCHIVE_API_ENABLED", False)
        if not enabled:
            return False

        # Source is available if we have an API key
        api_key = _get_api_key()
        if not api_key:
            logger.debug("Anna's Archive API key not configured")
            return False

        return True

    def search(
        self,
        book: BookMetadata,
        plan,
        expand_search: bool = False,
        content_type: str = "ebook"
    ) -> List[Release]:
        """Search Anna's Archive using JSON API."""
        api_key = _get_api_key()
        if not api_key:
            logger.warning("Anna's Archive API key not configured")
            return []

        base_url = _get_base_url()

        # Build search query
        search_terms = []
        if book.title:
            search_terms.append(book.title)
        if book.authors and not expand_search:
            search_terms.append(book.authors[0])

        query = " ".join(search_terms)

        # Try ISBN search first if available
        if book.isbn_13 or book.isbn_10:
            isbn = book.isbn_13 or book.isbn_10
            results = self._search_by_isbn(base_url, isbn, api_key, content_type)
            if results:
                return results

        # Fall back to text search
        return self._search_by_text(base_url, query, api_key, content_type, expand_search)

    def _search_by_isbn(
        self,
        base_url: str,
        isbn: str,
        api_key: str,
        content_type: str
    ) -> List[Release]:
        """Search by ISBN using the API."""
        try:
            # Anna's Archive ISBN search API
            url = f"{base_url}/dyn/api/search.json"
            params = {
                "q": f"isbn:{isbn}",
                "key": api_key,
                "limit": 10,
            }

            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            return self._parse_search_results(data, content_type)

        except requests.HTTPError as e:
            if e.response.status_code == 403:
                logger.error("Anna's Archive API returned 403 - check your API key or base URL")
            else:
                logger.error(f"Anna's Archive API HTTP error: {e}")
            return []
        except Exception as e:
            logger.error(f"Anna's Archive ISBN search failed: {e}")
            return []

    def _search_by_text(
        self,
        base_url: str,
        query: str,
        api_key: str,
        content_type: str,
        expand: bool
    ) -> List[Release]:
        """Search by text query using the API."""
        try:
            url = f"{base_url}/dyn/api/search.json"
            params = {
                "q": query,
                "key": api_key,
                "limit": 20 if expand else 10,
            }

            # Add content type filter
            if content_type == "audiobook":
                params["content"] = "book_unknown"  # AA uses different classification

            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()

            data = response.json()
            return self._parse_search_results(data, content_type)

        except requests.HTTPError as e:
            if e.response.status_code == 403:
                logger.error("Anna's Archive API returned 403 - check your API key or base URL")
            else:
                logger.error(f"Anna's Archive API HTTP error: {e}")
            return []
        except Exception as e:
            logger.error(f"Anna's Archive text search failed: {e}")
            return []

    def _parse_search_results(
        self,
        data: dict,
        content_type: str
    ) -> List[Release]:
        """Parse search results from API response."""
        releases = []

        results = data.get("results", [])
        for item in results:
            try:
                md5 = item.get("md5")
                if not md5:
                    continue

                title = item.get("title", "Unknown")
                authors = item.get("authors", [])
                if authors:
                    title = f"{title} - {', '.join(authors[:2])}"

                file_format = item.get("extension", "").upper()
                language = item.get("language", "")
                size_bytes = item.get("filesize", 0)
                size = self._format_size(size_bytes) if size_bytes else None

                # Build fast download URL using API key
                api_key = _get_api_key()
                base_url = _get_base_url()
                download_url = f"{base_url}/dyn/api/fast_download.json?md5={md5}&key={api_key}"

                # Info URL to book page
                info_url = f"{base_url}/md5/{md5}"

                release = Release(
                    source="annasarchive",
                    source_id=md5,
                    title=title,
                    format=file_format,
                    language=language,
                    size=size,
                    size_bytes=size_bytes,
                    download_url=download_url,
                    info_url=info_url,
                    protocol=ReleaseProtocol.HTTP,
                    indexer="Anna's Archive",
                    content_type=content_type,
                    extra={
                        "md5": md5,
                        "publisher": item.get("publisher"),
                        "year": item.get("year"),
                    }
                )

                releases.append(release)

            except Exception as e:
                logger.debug(f"Failed to parse Anna's Archive result: {e}")
                continue

        logger.info(f"Anna's Archive returned {len(releases)} releases")
        return releases

    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / (1024 ** 2):.1f} MB"
        else:
            return f"{size_bytes / (1024 ** 3):.2f} GB"

    def get_column_config(self) -> ReleaseColumnConfig:
        """Get column configuration for UI."""
        return ReleaseColumnConfig(
            columns=[
                ColumnSchema(
                    key="language",
                    label="Language",
                    render_type=ColumnRenderType.BADGE,
                    align=ColumnAlign.CENTER,
                    width="60px",
                    color_hint=ColumnColorHint(type="map", value="language"),
                    uppercase=True,
                ),
                ColumnSchema(
                    key="format",
                    label="Format",
                    render_type=ColumnRenderType.BADGE,
                    align=ColumnAlign.CENTER,
                    width="80px",
                    color_hint=ColumnColorHint(type="map", value="format"),
                    uppercase=True,
                ),
                ColumnSchema(
                    key="size",
                    label="Size",
                    render_type=ColumnRenderType.SIZE,
                    align=ColumnAlign.CENTER,
                    width="80px",
                ),
            ],
            grid_template="minmax(0,2fr) 60px 80px 80px",
            cache_ttl_seconds=3600,  # Cache for 1 hour (API results are stable)
            supported_filters=["format", "language"],
        )


@register_handler("annasarchive")
class AnnasArchiveHandler(DownloadHandler):
    """Download handler for Anna's Archive."""

    def __init__(self):
        """Initialize handler."""
        self.session = requests.Session()

    def download(
        self,
        task: DownloadTask,
        cancel_flag: Event,
        progress_callback: Callable[[float], None],
        status_callback: Callable[[str, Optional[str]], None]
    ) -> Optional[str]:
        """Download file from Anna's Archive."""
        release = task.release
        if not release or not release.download_url:
            logger.error("No download URL for Anna's Archive release")
            return None

        try:
            status_callback("downloading", "Downloading from Anna's Archive")

            # The download_url is already the fast API endpoint
            # First call returns JSON with actual download URL
            response = self.session.get(release.download_url, timeout=30)
            response.raise_for_status()

            result = response.json()

            # Extract actual download link from API response
            actual_url = result.get("download_url") or result.get("url")
            if not actual_url:
                logger.error(f"No download URL in API response: {result}")
                return None

            # Download the file
            from shelfmark.config.env import TMP_DIR
            output_path = Path(TMP_DIR) / f"{release.source_id}.{release.format.lower()}"

            with self.session.get(actual_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))

                downloaded = 0
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if cancel_flag.is_set():
                            logger.info("Download cancelled")
                            return None

                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_size:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)

            logger.info(f"Downloaded {output_path} ({downloaded} bytes)")
            return str(output_path)

        except requests.HTTPError as e:
            if e.response.status_code == 403:
                status_callback("failed", "403 Forbidden - Check API key or mirror URL")
            else:
                status_callback("failed", f"HTTP {e.response.status_code}")
            logger.error(f"Anna's Archive download failed: {e}")
            return None
        except Exception as e:
            status_callback("failed", str(e))
            logger.error(f"Anna's Archive download error: {e}")
            return None

    def cancel(self, task_id: str) -> bool:
        """Cancel download (handled by cancel_flag in download method)."""
        return True
