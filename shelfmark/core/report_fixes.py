"""Report triage and status transitions (the fixers themselves land in later tasks)."""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from shelfmark.core import report_db
from shelfmark.core.audiobookshelf import abs_client, local_path_for, local_root_for
from shelfmark.core.models import QueueStatus
from shelfmark.core.request_routes import _send_pushover, find_release_candidates
from shelfmark.core.user_db import UserDB

logger = logging.getLogger(__name__)
_request_db = None
_user_db: Optional[UserDB] = None

_PUSH_HEADINGS = {
    "needs_action": "Report Needs Manual Action",
    "awaiting_approval": "Report Fix Ready to Approve",
}
_METADATA_TYPES = ("wrong_cover", "wrong_details")
# report_id -> {"candidates": untried release dicts, "auto_swap": bool}. In memory only:
# a restart loses it, and fail_interrupted_fixes hands those reports to the admin.
_fixes: dict[int, dict] = {}
_fixes_lock = threading.Lock()


def init(request_db, user_db) -> None:
    global _request_db, _user_db
    _request_db, _user_db = request_db, user_db


def set_report_status(report_id: int, status: str, note: Optional[str] = None) -> dict:
    """Move a report to `status`; the single place that decides when the admin gets a push."""
    report = report_db.update_report(_request_db, report_id, status=status, resolution_note=note)
    heading = _PUSH_HEADINGS.get(status)
    if heading:
        problem = report["problem_type"].replace("_", " ")
        _send_pushover(
            {"id": report_id, "title": report["title"], "author": report["author"],
             "content_type": report["content_type"], "user_id": report["created_by"]},
            _user_db, heading, f"{problem}: {note}" if note else problem,
        )
    return report


def _load_book(provider: str, provider_id: str):
    from shelfmark.metadata_providers import get_provider, get_provider_kwargs, is_provider_registered

    if not is_provider_registered(provider):
        return None
    return get_provider(provider, **get_provider_kwargs(provider)).get_book(provider_id)


def _fix_dirs(item_path: str, report_id: int) -> tuple[Path, Path]:
    """(staging, archive) beside the library folder, on the same filesystem, outside every ABS root."""
    parent = local_root_for(item_path).parent
    return parent / ".shelfmark-staging" / str(report_id), parent / ".shelfmark-replaced" / str(report_id)


def _audio_dir(staging: Path) -> Optional[Path]:
    """The folder holding every staged audio file (the common parent), or None without audio."""
    from shelfmark.download.postprocess.policy import get_supported_audiobook_formats

    exts = {f".{e}" for e in get_supported_audiobook_formats()}
    parents = [str(f.parent) for f in staging.rglob("*") if f.is_file() and f.suffix.lower() in exts]
    return Path(os.path.commonpath(parents)) if parents else None


def start_file_fix(request_db, user_db, report_id: int, auto_swap: bool) -> None:
    """Re-download the reported audiobook into staging; on_fix_task_terminal takes it from there."""
    report = report_db.get_report(request_db, report_id)
    item = abs_client.get_item(report["library_item_id"])
    if item.get("isFile"):
        set_report_status(report_id, "needs_action", "Single-file audiobook; replace it by hand")
        return
    provider, provider_id = report["provider"], report["provider_id"]
    if not (provider and provider_id) and report["request_id"]:
        req = request_db.get_request(report["request_id"]) or {}
        provider, provider_id = req.get("provider"), req.get("provider_id")
    book = _load_book(provider, provider_id) if provider and provider_id else None
    if not book:
        set_report_status(report_id, "needs_action", "No book details to search with")
        return

    deliveries = report_db.deliveries_for_key(request_db, report["item_key"])
    excluded = {d["release_id"] for d in deliveries if d["release_id"]}
    candidates, note = find_release_candidates(book, "audiobook", excluded, f"Report #{report_id}")
    if report["problem_type"] == "broken_file" and deliveries:
        # The same source likely serves the same broken rip again.
        candidates.sort(key=lambda c: c.get("source") == deliveries[0]["source"])
    staging, _ = _fix_dirs(item["path"], report_id)
    with _fixes_lock:
        _fixes[report_id] = {"candidates": candidates, "auto_swap": auto_swap, "staging": str(staging)}
    if not _queue_next(report_id):
        set_report_status(report_id, "needs_action", note or "No release could be queued")


def _queue_next(report_id: int) -> bool:
    """Queue the report's next untried candidate; False when none is left."""
    from shelfmark.download import orchestrator as backend

    while True:
        with _fixes_lock:
            state = _fixes.get(report_id)
            if not state or not state["candidates"]:
                _fixes.pop(report_id, None)
                return False
            release = state["candidates"].pop(0)
            staging = Path(state["staging"])
        # Each attempt gets a fresh numbered subfolder, so a failed attempt's leftovers are
        # never verified or swapped in. Numbering skips folders left by earlier attempts.
        attempt = next(staging / str(n) for n in range(1, 10_000) if not (staging / str(n)).exists())
        attempt.mkdir(parents=True)
        ok, error = backend.queue_release(
            release, priority=0, output_args={"destination": str(attempt), "report_id": report_id},
        )
        if ok:
            break
        logger.warning("Report #%s: failed to queue release %s: %s", report_id, release.get("source_id"), error)
    set_report_status(report_id, "fixing")
    report_db.update_report(_request_db, report_id, auto_attempted=1, task_id=release.get("source_id", ""))
    logger.info("Report #%s: re-download queued (task=%s)", report_id, release.get("source_id"))
    return True


def on_fix_task_terminal(task, status) -> None:
    """A fix download ended: try the next release, hand it to the admin, or swap it in."""
    report_id = task.output_args["report_id"]
    try:
        report = report_db.get_report(_request_db, report_id)
        if not report or report["status"] != "fixing" or report["task_id"] != task.task_id:
            return  # superseded or already handled
        if status in (QueueStatus.ERROR, QueueStatus.CANCELLED):
            if not _queue_next(report_id):
                set_report_status(report_id, "needs_action", "The replacement download failed")
            return
        if status != QueueStatus.COMPLETE:
            return
        with _fixes_lock:
            auto_swap = (_fixes.pop(report_id, None) or {}).get("auto_swap", False)
        staged = task.output_args["destination"]
        if _audio_dir(Path(staged)) is None:
            set_report_status(report_id, "needs_action", "The downloaded copy has no audio files")
            return
        # Remember which attempt holds the good copy, for swap_in now or after approval.
        report = report_db.update_report(_request_db, report_id, undo_json=json.dumps({"staged": staged}))
        if auto_swap:
            swap_in(_request_db, report)
        else:
            set_report_status(report_id, "awaiting_approval")
    except Exception as e:
        logger.exception("Report #%s: handling download %s failed", report_id, task.task_id)
        set_report_status(report_id, "needs_action", f"Automatic fix failed: {str(e)[:100]}")


def swap_in(request_db, report: dict) -> None:
    """Archive the library copy and put the staged one at exactly its path. Never deletes.

    The staged copy is the completed attempt's folder recorded in undo_json["staged"].
    """
    report_id = report["id"]
    item = abs_client.get_item(report["library_item_id"])
    if not item:
        set_report_status(report_id, "needs_action", "The library item no longer exists")
        return
    if item.get("isFile"):
        set_report_status(report_id, "needs_action", "Single-file audiobook; replace it by hand")
        return
    old = local_path_for(item.get("path") or "")
    _, archive_dir = _fix_dirs(item["path"], report_id) if old else (None, None)
    staged = Path(json.loads(report.get("undo_json") or "{}").get("staged") or "")
    new = _audio_dir(staged) if staged.is_absolute() and staged.is_dir() else None
    if not old or not old.is_dir() or new is None:
        set_report_status(report_id, "needs_action", "Nothing to swap: library folder or staged copy missing")
        return
    archived = archive_dir / old.name
    if archived.exists():
        set_report_status(report_id, "needs_action", f"{archived} already exists")
        return
    archive_dir.mkdir(parents=True, exist_ok=True)

    # os.replace only renames (same filesystem), so neither move can leave a half-copied folder.
    os.replace(old, archived)
    try:
        os.replace(new, old)
    except Exception as e:
        try:
            os.replace(archived, old)
        except Exception:
            logger.critical("Report #%s: swap AND rollback failed; old copy is at %s", report_id, archived)
            set_report_status(report_id, "needs_action", f"Swap failed ({e}); old copy left at {archived}")
            return
        logger.exception("Report #%s: swap failed, old copy restored", report_id)
        set_report_status(report_id, "needs_action", f"Swap failed, nothing changed: {str(e)[:100]}")
        return

    logger.info("Report #%s: replaced %s (old copy in %s)", report_id, old, archived)
    from shelfmark.download import orchestrator as backend
    from shelfmark.download.clients import base_handler

    task_id = report["task_id"]
    task = backend.book_queue.get_task(task_id) if task_id else None
    try:
        abs_client.scan_libraries()
        report_db.record_delivery(
            request_db, report_id=report_id, source=getattr(task, "source", None),
            release_id=task_id, release_title=getattr(task, "title", None),
            format=getattr(task, "format", None), final_path=str(old), library="abs",
            library_item_id=report["library_item_id"], item_key=report["item_key"],
        )
    except Exception as e:
        logger.warning("Report #%s: swapped, but rescan/delivery record failed: %s", report_id, e)
    report_db.update_report(request_db, report_id, undo_json=json.dumps(
        {"archived": str(archived), "placed": str(old)}))
    set_report_status(report_id, "fixed")

    cleanup = base_handler.deferred_torrent_cleanup.pop(task_id, None) if task_id else None
    if cleanup:
        client, download_id = cleanup
        threading.Thread(
            target=base_handler._scan_abs_then_remove_torrent,
            args=(client, download_id, report["title"], report["author"]),
            daemon=True, name=f"abs-scan-report-{report_id}",
        ).start()


_interrupted_lock = None  # held open for the process lifetime once taken


def fail_interrupted_fixes(request_db) -> None:
    """A restart kills fix downloads and their retry state: hand those reports to the admin."""
    # Like resume_interrupted_requests: only the first process importing main owns this,
    # so a one-off script can't fail the live process's running fixes.
    global _interrupted_lock
    import fcntl
    import tempfile

    lock = open(os.path.join(tempfile.gettempdir(), "shelfmark-interrupted-fixes.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return
    _interrupted_lock = lock
    for report in report_db.list_reports(request_db, statuses=["fixing"]):
        set_report_status(report["id"], "needs_action", "Interrupted by a restart")


def fix_metadata(request_db, report_id: int) -> None:
    # Placeholder until the metadata-fix task replaces it.
    set_report_status(report_id, "needs_action", "Automatic fix not available yet")


def triage(request_db, user_db, report_id: int) -> None:
    try:
        _triage(request_db, user_db, report_id)
    except Exception as e:
        logger.exception("Report %s triage failed", report_id)
        set_report_status(report_id, "needs_action", f"Automatic check failed: {str(e)[:100]}")


def _triage(request_db, user_db, report_id: int) -> None:
    report = report_db.get_report(request_db, report_id)
    if report is None:
        return
    key, problem = report["item_key"], report["problem_type"]
    if report["content_type"] == "ebook":
        set_report_status(report_id, "needs_action", "Ebook fixes aren't automatic yet")
    elif problem == "other":
        set_report_status(report_id, "needs_action")
    elif report_db.had_auto_attempt(request_db, key, problem):
        set_report_status(report_id, "needs_action", "Already tried automatically once")
    elif problem in _METADATA_TYPES:
        if report_db.deliveries_for_key(request_db, key):
            fix_metadata(request_db, report_id)
        else:
            report_db.update_report(
                request_db, report_id,
                undo_json=json.dumps({"action": problem, "item_id": report["library_item_id"]}),
            )
            set_report_status(report_id, "awaiting_approval")
    else:
        item = abs_client.get_item(report["library_item_id"]) if report["library_item_id"] else None
        if not item or local_path_for(item.get("path") or "") is None:
            set_report_status(report_id, "needs_action", "Shelfmark can't replace files in this library")
        else:
            start_file_fix(request_db, user_db, report_id,
                           auto_swap=bool(report_db.deliveries_for_key(request_db, key)))
