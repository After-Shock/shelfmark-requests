"""Weekly report limit: same week/reset rules as requests, own counter."""

import sqlite3
from unittest.mock import patch

import pytest

from shelfmark.core import report_db, request_quota
from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB


@pytest.fixture
def dbs(tmp_path):
    path = str(tmp_path / "users.db")
    users = UserDB(path)
    users.initialize()
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
            [(1, "reader", "user"), (9, "boss", "admin")],
        )
    requests = RequestDB(path)
    requests.initialize()
    return requests, users


def _report(requests, users, title):
    user = users.get_user(user_id=1)
    return report_db.create_or_join_report(
        requests, user_id=1,
        fields={"library": "calibre", "content_type": "ebook", "title": title, "author": "A",
                "problem_type": "broken_file", "item_key": report_db.item_key("calibre", "ebook", title, "A")},
        quota_limit=6, quota_since=request_quota.counting_since(user, kind="report"),
    )


def test_report_quota_default_six(dbs):
    requests, users = dbs
    q = request_quota.report_quota_for(requests, users.get_user(user_id=1))
    assert (q["limit"], q["used"], q["remaining"], q["is_default"]) == (6, 0, 6, True)
    _report(requests, users, "Dune")
    assert request_quota.report_quota_for(requests, users.get_user(user_id=1))["used"] == 1


def test_report_quota_admin_unlimited(dbs):
    requests, users = dbs
    assert request_quota.report_quota_for(requests, users.get_user(user_id=9)) is None


def test_report_reset_restarts_count(dbs):
    requests, users = dbs
    _report(requests, users, "Dune")
    users.update_user(1, weekly_report_limit=3)
    assert request_quota.report_quota_for(requests, users.get_user(user_id=1))["limit"] == 3
    with sqlite3.connect(users._db_path) as conn:  # created_at must be strictly before reset
        conn.execute("UPDATE report_quota_usage SET created_at = '2000-01-01 00:00:00'")
    users.reset_report_limits(1)
    assert request_quota.report_quota_for(requests, users.get_user(user_id=1))["used"] == 0


def test_request_quota_unchanged(dbs):
    requests, users = dbs
    user = users.get_user(user_id=1)
    assert request_quota.limit_for(user) == 6
    assert request_quota.quota_for(requests, user)["used"] == 0
    with patch.object(request_quota.config, "get", return_value=4):
        assert request_quota.limit_for(user) == 4
    users.reset_request_limits(1)
    assert request_quota.counting_since(users.get_user(user_id=1)) >= request_quota.counting_since(user)
    assert request_quota.limit_for(users.get_user(user_id=9)) is None
