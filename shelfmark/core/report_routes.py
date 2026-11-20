"""Routes for media issue reports."""

import json
import logging
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request

from shelfmark.core import report_db, report_fixes, request_quota
from shelfmark.core.audiobookshelf import abs_client
from shelfmark.core import calibre_library
from shelfmark.core.calibre_library import find_matches as calibre_find_matches
from shelfmark.core.request_routes import (
    _get_db_user_id, _is_admin, _quota_user, _require_admin, _require_auth, _send_pushover,
)

logger = logging.getLogger(__name__)

_PROBLEM_TYPES = (
    "wrong_language", "wrong_edition", "broken_file", "audio_problem",
    "wrong_cover", "wrong_details", "other",
)
_FILE_PROBLEMS = ("wrong_language", "wrong_edition", "broken_file", "audio_problem")


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def approve_worker(request_db, report: dict) -> None:
    if report["problem_type"] in ("wrong_cover", "wrong_details"):
        report_fixes.fix_metadata(request_db, report["id"])
    else:
        try:
            report_fixes.swap_in(request_db, report)
        except Exception as e:
            logger.exception("Report #%s: approve failed", report["id"])
            report_fixes.set_report_status(report["id"], "needs_action", f"Swap failed: {str(e)[:100]}")


def retry_worker(request_db, user_db, report_id: int) -> None:
    try:
        report_fixes.start_file_fix(request_db, user_db, report_id, auto_swap=True)
    except Exception as e:
        logger.exception("Report #%s: retry failed", report_id)
        report_fixes.set_report_status(report_id, "needs_action", f"Automatic fix failed: {str(e)[:100]}")


def dismiss_worker(request_db, report: dict, note: str) -> None:
    """Park any staged copy in the archive (never deleted), then close the report."""
    try:
        staged = Path(json.loads(report.get("undo_json") or "{}").get("staged") or "")
        if staged.is_absolute() and staged.is_dir():
            item = abs_client.get_item(report["library_item_id"]) if report["library_item_id"] else None
            if item:
                _, archive = report_fixes._fix_dirs(item["path"], report["id"])
            else:  # the item is gone; staging sits beside .shelfmark-replaced under the same parent
                archive = staged.parent.parent.parent / ".shelfmark-replaced" / str(report["id"])
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / "dismissed-staging"
            if not target.exists():
                os.replace(staged, target)
    except Exception:
        logger.exception("Report #%s: could not archive staging on dismiss", report["id"])
    report_fixes.set_report_status(report["id"], "dismissed", note)


def register_report_routes(app: Flask, request_db, user_db) -> None:
    @app.route("/api/library/matches", methods=["GET"])
    @_require_auth
    def library_matches():
        title = request.args.get("title", "").strip()
        author = request.args.get("author", "").strip()
        if request.args.get("content_type") == "audiobook":
            matches = [
                {"library": "abs", "library_item_id": m["id"], "title": m["title"],
                 "author": m["author"], "cover": m.get("cover")}
                for m in abs_client.find_matches(title, author, limit=5)
            ]
        else:
            matches = [
                {"library": "calibre", "library_item_id": str(m["id"]) if m.get("id") is not None else None,
                 "title": m["title"], "author": m["author"], "cover": None}
                for m in calibre_find_matches(title, author)
            ]
        return jsonify({"matches": matches})

    @app.route("/api/reports", methods=["GET"])
    @_require_auth
    def list_my_reports():
        return jsonify(report_db.list_reports(request_db, user_id=_get_db_user_id()))

    @app.route("/api/reports", methods=["POST"])
    @_require_auth
    def create_report():
        data = request.get_json(silent=True) or {}
        problem = data.get("problem_type")
        note = (data.get("note") or "").strip()
        title = (data.get("title") or "").strip()
        content_type = data.get("content_type")
        if problem not in _PROBLEM_TYPES:
            return jsonify({"error": "Unknown problem type"}), 400
        if problem == "other" and not note:
            return jsonify({"error": "Please describe the problem"}), 400
        if not title or content_type not in ("ebook", "audiobook"):
            return jsonify({"error": "title and content_type are required"}), 400
        author = data.get("author") or ""
        item_id = data.get("library_item_id")
        if (len(note) > 1000 or len(title) > 300 or not isinstance(author, str) or len(author) > 300
                or (item_id is not None and not isinstance(item_id, str))
                or (data.get("request_id") is not None
                    and (type(data["request_id"]) is not int))):
            return jsonify({"error": "Invalid field"}), 400

        user_id = _get_db_user_id()
        request_id = data.get("request_id")
        if request_id is not None:
            req = request_db.get_request(request_id)
            if not req or (req.get("user_id") != user_id and not _is_admin()):
                return jsonify({"error": "Request not found"}), 404

        library = "abs" if content_type == "audiobook" else "calibre"
        if item_id:
            # Bind the report to the real library item so identity and fix target can't diverge.
            if library == "abs":
                item = abs_client.get_cached_item(item_id)
            else:
                item = calibre_library.get_book(int(item_id)) if item_id.isdigit() else None
            if not item:
                return jsonify({"error": "That item is no longer in the library"}), 400
            title, author = item["title"], item["author"]
        fields = {
            **{k: data.get(k) for k in ("library_item_id", "provider", "provider_id")},
            "library": library, "content_type": content_type, "title": title, "author": author,
            "request_id": request_id, "problem_type": problem, "note": note or None,
            "item_key": report_db.item_key(library, content_type, title, author),
        }
        requester = _quota_user(user_db, user_id)
        limit = request_quota.limit_for(requester, kind="report")
        try:
            report, joined = report_db.create_or_join_report(
                request_db, user_id=user_id, fields=fields, quota_limit=limit,
                quota_since=request_quota.counting_since(requester, kind="report") if limit is not None else None,
            )
        except report_db.ReportLimitReached as e:
            return jsonify({
                "error": f"{e}. Your reports reset on Monday.",
                "quota": request_quota.report_quota_for(request_db, requester),
            }), 429

        quota = request_quota.report_quota_for(request_db, requester)
        if not joined:
            threading.Thread(
                target=report_fixes.triage, args=(request_db, user_db, report["id"]), daemon=True
            ).start()
            if quota and quota["remaining"] == 0:
                _send_pushover(
                    {**report, "user_id": user_id}, user_db, "Weekly Report Limit Reached",
                    f"{requester.get('username')} has used all {quota['limit']} reports this week.",
                )
        return jsonify({"report": report, "joined": joined, "quota": quota}), 201


    # --- admin ---------------------------------------------------------------

    def _admin_row(report: dict) -> dict:
        conn = request_db._connect()
        try:
            others = conn.execute(
                "SELECT COUNT(*) - 1 FROM media_report_users WHERE report_id = ?", (report["id"],)
            ).fetchone()[0]
        finally:
            conn.close()
        user = user_db.get_user(user_id=report["created_by"]) if report.get("created_by") else None
        return {**report, "reporter": (user or {}).get("username"), "joined_count": max(0, others)}

    @app.route("/api/admin/reports", methods=["GET"])
    @_require_admin
    def admin_list_reports():
        statuses = [s for s in request.args.get("status", "needs_action,awaiting_approval").split(",") if s]
        return jsonify([_admin_row(r) for r in report_db.list_reports(request_db, statuses=statuses)])

    def _claim(report_id: int, allowed: tuple, check=None):
        """The report if it is in an allowed state, else a 409 response."""
        report = report_db.get_report(request_db, report_id)
        if report is None:
            return None, (jsonify({"error": "Report not found"}), 404)
        if report["status"] not in allowed or (check and not check(report)):
            return None, (jsonify({"error": f"Can't do that to a report that is {report['status']}"}), 409)
        return report, None

    def _start(report_id: int, allowed: tuple, worker, check=None, busy: bool = True):
        report, err = _claim(report_id, allowed, check)
        if err:
            return err
        if busy:  # blocks a second click from starting the same work twice
            report = report_fixes.set_report_status(report_id, "fixing")
        _spawn(worker, report)
        return jsonify({"report": report}), 202

    @app.route("/api/admin/reports/<int:report_id>/approve", methods=["POST"])
    @_require_admin
    def admin_approve_report(report_id):
        return _start(report_id, ("awaiting_approval",), lambda r: approve_worker(request_db, r))

    @app.route("/api/admin/reports/<int:report_id>/retry", methods=["POST"])
    @_require_admin
    def admin_retry_report(report_id):
        return _start(
            report_id, ("needs_action",), lambda r: retry_worker(request_db, user_db, r["id"]),
            check=lambda r: r["problem_type"] in _FILE_PROBLEMS and r["library"] == "abs" and r["library_item_id"],
        )

    @app.route("/api/admin/reports/<int:report_id>/undo", methods=["POST"])
    @_require_admin
    def admin_undo_report(report_id):
        return _start(report_id, ("fixed",), lambda r: report_fixes.undo(request_db, r["id"]))

    @app.route("/api/admin/reports/<int:report_id>/dismiss", methods=["POST"])
    @_require_admin
    def admin_dismiss_report(report_id):
        note = ((request.get_json(silent=True) or {}).get("note") or "").strip()[:1000] or "Dismissed by admin"
        return _start(
            report_id, ("needs_action", "awaiting_approval"),
            lambda r: dismiss_worker(request_db, r, note), busy=False,
        )
