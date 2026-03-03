"""Test prefer_alternate_version field on request DB."""
import sqlite3
import pytest
from shelfmark.core.request_db import RequestDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    # Create users table (required by FK)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        display_name TEXT,
        requests_last_viewed_at TIMESTAMP
    )""")
    conn.execute("INSERT INTO users (username) VALUES ('testuser')")
    conn.commit()
    conn.close()
    rdb = RequestDB(db_path)
    rdb.initialize()
    return rdb


def test_prefer_alternate_version_defaults_false(db):
    req = db.create_request(user_id=1, title="Dune", content_type="audiobook")
    assert req["prefer_alternate_version"] == 0


def test_prefer_alternate_version_stored_true(db):
    req = db.create_request(
        user_id=1, title="Dune", content_type="audiobook",
        prefer_alternate_version=True
    )
    assert req["prefer_alternate_version"] == 1


def test_prefer_alternate_version_stored_false_explicitly(db):
    req = db.create_request(
        user_id=1, title="Dune", content_type="audiobook",
        prefer_alternate_version=False
    )
    assert req["prefer_alternate_version"] == 0


def test_migration_adds_column_to_existing_db(tmp_path):
    """Migration 3 should add prefer_alternate_version to an existing v2 database."""
    db_path = str(tmp_path / "existing.db")

    # Bootstrap a v2 database manually (no prefer_alternate_version column)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        display_name TEXT,
        requests_last_viewed_at TIMESTAMP
    )""")
    conn.execute("INSERT INTO users (username) VALUES ('testuser')")
    conn.execute("""CREATE TABLE schema_version (version INTEGER NOT NULL)""")
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    conn.execute("""CREATE TABLE requests (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',
        content_type    TEXT NOT NULL DEFAULT 'ebook',
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
        approved_by     INTEGER,
        download_task_id TEXT,
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        hidden_from_admin INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()

    # Run initialize() — should run Migration 3 and add the column
    rdb = RequestDB(db_path)
    rdb.initialize()

    # Verify the column was added and is usable
    req = rdb.create_request(user_id=1, title="Test Book", content_type="audiobook",
                             prefer_alternate_version=True)
    assert req["prefer_alternate_version"] == 1
