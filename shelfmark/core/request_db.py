"""SQLite request database for book/audiobook request workflow."""

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)


def _sanitize_url(url: Optional[str]) -> Optional[str]:
    """Return url only if it uses http:// or https://, else None."""
    if url and (url.startswith("http://") or url.startswith("https://")):
        return url
    return None


_VALID_STATUSES = ("pending", "approved", "denied", "downloading", "fulfilled", "failed", "cancelled")
_VALID_CONTENT_TYPES = ("ebook", "audiobook")

_CREATE_REQUESTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','denied','downloading','fulfilled','failed','cancelled')),
    content_type    TEXT NOT NULL DEFAULT 'ebook' CHECK(content_type IN ('ebook','audiobook')),
    title           TEXT NOT NULL,
    author          TEXT,
    year            TEXT,
    cover_url       TEXT,
    description     TEXT,
    isbn_10         TEXT,
    isbn_13         TEXT,
    provider        TEXT,
    provider_id     TEXT,
    series_name     TEXT,
    series_position REAL,
    admin_note      TEXT,
    approved_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    download_task_id TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class RequestDB:
    """Thread-safe SQLite request database (shares users.db)."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """Create requests table if it doesn't exist, then run migrations."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_CREATE_REQUESTS_TABLE_SQL)
                self._run_migrations(conn)
                conn.commit()
            finally:
                conn.close()
        logger.info("Request database initialized")

    def _run_migrations(self, conn: sqlite3.Connection) -> None:
        """Run numbered schema migrations."""
        # Ensure schema_version table exists
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        current_version = row["version"] if row else 0
        if not row:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")

        if current_version < 1:
            # Migration 1: add hidden_from_admin column
            cursor = conn.execute("PRAGMA table_info(requests)")
            columns = [r[1] for r in cursor.fetchall()]
            if "hidden_from_admin" not in columns:
                logger.info("Migration 1: Adding hidden_from_admin column")
                conn.execute(
                    "ALTER TABLE requests ADD COLUMN hidden_from_admin INTEGER DEFAULT 0"
                )
            conn.execute("UPDATE schema_version SET version = 1")

        if current_version < 2:
            # Migration 2: add 'cancelled' to CHECK constraint
            # SQLite can't ALTER CHECK constraints, so recreate the table
            table_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='requests'"
            ).fetchone()
            if table_sql and "'cancelled'" not in table_sql["sql"]:
                logger.info("Migration 2: Adding 'cancelled' to status CHECK constraint")
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS requests_new (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        status          TEXT NOT NULL DEFAULT 'pending'
                                        CHECK(status IN ('pending','approved','denied','downloading','fulfilled','failed','cancelled')),
                        content_type    TEXT NOT NULL DEFAULT 'ebook' CHECK(content_type IN ('ebook','audiobook')),
                        title           TEXT NOT NULL,
                        author          TEXT,
                        year            TEXT,
                        cover_url       TEXT,
                        description     TEXT,
                        isbn_10         TEXT,
                        isbn_13         TEXT,
                        provider        TEXT,
                        provider_id     TEXT,
                        series_name     TEXT,
                        series_position REAL,
                        admin_note      TEXT,
                        approved_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        download_task_id TEXT,
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        hidden_from_admin INTEGER DEFAULT 0
                    );
                    INSERT INTO requests_new SELECT
                        id, user_id, status, content_type, title, author, year,
                        cover_url, description, isbn_10, isbn_13, provider, provider_id,
                        series_name, series_position, admin_note, approved_by,
                        download_task_id, created_at, updated_at, hidden_from_admin
                    FROM requests;
                    DROP TABLE requests;
                    ALTER TABLE requests_new RENAME TO requests;
                """)
            conn.execute("UPDATE schema_version SET version = 2")

    def create_request(
        self,
        user_id: int,
        title: str,
        content_type: str = "ebook",
        author: Optional[str] = None,
        year: Optional[str] = None,
        cover_url: Optional[str] = None,
        description: Optional[str] = None,
        isbn_10: Optional[str] = None,
        isbn_13: Optional[str] = None,
        provider: Optional[str] = None,
        provider_id: Optional[str] = None,
        series_name: Optional[str] = None,
        series_position: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a new request. Returns the created request dict."""
        if content_type not in _VALID_CONTENT_TYPES:
            raise ValueError(f"Invalid content_type: {content_type}")
        with self._lock:
            conn = self._connect()
            try:
                safe_cover_url = _sanitize_url(cover_url)
                cursor = conn.execute(
                    """INSERT INTO requests
                       (user_id, title, content_type, author, year, cover_url, description,
                        isbn_10, isbn_13, provider, provider_id, series_name, series_position)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, title, content_type, author, year, safe_cover_url, description,
                     isbn_10, isbn_13, provider, provider_id, series_name, series_position),
                )
                conn.commit()
                request_id = cursor.lastrowid
                return self._get_request(conn, request_id)
            finally:
                conn.close()

    def get_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        """Get a single request by ID with requester info."""
        conn = self._connect()
        try:
            return self._get_request(conn, request_id)
        finally:
            conn.close()

    def _get_request(self, conn: sqlite3.Connection, request_id: int) -> Optional[Dict[str, Any]]:
        row = conn.execute(
            """SELECT r.*, u.username AS requester_username, u.display_name AS requester_display_name
               FROM requests r
               JOIN users u ON r.user_id = u.id
               WHERE r.id = ?""",
            (request_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_requests(
        self,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        include_hidden_from_admin: bool = False,
    ) -> List[Dict[str, Any]]:
        """List requests with optional filters. Returns list of request dicts.

        Args:
            user_id: Filter by specific user (None = all users for admin view)
            status: Filter by status
            limit: Max results
            offset: Result offset
            include_hidden_from_admin: If False and user_id is None (admin view),
                                      exclude requests hidden from admin
        """
        conn = self._connect()
        try:
            conditions = []
            params: list = []
            if user_id is not None:
                conditions.append("r.user_id = ?")
                params.append(user_id)
            else:
                # Admin view - exclude hidden requests unless explicitly requested
                if not include_hidden_from_admin:
                    conditions.append("(r.hidden_from_admin = 0 OR r.hidden_from_admin IS NULL)")
            if status is not None:
                conditions.append("r.status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.extend([limit, offset])
            rows = conn.execute(
                f"""SELECT r.*, u.username AS requester_username, u.display_name AS requester_display_name
                    FROM requests r
                    JOIN users u ON r.user_id = u.id
                    {where}
                    ORDER BY r.created_at DESC
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def count_requests(
        self,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> int:
        """Count requests with optional filters."""
        conn = self._connect()
        try:
            conditions = []
            params: list = []
            if user_id is not None:
                conditions.append("user_id = ?")
                params.append(user_id)
            if status is not None:
                conditions.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM requests {where}", params
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def get_request_counts(self, user_id: Optional[int] = None) -> Dict[str, int]:
        """Get counts per status. Admins see all (user_id=None), users see own."""
        conn = self._connect()
        try:
            if user_id is not None:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM requests WHERE user_id = ? GROUP BY status",
                    (user_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM requests GROUP BY status"
                ).fetchall()
            counts: Dict[str, int] = {s: 0 for s in _VALID_STATUSES}
            total = 0
            for r in rows:
                counts[r["status"]] = r["cnt"]
                total += r["cnt"]
            counts["total"] = total
            return counts
        finally:
            conn.close()

    def get_unviewed_count(self, user_id: int) -> int:
        """Get count of requests with status updates since user last viewed."""
        conn = self._connect()
        try:
            # Get user's last viewed timestamp from users table
            user_row = conn.execute(
                "SELECT requests_last_viewed_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

            if not user_row or not user_row["requests_last_viewed_at"]:
                # User has never viewed requests, count all their requests
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM requests WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                return row["cnt"] if row else 0

            # Count requests updated after last viewed time
            row = conn.execute(
                """SELECT COUNT(*) AS cnt FROM requests
                   WHERE user_id = ? AND updated_at > ?""",
                (user_id, user_row["requests_last_viewed_at"]),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    def update_request_status(
        self,
        request_id: int,
        status: str,
        admin_note: Optional[str] = None,
        approved_by: Optional[int] = None,
        download_task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update request status and optional fields. Returns updated request or None."""
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        with self._lock:
            conn = self._connect()
            try:
                sets = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
                params: list = [status]
                if admin_note is not None:
                    sets.append("admin_note = ?")
                    params.append(admin_note)
                if approved_by is not None:
                    sets.append("approved_by = ?")
                    params.append(approved_by)
                if download_task_id is not None:
                    sets.append("download_task_id = ?")
                    params.append(download_task_id)
                params.append(request_id)
                conn.execute(
                    f"UPDATE requests SET {', '.join(sets)} WHERE id = ?", params
                )
                conn.commit()
                return self._get_request(conn, request_id)
            finally:
                conn.close()

    def update_request_metadata(
        self,
        request_id: int,
        provider: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update request metadata (provider and provider_id). Returns updated request or None."""
        with self._lock:
            conn = self._connect()
            try:
                sets = ["updated_at = CURRENT_TIMESTAMP"]
                params: list = []
                if provider is not None:
                    sets.append("provider = ?")
                    params.append(provider)
                if provider_id is not None:
                    sets.append("provider_id = ?")
                    params.append(provider_id)
                params.append(request_id)
                conn.execute(
                    f"UPDATE requests SET {', '.join(sets)} WHERE id = ?", params
                )
                conn.commit()
                return self._get_request(conn, request_id)
            finally:
                conn.close()

    def delete_request(self, request_id: int) -> bool:
        """Delete a request. Returns True if a row was deleted."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def hide_request_from_admin(self, request_id: int) -> bool:
        """Hide a request from admin view. Returns True if updated."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "UPDATE requests SET hidden_from_admin = 1 WHERE id = ?",
                    (request_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def delete_requests_by_user(self, user_id: int) -> int:
        """Delete all requests for a given user. Returns number of deleted requests."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute("DELETE FROM requests WHERE user_id = ?", (user_id,))
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def get_requests_by_download_task(self, task_id: str) -> List[Dict[str, Any]]:
        """Get all requests linked to a download task ID."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT r.*, u.username AS requester_username, u.display_name AS requester_display_name
                   FROM requests r
                   JOIN users u ON r.user_id = u.id
                   WHERE r.download_task_id = ?""",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
