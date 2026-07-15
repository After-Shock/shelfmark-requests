"""Tests for linked request persistence and canonical query behavior."""

import sqlite3

import pytest

from shelfmark.core.request_db import RequestDB


@pytest.fixture
def request_db(tmp_path):
    db_path = str(tmp_path / "requests.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            display_name TEXT,
            role TEXT NOT NULL
        )"""
    )
    conn.commit()
    conn.close()

    db = RequestDB(db_path)
    db.initialize()
    return db


def _create_user(conn: sqlite3.Connection, username: str) -> int:
    cursor = conn.execute(
        "INSERT INTO users (username, role) VALUES (?, 'user')",
        (username,),
    )
    conn.commit()
    return cursor.lastrowid


@pytest.fixture
def two_users(request_db):
    with request_db._connect() as conn:
        return _create_user(conn, "first"), _create_user(conn, "second")


def test_schema_v9_adds_canonical_request_id_and_index(tmp_path):
    db = RequestDB(str(tmp_path / "requests.db"))
    with db._connect() as conn:
        conn.execute(
            """CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                display_name TEXT,
                role TEXT NOT NULL
            )"""
        )
        conn.commit()
    db.initialize()
    with db._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(requests)")}
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert "canonical_request_id" in columns
    assert "idx_requests_canonical_request_id" in indexes
    assert version == 9


def test_admin_lists_exclude_linked_rows_but_user_lists_include_them(request_db, two_users):
    canonical = request_db.create_request(user_id=two_users[0], title="Dune", author="Frank Herbert")
    linked = request_db.create_request(
        user_id=two_users[1],
        title="Dune",
        author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    assert [row["id"] for row in request_db.list_requests(user_id=None)] == [canonical["id"]]
    assert [row["id"] for row in request_db.list_requests(user_id=two_users[1])] == [linked["id"]]
    assert request_db.get_request(canonical["id"])["requester_count"] == 2
