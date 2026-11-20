"""Report API and triage."""
import json
import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask

from shelfmark.core import report_db, report_fixes
from shelfmark.core.report_routes import register_report_routes
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
            [(1, "reader", "user"), (2, "other", "user")],
        )
    requests = RequestDB(path)
    requests.initialize()
    report_fixes.init(requests, users)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="t")
    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
        register_report_routes(app, requests, users)
    return app, requests, users


def _post(app, body, uid=1, item=None):
    item = {} if item is False else item or {"id": body.get("library_item_id"), "title": body["title"], "author": body["author"]}
    with app.test_client() as c, \
         patch("shelfmark.core.report_routes.abs_client.get_cached_item", return_value=item or None):
        with c.session_transaction() as s:
            s.update(user_id=f"u{uid}", db_user_id=uid, is_admin=False)
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.report_routes.report_fixes.triage") as triage, \
             patch("shelfmark.core.report_routes._send_pushover") as push:
            resp = c.post("/api/reports", json=body)
    return resp, triage, push


def _body(**kw):
    return {"content_type": "audiobook", "title": "Dune", "author": "Herbert",
            "problem_type": "broken_file", "library_item_id": "abs1", **kw}


def _report(requests, **kw):
    fields = {"library": "abs", "library_item_id": "abs1", "content_type": "audiobook",
              "title": "Dune", "author": "Herbert", "problem_type": "broken_file", **kw}
    fields["item_key"] = report_db.item_key(fields["library"], fields["content_type"], "Dune", "Herbert")
    return report_db.create_or_join_report(requests, user_id=1, fields=fields, quota_limit=None, quota_since=None)[0]


def test_report_create_and_join(env):
    app, requests, _ = env
    resp, triage, _ = _post(app, _body())
    assert resp.status_code == 201 and resp.json["joined"] is False
    assert resp.json["quota"]["used"] == 1
    triage.assert_called_once()
    resp2, triage2, _ = _post(app, _body(), uid=2)
    assert resp2.json["joined"] is True and resp2.json["report"]["id"] == resp.json["report"]["id"]
    triage2.assert_not_called()
    with app.test_client() as c:
        with c.session_transaction() as s:
            s.update(user_id="u2", db_user_id=2, is_admin=False)
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            mine = c.get("/api/reports").json
    assert [r["status"] for r in mine] == ["open"]


def test_report_429_at_limit_with_quota(env):
    app, _, users = env
    users.update_user(1, weekly_report_limit=1)
    assert _post(app, _body())[0].status_code == 201
    resp, _, _ = _post(app, _body(title="Other"))
    assert resp.status_code == 429 and resp.json["quota"]["remaining"] == 0


def test_no_push_on_create(env):
    app, _, users = env
    users.update_user(1, weekly_report_limit=5)
    _, _, push = _post(app, _body())
    push.assert_not_called()
    users.update_user(1, weekly_report_limit=2)
    _, _, push = _post(app, _body(title="Last"))
    assert push.call_args[0][2] == "Weekly Report Limit Reached"


def test_other_requires_note(env):
    app, _, _ = env
    assert _post(app, _body(problem_type="other"))[0].status_code == 400
    assert _post(app, _body(problem_type="bogus"))[0].status_code == 400
    assert _post(app, _body(problem_type="other", note="hum"))[0].status_code == 201


def test_cannot_report_someone_elses_request_id(env):
    app, requests, _ = env
    with patch.object(requests, "get_request", return_value={"id": 5, "user_id": 2}):
        assert _post(app, _body(request_id=5))[0].status_code == 404
        assert _post(app, _body(request_id=5), uid=2)[0].status_code == 201


def _triage(env, **kw):
    _, requests, users = env
    rep = _report(requests, **kw)
    with patch("shelfmark.core.report_fixes._send_pushover") as push, \
         patch("shelfmark.core.report_fixes.start_file_fix") as sff, \
         patch("shelfmark.core.report_fixes.fix_metadata") as fm:
        report_fixes.triage(requests, users, rep["id"])
    return report_db.get_report(requests, rep["id"]), push, sff, fm


def test_ebook_report_goes_to_needs_action_with_push(env):
    rep, push, sff, _ = _triage(env, library="calibre", content_type="ebook")
    assert rep["status"] == "needs_action" and "Ebook" in rep["resolution_note"]
    assert push.call_args[0][2] == "Report Needs Manual Action"
    sff.assert_not_called()


def test_unmapped_abs_path_goes_to_admin(env):
    with patch("shelfmark.core.report_fixes.abs_client.get_item", return_value={"path": "/x/y"}), \
         patch("shelfmark.core.report_fixes.local_path_for", return_value=None):
        rep, push, sff, _ = _triage(env)
    assert rep["status"] == "needs_action" and "can't replace" in rep["resolution_note"]
    sff.assert_not_called()


def test_mapped_abs_path_starts_file_fix(env):
    _, requests, _ = env
    report_db.record_delivery(requests, source="x", item_key=report_db.item_key("abs", "audiobook", "Dune", "Herbert"))
    with patch("shelfmark.core.report_fixes.abs_client.get_item", return_value={"path": "/a/b"}), \
         patch("shelfmark.core.report_fixes.local_path_for", return_value="/l/b"):
        rep, push, sff, _ = _triage(env)
    assert sff.call_args.kwargs["auto_swap"] is True and rep["status"] == "open"


def test_second_auto_attempt_goes_to_admin(env):
    _, requests, _ = env
    prior = _report(requests)
    report_db.update_report(requests, prior["id"], auto_attempted=1, status="fixed")
    rep, push, sff, _ = _triage(env)
    assert rep["status"] == "needs_action" and "once" in rep["resolution_note"]


def test_not_delivered_cover_waits_for_approval(env):
    rep, push, _, fm = _triage(env, problem_type="wrong_cover")
    assert rep["status"] == "awaiting_approval"
    assert json.loads(rep["undo_json"]) == {"action": "wrong_cover", "item_id": "abs1"}
    assert push.call_args[0][2] == "Report Fix Ready to Approve"
    fm.assert_not_called()


def test_item_id_binds_title_and_author_server_side(env):
    app, requests, _ = env
    report_db.record_delivery(requests, source="x", item_key=report_db.item_key("abs", "audiobook", "Dune", "Herbert"))
    other = {"id": "abs2", "title": "Emma", "author": "Austen"}
    with patch("shelfmark.core.report_routes.abs_client.get_cached_item", return_value=other):
        resp, _, _ = _post(app, _body(library_item_id="abs2"), item=other)
    rep = resp.json["report"]
    assert (rep["title"], rep["item_key"]) == ("Emma", report_db.item_key("abs", "audiobook", "Emma", "Austen"))
    with patch("shelfmark.core.report_fixes.abs_client.get_item", return_value={"path": "/a/b"}), \
         patch("shelfmark.core.report_fixes.local_path_for", return_value="/l/b"), \
         patch("shelfmark.core.report_fixes._send_pushover"), \
         patch("shelfmark.core.report_fixes.start_file_fix") as sff:
        report_fixes.triage(requests, env[2], rep["id"])
    assert sff.call_args.kwargs["auto_swap"] is False


def test_unknown_item_id_is_400(env):
    app, _, _ = env
    resp, _, _ = _post(app, _body(library_item_id="gone"), item=False)
    assert resp.status_code == 400 and "no longer" in resp.json["error"]


def test_field_validation(env):
    app, _, _ = env
    assert _post(app, _body(note="x" * 1001))[0].status_code == 400
    assert _post(app, _body(title="t" * 301))[0].status_code == 400
    assert _post(app, _body(library_item_id=5))[0].status_code == 400
    assert _post(app, _body(request_id="5"))[0].status_code == 400


def test_triage_exception_goes_to_needs_action(env):
    _, requests, users = env
    rep = _report(requests)
    with patch("shelfmark.core.report_fixes.abs_client.get_item", side_effect=RuntimeError("boom")), \
         patch("shelfmark.core.report_fixes._send_pushover") as push:
        report_fixes.triage(requests, users, rep["id"])
    got = report_db.get_report(requests, rep["id"])
    assert got["status"] == "needs_action" and got["resolution_note"] == "Automatic check failed: boom"
    push.assert_called_once()
