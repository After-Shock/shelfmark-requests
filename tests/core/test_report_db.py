import sqlite3

import pytest

from shelfmark.core import report_db
from shelfmark.core.report_db import ReportLimitReached, item_key
from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "users.db")
    users = UserDB(path)
    users.initialize()
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
            [(1, "a", "user"), (2, "b", "user")],
        )
    db = RequestDB(path)
    db.initialize()
    return db, path


def _fields(n=1, **extra):
    return {
        "item_key": item_key("abs", "audiobook", f"Book {n}", "Author"),
        "library": "abs", "content_type": "audiobook", "title": f"Book {n}",
        "author": "Author", "problem_type": "wrong_language", **extra,
    }


def _create(db, user, n=1, limit=6, since="2000-01-01", **extra):
    return report_db.create_or_join_report(
        db, user_id=user, fields=_fields(n, **extra), quota_limit=limit, quota_since=since
    )


def test_migration_12_backfills_deliveries(tmp_path):
    path = str(tmp_path / "users.db")
    UserDB(path).initialize()
    db = RequestDB(path)
    db.initialize()
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "DROP TABLE request_deliveries; DROP TABLE media_report_users; "
            "DROP TABLE report_quota_usage; DROP TABLE media_reports; "
            "UPDATE schema_version SET version = 11;"
        )
        conn.execute("INSERT INTO users (id, username, role) VALUES (1, 'a', 'user')")
        conn.execute(
            "INSERT INTO requests (id, user_id, title, author, content_type, status, download_task_id) "
            "VALUES (1, 1, 'Dune', 'Frank Herbert', 'audiobook', 'fulfilled', 'abc')"
        )
        conn.execute(
            "INSERT INTO requests (id, user_id, title, content_type, status) "
            "VALUES (2, 1, 'No Task', 'ebook', 'fulfilled')"
        )
        conn.execute(
            "INSERT INTO requests (id, user_id, title, content_type, status, download_task_id, "
            "canonical_request_id) VALUES (3, 1, 'Dune', 'audiobook', 'fulfilled', 'abc', 1)"
        )
    db.initialize()
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT request_id, release_id, library, item_key FROM request_deliveries").fetchall()
    assert rows == [(1, "abc", "abs", item_key("abs", "audiobook", "Dune", "Frank Herbert"))]


def test_second_reporter_joins_for_free(env):
    db, _ = env
    first, joined1 = _create(db, 1)
    second, joined2 = _create(db, 2)
    assert (joined1, joined2) == (False, True)
    assert first["id"] == second["id"]
    assert report_db.count_report_usage(db, 2, "2000-01-01") == 0
    assert [r["id"] for r in report_db.list_reports(db, user_id=2)] == [first["id"]]


def test_report_limit(env):
    db, _ = env
    for n in range(6):
        _create(db, 1, n, limit=6)
    with pytest.raises(ReportLimitReached):
        _create(db, 1, 7, limit=6)
    # usage before quota_since is ignored
    _create(db, 1, 7, limit=6, since="2999-01-01")


def test_closed_report_allows_new_one(env):
    db, _ = env
    first, _ = _create(db, 1)
    report_db.update_report(db, first["id"], status="fixed")
    second, joined = _create(db, 1)
    assert not joined and second["id"] != first["id"]


def test_deliveries_and_auto_attempt(env):
    db, _ = env
    key = item_key("abs", "audiobook", "Book 1", "Author")
    report_db.record_delivery(db, item_key=key, release_id="x", library="abs")
    report_db.record_delivery(db, item_key=key, release_id="y", library="abs")
    assert [d["release_id"] for d in report_db.deliveries_for_key(db, key)] == ["y", "x"]
    r, _ = _create(db, 1)
    assert not report_db.had_auto_attempt(db, key, "wrong_language")
    report_db.update_report(db, r["id"], auto_attempted=1, status="dismissed")
    assert report_db.had_auto_attempt(db, key, "wrong_language")
