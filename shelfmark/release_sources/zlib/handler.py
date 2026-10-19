"""Z-Library download handler - fetches a file via the EAPI download link."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shelfmark.config.env import TMP_DIR
from shelfmark.core.config import config
from shelfmark.core.logger import setup_logger
from shelfmark.core.models import build_filename
from shelfmark.release_sources import DownloadHandler, register_handler
from shelfmark.release_sources.zlib import client

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from shelfmark.core.models import DownloadTask

logger = setup_logger(__name__)

_MIN_VALID_FILE_SIZE = 10 * 1024  # smaller is an error page, not a book


@register_handler("zlib")
class ZlibHandler(DownloadHandler):
    """Download handler for Z-Library releases (source_id ``zlib:<id>:<hash>``)."""

    def download(
        self,
        task: DownloadTask,
        cancel_flag: Event,
        progress_callback: Callable[[float], None],
        status_callback: Callable[[str, str | None], None],
    ) -> str | None:
        try:
            _, book_id, book_hash = task.task_id.split(":", 2)
            if config.get("FILE_ORGANIZATION", "rename") == "none":
                book_name = f"zlib-{book_id}.{task.format or 'bin'}"
            else:
                book_name = build_filename(task.title, task.author, task.year, task.format)
            book_path = TMP_DIR / book_name

            status_callback("resolving", "Getting Z-Library download link")
            link = client.download_link(book_id, book_hash)
            status_callback("downloading", "Downloading from Z-Library")
            if not client.download(link, book_path, progress_callback, cancel_flag.is_set):
                book_path.unlink(missing_ok=True)
                status_callback("cancelled", "Cancelled")
                return None
            if book_path.stat().st_size < _MIN_VALID_FILE_SIZE:
                book_path.unlink(missing_ok=True)
                status_callback("error", "Z-Library returned an invalid file")
                return None
            return str(book_path)
        except client.ZlibError as e:
            status_callback("error", str(e))
            return None
        except Exception as e:
            logger.exception("Error downloading from Z-Library")
            status_callback("error", str(e))
            return None

    def cancel(self, task_id: str) -> bool:
        """Cancellation is handled by the orchestrator via the cancel_flag."""
        return False
