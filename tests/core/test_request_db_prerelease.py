"""Focused tests for prerelease_requested request status support."""

import sqlite3

import pytest

from shelfmark.core.request_db import RequestDB


def _create_users_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            display_name TEXT,
            requests_last_viewed_at TIMESTAMP
        )"""
    )
    conn.execute("INSERT INTO users (username) VALUES ('testuser')")
    conn.commit()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    _create_users_table(conn)
    conn.close()

    request_db = RequestDB(db_path)
    request_db.initialize()
    return request_db


def test_get_request_counts_includes_prerelease_requested_bucket(db):
    counts = db.get_request_counts(user_id=1)

    assert counts["prerelease_requested"] == 0
    assert counts["total"] == 0


def test_create_update_list_and_count_prerelease_requested(db):
    req = db.create_request(user_id=1, title="Dune", content_type="audiobook")

    updated = db.update_request_status(
        req["id"],
        "prerelease_requested",
        admin_note="Waiting for release",
    )

    assert updated is not None
    assert updated["status"] == "prerelease_requested"
    assert updated["admin_note"] == "Waiting for release"

    listed = db.list_requests(user_id=1, status="prerelease_requested")
    assert len(listed) == 1
    assert listed[0]["id"] == req["id"]
    assert listed[0]["status"] == "prerelease_requested"

    assert db.count_requests(user_id=1, status="prerelease_requested") == 1

    counts = db.get_request_counts(user_id=1)
    assert counts["prerelease_requested"] == 1
    assert counts["total"] == 1


def test_initialize_migrates_existing_v5_schema_to_allow_prerelease_requested(tmp_path):
    db_path = str(tmp_path / "existing.db")
    conn = sqlite3.connect(db_path)
    _create_users_table(conn)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    conn.execute(
        """CREATE TABLE requests (
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
            hidden_from_admin INTEGER DEFAULT 0,
            prefer_alternate_version INTEGER DEFAULT 0,
            is_manual_request INTEGER DEFAULT 0,
            is_released INTEGER DEFAULT NULL,
            expected_release_date TEXT DEFAULT NULL
        )"""
    )
    conn.commit()
    conn.close()

    request_db = RequestDB(db_path)
    request_db.initialize()

    req = request_db.create_request(user_id=1, title="Dune", content_type="audiobook")
    updated = request_db.update_request_status(req["id"], "prerelease_requested")

    assert updated is not None
    assert updated["status"] == "prerelease_requested"
