"""Routes for media issue reports."""

import threading

from flask import Flask, jsonify, request

from shelfmark.core import report_db, report_fixes, request_quota
from shelfmark.core.audiobookshelf import abs_client
from shelfmark.core.calibre_library import find_matches as calibre_find_matches
from shelfmark.core.request_routes import (
    _get_db_user_id, _is_admin, _quota_user, _require_auth, _send_pushover,
)

_PROBLEM_TYPES = (
    "wrong_language", "wrong_edition", "broken_file", "audio_problem",
    "wrong_cover", "wrong_details", "other",
)


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

        user_id = _get_db_user_id()
        request_id = data.get("request_id")
        if request_id is not None:
            req = request_db.get_request(request_id)
            if not req or (req.get("user_id") != user_id and not _is_admin()):
                return jsonify({"error": "Request not found"}), 404

        library = "abs" if content_type == "audiobook" else "calibre"
        author = data.get("author") or ""
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
