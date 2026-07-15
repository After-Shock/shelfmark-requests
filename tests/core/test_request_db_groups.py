"""Tests for linked request persistence and canonical query behavior."""

import sqlite3
import threading

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


@pytest.fixture
def user_id(two_users):
    return two_users[0]


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


def test_linked_target_is_normalized_to_its_canonical_request(request_db, two_users):
    canonical = request_db.create_request(user_id=two_users[0], title="Dune")
    linked = request_db.create_request(
        user_id=two_users[1],
        title="Dune",
        canonical_request_id=canonical["id"],
    )

    nested_link = request_db.create_request(
        user_id=two_users[0],
        title="Dune",
        canonical_request_id=linked["id"],
    )

    assert nested_link["canonical_request_id"] == canonical["id"]
    assert request_db.get_request(canonical["id"])["requester_count"] == 3
    assert request_db.get_request(linked["id"])["requester_count"] == 3
    assert request_db.get_request(nested_link["id"])["requester_count"] == 3


def test_missing_canonical_request_id_is_rejected(request_db, two_users):
    with pytest.raises(sqlite3.IntegrityError):
        request_db.create_request(
            user_id=two_users[0],
            title="Dune",
            canonical_request_id=999,
        )


def test_provider_identity_precedes_title_fallback(request_db, two_users):
    first, outcome = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert",
        content_type="ebook", provider="GoogleBooks", provider_id="gb-1",
    )
    second, second_outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune: Deluxe", author="F. Herbert",
        content_type="ebook", provider="googlebooks", provider_id="gb-1",
    )
    assert outcome == "created"
    assert second_outcome == "joined"
    assert second["canonical_request_id"] == first["id"]


def test_same_user_repeat_is_idempotent(request_db, user_id):
    first, _ = request_db.create_or_join_request(
        user_id=user_id, title="  THE   HOBBIT ", author="J.R.R. Tolkien"
    )
    repeated, outcome = request_db.create_or_join_request(
        user_id=user_id, title="the hobbit", author="j.r.r. tolkien"
    )
    assert outcome == "already_joined"
    assert repeated["id"] == first["id"]


def test_content_types_do_not_join(request_db, two_users):
    ebook, _ = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert", content_type="ebook"
    )
    audiobook, outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune", author="Frank Herbert", content_type="audiobook"
    )
    assert outcome == "created"
    assert audiobook["canonical_request_id"] is None
    assert audiobook["id"] != ebook["id"]


@pytest.mark.parametrize(
    ("status", "expected_outcome"),
    [
        ("pending", "joined"),
        ("prerelease_requested", "joined"),
        ("approved", "joined"),
        ("downloading", "joined"),
        ("no_sources_requested", "joined"),
        ("fulfilled", "created"),
        ("denied", "created"),
        ("failed", "created"),
        ("cancelled", "created"),
    ],
)
def test_status_determines_whether_requests_join(
    request_db, two_users, status, expected_outcome
):
    first, _ = request_db.create_or_join_request(
        user_id=two_users[0], title="The Hobbit", author="J.R.R. Tolkien"
    )
    request_db.update_request_status(first["id"], status)

    second, outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="the hobbit", author="j.r.r. tolkien"
    )

    assert outcome == expected_outcome
    assert second["canonical_request_id"] == (
        first["id"] if expected_outcome == "joined" else None
    )


def test_joined_request_copies_canonical_metadata_and_status(request_db, two_users):
    first, _ = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert", year="1965",
        cover_url="https://example.com/dune.jpg", description="A classic",
        isbn_10="0441172717", isbn_13="9780441172719", provider="GoogleBooks",
        provider_id="gb-1", series_name="Dune Chronicles", series_position=1,
        prefer_alternate_version=True, is_manual_request=True, is_released=False,
    )
    with request_db._connect() as conn:
        conn.execute(
            "UPDATE requests SET expected_release_date = ? WHERE id = ?",
            ("2027-01-01", first["id"]),
        )
        conn.commit()
    request_db.update_request_status(first["id"], "approved")

    joined, outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune: Deluxe", author="F. Herbert",
        provider="googlebooks", provider_id="gb-1",
    )

    assert outcome == "joined"
    assert joined["canonical_request_id"] == first["id"]
    assert joined["status"] == "approved"
    for field in (
        "title", "author", "year", "cover_url", "description", "isbn_10", "isbn_13",
        "provider", "provider_id", "series_name", "series_position",
        "prefer_alternate_version", "is_manual_request", "is_released",
        "expected_release_date",
    ):
        assert joined[field] == request_db.get_request(first["id"])[field]


def test_concurrent_requests_create_one_group(request_db, two_users):
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def create(db, user_id):
        try:
            barrier.wait()
            results.append(db.create_or_join_request(
                user_id=user_id, title="Dune", author="Frank Herbert"
            ))
        except Exception as error:
            errors.append(error)

    databases = (RequestDB(request_db._db_path), RequestDB(request_db._db_path))
    threads = [
        threading.Thread(target=create, args=(db, user_id))
        for db, user_id in zip(databases, two_users)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert sorted(outcome for _, outcome in results) == ["created", "joined"]
    assert request_db.count_requests() == 1
    assert sum(request_db.count_requests(user_id=user_id) for user_id in two_users) == 2
