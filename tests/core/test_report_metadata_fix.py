"""Cover and details fixes, and undo."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shelfmark.core import report_db, report_fixes
from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path / "users.db")
    users = UserDB(path)
    users.initialize()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO users (id, username, role) VALUES (1, 'reader', 'user')")
    requests = RequestDB(path)
    requests.initialize()
    report_fixes.init(requests, users)
    root = tmp_path / "UnRaid" / "audiobooks"
    folder = root / "Herbert" / "Dune"
    folder.mkdir(parents=True)
    (folder / "cover.jpg").write_bytes(b"oldcover")
    item = {"id": "abs1", "path": "/abs/Herbert/Dune", "media": {
        "coverPath": "/abs/Herbert/Dune/cover.jpg",
        "metadata": {"title": "Dune (wrong)", "authors": [{"id": "a", "name": "Herbert"}]}}}
    ab = report_fixes.abs_client
    with patch.object(ab, "get_item", return_value=item) as get_item, \
         patch.object(ab, "set_cover_url") as set_url, \
         patch.object(ab, "set_cover_path") as set_path, \
         patch.object(ab, "match_item") as match, \
         patch.object(ab, "update_details") as details, \
         patch.object(ab, "scan_libraries", return_value=True), \
         patch.object(report_fixes, "local_path_for", side_effect=lambda p: root / p[len("/abs/"):]), \
         patch.object(report_fixes, "local_root_for", return_value=root), \
         patch.object(report_fixes, "_load_book", return_value=SimpleNamespace(cover_url="http://new")) as load, \
         patch.object(report_fixes, "_send_pushover"):
        yield SimpleNamespace(requests=requests, root=root, folder=folder, get_item=get_item,
                              set_url=set_url, set_path=set_path, match=match, details=details,
                              load=load, tmp=tmp_path)


def _report(env, problem="wrong_cover", **kw):
    fields = {"library": "abs", "library_item_id": "abs1", "content_type": "audiobook",
              "title": "Dune", "author": "Herbert", "problem_type": problem,
              "provider": "hardcover", "provider_id": "42", **kw}
    fields["item_key"] = report_db.item_key("abs", "audiobook", "Dune", "Herbert")
    return report_db.create_or_join_report(
        env.requests, user_id=1, fields=fields, quota_limit=None, quota_since=None)[0]


def _req(env, cover):
    return env.requests.create_request(
        user_id=1, title="Dune", author="Herbert", content_type="audiobook", cover_url=cover,
        provider="hardcover", provider_id="42")["id"]


def test_cover_uses_provider_url_when_different(env):
    r = _report(env, request_id=_req(env, "http://old"))
    report_fixes.fix_metadata(env.requests, r["id"])
    env.set_url.assert_called_once_with("abs1", "http://new")
    env.match.assert_not_called()
    after = report_db.get_report(env.requests, r["id"])
    assert (after["status"], after["resolution_note"], after["auto_attempted"]) == ("fixed", "Cover updated", 1)
    undo = json.loads(after["undo_json"])
    assert (env.tmp / "UnRaid" / ".shelfmark-replaced" / str(r["id"]) / "cover.jpg").read_bytes() == b"oldcover"
    assert undo["cover_backup"] and undo["title"] == "Dune (wrong)" and undo["author"] == "Herbert"
    assert (env.folder / "cover.jpg").exists()  # copied, not moved


def test_cover_rematches_when_same_image(env):
    r = _report(env, request_id=_req(env, "http://new"))
    report_fixes.fix_metadata(env.requests, r["id"])
    env.match.assert_called_once_with("abs1", "Dune", "Herbert")
    env.set_url.assert_not_called()


def test_cover_without_request_uses_provider_cover(env):
    r = _report(env)
    report_fixes.fix_metadata(env.requests, r["id"])
    env.set_url.assert_called_once_with("abs1", "http://new")


def test_cover_without_provider_ids_rematches(env):
    r = _report(env, provider=None, provider_id=None)
    report_fixes.fix_metadata(env.requests, r["id"])
    env.match.assert_called_once()


def test_details_rematch_saves_undo_first(env):
    r = _report(env, "wrong_details")
    seen = {}
    env.match.side_effect = lambda *a: seen.update(undo=report_db.get_report(env.requests, r["id"])["undo_json"])
    report_fixes.fix_metadata(env.requests, r["id"])
    assert json.loads(seen["undo"])["title"] == "Dune (wrong)"
    after = report_db.get_report(env.requests, r["id"])
    assert (after["status"], after["resolution_note"]) == ("fixed", "Details updated")


def test_missing_abs_item_goes_to_admin(env):
    env.get_item.return_value = None
    r = _report(env)
    report_fixes.fix_metadata(env.requests, r["id"])
    after = report_db.get_report(env.requests, r["id"])
    assert (after["status"], after["resolution_note"]) == ("needs_action", "No longer in Audiobookshelf")


def test_abs_write_failure_goes_to_admin(env):
    env.set_url.side_effect = RuntimeError("boom")
    r = _report(env)
    report_fixes.fix_metadata(env.requests, r["id"])
    assert report_db.get_report(env.requests, r["id"])["status"] == "needs_action"


def test_undo_cover_restores_file_and_details(env):
    r = _report(env)
    report_fixes.fix_metadata(env.requests, r["id"])
    (env.folder / "cover.jpg").write_bytes(b"newcover")
    report_fixes.undo(env.requests, r["id"])
    assert (env.folder / "cover.jpg").read_bytes() == b"oldcover"
    env.set_path.assert_called_once_with("abs1", "/abs/Herbert/Dune/cover.jpg")
    env.details.assert_called_once_with("abs1", "Dune (wrong)", "Herbert")
    after = report_db.get_report(env.requests, r["id"])
    assert (after["status"], after["resolution_note"]) == ("needs_action", "Undone by admin")


def test_undo_cover_without_backup_says_so(env):
    (env.folder / "cover.jpg").unlink()
    r = _report(env)
    report_fixes.fix_metadata(env.requests, r["id"])
    report_fixes.undo(env.requests, r["id"])
    env.set_path.assert_not_called()
    note = report_db.get_report(env.requests, r["id"])["resolution_note"]
    assert "old cover could not be kept" in note


def test_undo_file_fix_swaps_back_without_deleting(env):
    archive = env.tmp / "UnRaid" / ".shelfmark-replaced" / "9"
    (archive / "Dune").mkdir(parents=True)
    (archive / "Dune" / "old.m4b").write_bytes(b"old")
    (env.folder / "new.m4b").write_bytes(b"new")
    r = _report(env, "broken_file")
    report_db.update_report(env.requests, r["id"], undo_json=json.dumps(
        {"archived": str(archive / "Dune"), "placed": str(env.folder)}))
    report_fixes.undo(env.requests, r["id"])
    assert (env.folder / "old.m4b").read_bytes() == b"old"
    assert (archive / "undo-1" / "Dune" / "new.m4b").read_bytes() == b"new"
    assert report_db.get_report(env.requests, r["id"])["resolution_note"] == "Undone by admin"


def _file_fix_report(env):
    archive = env.tmp / "UnRaid" / ".shelfmark-replaced" / "9"
    (archive / "Dune").mkdir(parents=True)
    (archive / "Dune" / "old.m4b").write_bytes(b"old")
    (env.folder / "new.m4b").write_bytes(b"new")
    r = _report(env, "broken_file")
    report_db.update_report(env.requests, r["id"], undo_json=json.dumps(
        {"archived": str(archive / "Dune"), "placed": str(env.folder)}))
    return r, archive


def _assert_refused(env, r, archive):
    after = report_db.get_report(env.requests, r["id"])
    assert after["status"] == "needs_action"
    assert not list(archive.glob("undo-*"))
    return after


def test_undo_archived_missing_moves_nothing(env):
    r, archive = _file_fix_report(env)
    (archive / "Dune" / "old.m4b").unlink()
    (archive / "Dune").rmdir()
    report_fixes.undo(env.requests, r["id"])
    assert (env.folder / "new.m4b").exists()
    assert "archived copy missing" in _assert_refused(env, r, archive)["resolution_note"]


def test_undo_placed_missing_moves_nothing(env):
    r, archive = _file_fix_report(env)
    (env.folder / "new.m4b").unlink()
    (env.folder / "cover.jpg").unlink()
    env.folder.rmdir()
    report_fixes.undo(env.requests, r["id"])
    assert (archive / "Dune" / "old.m4b").exists()
    assert "library folder missing" in _assert_refused(env, r, archive)["resolution_note"]


def test_repeat_undo_is_refused(env):
    r, archive = _file_fix_report(env)
    report_fixes.undo(env.requests, r["id"])
    report_fixes.undo(env.requests, r["id"])
    assert (env.folder / "old.m4b").read_bytes() == b"old"
    assert sorted(p.name for p in archive.glob("undo-*")) == ["undo-1"]
    assert report_db.get_report(env.requests, r["id"])["resolution_note"] == "Nothing to undo"


def test_undo_rescan_failure_is_not_undo_failure(env):
    r, archive = _file_fix_report(env)
    report_fixes.abs_client.scan_libraries.side_effect = RuntimeError("down")
    report_fixes.undo(env.requests, r["id"])
    assert (env.folder / "old.m4b").exists()
    assert report_db.get_report(env.requests, r["id"])["resolution_note"] == "Undone; library rescan failed"


def test_fix_metadata_from_awaiting_approval(env):
    r = _report(env, "wrong_details")
    report_db.update_report(env.requests, r["id"], status="awaiting_approval",
                            undo_json=json.dumps({"action": "wrong_details", "item_id": "abs1"}))
    report_fixes.fix_metadata(env.requests, r["id"])
    assert report_db.get_report(env.requests, r["id"])["status"] == "fixed"
