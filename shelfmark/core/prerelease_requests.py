"""Helpers for promoting prerelease requests into the normal pending queue."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from shelfmark.core.logger import setup_logger
from shelfmark.core.request_notifications import send_request_notification

logger = setup_logger(__name__)

PRERELEASE_SCAN_INTERVAL_SECONDS = 60
RELEASE_NOTIFICATION_TZ = ZoneInfo("America/New_York")
RELEASE_NOTIFICATION_HOUR = 9


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


def _notify_group_activated(request_db: Any, user_db: Any, request_id: int) -> None:
    """Notify every active member after a prerelease group is activated."""
    for member in request_db.get_request_group(request_id, active_only=True):
        try:
            user = user_db.get_user(user_id=member["user_id"])
            email = (user or {}).get("email")
            if not email:
                continue
            send_request_notification(
                user_email=email,
                request_title=member.get("title", "Unknown"),
                new_status="activated",
            )
        except Exception as exc:
            logger.warning(
                "Prerelease activation notification failed for user %s: %s",
                member["user_id"],
                exc,
            )


def promote_due_prerelease_requests(
    request_db: Any,
    user_db: Any,
    *,
    on_request_update: Callable[[dict[str, Any]], None] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Promote due prerelease requests to pending and notify requesters."""
    current_time = now.astimezone(RELEASE_NOTIFICATION_TZ) if now else datetime.now(RELEASE_NOTIFICATION_TZ)
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
        release_ready_at = datetime.combine(
            release_date,
            dt_time(hour=RELEASE_NOTIFICATION_HOUR),
            tzinfo=RELEASE_NOTIFICATION_TZ,
        )
        if current_time < release_ready_at:
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
        _notify_group_activated(request_db, user_db, updated["id"])
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
        now_ts = time.time()
        sleep_for = delay - (now_ts % delay)
        time.sleep(max(1, sleep_for))
