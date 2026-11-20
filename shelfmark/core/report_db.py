"""Storage for media issue reports and delivery records (lives in users.db via RequestDB)."""

from typing import Any, Optional

from shelfmark.core.audiobookshelf import _normalize

OPEN_STATUSES = ("open", "fixing", "awaiting_approval", "needs_action")
_OPEN_SQL = ",".join(f"'{s}'" for s in OPEN_STATUSES)

_REPORT_FIELDS = (
    "item_key", "library", "library_item_id", "content_type", "title", "author",
    "provider", "provider_id", "request_id", "problem_type", "note",
)
_UPDATABLE = _REPORT_FIELDS + (
    "status", "auto_attempted", "task_id", "undo_json", "resolution_note",
)
_DELIVERY_FIELDS = (
    "request_id", "report_id", "source", "release_id", "release_title", "format",
    "final_path", "library", "library_item_id", "item_key",
)


class ReportLimitReached(Exception):
    """The user has no weekly reports left and the report would be a new one."""


def item_key(library: str, content_type: str, title: str, author: str) -> str:
    return "|".join((library, content_type, _normalize(title or ""), _normalize(author or "")))


def _row(conn, report_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM media_reports WHERE id = ?", (report_id,)).fetchone()
    return dict(row) if row else None


def create_or_join_report(
    request_db, *, user_id: int, fields: dict, quota_limit: Optional[int], quota_since: Optional[str]
) -> tuple[dict[str, Any], bool]:
    values = {k: fields.get(k) for k in _REPORT_FIELDS}
    with request_db._lock:
        conn = request_db._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT id FROM media_reports WHERE item_key = ? AND status IN ({_OPEN_SQL})",
                (values["item_key"],),
            ).fetchone()
            if existing:
                conn.execute(
                    "INSERT OR IGNORE INTO media_report_users (report_id, user_id) VALUES (?, ?)",
                    (existing["id"], user_id),
                )
                result, joined = _row(conn, existing["id"]), True
            else:
                if quota_limit is not None:
                    used = conn.execute(
                        "SELECT COUNT(*) FROM report_quota_usage WHERE user_id = ? AND created_at >= ?",
                        (user_id, quota_since or ""),
                    ).fetchone()[0]
                    if used >= quota_limit:
                        raise ReportLimitReached(
                            f"You've used all {quota_limit} of your reports this week"
                        )
                cur = conn.execute(
                    f"INSERT INTO media_reports ({','.join(_REPORT_FIELDS)}, status, created_by) "
                    f"VALUES ({','.join('?' * len(_REPORT_FIELDS))}, 'open', ?)",
                    (*values.values(), user_id),
                )
                conn.execute(
                    "INSERT INTO media_report_users (report_id, user_id) VALUES (?, ?)",
                    (cur.lastrowid, user_id),
                )
                conn.execute(
                    "INSERT INTO report_quota_usage (report_id, user_id) VALUES (?, ?)",
                    (cur.lastrowid, user_id),
                )
                result, joined = _row(conn, cur.lastrowid), False
            conn.commit()
            return result, joined
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_report(request_db, report_id: int) -> Optional[dict[str, Any]]:
    conn = request_db._connect()
    try:
        return _row(conn, report_id)
    finally:
        conn.close()


def update_report(request_db, report_id: int, **fields: Any) -> dict[str, Any]:
    bad = set(fields) - set(_UPDATABLE)
    if bad:
        raise ValueError(f"Cannot update report fields: {sorted(bad)}")
    with request_db._lock:
        conn = request_db._connect()
        try:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(
                f"UPDATE media_reports SET {sets + ', ' if sets else ''}updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (*fields.values(), report_id),
            )
            conn.commit()
            result = _row(conn, report_id)
        finally:
            conn.close()
    if result is None:
        raise KeyError(report_id)
    return result


def claim_report(request_db, report_id: int, allowed: tuple, new_status: str) -> Optional[dict[str, Any]]:
    """Atomically move a report to new_status if it is in an allowed status; None if not."""
    with request_db._lock:
        conn = request_db._connect()
        try:
            cur = conn.execute(
                f"UPDATE media_reports SET status = ?, resolution_note = NULL, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
                (new_status, report_id, *allowed),
            )
            conn.commit()
            return _row(conn, report_id) if cur.rowcount else None
        finally:
            conn.close()


def count_reports(request_db, statuses: list[str]) -> int:
    conn = request_db._connect()
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM media_reports WHERE status IN ({','.join('?' * len(statuses))})", statuses
        ).fetchone()[0]
    finally:
        conn.close()


def joined_counts(request_db) -> dict[int, int]:
    """report_id -> number of users who joined besides the creator."""
    conn = request_db._connect()
    try:
        return {r[0]: r[1] - 1 for r in conn.execute(
            "SELECT report_id, COUNT(*) FROM media_report_users GROUP BY report_id")}
    finally:
        conn.close()


def list_reports(
    request_db, *, user_id: Optional[int] = None, statuses: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    where, params = [], []
    if user_id is not None:
        where.append(
            "(created_by = ? OR id IN (SELECT report_id FROM media_report_users WHERE user_id = ?))"
        )
        params += [user_id, user_id]
    if statuses:
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        params += statuses
    conn = request_db._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM media_reports"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_report_usage(request_db, user_id: int, since: str) -> int:
    conn = request_db._connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM report_quota_usage WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        ).fetchone()[0]
    finally:
        conn.close()


def had_auto_attempt(request_db, item_key: str, problem_type: str) -> bool:
    conn = request_db._connect()
    try:
        return conn.execute(
            "SELECT 1 FROM media_reports WHERE item_key = ? AND problem_type = ? "
            "AND auto_attempted = 1 LIMIT 1",
            (item_key, problem_type),
        ).fetchone() is not None
    finally:
        conn.close()


def record_delivery(request_db, **fields: Any) -> None:
    bad = set(fields) - set(_DELIVERY_FIELDS)
    if bad:
        raise ValueError(f"Unknown delivery fields: {sorted(bad)}")
    with request_db._lock:
        conn = request_db._connect()
        try:
            conn.execute(
                f"INSERT INTO request_deliveries ({','.join(fields)}) "
                f"VALUES ({','.join('?' * len(fields))})",
                tuple(fields.values()),
            )
            conn.commit()
        finally:
            conn.close()


def deliveries_for_key(request_db, item_key: str) -> list[dict[str, Any]]:
    conn = request_db._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM request_deliveries WHERE item_key = ? ORDER BY delivered_at DESC, id DESC",
            (item_key,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def deliveries_for_request(request_db, request_id: Optional[int]) -> list[dict[str, Any]]:
    if request_id is None:
        return []
    conn = request_db._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM request_deliveries WHERE request_id = ? ORDER BY delivered_at DESC, id DESC",
            (request_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
