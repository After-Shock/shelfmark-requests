"""Weekly request limit: every new request a non-admin creates uses one slot.

The week runs Monday 00:00 to Monday 00:00 US Eastern. An admin reset starts a
user's count over from that moment. Usage lives in request_quota_usage (see
RequestDB), so a user deleting their own request does not hand the slot back;
only a denial refunds it.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from shelfmark.core.config import config

QUOTA_TIMEZONE = ZoneInfo("America/New_York")
DEFAULT_WEEKLY_LIMIT = 6
_SQLITE_FORMAT = "%Y-%m-%d %H:%M:%S"  # matches CURRENT_TIMESTAMP (UTC)


def week_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Return the current week's start and the next reset, both timezone-aware."""
    local = (now or datetime.now(timezone.utc)).astimezone(QUOTA_TIMEZONE)
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    # Build next Monday from the date, not start + 7 days, so DST changes keep midnight.
    next_monday = (start + timedelta(days=7)).date()
    resets = datetime(next_monday.year, next_monday.month, next_monday.day, tzinfo=QUOTA_TIMEZONE)
    return start, resets


def default_limit() -> int:
    try:
        return max(0, int(config.get("WEEKLY_REQUEST_LIMIT", DEFAULT_WEEKLY_LIMIT)))
    except (TypeError, ValueError):
        return DEFAULT_WEEKLY_LIMIT


def limit_for(user: dict[str, Any]) -> Optional[int]:
    """The user's weekly limit, or None when unlimited (admins)."""
    if user.get("role") == "admin":
        return None
    own = user.get("weekly_request_limit")
    return max(0, own) if isinstance(own, int) and not isinstance(own, bool) else default_limit()


def counting_since(user: dict[str, Any], now: Optional[datetime] = None) -> str:
    """UTC timestamp (SQLite format) from which this user's requests count."""
    start = week_bounds(now)[0].astimezone(timezone.utc).strftime(_SQLITE_FORMAT)
    reset_at = user.get("request_limit_reset_at")
    return max(start, reset_at) if isinstance(reset_at, str) and reset_at else start


def quota_for(request_db, user: dict[str, Any], now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Limit, used and remaining for this week, or None for unlimited users."""
    limit = limit_for(user)
    if limit is None:
        return None
    used = request_db.count_quota_usage(user["id"], counting_since(user, now))
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "is_default": not isinstance(user.get("weekly_request_limit"), int),
        "resets_at": week_bounds(now)[1].isoformat(),
    }
