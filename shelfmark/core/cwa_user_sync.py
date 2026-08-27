"""Helpers for provisioning and syncing Calibre-Web users into users.db."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping, Optional

from shelfmark.core.auth_modes import AUTH_SOURCE_CWA, normalize_auth_source
from shelfmark.core.config import config
from shelfmark.core.external_user_linking import upsert_external_user
from shelfmark.core.logger import setup_logger
from shelfmark.core.user_db import UserDB

_CWA_ALIAS_SUFFIX = "__cwa"

logger = setup_logger(__name__)

# CWA role flags: bit 0 = admin, 0 = regular user.
_CWA_ROLE_ADMIN = 1

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
    cwa_role = _CWA_ROLE_ADMIN if role == "admin" else 0
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
