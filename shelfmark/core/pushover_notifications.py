"""Pushover push notifications for admin: fires when a new book request is submitted."""

import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


def _is_enabled() -> bool:
    try:
        import shelfmark.core.config as core_config
        return bool(core_config.config.get("PUSHOVER_ENABLED", False))
    except Exception:
        return False


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    try:
        import shelfmark.core.config as core_config
        user_key = core_config.config.get("PUSHOVER_USER_KEY", "") or None
        api_token = core_config.config.get("PUSHOVER_API_TOKEN", "") or None
        return user_key, api_token
    except Exception:
        return None, None


def send_new_request_pushover(
    title: str,
    author: Optional[str] = None,
    requester: Optional[str] = None,
    content_type: str = "ebook",
) -> bool:
    """Send a Pushover notification to the admin when a new request is created.

    Args:
        title: Book title.
        author: Book author (optional).
        requester: Username of the requesting user (optional).
        content_type: "ebook" or "audiobook".

    Returns:
        True if sent successfully, False otherwise. Never raises.
    """
    try:
        if not _is_enabled():
            return False

        user_key, api_token = _get_credentials()
        if not user_key or not api_token:
            logger.warning("Cannot send Pushover notification: user key or API token not configured")
            return False

        content_label = "Audiobook" if content_type == "audiobook" else "Ebook"
        lines = [f"{content_label}: {title}"]
        if author:
            lines.append(f"By {author}")
        if requester:
            lines.append(f"Requested by {requester}")
        message = "\n".join(lines)

        payload = urllib.parse.urlencode({
            "token": api_token,
            "user": user_key,
            "title": "New Request",
            "message": message,
            "priority": "0",
        }).encode()

        req = urllib.request.Request(
            _PUSHOVER_API_URL,
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

        logger.info(f"Pushover notification sent for new request: {title!r}")
        return True

    except Exception as e:
        logger.warning(f"Failed to send Pushover notification: {e}")
        return False


def test_pushover_connection(current_values: dict) -> dict:
    """Test Pushover connectivity using current form values (including unsaved changes).

    Used as a settings ActionButton callback.
    """
    user_key = (current_values.get("PUSHOVER_USER_KEY") or "").strip()
    api_token = (current_values.get("PUSHOVER_API_TOKEN") or "").strip()

    if not user_key or not api_token:
        return {"success": False, "message": "User Key and API Token are required"}

    try:
        payload = urllib.parse.urlencode({
            "token": api_token,
            "user": user_key,
            "title": "Shelfmark Test",
            "message": "Pushover is configured correctly.",
            "priority": "0",
        }).encode()

        req = urllib.request.Request(
            _PUSHOVER_API_URL,
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

        return {"success": True, "message": "Test notification sent"}

    except Exception as e:
        return {"success": False, "message": f"Pushover test failed: {e}"}
