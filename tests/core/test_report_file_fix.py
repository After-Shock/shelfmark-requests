"""File fix: re-download a broken audiobook into staging, then swap it into the library."""
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shelfmark.core import report_db, report_fixes
from shelfmark.core.models import QueueStatus
from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB
import shelfmark.release_sources  # noqa: F401  (loads before base_handler: import cycle)
from shelfmark.download.clients import base_handler
from tests.core.test_terminal_request_sync import main_module  # noqa: F401  (fixture)

BOOK = SimpleNamespace(title="Dune", authors=["Herbert"])


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
    old = root / "Herbert" / "Dune"
    old.mkdir(parents=True)
    (old / "old.m4b").write_bytes(b"old")
    item = {"id": "abs1", "path": "/abs/Herbert/Dune", "isFile": False}
    queued = []

    def queue_release(release, **kw):
        queued.append((release, kw))
        return True, None

    with patch.object(report_fixes.abs_client, "get_item", return_value=item), \
         patch.object(report_fixes.abs_client, "scan_libraries", return_value=True) as scan, \
         patch.object(report_fixes, "local_path_for", return_value=old), \
         patch.object(report_fixes, "local_root_for", return_value=root), \
         patch.object(report_fixes, "_load_book", return_value=BOOK), \
         patch("shelfmark.download.orchestrator.queue_release", side_effect=queue_release), \
         patch.object(report_fixes, "_send_pushover") as push:
        yield SimpleNamespace(requests=requests, users=users, root=root, old=old, item=item,
                              queued=queued, scan=scan, push=push, tmp=tmp_path)
    report_fixes._fixes.clear()
    base_handler.deferred_torrent_cleanup.clear()


def _report(env, **kw):
    fields = {"library": "abs", "library_item_id": "abs1", "content_type": "audiobook",
              "title": "Dune", "author": "Herbert", "problem_type": "broken_file",
              "provider": "hardcover", "provider_id": "42", **kw}
    fields["item_key"] = report_db.item_key("abs", "audiobook", "Dune", "Herbert")
    return report_db.create_or_join_report(
        env.requests, user_id=1, fields=fields, quota_limit=None, quota_since=None)[0]


def _deliver(env, release_id, source):
    report_db.record_delivery(env.requests, release_id=release_id, source=source, library="abs",
                              item_key=report_db.item_key("abs", "audiobook", "Dune", "Herbert"))


def _rel(source_id, source="prowlarr"):
    return {"source_id": source_id, "source": source, "title": "Dune", "series_pack": False}


def _start(env, report, candidates, auto_swap=True):
    with patch.object(report_fixes, "find_release_candidates",
                      return_value=(candidates, None if candidates else "Nothing found")) as find:
        report_fixes.start_file_fix(env.requests, env.users, report["id"], auto_swap=auto_swap)
    return find


def _staging(env, report_id, attempt=1):
    return env.root.parent / ".shelfmark-staging" / str(report_id) / str(attempt)


def _task(env, report_id, task_id="r1", source="prowlarr", attempt=1):
    return SimpleNamespace(
        task_id=task_id, source=source, title="Dune", author="Herbert", format="m4b",
        output_args={"destination": str(_staging(env, report_id, attempt)), "report_id": report_id},
    )


def _stage(env, report_id, files=("Dune.m4b",), attempt=1):
    book_dir = _staging(env, report_id, attempt) / "Herbert" / "Dune (2020)"
    book_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        (book_dir / f).write_bytes(b"new")
    return book_dir


def _status(env, report_id):
    return report_db.get_report(env.requests, report_id)


def test_fix_excludes_delivered_release(env):
    _deliver(env, "r0", "prowlarr")
    report = _report(env)
    find = _start(env, report, [_rel("r1")])
    assert find.call_args.args[2] == {"r0"}
    release, kw = env.queued[0]
    assert release["source_id"] == "r1"
    assert kw["output_args"] == {"destination": str(_staging(env, report["id"])), "report_id": report["id"]}
    row = _status(env, report["id"])
    assert (row["status"], row["auto_attempted"], row["task_id"]) == ("fixing", 1, "r1")


def test_broken_file_prefers_other_source(env):
    _deliver(env, "r0", "prowlarr")
    report = _report(env)
    _start(env, report, [_rel("a", "prowlarr"), _rel("b", "audiobookbay"), _rel("c", "prowlarr")])
    assert env.queued[0][0]["source_id"] == "b"
    # A failed download moves on to the next candidate, keeping the stable order.
    report_fixes.on_fix_task_terminal(_task(env, report["id"], "b"), QueueStatus.ERROR)
    assert env.queued[1][0]["source_id"] == "a"
    assert env.queued[1][1]["output_args"]["destination"] == str(_staging(env, report["id"], 2))
    assert _status(env, report["id"])["task_id"] == "a"


def test_no_candidates_goes_to_admin(env):
    report = _report(env)
    _start(env, report, [])
    row = _status(env, report["id"])
    assert (row["status"], row["resolution_note"]) == ("needs_action", "Nothing found")
    assert env.queued == []
    env.push.assert_called_once()


def test_no_book_details_goes_to_admin(env):
    report = _report(env, provider=None, provider_id=None)
    _start(env, report, [_rel("r1")])
    row = _status(env, report["id"])
    assert (row["status"], row["resolution_note"]) == ("needs_action", "No book details to search with")


def test_single_file_item_is_never_swapped(env):
    env.item["isFile"] = True
    report = _report(env)
    _start(env, report, [_rel("r1")])
    row = _status(env, report["id"])
    assert (row["status"], row["resolution_note"]) == (
        "needs_action", "Single-file audiobook; replace it by hand")
    assert env.queued == []


def test_complete_swaps_and_archives(env):
    _deliver(env, "r0", "prowlarr")
    report = _report(env)
    _start(env, report, [_rel("r1", "audiobookbay")])
    _stage(env, report["id"])
    task = _task(env, report["id"], source="audiobookbay")
    with patch("shelfmark.download.orchestrator.book_queue.get_task", return_value=task):
        report_fixes.on_fix_task_terminal(task, QueueStatus.COMPLETE)

    archived = env.root.parent / ".shelfmark-replaced" / str(report["id"]) / "Dune"
    assert (archived / "old.m4b").read_bytes() == b"old"
    assert (env.old / "Dune.m4b").read_bytes() == b"new" and not (env.old / "old.m4b").exists()
    row = _status(env, report["id"])
    assert row["status"] == "fixed"
    assert json.loads(row["undo_json"]) == {"archived": str(archived), "placed": str(env.old)}
    env.scan.assert_called_once()
    latest = report_db.deliveries_for_key(env.requests, report["item_key"])[0]
    assert (latest["report_id"], latest["release_id"], latest["source"]) == (report["id"], "r1", "audiobookbay")


def test_staged_copy_without_audio_is_not_swapped(env):
    report = _report(env)
    _start(env, report, [_rel("r1")])
    staged = _stage(env, report["id"], files=("cover.jpg",))
    report_fixes.on_fix_task_terminal(_task(env, report["id"]), QueueStatus.COMPLETE)
    assert _status(env, report["id"])["status"] == "needs_action"
    assert (env.old / "old.m4b").exists() and (staged / "cover.jpg").exists()


def test_swap_rolls_back_when_new_move_fails(env):
    report = _report(env)
    _start(env, report, [_rel("r1")])
    staged = _stage(env, report["id"])
    real_replace = os.replace
    calls = []

    def replace(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("disk full")
        real_replace(src, dst)

    with patch.object(report_fixes.os, "replace", side_effect=replace):
        report_fixes.on_fix_task_terminal(_task(env, report["id"]), QueueStatus.COMPLETE)
    assert (env.old / "old.m4b").read_bytes() == b"old"
    assert (staged / "Dune.m4b").exists()
    row = _status(env, report["id"])
    assert row["status"] == "needs_action" and "disk full" in row["resolution_note"]


def test_not_delivered_waits_for_approval_with_staged_copy(env):
    report = _report(env)
    _start(env, report, [_rel("r1")], auto_swap=False)
    staged = _stage(env, report["id"])
    report_fixes.on_fix_task_terminal(_task(env, report["id"]), QueueStatus.COMPLETE)
    assert _status(env, report["id"])["status"] == "awaiting_approval"
    assert (staged / "Dune.m4b").exists() and (env.old / "old.m4b").exists()
    env.scan.assert_not_called()


def test_torrent_removed_only_after_swap(env):
    report = _report(env)
    _start(env, report, [_rel("r1")])
    handler = MagicMock(spec=base_handler.ExternalClientHandler)
    handler._cleanup_refs = {"r1": ("client", "dl1", "torrent")}
    task = SimpleNamespace(task_id="r1", content_type="audiobook", title="Dune", author="Herbert",
                           output_args={"report_id": report["id"]})
    with patch.object(base_handler.threading, "Thread") as thread:
        base_handler.ExternalClientHandler.post_process_cleanup(handler, task, success=True)
        thread.assert_not_called()
        assert base_handler.deferred_torrent_cleanup["r1"] == ("client", "dl1")

        _stage(env, report["id"])
        with patch.object(report_fixes.threading, "Thread") as fix_thread:
            report_fixes.on_fix_task_terminal(_task(env, report["id"]), QueueStatus.COMPLETE)
    assert _status(env, report["id"])["status"] == "fixed"
    kwargs = fix_thread.call_args.kwargs
    assert kwargs["target"] is base_handler._scan_abs_then_remove_torrent
    assert kwargs["args"] == ("client", "dl1", "Dune", "Herbert")
    assert "r1" not in base_handler.deferred_torrent_cleanup


def test_interrupted_fix_moves_to_needs_action(env):
    report = _report(env)
    _start(env, report, [_rel("r1")])
    with patch.object(report_fixes, "_interrupted_lock", None), \
         patch("tempfile.gettempdir", return_value=str(env.tmp)):
        report_fixes.fail_interrupted_fixes(env.requests)
    row = _status(env, report["id"])
    assert (row["status"], row["resolution_note"]) == ("needs_action", "Interrupted by a restart")


def test_fix_creates_no_request_rows_and_no_discord(env, main_module):  # noqa: F811
    report = _report(env)
    _start(env, report, [_rel("r1")])
    task = _task(env, report["id"])
    with patch.object(main_module, "_sync_request_db_on_terminal") as sync, \
         patch.object(main_module, "_notify_admin_for_terminal_download_status") as notify, \
         patch.object(report_fixes, "on_fix_task_terminal") as on_fix, \
         patch("shelfmark.core.discord_notifications.send_discord_book_available") as discord:
        main_module._on_download_terminal("r1", QueueStatus.COMPLETE, task)
    on_fix.assert_called_once_with(task, QueueStatus.COMPLETE)
    sync.assert_not_called()
    notify.assert_not_called()
    discord.assert_not_called()
    with sqlite3.connect(env.tmp / "users.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def test_failed_attempt_leftovers_never_reach_the_library(env):
    report = _report(env)
    _start(env, report, [_rel("r1"), _rel("r2")])
    leftover = _stage(env, report["id"], files=("partial.mp3",), attempt=1)
    report_fixes.on_fix_task_terminal(_task(env, report["id"], "r1"), QueueStatus.ERROR)
    _stage(env, report["id"], files=("Dune.m4b",), attempt=2)
    report_fixes.on_fix_task_terminal(_task(env, report["id"], "r2", attempt=2), QueueStatus.COMPLETE)

    assert _status(env, report["id"])["status"] == "fixed"
    assert sorted(p.name for p in env.old.iterdir()) == ["Dune.m4b"]
    assert (leftover / "partial.mp3").exists()
