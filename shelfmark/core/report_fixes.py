"""Report triage and status transitions (the fixers themselves land in later tasks)."""

import json
import logging
from typing import Optional

from shelfmark.core import report_db
from shelfmark.core.audiobookshelf import abs_client, local_path_for
from shelfmark.core.request_routes import _send_pushover
from shelfmark.core.user_db import UserDB

logger = logging.getLogger(__name__)
_request_db = None
_user_db: Optional[UserDB] = None

_PUSH_HEADINGS = {
    "needs_action": "Report Needs Manual Action",
    "awaiting_approval": "Report Fix Ready to Approve",
}
_METADATA_TYPES = ("wrong_cover", "wrong_details")


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


def start_file_fix(request_db, user_db, report_id: int, auto_swap: bool) -> None:
    # Placeholder until the file-fix task replaces it.
    set_report_status(report_id, "needs_action", "Automatic fix not available yet")


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
