"""Admin report actions, views and limits."""
import json
import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask

from shelfmark.core import report_db, report_fixes, report_routes
from shelfmark.core.admin_routes import register_admin_routes
from shelfmark.core.report_routes import register_report_routes
from shelfmark.core.request_db import RequestDB
from shelfmark.core.request_routes import register_request_routes
from shelfmark.core.user_db import UserDB


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "users.db")
    users = UserDB(path)
    users.initialize()
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
                         [(1, "reader", "user"), (2, "other", "user"), (3, "boss", "admin")])
    requests = RequestDB(path)
    requests.initialize()
    report_fixes.init(requests, users)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="t")
    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
         patch("shelfmark.core.admin_routes._get_auth_mode", return_value="builtin"), \
         patch.object(report_routes, "_spawn", lambda fn, *a: fn(*a)), \
         patch.object(report_fixes, "_send_pushover"):
        register_report_routes(app, requests, users)
        register_admin_routes(app, users, requests)
        register_request_routes(app, requests, users)
        yield app, requests, users


def _client(app, uid, admin):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(user_id=f"u{uid}", db_user_id=uid, is_admin=admin)
    return c


def _report(requests, status="awaiting_approval", **kw):
    extra = {k: kw.pop(k) for k in ("undo_json",) if k in kw}
    fields = {"library": "abs", "library_item_id": "abs1", "content_type": "audiobook",
              "title": "Dune", "author": "Herbert", "problem_type": "broken_file", **kw}
    fields["item_key"] = report_db.item_key("abs", "audiobook", fields["title"], "Herbert")
    r = report_db.create_or_join_report(requests, user_id=1, fields=fields, quota_limit=None, quota_since=None)[0]
    return report_db.update_report(requests, r["id"], status=status, **extra)


def test_non_admin_forbidden(env):
    app, requests, _ = env
    r = _report(requests)
    c = _client(app, 1, False)
    assert c.get("/api/admin/reports").status_code == 403
    for action in ("approve", "dismiss", "undo", "retry"):
        assert c.post(f"/api/admin/reports/{r['id']}/{action}").status_code == 403
    assert c.post("/api/admin/report-limits/reset", json={}).status_code == 403


def test_list_reports_default_and_filter(env):
    app, requests, users = env
    _report(requests)
    c = _client(app, 3, True)
    rows = c.get("/api/admin/reports").json
    assert [(r["reporter"], r["joined_count"]) for r in rows] == [("reader", 0)]
    report_db.create_or_join_report(requests, user_id=2, fields={"item_key": rows[0]["item_key"]},
                                    quota_limit=None, quota_since=None)
    assert c.get("/api/admin/reports").json[0]["joined_count"] == 1
    assert c.get("/api/admin/reports?status=fixed").json == []


def test_approve_swaps_staged_copy(env):
    app, requests, _ = env
    r = _report(requests, undo_json=json.dumps({"staged": "/x"}))
    c = _client(app, 3, True)
    with patch.object(report_fixes, "swap_in") as swap:
        resp = c.post(f"/api/admin/reports/{r['id']}/approve")
    assert resp.status_code == 202 and resp.json["report"]["status"] == "fixing"
    swap.assert_called_once()
    assert swap.call_args.args[1]["id"] == r["id"]
    assert c.post(f"/api/admin/reports/{r['id']}/approve").status_code == 409  # no longer awaiting


def test_approve_metadata_applies_prepared_change(env):
    app, requests, _ = env
    r = _report(requests, problem_type="wrong_cover")
    with patch.object(report_fixes, "fix_metadata") as fix:
        _client(app, 3, True).post(f"/api/admin/reports/{r['id']}/approve")
    fix.assert_called_once_with(requests, r["id"])


def test_dismiss_keeps_slot_used_and_archives_staging(env, tmp_path):
    app, requests, users = env
    staged = tmp_path / "UnRaid" / ".shelfmark-staging" / "1" / "1"
    staged.mkdir(parents=True)
    (staged / "a.m4b").write_bytes(b"new")
    r = _report(requests, undo_json=json.dumps({"staged": str(staged)}))
    archive = tmp_path / "UnRaid" / ".shelfmark-replaced" / str(r["id"])
    with patch.object(report_routes.abs_client, "get_item", return_value={"path": "/abs/x"}), \
         patch.object(report_fixes, "_fix_dirs", return_value=(None, archive)):
        resp = _client(app, 3, True).post(f"/api/admin/reports/{r['id']}/dismiss", json={"note": "not a bug"})
    assert resp.status_code == 202
    done = report_db.get_report(requests, r["id"])
    assert done["status"] == "dismissed" and done["resolution_note"] == "not a bug"
    assert (archive / "dismissed-staging" / "a.m4b").read_bytes() == b"new" and not staged.exists()
    assert report_db.count_report_usage(requests, 1, "") == 1  # no refund


def test_dismiss_default_note_and_wrong_state(env):
    app, requests, _ = env
    r = _report(requests, status="needs_action")
    c = _client(app, 3, True)
    c.post(f"/api/admin/reports/{r['id']}/dismiss")
    assert report_db.get_report(requests, r["id"])["resolution_note"] == "Dismissed by admin"
    assert c.post(f"/api/admin/reports/{r['id']}/dismiss").status_code == 409


def test_undo_restores_archived_copy(env):
    app, requests, _ = env
    r = _report(requests, status="fixed")
    c = _client(app, 3, True)
    with patch.object(report_fixes, "undo") as undo:
        assert c.post(f"/api/admin/reports/{r['id']}/undo").status_code == 202
    undo.assert_called_once_with(requests, r["id"])
    assert c.post("/api/admin/reports/999/undo").status_code == 404


def test_retry_only_needs_action_file_reports(env):
    app, requests, _ = env
    r = _report(requests, status="needs_action")
    c = _client(app, 3, True)
    with patch.object(report_fixes, "start_file_fix") as fix:
        assert c.post(f"/api/admin/reports/{r['id']}/retry").status_code == 202
    fix.assert_called_once_with(requests, env[2], r["id"], auto_swap=True)
    cover = _report(requests, status="needs_action", problem_type="wrong_cover", title="Other")
    assert c.post(f"/api/admin/reports/{cover['id']}/retry").status_code == 409


def test_counts_for_admin_and_user(env):
    app, requests, _ = env
    _report(requests, status="needs_action")
    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
        assert _client(app, 3, True).get("/api/requests/counts").json["reports_needing_action"] == 1
        user_counts = _client(app, 1, False).get("/api/requests/counts").json
    assert "reports_needing_action" not in user_counts and user_counts["report_quota"]["limit"] == 6


def test_report_limit_routes_mirror_request_limits(env):
    app, requests, users = env
    c = _client(app, 3, True)
    assert c.put("/api/admin/users/1", json={"weekly_report_limit": 9}).json["report_quota"]["limit"] == 9
    for bad in (-1, 101, "lots", 2.5, True):
        assert c.put("/api/admin/users/1", json={"weekly_report_limit": bad}).status_code == 400
    cleared = c.put("/api/admin/users/1", json={"weekly_report_limit": None}).json
    assert cleared["weekly_report_limit"] is None and cleared["report_quota"]["is_default"] is True
    with patch("shelfmark.core.admin_routes.update_settings", return_value={"success": True}) as upd:
        assert c.put("/api/admin/report-limits", json={"default": 4}).status_code == 200
        upd.assert_called_once_with("users", {"WEEKLY_REPORT_LIMIT": 4})
        assert c.put("/api/admin/report-limits", json={"default": 500}).status_code == 400
    assert "default" in c.get("/api/admin/report-limits").json
    assert c.post("/api/admin/report-limits/reset", json={"user_id": 1}).status_code == 200
    assert users.get_user(user_id=1)["report_limit_reset_at"] is not None
    assert users.get_user(user_id=2)["report_limit_reset_at"] is None
    assert c.post("/api/admin/report-limits/reset", json={"user_id": 99}).status_code == 404
    assert c.post("/api/admin/report-limits/reset", json={}).status_code == 200
    assert users.get_user(user_id=2)["report_limit_reset_at"] is not None
