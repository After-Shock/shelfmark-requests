"""Discord webhook notifications for book request events.

Fires rich embeds to a Discord channel on:
- New book request (admin notification)
- Book fulfilled / available (fulfilled notification)
"""

import json
import urllib.error
import urllib.request
from typing import Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_DISCORD_COLOR_NEW_REQUEST = 0x5865F2   # Discord blurple
_DISCORD_COLOR_AVAILABLE   = 0x57F287   # Discord green

_VALID_WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)


def _is_enabled() -> bool:
    try:
        import shelfmark.core.config as core_config
        return bool(core_config.config.get("DISCORD_WEBHOOK_ENABLED", False))
    except Exception:
        return False


def _get_webhook_url() -> Optional[str]:
    try:
        import shelfmark.core.config as core_config
        url = (core_config.config.get("DISCORD_WEBHOOK_URL", "") or "").strip()
        if url and any(url.startswith(p) for p in _VALID_WEBHOOK_PREFIXES):
            return url
        if url:
            logger.warning("DISCORD_WEBHOOK_URL looks invalid, skipping")
        return None
    except Exception:
        return None


def _get_notify_new_request() -> bool:
    try:
        import shelfmark.core.config as core_config
        return bool(core_config.config.get("DISCORD_NOTIFY_NEW_REQUEST", True))
    except Exception:
        return True


def _get_notify_book_available() -> bool:
    try:
        import shelfmark.core.config as core_config
        return bool(core_config.config.get("DISCORD_NOTIFY_BOOK_AVAILABLE", True))
    except Exception:
        return True


def build_new_request_embed(
    title: str,
    author: Optional[str],
    requester: Optional[str],
    content_type: str = "ebook",
    cover_url: Optional[str] = None,
) -> dict:
    """Build a Discord embed dict for a new book request."""
    fields = [{"name": "Title", "value": title, "inline": True}]
    if author:
        fields.append({"name": "Author", "value": author, "inline": True})
    fields.append({"name": "Type", "value": content_type, "inline": True})
    if requester:
        fields.append({"name": "Requested by", "value": requester, "inline": True})

    embed: dict = {
        "title": "🔖 New Book Request",
        "color": _DISCORD_COLOR_NEW_REQUEST,
        "fields": fields,
    }
    if cover_url and (cover_url.startswith("http://") or cover_url.startswith("https://")):
        embed["thumbnail"] = {"url": cover_url}
    return embed


def build_book_available_embed(
    title: str,
    author: Optional[str],
    requester: Optional[str],
    cover_url: Optional[str] = None,
) -> dict:
    """Build a Discord embed dict for a book now available."""
    fields = [{"name": "Title", "value": title, "inline": True}]
    if author:
        fields.append({"name": "Author", "value": author, "inline": True})
    if requester:
        fields.append({"name": "Requested by", "value": requester, "inline": True})

    embed: dict = {
        "title": "📗 Book Now Available",
        "color": _DISCORD_COLOR_AVAILABLE,
        "fields": fields,
    }
    if cover_url and (cover_url.startswith("http://") or cover_url.startswith("https://")):
        embed["thumbnail"] = {"url": cover_url}
    return embed


def _post_embed(webhook_url: str, embed: dict) -> bool:
    """POST a single embed to a Discord webhook URL. Returns True on success."""
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        logger.warning(f"Discord webhook HTTP error {e.code}: {e.read()[:200]}")
        return False
    except Exception as e:
        logger.warning(f"Discord webhook failed: {e}")
        return False


def send_discord_new_request(
    title: str,
    author: Optional[str] = None,
    requester: Optional[str] = None,
    content_type: str = "ebook",
    cover_url: Optional[str] = None,
) -> bool:
    """Send a Discord embed when a new book request is created. Best-effort; never raises."""
    try:
        if not _is_enabled():
            return False
        if not _get_notify_new_request():
            return False
        webhook_url = _get_webhook_url()
        if not webhook_url:
            return False
        embed = build_new_request_embed(
            title=title, author=author, requester=requester,
            content_type=content_type, cover_url=cover_url,
        )
        result = _post_embed(webhook_url, embed)
        if result:
            logger.info(f"Discord new-request notification sent for: {title!r}")
        return result
    except Exception as e:
        logger.warning(f"Discord send_discord_new_request failed: {e}")
        return False


def send_discord_book_available(
    title: str,
    author: Optional[str] = None,
    requester: Optional[str] = None,
    cover_url: Optional[str] = None,
) -> bool:
    """Send a Discord embed when a requested book is fulfilled. Best-effort; never raises."""
    try:
        if not _is_enabled():
            return False
        if not _get_notify_book_available():
            return False
        webhook_url = _get_webhook_url()
        if not webhook_url:
            return False
        embed = build_book_available_embed(
            title=title, author=author, requester=requester, cover_url=cover_url,
        )
        result = _post_embed(webhook_url, embed)
        if result:
            logger.info(f"Discord book-available notification sent for: {title!r}")
        return result
    except Exception as e:
        logger.warning(f"Discord send_discord_book_available failed: {e}")
        return False


def test_discord_connection(current_values: dict) -> dict:
    """Test Discord webhook using current form values. Used as a settings ActionButton callback."""
    webhook_url = (current_values.get("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        return {"success": False, "message": "Webhook URL is required"}
    if not any(webhook_url.startswith(p) for p in _VALID_WEBHOOK_PREFIXES):
        return {"success": False, "message": "URL must start with https://discord.com/api/webhooks/"}

    embed = {
        "title": "🔖 Shelfmark Test",
        "description": "Discord webhook is configured correctly.",
        "color": _DISCORD_COLOR_NEW_REQUEST,
    }
    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as req_obj:
            req_obj.read()
        return {"success": True, "message": "Test notification sent to Discord"}
    except Exception as e:
        return {"success": False, "message": f"Discord test failed: {e}"}
