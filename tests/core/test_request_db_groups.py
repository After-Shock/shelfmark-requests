"""Tests for linked request persistence and canonical query behavior."""

import sqlite3
import threading

import pytest

import shelfmark.core.request_db as request_db_module
from shelfmark.core.request_db import RequestDB, RequestGroupIntegrityError


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


def _corrupt_canonical_link(db: RequestDB, request_id: int, canonical_request_id: int) -> None:
    with sqlite3.connect(db._db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "UPDATE requests SET canonical_request_id = ? WHERE id = ?",
            (canonical_request_id, request_id),
        )


def _request_snapshots(db: RequestDB, request_ids: list[int]) -> list[dict]:
    placeholders = ", ".join("?" for _ in request_ids)
    with db._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM requests WHERE id IN ({placeholders}) ORDER BY id",
            request_ids,
        ).fetchall()
    return [dict(row) for row in rows]


def _capture_integrity_logs(monkeypatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(request_db_module.logger, "error", messages.append)
    return messages


@pytest.fixture
def two_users(request_db):
    with request_db._connect() as conn:
        return _create_user(conn, "first"), _create_user(conn, "second")


@pytest.fixture
def user_id(two_users):
    return two_users[0]


@pytest.fixture
def grouped_requests(request_db, two_users):
    canonical, _ = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert"
    )
    linked, outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune", author="Frank Herbert"
    )
    assert outcome == "joined"
    return request_db, canonical, linked


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


def test_title_fallback_normalizes_unicode_casefold_and_whitespace(request_db, two_users):
    first, first_outcome = request_db.create_or_join_request(
        user_id=two_users[0],
        title="Straße Ｆｏｏ",
        author="Jörg　Müller",
    )
    joined, joined_outcome = request_db.create_or_join_request(
        user_id=two_users[1],
        title="STRASSE FOO",
        author="jörg müller",
    )

    assert first_outcome == "created"
    assert joined_outcome == "joined"
    assert joined["canonical_request_id"] == first["id"]


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


def test_prerelease_creation_is_atomic_and_does_not_mutate_existing_group(request_db, two_users):
    prerelease, outcome = request_db.create_or_join_request(
        user_id=two_users[0],
        title="Future Dune",
        author="Frank Herbert",
        provider="GoogleBooks",
        provider_id="gb-future",
        is_released=False,
        expected_release_date="2099-01-01",
        status="prerelease_requested",
    )

    assert outcome == "created"
    assert prerelease["status"] == "prerelease_requested"
    assert prerelease["expected_release_date"] == "2099-01-01"
    assert prerelease["is_released"] == 0

    joined, joined_outcome = request_db.create_or_join_request(
        user_id=two_users[1],
        title="Future Dune",
        author="Frank Herbert",
        provider="GoogleBooks",
        provider_id="gb-future",
        is_released=True,
        expected_release_date="2000-01-01",
        status="pending",
    )

    assert joined_outcome == "joined"
    assert joined["canonical_request_id"] == prerelease["id"]
    assert request_db.get_request(prerelease["id"])["status"] == "prerelease_requested"
    assert request_db.get_request(prerelease["id"])["expected_release_date"] == "2099-01-01"
    assert request_db.get_request(prerelease["id"])["is_released"] == 0


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


def test_group_status_update_changes_all_active_rows(grouped_requests):
    db, canonical, linked = grouped_requests

    updated = db.update_request_status(
        linked["id"], "approved", admin_note="Queued", approved_by=canonical["user_id"],
        download_task_id="task-1",
    )

    rows = db.get_request_group(canonical["id"])
    assert updated["id"] == canonical["id"]
    assert {row["status"] for row in rows} == {"approved"}
    assert {row["admin_note"] for row in rows} == {"Queued"}
    assert {row["download_task_id"] for row in rows} == {"task-1"}


def test_group_metadata_update_resolves_linked_id_and_propagates_to_active_members(grouped_requests):
    db, canonical, linked = grouped_requests

    updated = db.update_request_metadata(
        linked["id"],
        provider="OpenLibrary",
        provider_id="ol-123",
        expected_release_date="2099-01-01",
        is_released=False,
    )
    db.update_request_status(linked["id"], "prerelease_requested")

    assert updated["id"] == canonical["id"]
    rows = db.get_request_group(canonical["id"])
    assert {row["provider"] for row in rows} == {"OpenLibrary"}
    assert {row["provider_id"] for row in rows} == {"ol-123"}
    assert {row["expected_release_date"] for row in rows} == {"2099-01-01"}
    assert {row["is_released"] for row in rows} == {0}
    assert {row["status"] for row in rows} == {"prerelease_requested"}


def test_group_metadata_update_rolls_back_all_members_on_failure(grouped_requests):
    db, canonical, linked = grouped_requests
    before = _request_snapshots(db, [canonical["id"], linked["id"]])
    with db._connect() as conn:
        conn.execute(
            f"""CREATE TRIGGER fail_group_metadata
                BEFORE UPDATE OF provider ON requests
                WHEN NEW.id = {linked["id"]}
                BEGIN SELECT RAISE(ABORT, 'metadata propagation failure'); END"""
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="metadata propagation failure"):
        db.update_request_metadata(linked["id"], provider="OpenLibrary")

    assert _request_snapshots(db, [canonical["id"], linked["id"]]) == before


def test_shared_metadata_update_preserves_member_specific_admin_visibility(grouped_requests):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        conn.execute(
            "UPDATE requests SET hidden_from_admin = 1 WHERE id = ?", (canonical["id"],)
        )
        conn.execute(
            "UPDATE requests SET hidden_from_admin = 0 WHERE id = ?", (linked["id"],)
        )
        conn.commit()

    db.update_request_metadata(
        linked["id"],
        provider="OpenLibrary",
        provider_id="ol-123",
        expected_release_date="2099-01-01",
        is_released=False,
        hidden_from_admin=False,
    )

    rows = {row["id"]: row for row in db.get_request_group(canonical["id"])}
    assert rows[canonical["id"]]["hidden_from_admin"] == 1
    assert rows[linked["id"]]["hidden_from_admin"] == 0
    assert {row["provider"] for row in rows.values()} == {"OpenLibrary"}
    assert {row["provider_id"] for row in rows.values()} == {"ol-123"}
    assert {row["expected_release_date"] for row in rows.values()} == {"2099-01-01"}
    assert {row["is_released"] for row in rows.values()} == {0}


def test_group_lookup_resolves_linked_rows_and_can_exclude_cancelled(grouped_requests):
    db, canonical, linked = grouped_requests
    cancelled = db.create_request(
        user_id=canonical["user_id"], title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    with db._connect() as conn:
        conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = ?", (cancelled["id"],))
        conn.commit()

    assert {row["id"] for row in db.get_request_group(linked["id"])} == {
        canonical["id"], linked["id"], cancelled["id"],
    }
    assert {row["id"] for row in db.get_request_group(linked["id"], active_only=True)} == {
        canonical["id"], linked["id"],
    }


def test_deleting_linked_row_keeps_canonical(grouped_requests):
    db, canonical, linked = grouped_requests

    remaining = db.delete_user_request(linked["id"], linked["user_id"])

    assert remaining["id"] == canonical["id"]
    assert db.get_request(linked["id"]) is None
    assert [row["id"] for row in db.get_request_group(canonical["id"])] == [canonical["id"]]


def test_deleting_canonical_promotes_oldest_linked_member(grouped_requests):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third")
    third = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )

    remaining = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert remaining["id"] == linked["id"]
    assert remaining["canonical_request_id"] is None
    assert db.get_request(canonical["id"]) is None
    assert db.get_request(third["id"])["canonical_request_id"] == linked["id"]


def test_deleting_final_group_member_returns_none(grouped_requests):
    db, canonical, _ = grouped_requests
    only = db.create_request(user_id=canonical["user_id"], title="Foundation")

    assert db.delete_user_request(only["id"], canonical["user_id"]) is None
    assert db.get_request(only["id"]) is None


def test_promotion_preserves_prerelease_and_download_metadata(grouped_requests):
    db, canonical, linked = grouped_requests
    db.update_request_status(
        canonical["id"], "prerelease_requested", admin_note="Awaiting release",
        approved_by=canonical["user_id"], download_task_id="task-1",
    )

    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert promoted["id"] == linked["id"]
    assert promoted["status"] == "prerelease_requested"
    assert promoted["admin_note"] == "Awaiting release"
    assert promoted["approved_by"] == canonical["user_id"]
    assert promoted["download_task_id"] == "task-1"


def test_failed_canonical_promotion_rolls_back_deletion(grouped_requests):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        conn.execute(
            f"""CREATE TRIGGER fail_promotion
                BEFORE UPDATE OF canonical_request_id ON requests
                WHEN NEW.id = {linked["id"]}
                BEGIN SELECT RAISE(ABORT, 'promotion failure'); END"""
        )
        conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="promotion failure"):
        db.delete_user_request(canonical["id"], canonical["user_id"])

    assert db.get_request(canonical["id"])["id"] == canonical["id"]
    assert db.get_request(linked["id"])["canonical_request_id"] == canonical["id"]


def test_canonical_deletion_promotes_oldest_active_member(grouped_requests):
    db, canonical, cancelled = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third-active")
    active = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    with db._connect() as conn:
        conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = ?", (cancelled["id"],))
        conn.commit()

    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert promoted["id"] == active["id"]
    assert db.get_request(cancelled["id"])["canonical_request_id"] == active["id"]


def test_canonical_deletion_promotes_oldest_cancelled_member_when_no_active_member(grouped_requests):
    db, canonical, cancelled = grouped_requests
    with db._connect() as conn:
        conn.execute("UPDATE requests SET status = 'cancelled' WHERE id = ?", (cancelled["id"],))
        conn.commit()

    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert promoted["id"] == cancelled["id"]
    assert promoted["canonical_request_id"] is None


def test_canonical_deletion_skips_terminal_members_when_promoting(grouped_requests):
    db, canonical, terminal = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third-after-terminal")
        conn.execute("UPDATE requests SET status = 'fulfilled' WHERE id = ?", (terminal["id"],))
        conn.commit()
    active = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )

    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert promoted["id"] == active["id"]
    assert db.get_request(terminal["id"])["canonical_request_id"] == active["id"]


def test_canonical_promotion_copies_current_canonical_metadata(grouped_requests):
    db, canonical, linked = grouped_requests
    db.update_request_metadata(
        canonical["id"], provider="OpenLibrary", provider_id="ol-2",
        expected_release_date="2027-01-01", is_released=True, hidden_from_admin=True,
    )

    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])

    assert promoted["id"] == linked["id"]
    assert promoted["provider"] == "OpenLibrary"
    assert promoted["provider_id"] == "ol-2"
    assert promoted["expected_release_date"] == "2027-01-01"
    assert promoted["is_released"] == 1
    assert promoted["hidden_from_admin"] == 1


@pytest.mark.parametrize("target", ["canonical", "linked"])
def test_hiding_group_from_admin_resolves_any_member_and_survives_promotion(
    grouped_requests, target
):
    db, canonical, linked = grouped_requests
    target_id = canonical["id"] if target == "canonical" else linked["id"]

    hidden = db.hide_request_group_from_admin(target_id)

    assert hidden["id"] == canonical["id"]
    assert {row["hidden_from_admin"] for row in db.get_request_group(canonical["id"])} == {1}
    promoted = db.delete_user_request(canonical["id"], canonical["user_id"])
    assert promoted["id"] == linked["id"]
    assert promoted["hidden_from_admin"] == 1


def test_group_lookup_rejects_dangling_canonical_reference(grouped_requests, monkeypatch):
    db, _, linked = grouped_requests
    _corrupt_canonical_link(db, linked["id"], 999)
    before = _request_snapshots(db, [linked["id"]])
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="dangling"):
        db.get_request_group(linked["id"])

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, [linked["id"]]) == before


def test_status_update_rejects_self_referential_link_without_mutating(grouped_requests, monkeypatch):
    db, _, linked = grouped_requests
    _corrupt_canonical_link(db, linked["id"], linked["id"])
    before = _request_snapshots(db, [linked["id"]])
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="self-referential"):
        db.update_request_status(linked["id"], "approved")

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, [linked["id"]]) == before


def test_owned_deletion_rejects_linked_chain_without_mutating(grouped_requests, monkeypatch):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third-chain")
    chained = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    _corrupt_canonical_link(db, chained["id"], linked["id"])
    request_ids = [canonical["id"], linked["id"], chained["id"]]
    before = _request_snapshots(db, request_ids)
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="linked request"):
        db.delete_user_request(chained["id"], third_user_id)

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, request_ids) == before


def test_group_lookup_rejects_cyclic_links(grouped_requests, monkeypatch):
    db, canonical, linked = grouped_requests
    _corrupt_canonical_link(db, canonical["id"], linked["id"])
    request_ids = [canonical["id"], linked["id"]]
    before = _request_snapshots(db, request_ids)
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="cyclic"):
        db.get_request_group(canonical["id"])

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, request_ids) == before


def test_group_status_update_rejects_nested_link_without_mutating(grouped_requests, monkeypatch):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third-nested")
    nested = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    _corrupt_canonical_link(db, nested["id"], linked["id"])
    request_ids = [canonical["id"], linked["id"], nested["id"]]
    before = _request_snapshots(db, request_ids)
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="linked request"):
        db.update_request_status(canonical["id"], "approved")

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, request_ids) == before


def test_legacy_delete_promotes_canonical_and_repoints_members(grouped_requests):
    db, canonical, linked = grouped_requests
    with db._connect() as conn:
        third_user_id = _create_user(conn, "third-legacy")
    third = db.create_request(
        user_id=third_user_id, title="Dune", author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )

    assert db.delete_request(canonical["id"])

    assert db.get_request(linked["id"])["canonical_request_id"] is None
    assert db.get_request(third["id"])["canonical_request_id"] == linked["id"]


def test_legacy_delete_rejects_malformed_group_without_mutating(grouped_requests, monkeypatch):
    db, _, linked = grouped_requests
    _corrupt_canonical_link(db, linked["id"], 999)
    before = _request_snapshots(db, [linked["id"]])
    logged = _capture_integrity_logs(monkeypatch)

    with pytest.raises(RequestGroupIntegrityError, match="dangling"):
        db.delete_request(linked["id"])

    assert any("Request group integrity error" in message for message in logged)
    assert _request_snapshots(db, [linked["id"]]) == before


@pytest.mark.parametrize(
    ("topology", "reason"),
    [
        ("dangling", "dangling canonical request link"),
        ("self_reference", "self-referential canonical request link"),
        ("two_node_cycle", "cyclic canonical request link"),
        ("nested_parent", "canonical request points to another linked request"),
    ],
)
@pytest.mark.parametrize("operation", ["lookup", "status", "owned_delete", "delete"])
def test_malformed_group_operation_matrix_preserves_all_rows(
    grouped_requests, monkeypatch, topology, reason, operation,
):
    db, canonical, linked = grouped_requests
    target = linked
    request_ids = [canonical["id"], linked["id"]]
    if topology == "dangling":
        _corrupt_canonical_link(db, linked["id"], 999)
    elif topology == "self_reference":
        _corrupt_canonical_link(db, linked["id"], linked["id"])
    elif topology == "two_node_cycle":
        _corrupt_canonical_link(db, canonical["id"], linked["id"])
        target = canonical
    else:
        with db._connect() as conn:
            third_user_id = _create_user(conn, "third-matrix")
        nested = db.create_request(
            user_id=third_user_id, title="Dune", author="Frank Herbert",
            canonical_request_id=canonical["id"],
        )
        _corrupt_canonical_link(db, nested["id"], linked["id"])
        request_ids.append(nested["id"])
        target = canonical

    before = _request_snapshots(db, request_ids)
    logged = _capture_integrity_logs(monkeypatch)
    with pytest.raises(RequestGroupIntegrityError, match=reason) as error:
        if operation == "lookup":
            db.get_request_group(target["id"])
        elif operation == "status":
            db.update_request_status(target["id"], "approved")
        elif operation == "owned_delete":
            db.delete_user_request(target["id"], target["user_id"])
        else:
            db.delete_request(target["id"])

    assert str(error.value) in logged
    assert _request_snapshots(db, request_ids) == before
