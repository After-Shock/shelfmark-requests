"""SQLite request database for book/audiobook request workflow."""

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_VALID_STATUSES = ("pending", "approved", "denied", "downloading", "fulfilled", "failed")
_VALID_CONTENT_TYPES = ("ebook", "audiobook")

_CREATE_REQUESTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','denied','downloading','fulfilled','failed')),
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
        """Create requests table if it doesn't exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_CREATE_REQUESTS_TABLE_SQL)
                conn.commit()
            finally:
                conn.close()
        logger.info("Request database initialized")

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
                cursor = conn.execute(
                    """INSERT INTO requests
                       (user_id, title, content_type, author, year, cover_url, description,
                        isbn_10, isbn_13, provider, provider_id, series_name, series_position)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, title, content_type, author, year, cover_url, description,
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
    ) -> List[Dict[str, Any]]:
        """List requests with optional filters. Returns list of request dicts."""
        conn = self._connect()
        try:
            conditions = []
            params: list = []
            if user_id is not None:
                conditions.append("r.user_id = ?")
                params.append(user_id)
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
