"""Helpers for promoting prerelease requests into the normal pending queue."""

from __future__ import annotations

from datetime import date
import time
from typing import Any, Callable

from shelfmark.core.logger import setup_logger
from shelfmark.core.request_notifications import send_request_notification

logger = setup_logger(__name__)

PRERELEASE_SCAN_INTERVAL_SECONDS = 900


def _parse_release_date(raw_value: Any) -> date | None:
    if not isinstance(raw_value, str):
        return None
    value = raw_value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _notify_request_activated(user_db: Any, request_row: dict[str, Any]) -> None:
    user_id = request_row.get("user_id")
    if not user_id:
        return
    try:
        user = user_db.get_user(user_id=user_id)
    except Exception as exc:
        logger.warning("Failed to load user for prerelease request #%s: %s", request_row.get("id"), exc)
        return
    if not user or not user.get("email"):
        return
    send_request_notification(
        user_email=user["email"],
        request_title=request_row.get("title", "Unknown"),
        new_status="activated",
    )


def promote_due_prerelease_requests(
    request_db: Any,
    user_db: Any,
    *,
    on_request_update: Callable[[dict[str, Any]], None] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Promote due prerelease requests to pending and notify requesters."""
    current_date = today or date.today()
    promoted: list[dict[str, Any]] = []
    rows = request_db.list_requests(
        status="prerelease_requested",
        limit=1000,
        include_hidden_from_admin=True,
    )
    for row in rows:
        release_date = _parse_release_date(row.get("expected_release_date"))
        if release_date is None:
            logger.warning(
                "Skipping prerelease request #%s with invalid expected_release_date=%r",
                row.get("id"),
                row.get("expected_release_date"),
            )
            continue
        if release_date > current_date:
            continue

        request_db.update_request_metadata(
            row["id"],
            is_released=True,
            clear_expected_release_date=True,
        )
        updated = request_db.update_request_status(row["id"], "pending")
        if not updated:
            continue
        promoted.append(updated)
        logger.info(
            "Promoted prerelease request #%s to pending after release date %s",
            updated.get("id"),
            release_date.isoformat(),
        )
        if on_request_update is not None:
            on_request_update(updated)
        _notify_request_activated(user_db, updated)
    return promoted


def run_prerelease_request_loop(
    request_db: Any,
    user_db: Any,
    *,
    on_request_update: Callable[[dict[str, Any]], None] | None = None,
    interval_seconds: int = PRERELEASE_SCAN_INTERVAL_SECONDS,
) -> None:
    """Continuously promote due prerelease requests at a fixed interval."""
    delay = max(1, int(interval_seconds))
    while True:
        try:
            promote_due_prerelease_requests(
                request_db,
                user_db,
                on_request_update=on_request_update,
            )
        except Exception as exc:
            logger.warning("Prerelease promotion loop failed: %s", exc)
        time.sleep(delay)
