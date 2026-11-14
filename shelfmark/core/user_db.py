"""SQLite user database for multi-user support."""

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from shelfmark.core.auth_modes import AUTH_SOURCE_BUILTIN, AUTH_SOURCE_SET
from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    email         TEXT,
    display_name  TEXT,
    password_hash TEXT,
    oidc_subject  TEXT UNIQUE,
    auth_source   TEXT NOT NULL DEFAULT 'builtin',
    role          TEXT NOT NULL DEFAULT 'user',
    provisioned_services TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS download_requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status         TEXT NOT NULL DEFAULT 'pending',
    delivery_state TEXT NOT NULL DEFAULT 'none',
    source_hint    TEXT,
    content_type   TEXT NOT NULL,
    request_level  TEXT NOT NULL,
    policy_mode    TEXT NOT NULL,
    book_data      TEXT NOT NULL,
    release_data   TEXT,
    note           TEXT,
    admin_note     TEXT,
    reviewed_by    INTEGER REFERENCES users(id),
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at    TIMESTAMP,
    delivery_updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_download_requests_user_status_created_at
ON download_requests (user_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_download_requests_status_created_at
ON download_requests (status, created_at DESC);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    request_id INTEGER,
    source_id TEXT,
    origin TEXT NOT NULL,
    final_status TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    terminal_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_log_user_terminal
ON activity_log (user_id, terminal_at DESC);

CREATE INDEX IF NOT EXISTS idx_activity_log_lookup
ON activity_log (user_id, item_type, item_key, id DESC);

CREATE TABLE IF NOT EXISTS activity_dismissals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    activity_log_id INTEGER REFERENCES activity_log(id) ON DELETE SET NULL,
    dismissed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, item_type, item_key)
);

CREATE INDEX IF NOT EXISTS idx_activity_dismissals_user_dismissed_at
ON activity_dismissals (user_id, dismissed_at DESC);

CREATE TABLE IF NOT EXISTS invite_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_invite_codes_code
ON invite_codes (code);

CREATE TABLE IF NOT EXISTS password_reset_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code TEXT UNIQUE NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    used_at TIMESTAMP,
    expires_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_reset_codes_code
ON password_reset_codes (code);
"""


def get_users_db_path(config_dir: Optional[str] = None) -> str:
    """Return the configured users database path."""
    root = config_dir or os.environ.get("CONFIG_DIR", "/config")
    return os.path.join(root, "users.db")


def sync_builtin_admin_user(
    username: str,
    password_hash: str,
    db_path: Optional[str] = None,
) -> None:
    """Ensure a local admin user exists for configured builtin credentials."""
    normalized_username = (username or "").strip()
    normalized_hash = password_hash or ""
    if not normalized_username or not normalized_hash:
        return

    user_db = UserDB(db_path or get_users_db_path())
    user_db.initialize()

    existing = user_db.get_user(username=normalized_username)
    if existing:
        updates: dict[str, Any] = {}
        if existing.get("password_hash") != normalized_hash:
            updates["password_hash"] = normalized_hash
        if existing.get("role") != "admin":
            updates["role"] = "admin"
        if existing.get("auth_source") != AUTH_SOURCE_BUILTIN:
            updates["auth_source"] = AUTH_SOURCE_BUILTIN
        if updates:
            user_db.update_user(existing["id"], **updates)
            logger.info(f"Updated local admin user '{normalized_username}' from builtin settings")
        return

    user_db.create_user(
        username=normalized_username,
        password_hash=normalized_hash,
        auth_source=AUTH_SOURCE_BUILTIN,
        role="admin",
    )
    logger.info(f"Created local admin user '{normalized_username}' from builtin settings")


class UserDB:
    """Thread-safe SQLite user database."""

    _VALID_AUTH_SOURCES = set(AUTH_SOURCE_SET)

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_CREATE_TABLES_SQL)
                self._migrate_auth_source_column(conn)
                self._migrate_requests_last_viewed_column(conn)
                self._migrate_request_delivery_columns(conn)
                self._migrate_activity_tables(conn)
                self._migrate_invite_tables(conn)
                self._migrate_password_reset_tables(conn)
                self._migrate_provisioned_services_column(conn)
                conn.execute("""CREATE TABLE IF NOT EXISTS library_accounts (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    service TEXT NOT NULL, account_id TEXT NOT NULL, username TEXT NOT NULL,
                    PRIMARY KEY(user_id, service), UNIQUE(service, account_id))""")
                conn.execute("""CREATE TABLE IF NOT EXISTS retired_library_accounts (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    service TEXT NOT NULL, account_id TEXT NOT NULL, username TEXT NOT NULL,
                    PRIMARY KEY(user_id, service, account_id, username))""")
                conn.commit()
                # WAL mode must be changed outside an open transaction.
                conn.execute("PRAGMA journal_mode=WAL")
            finally:
                conn.close()

    def _migrate_auth_source_column(self, conn: sqlite3.Connection) -> None:
        """Ensure users.auth_source exists and backfill historical rows."""
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        column_names = {str(col["name"]) for col in columns}

        if "auth_source" not in column_names:
            conn.execute(
                "ALTER TABLE users ADD COLUMN auth_source TEXT NOT NULL DEFAULT 'builtin'"
            )

        # Backfill OIDC-origin users created before auth_source existed.
        conn.execute(
            "UPDATE users SET auth_source = 'oidc' WHERE oidc_subject IS NOT NULL"
        )
        # Defensive cleanup for any legacy null/blank values.
        conn.execute(
            "UPDATE users SET auth_source = 'builtin' WHERE auth_source IS NULL OR auth_source = ''"
        )

    def _migrate_provisioned_services_column(self, conn: sqlite3.Connection) -> None:
        """Ensure users.provisioned_services exists.

        Deliberately NOT backfilled. A NULL here means "Shelfmark never created
        external accounts for this user", which is the truth for every account
        that predates signup provisioning - and it is what stops us from
        overwriting an Audiobookshelf/Calibre-Web password we did not set.
        """
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        column_names = {str(col["name"]) for col in columns}
        if "provisioned_services" not in column_names:
            conn.execute("ALTER TABLE users ADD COLUMN provisioned_services TEXT")

    def _migrate_requests_last_viewed_column(self, conn: sqlite3.Connection) -> None:
        """Ensure legacy user databases support request-count tracking."""
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        column_names = {str(col["name"]) for col in columns}
        if "requests_last_viewed_at" not in column_names:
            conn.execute("ALTER TABLE users ADD COLUMN requests_last_viewed_at TIMESTAMP")

    def _migrate_request_delivery_columns(self, conn: sqlite3.Connection) -> None:
        """Ensure request delivery-state columns exist and backfill historical rows."""
        columns = conn.execute("PRAGMA table_info(download_requests)").fetchall()
        column_names = {str(col["name"]) for col in columns}

        if "delivery_state" not in column_names:
            conn.execute(
                "ALTER TABLE download_requests ADD COLUMN delivery_state TEXT NOT NULL DEFAULT 'none'"
            )
        if "delivery_updated_at" not in column_names:
            conn.execute("ALTER TABLE download_requests ADD COLUMN delivery_updated_at TIMESTAMP")
        if "last_failure_reason" not in column_names:
            conn.execute("ALTER TABLE download_requests ADD COLUMN last_failure_reason TEXT")

        conn.execute(
            """
            UPDATE download_requests
            SET delivery_state = 'unknown'
            WHERE status = 'fulfilled' AND (delivery_state IS NULL OR TRIM(delivery_state) = '' OR delivery_state = 'none')
            """
        )
        conn.execute(
            """
            UPDATE download_requests
            SET delivery_state = 'none'
            WHERE status != 'fulfilled' AND (delivery_state IS NULL OR TRIM(delivery_state) = '')
            """
        )
        conn.execute(
            """
            UPDATE download_requests
            SET delivery_updated_at = COALESCE(delivery_updated_at, reviewed_at, created_at)
            WHERE delivery_state != 'none' AND delivery_updated_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE download_requests
            SET delivery_state = 'complete'
            WHERE delivery_state = 'cleared'
            """
        )

    def _migrate_activity_tables(self, conn: sqlite3.Connection) -> None:
        """Ensure activity log and dismissal tables exist with current columns/indexes."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                request_id INTEGER,
                source_id TEXT,
                origin TEXT NOT NULL,
                final_status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                terminal_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_activity_log_user_terminal
            ON activity_log (user_id, terminal_at DESC);

            CREATE INDEX IF NOT EXISTS idx_activity_log_lookup
            ON activity_log (user_id, item_type, item_key, id DESC);

            CREATE TABLE IF NOT EXISTS activity_dismissals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                activity_log_id INTEGER REFERENCES activity_log(id) ON DELETE SET NULL,
                dismissed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, item_type, item_key)
            );

            CREATE INDEX IF NOT EXISTS idx_activity_dismissals_user_dismissed_at
            ON activity_dismissals (user_id, dismissed_at DESC);
            """
        )

        dismissal_columns = conn.execute("PRAGMA table_info(activity_dismissals)").fetchall()
        dismissal_column_names = {str(col["name"]) for col in dismissal_columns}
        if "activity_log_id" not in dismissal_column_names:
            conn.execute("ALTER TABLE activity_dismissals ADD COLUMN activity_log_id INTEGER")

    def _migrate_invite_tables(self, conn: sqlite3.Connection) -> None:
        """Ensure invite-code table exists."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS invite_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                used_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                used_at TIMESTAMP,
                expires_at TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_invite_codes_code
            ON invite_codes (code);
            """
        )

    def create_invite_code(
        self,
        code: str,
        created_by: Optional[int] = None,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a signup invite code."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """INSERT INTO invite_codes (code, created_by, expires_at)
                       VALUES (?, ?, ?)""",
                    (code, created_by, expires_at),
                )
                conn.commit()
                return self._get_invite_by_id(conn, int(cursor.lastrowid))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Invite code already exists: {e}")
            finally:
                conn.close()

    def list_invite_codes(self) -> List[Dict[str, Any]]:
        """List invite codes, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM invite_codes
                   ORDER BY used_at IS NOT NULL, created_at DESC, id DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_invite_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Get an invite code row by code."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM invite_codes WHERE code = ?", (code,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def consume_invite_code(self, code: str, used_by: int) -> bool:
        """Mark an unused, unexpired invite code as consumed."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """SELECT * FROM invite_codes
                       WHERE code = ?
                         AND used_at IS NULL
                         AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)""",
                    (code,),
                ).fetchone()
                if not row:
                    return False
                conn.execute(
                    """UPDATE invite_codes
                       SET used_by = ?, used_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (used_by, row["id"]),
                )
                conn.commit()
                return True
            finally:
                conn.close()

    def delete_invite_code(self, invite_id: int) -> None:
        """Delete an invite code."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM invite_codes WHERE id = ? AND used_at IS NULL", (invite_id,))
                conn.commit()
            finally:
                conn.close()

    def _get_invite_by_id(self, conn: sqlite3.Connection, invite_id: int) -> Dict[str, Any]:
        row = conn.execute("SELECT * FROM invite_codes WHERE id = ?", (invite_id,)).fetchone()
        if not row:
            raise ValueError(f"Invite {invite_id} not found")
        return dict(row)

    def _migrate_password_reset_tables(self, conn: sqlite3.Connection) -> None:
        """Ensure password-reset table exists."""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                code TEXT UNIQUE NOT NULL,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                used_at TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_password_reset_codes_code
            ON password_reset_codes (code);
            """
        )

    def create_password_reset_code(
        self,
        user_id: int,
        code: str,
        created_by: Optional[int],
        expires_at: str,
    ) -> Dict[str, Any]:
        """Create a one-time password reset code for a user."""
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """INSERT INTO password_reset_codes (user_id, code, created_by, expires_at)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, code, created_by, expires_at),
                )
                conn.commit()
                return self._get_password_reset_by_id(conn, int(cursor.lastrowid))
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Password reset code could not be created: {e}")
            finally:
                conn.close()

    def list_password_reset_codes(self) -> List[Dict[str, Any]]:
        """List password reset codes, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT prc.*, users.username
                   FROM password_reset_codes prc
                   JOIN users ON users.id = prc.user_id
                   WHERE prc.code NOT LIKE 'self:%'
                   ORDER BY prc.used_at IS NOT NULL, prc.created_at DESC, prc.id DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def consume_password_reset_code(self, username: Optional[str], code: str) -> Optional[Dict[str, Any]]:
        """Consume a valid reset code and return the target user.

        username=None matches on the code alone (emailed self-service links,
        whose codes are long random tokens).
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """SELECT prc.id AS reset_id, users.*
                       FROM password_reset_codes prc
                       JOIN users ON users.id = prc.user_id
                       WHERE prc.code = ?
                         AND (? IS NULL OR LOWER(users.username) = LOWER(?))
                         AND prc.used_at IS NULL
                         AND prc.expires_at > CURRENT_TIMESTAMP""",
                    (code, username, username),
                ).fetchone()
                if not row:
                    return None
                conn.execute(
                    "UPDATE password_reset_codes SET used_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["reset_id"],),
                )
                conn.commit()
                return self._get_user_by_id(conn, row["id"])
            finally:
                conn.close()

    def has_recent_password_reset(self, user_id: int, code_prefix: str, minutes: int) -> bool:
        """True if a reset code with this prefix was made for the user in the last N minutes."""
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT 1 FROM password_reset_codes
                   WHERE user_id = ? AND code LIKE ? || '%'
                     AND created_at > datetime('now', ?)""",
                (user_id, code_prefix, f"-{int(minutes)} minutes"),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def delete_password_reset_code(self, reset_id: int) -> None:
        """Delete an unused password reset code."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM password_reset_codes WHERE id = ? AND used_at IS NULL", (reset_id,))
                conn.commit()
            finally:
                conn.close()

    def _get_password_reset_by_id(self, conn: sqlite3.Connection, reset_id: int) -> Dict[str, Any]:
        row = conn.execute(
            """SELECT prc.*, users.username
               FROM password_reset_codes prc
               JOIN users ON users.id = prc.user_id
               WHERE prc.id = ?""",
            (reset_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Password reset {reset_id} not found")
        return dict(row)

    def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        display_name: Optional[str] = None,
        password_hash: Optional[str] = None,
        oidc_subject: Optional[str] = None,
        auth_source: str = "builtin",
        role: str = "user",
    ) -> Dict[str, Any]:
        """Create a new user. Raises ValueError if username or oidc_subject already exists."""
        if auth_source not in self._VALID_AUTH_SOURCES:
            raise ValueError(f"Invalid auth_source: {auth_source}")
        with self._lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    """INSERT INTO users (
                           username, email, display_name, password_hash, oidc_subject, auth_source, role
                       )
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        username,
                        email,
                        display_name,
                        password_hash,
                        oidc_subject,
                        auth_source,
                        role,
                    ),
                )
                conn.commit()
                user_id = cursor.lastrowid
                return self._get_user_by_id(conn, user_id)
            except sqlite3.IntegrityError as e:
                raise ValueError(f"User already exists: {e}")
            finally:
                conn.close()

    def get_user(
        self,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        oidc_subject: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a user by id, username, or oidc_subject. Returns None if not found."""
        conn = self._connect()
        try:
            if user_id is not None:
                return self._get_user_by_id(conn, user_id)
            elif username is not None:
                row = conn.execute(
                    "SELECT * FROM users WHERE username = ?", (username,)
                ).fetchone()
            elif oidc_subject is not None:
                row = conn.execute(
                    "SELECT * FROM users WHERE oidc_subject = ?", (oidc_subject,)
                ).fetchone()
            else:
                return None
            return self._get_user_by_id(conn, row["id"]) if row else None
        finally:
            conn.close()

    def _get_user_by_id(self, conn: sqlite3.Connection, user_id: int) -> Optional[Dict[str, Any]]:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["library_accounts"] = {r["service"]: dict(r) for r in conn.execute(
            "SELECT * FROM library_accounts WHERE user_id = ?", (user_id,))}
        user["retired_library_accounts"] = [dict(r) for r in conn.execute(
            "SELECT * FROM retired_library_accounts WHERE user_id = ?", (user_id,))]
        return user

    _ALLOWED_UPDATE_COLUMNS = {
        "email",
        "display_name",
        "password_hash",
        "oidc_subject",
        "auth_source",
        "role",
        "provisioned_services",
    }

    def update_user(self, user_id: int, **kwargs) -> None:
        """Update user fields. Raises ValueError if user not found or invalid column."""
        if not kwargs:
            return
        for k in kwargs:
            if k not in self._ALLOWED_UPDATE_COLUMNS:
                raise ValueError(f"Invalid column: {k}")
        if "auth_source" in kwargs and kwargs["auth_source"] not in self._VALID_AUTH_SOURCES:
            raise ValueError(f"Invalid auth_source: {kwargs['auth_source']}")
        with self._lock:
            conn = self._connect()
            try:
                # Verify user exists
                if not self._get_user_by_id(conn, user_id):
                    raise ValueError(f"User {user_id} not found")
                sets = ", ".join(f"{k} = ?" for k in kwargs)
                values = list(kwargs.values()) + [user_id]
                conn.execute(f"UPDATE users SET {sets} WHERE id = ?", values)
                conn.commit()
            finally:
                conn.close()

    def delete_user(self, user_id: int) -> None:
        """Delete a user and their settings."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE download_requests SET reviewed_by = NULL WHERE reviewed_by = ?", (user_id,))
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                conn.commit()
            finally:
                conn.close()

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
            return [self._get_user_by_id(conn, r["id"]) for r in rows]
        finally:
            conn.close()

    def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        """Get per-user settings. Returns empty dict if none set."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT settings_json FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row:
                return json.loads(row["settings_json"])
            return {}
        finally:
            conn.close()

    def update_requests_last_viewed(self, user_id: int) -> None:
        """Record that a user viewed their request updates."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE users SET requests_last_viewed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (user_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def set_user_settings(self, user_id: int, settings: Dict[str, Any]) -> None:
        """Merge settings into user's existing settings."""
        with self._lock:
            conn = self._connect()
            try:
                existing = {}
                row = conn.execute(
                    "SELECT settings_json FROM user_settings WHERE user_id = ?", (user_id,)
                ).fetchone()
                if row:
                    existing = json.loads(row["settings_json"])

                existing.update(settings)
                # Remove keys set to None (meaning "clear this override")
                existing = {k: v for k, v in existing.items() if v is not None}
                settings_json = json.dumps(existing)

                conn.execute(
                    """INSERT INTO user_settings (user_id, settings_json) VALUES (?, ?)
                       ON CONFLICT(user_id) DO UPDATE SET settings_json = ?""",
                    (user_id, settings_json, settings_json),
                )
                conn.commit()
            finally:
                conn.close()
