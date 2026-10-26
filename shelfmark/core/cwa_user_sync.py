"""Helpers for provisioning and syncing Calibre-Web users into users.db."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping, Optional

from werkzeug.security import check_password_hash

from shelfmark.core.auth_modes import AUTH_SOURCE_CWA, normalize_auth_source
from shelfmark.core.config import config
from shelfmark.core.external_user_linking import upsert_external_user
from shelfmark.core.logger import setup_logger
from shelfmark.core.user_db import UserDB

_CWA_ALIAS_SUFFIX = "__cwa"

logger = setup_logger(__name__)

# Calibre-Web role bits: 1 admin, 2 download, 16 change password, 256 view books.
# 0 is no permissions at all - the user can log in but not read or download.
_CWA_ROLE_ADMIN = 1
# download + viewer (258). No "change password" (16): passwords are managed
# from the requests site, so they stay in sync across the library apps.
_CWA_ROLE_USER = 2 | 256

# Columns that should not be cloned from an existing user row when creating a
# new Calibre-Web account (identity/secret columns we set explicitly).
_TEMPLATE_SKIP_COLUMNS = {"id", "name", "email", "password", "kobo_token", "kindle_mail"}


def _get_cwa_db_path() -> Optional[str]:
    """Return the path to the mounted Calibre-Web app.db, if available."""
    from shelfmark.config.env import CWA_DB_PATH

    if CWA_DB_PATH and CWA_DB_PATH.exists() and CWA_DB_PATH.is_file():
        return str(CWA_DB_PATH)
    return None


def is_provisioning_enabled() -> bool:
    """Return True if CWA signup provisioning is enabled and app.db is mounted."""
    if not bool(config.get("CWA_USER_SYNC_ENABLED", False)):
        return False
    return _get_cwa_db_path() is not None


def _hash_cwa_password(password: str) -> str:
    """Hash a password in the pbkdf2 format Calibre-Web verifies.

    We pin the method/iterations instead of using the werkzeug default because
    Calibre-Web (CWA) must be able to verify it regardless of the werkzeug
    version either app ships with. pbkdf2:sha256:600000 is verifiable by both
    older and current werkzeug releases.
    """
    from werkzeug.security import generate_password_hash

    return generate_password_hash(password, method="pbkdf2:sha256:600000")


def _clone_template_row(row: sqlite3.Row, mapping: dict[str, Any]) -> tuple[list[str], list[Any]]:
    """Clone a template user row, overriding the columns in `mapping`."""
    columns = []
    values = []
    for key in row.keys():
        if key in _TEMPLATE_SKIP_COLUMNS:
            continue
        columns.append(key)
        values.append(mapping.get(key, row[key]))
    return columns, values


def provision_cwa_user(username: str, password: str, email: Optional[str] = None,
                       role: str = "user") -> dict[str, Any]:
    """Create a matching user account in the mounted Calibre-Web database.

    Uses the same app.db that powers the "sync users from Calibre-Web" feature
    (mounted at /auth/app.db or via CWA_DB_PATH).

    Returns a dict with keys:
          - status: 'created' | 'exists' | 'skipped' | 'error'
          - message: human-readable detail for logging/UI
    """
    if not bool(config.get("CWA_USER_SYNC_ENABLED", False)):
        return {"status": "skipped", "message": "Calibre-Web user sync is disabled"}

    db_path = _get_cwa_db_path()
    if not db_path:
        return {"status": "skipped", "message": "Calibre-Web database not mounted (/auth/app.db)"}

    normalized_email = _normalize_email(email)
    cwa_role = _CWA_ROLE_ADMIN if role == "admin" else _CWA_ROLE_USER
    password_hash = _hash_cwa_password(password)

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            existing = conn.execute(
                "SELECT name FROM user WHERE name = ?", (username,)
            ).fetchone()
            if existing:
                return {"status": "exists", "message": f"User '{username}' already exists in Calibre-Web"}

            # Prefer cloning column values (locale, sidebar settings, view
            # preferences, etc.) from an existing user so the new row matches
            # whatever schema/defaults this Calibre-Web version expects.
            template = conn.execute("SELECT * FROM user ORDER BY id LIMIT 1").fetchone()

            if template is not None:
                mapping: dict[str, Any] = {
                    "role": cwa_role,
                }
                if "email" in template.keys():
                    mapping["email"] = normalized_email
                if "kobo_only_shelves_sync" in template.keys():
                    mapping["kobo_only_shelves_sync"] = 0
                columns, values = _clone_template_row(template, mapping)
                columns.extend(["name", "email", "password"])
                values.extend([username, normalized_email, password_hash])
            else:
                # Fresh Calibre-Web database: fall back to a minimal insert.
                table_info = conn.execute("PRAGMA table_info(user)").fetchall()
                available = {info["name"] for info in table_info}
                columns = [c for c in ["name", "email", "password", "role", "locale", "default_language"] if c in available]
                values = [v for c, v in {
                    "name": username,
                    "email": normalized_email,
                    "password": password_hash,
                    "role": cwa_role,
                    "locale": "en",
                    "default_language": "en",
                }.items() if c in available]

            placeholders = ", ".join("?" for _ in columns)
            column_list = ", ".join(f'"{c}"' for c in columns)
            conn.execute(
                f"INSERT INTO user ({column_list}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.error("Calibre-Web user creation for '%s' failed: %s", username, e)
        return {"status": "error", "message": f"Could not write to Calibre-Web database: {e}"}

    logger.info("Created Calibre-Web account for user '%s'", username)
    return {"status": "created", "message": "Calibre-Web account created"}


def _normalize_email(value: Any) -> str | None:
    if value is None:
        return None
    email = str(value).strip()
    return email or None


def update_cwa_password(username: str, password: str) -> dict[str, Any]:
    """Update an existing Calibre-Web user's password, best-effort."""
    if not bool(config.get("CWA_USER_SYNC_ENABLED", False)):
        return {"status": "skipped", "message": "Calibre-Web user sync is disabled"}
    db_path = _get_cwa_db_path()
    if not db_path:
        return {"status": "skipped", "message": "Calibre-Web database not mounted (/auth/app.db)"}
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            # Same case-insensitive match as login/linking, but only when it is
            # unambiguous ("sarah" and "Sarah" can both exist in Calibre-Web).
            names = [r[0] for r in conn.execute(
                "SELECT name FROM user WHERE lower(name) = lower(?)", (username,)
            )]
            if username in names:
                names = [username]
            if len(names) != 1:
                return {"status": "skipped", "message": "No single matching Calibre-Web account"}
            conn.execute(
                "UPDATE user SET password = ? WHERE name = ?",
                (_hash_cwa_password(password), names[0]),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.error("Calibre-Web password update for '%s' failed: %s", username, e)
        return {"status": "error", "message": f"Could not update Calibre-Web password: {e}"}
    return {"status": "updated", "message": "Calibre-Web password updated"}


def upsert_cwa_user(
    user_db: UserDB,
    cwa_username: str,
    cwa_email: str | None,
    role: str,
    context: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Create/update a CWA-backed user with collision-safe matching."""
    normalized_email = _normalize_email(cwa_email)
    collision_strategy = "alias" if normalized_email else "takeover"
    user, action = upsert_external_user(
        user_db,
        auth_source="cwa",
        username=cwa_username,
        email=normalized_email,
        role=role,
        allow_email_link=True,
        collision_strategy=collision_strategy,
        alias_suffix=_CWA_ALIAS_SUFFIX,
        context=context,
    )
    if user is None:
        raise RuntimeError("Unexpected CWA user sync result: no user returned")
    return user, action


def sync_cwa_users_from_rows(
    user_db: UserDB,
    rows: Iterable[tuple[Any, Any, Any]],
) -> dict[str, int]:
    """Sync CWA users from raw `(name, role_flags, email)` rows."""
    created = 0
    updated = 0
    active_cwa_user_ids: set[int] = set()
    for username, role_flags, email in rows:
        normalized_username = str(username or "").strip()
        if not normalized_username:
            continue

        role = "admin" if (int(role_flags or 0) & 1) == 1 else "user"
        user, action = upsert_cwa_user(
            user_db,
            cwa_username=normalized_username,
            cwa_email=_normalize_email(email),
            role=role,
            context="cwa_manual_sync",
        )
        active_cwa_user_ids.add(int(user["id"]))
        if action == "created":
            created += 1
        else:
            updated += 1

    deleted = 0
    for existing_user in user_db.list_users():
        if normalize_auth_source(
            existing_user.get("auth_source"),
            existing_user.get("oidc_subject"),
        ) != AUTH_SOURCE_CWA:
            continue

        existing_id = int(existing_user.get("id") or 0)
        if existing_id in active_cwa_user_ids:
            continue

        user_db.delete_user(existing_id)
        deleted += 1

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "total": created + updated,
    }


def find_cwa_user(username: str) -> Optional[dict[str, Any]]:
    """Return {'name', 'password', 'email'} for a Calibre-Web user, or None.

    Names are compared case-insensitively, as Calibre-Web's own login does.
    """
    db_path = _get_cwa_db_path()
    if not db_path:
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT name, password, email FROM user WHERE lower(name) = lower(?)", (username,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"name": row[0], "password": row[1], "email": _normalize_email(row[2])}


def find_cwa_names_by_email(email: str) -> list[str]:
    """Names of Calibre-Web users registered to this email (case-insensitive)."""
    db_path = _get_cwa_db_path()
    if not db_path or not email:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT name FROM user WHERE lower(trim(email)) = lower(trim(?))", (email,)
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def get_cwa_mail_from() -> Optional[str]:
    """The address Calibre-Web sends Send-to-Kindle mail from, if set."""
    db_path = _get_cwa_db_path()
    if not db_path:
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT mail_from FROM settings").fetchone()
    finally:
        conn.close()
    return ((row[0] if row else None) or "").strip() or None


def verify_cwa_login(username: str, password: str) -> Optional[dict[str, Any]]:
    """Return the Calibre-Web user when username/password is a valid login there, else None."""
    user = find_cwa_user(username)
    if not user or not user["password"] or not check_password_hash(user["password"], password):
        return None
    return user
