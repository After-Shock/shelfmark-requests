"""
Tests for SQLite user database.

Tests CRUD operations on users and user_settings tables.
"""

import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "shelfmark.db")


@pytest.fixture
def user_db(db_path):
    """Create a UserDB instance with a temporary database."""
    from shelfmark.core.user_db import UserDB

    db = UserDB(db_path)
    db.initialize()
    return db


class TestUserDBInitialization:
    """Tests for database creation and schema setup."""

    def test_initialize_creates_database_file(self, db_path):
        from shelfmark.core.user_db import UserDB

        db = UserDB(db_path)
        db.initialize()
        assert os.path.exists(db_path)

    def test_initialize_creates_users_table(self, user_db, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_initialize_creates_user_settings_table(self, user_db, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_settings'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_initialize_enables_wal_mode(self, user_db, db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_initialize_is_idempotent(self, db_path):
        from shelfmark.core.user_db import UserDB

        db = UserDB(db_path)
        db.initialize()
        db.initialize()  # Should not raise
        assert os.path.exists(db_path)

    def test_initialize_migrates_request_last_viewed_column(self, db_path):
        from shelfmark.core.user_db import UserDB

        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                display_name TEXT,
                password_hash TEXT,
                oidc_subject TEXT UNIQUE,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            "INSERT INTO users (username, email, display_name, password_hash, role) VALUES (?, ?, ?, ?, ?)",
            ("legacy_user", "legacy@example.invalid", "Legacy User", "legacy_hash", "user"),
        )
        conn.commit()
        conn.close()

        db = UserDB(db_path)
        db.initialize()
        db.initialize()

        conn = sqlite3.connect(db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        row = conn.execute(
            "SELECT username, email, display_name, password_hash, role FROM users WHERE username = ?",
            ("legacy_user",),
        ).fetchone()
        conn.close()
        assert "requests_last_viewed_at" in columns
        assert row == ("legacy_user", "legacy@example.invalid", "Legacy User", "legacy_hash", "user")


class TestUserCRUD:
    """Tests for user create, read, update, delete operations."""

    def test_create_user(self, user_db):
        user = user_db.create_user(
            username="john",
            email="john@example.com",
            display_name="John Doe",
        )
        assert user["id"] is not None
        assert user["username"] == "john"
        assert user["email"] == "john@example.com"
        assert user["display_name"] == "John Doe"
        assert user["role"] == "user"

    def test_create_user_with_password(self, user_db):
        user = user_db.create_user(
            username="admin",
            password_hash="hashed_pw",
            role="admin",
        )
        assert user["role"] == "admin"
        assert user["password_hash"] == "hashed_pw"

    def test_create_user_with_oidc_subject(self, user_db):
        user = user_db.create_user(
            username="oidcuser",
            oidc_subject="sub-12345",
            email="oidc@example.com",
        )
        assert user["oidc_subject"] == "sub-12345"

    def test_create_duplicate_username_fails(self, user_db):
        user_db.create_user(username="john")
        with pytest.raises(ValueError, match="already exists"):
            user_db.create_user(username="john")

    def test_create_duplicate_oidc_subject_fails(self, user_db):
        user_db.create_user(username="user1", oidc_subject="sub-123")
        with pytest.raises(ValueError, match="already exists"):
            user_db.create_user(username="user2", oidc_subject="sub-123")

    def test_get_user_by_id(self, user_db):
        created = user_db.create_user(username="john")
        fetched = user_db.get_user(user_id=created["id"])
        assert fetched["username"] == "john"

    def test_get_user_by_username(self, user_db):
        user_db.create_user(username="john", email="john@example.com")
        fetched = user_db.get_user(username="john")
        assert fetched["email"] == "john@example.com"

    def test_get_user_by_oidc_subject(self, user_db):
        user_db.create_user(username="john", oidc_subject="sub-123")
        fetched = user_db.get_user(oidc_subject="sub-123")
        assert fetched["username"] == "john"

    def test_get_nonexistent_user_returns_none(self, user_db):
        assert user_db.get_user(username="nobody") is None

    def test_update_user(self, user_db):
        user = user_db.create_user(username="john", role="user")
        user_db.update_user(user["id"], role="admin", email="new@example.com")
        updated = user_db.get_user(user_id=user["id"])
        assert updated["role"] == "admin"
        assert updated["email"] == "new@example.com"

    def test_update_nonexistent_user_raises(self, user_db):
        with pytest.raises(ValueError, match="not found"):
            user_db.update_user(9999, role="admin")

    def test_delete_user(self, user_db):
        user = user_db.create_user(username="john")
        user_db.delete_user(user["id"])
        assert user_db.get_user(user_id=user["id"]) is None

    def test_delete_user_cascades_settings(self, user_db):
        user = user_db.create_user(username="john")
        user_db.set_user_settings(user["id"], {"booklore_library_id": 1})
        user_db.delete_user(user["id"])
        assert user_db.get_user_settings(user["id"]) == {}

    def test_list_users(self, user_db):
        user_db.create_user(username="alice")
        user_db.create_user(username="bob")
        user_db.create_user(username="charlie")
        users = user_db.list_users()
        assert len(users) == 3
        usernames = [u["username"] for u in users]
        assert "alice" in usernames
        assert "bob" in usernames
        assert "charlie" in usernames


class TestUserSettings:
    """Tests for per-user settings."""

    def test_set_and_get_user_settings(self, user_db):
        user = user_db.create_user(username="john")
        settings = {"booklore_library_id": 5, "booklore_path_id": 2}
        user_db.set_user_settings(user["id"], settings)
        fetched = user_db.get_user_settings(user["id"])
        assert fetched["booklore_library_id"] == 5
        assert fetched["booklore_path_id"] == 2

    def test_get_settings_for_user_without_settings(self, user_db):
        user = user_db.create_user(username="john")
        assert user_db.get_user_settings(user["id"]) == {}

    def test_update_user_settings_merges(self, user_db):
        user = user_db.create_user(username="john")
        user_db.set_user_settings(user["id"], {"key1": "val1"})
        user_db.set_user_settings(user["id"], {"key2": "val2"})
        settings = user_db.get_user_settings(user["id"])
        assert settings["key1"] == "val1"
        assert settings["key2"] == "val2"

    def test_update_user_settings_overwrites_existing_key(self, user_db):
        user = user_db.create_user(username="john")
        user_db.set_user_settings(user["id"], {"key1": "old"})
        user_db.set_user_settings(user["id"], {"key1": "new"})
        settings = user_db.get_user_settings(user["id"])
        assert settings["key1"] == "new"


def test_provisioned_services_migration_leaves_existing_users_untouched(tmp_path):
    """The new column is additive: legacy rows survive intact and stay NULL.

    NULL is what keeps a pre-existing user's Audiobookshelf/Calibre-Web
    password from being overwritten on their next password change.
    """
    import sqlite3

    from shelfmark.core.user_db import UserDB

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT,
            display_name TEXT,
            password_hash TEXT,
            oidc_subject TEXT UNIQUE,
            auth_source TEXT NOT NULL DEFAULT 'builtin',
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.executemany(
        "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
        [
            ("oldtimer", "old@example.com", "hash-a", "user"),
            ("katie.erb15@gmail.com", None, "hash-b", "user"),
            ("theadmin", None, "hash-c", "admin"),
        ],
    )
    conn.commit()
    conn.close()

    db = UserDB(str(db_path))
    db.initialize()

    rows = {u["username"]: u for u in db.list_users()}
    assert set(rows) == {"oldtimer", "katie.erb15@gmail.com", "theadmin"}
    for user in rows.values():
        assert user["provisioned_services"] is None
    # Nothing else about the legacy rows moved.
    assert rows["oldtimer"]["email"] == "old@example.com"
    assert rows["oldtimer"]["password_hash"] == "hash-a"
    assert rows["theadmin"]["role"] == "admin"

    # Idempotent: re-initializing an already-migrated db is a no-op.
    db.initialize()
    assert db.get_user(username="oldtimer")["provisioned_services"] is None
