"""Request management API routes.

Registers /api/requests endpoints for the book request workflow.
Authenticated users can create requests; admins can approve/deny them.
"""

import threading
from functools import wraps

from flask import Flask, jsonify, request, session

from shelfmark.core.logger import setup_logger
from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB

logger = setup_logger(__name__)


def _get_auth_mode():
    """Get current auth mode from config."""
    try:
        from shelfmark.core.settings_registry import load_config_file
        config = load_config_file("security")
        return config.get("AUTH_METHOD", "none")
    except Exception:
        return "none"


def _require_auth(f):
    """Decorator requiring an authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_mode = _get_auth_mode()
        if auth_mode != "none":
            if "user_id" not in session:
                return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def _require_admin(f):
    """Decorator requiring admin session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_mode = _get_auth_mode()
        if auth_mode != "none":
            if "user_id" not in session:
                return jsonify({"error": "Authentication required"}), 401
            if not session.get("is_admin", False):
                return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def _get_db_user_id() -> int | None:
    """Get the database user ID from session."""
    return session.get("db_user_id")


def _is_admin() -> bool:
    """Check if current user is admin."""
    auth_mode = _get_auth_mode()
    if auth_mode == "none":
        return True
    return session.get("is_admin", False)


def _broadcast_request_update(request_data: dict | None = None) -> None:
    """Broadcast a request_update event via WebSocket."""
    try:
        from shelfmark.api.websocket import ws_manager
        if ws_manager and ws_manager.is_enabled():
            ws_manager.socketio.emit("request_update", request_data or {})
    except Exception as e:
        logger.warning(f"Failed to broadcast request update: {e}")


def _send_pushover_new_request(req: dict, user_db: UserDB) -> None:
    """Send Pushover notification to admin when a new request is created (best-effort)."""
    try:
        from shelfmark.core.pushover_notifications import send_new_request_pushover
        user_id = req.get("user_id")
        requester = None
        if user_id:
            user = user_db.get_user(user_id=user_id)
            if user:
                requester = user.get("username")
        send_new_request_pushover(
            title=req.get("title", "Unknown"),
            author=req.get("author"),
            requester=requester,
            content_type=req.get("content_type", "ebook"),
        )
    except Exception as e:
        logger.warning(f"Failed to send Pushover notification for new request #{req.get('id')}: {e}")


def _send_discord_new_request(req: dict, user_db: UserDB) -> None:
    """Send Discord embed notification on new request (best-effort)."""
    try:
        from shelfmark.core.discord_notifications import send_discord_new_request
        requester = req.get("requester_username")
        if not requester:
            user_id = req.get("user_id")
            if user_id:
                user = user_db.get_user(user_id=user_id)
                if user:
                    requester = user.get("username")
        send_discord_new_request(
            title=req.get("title", "Unknown"),
            author=req.get("author"),
            requester=requester,
            content_type=req.get("content_type", "ebook"),
            cover_url=req.get("cover_url"),
        )
    except Exception as e:
        logger.warning(f"Discord new-request notification failed for #{req.get('id')}: {e}")


def _send_discord_book_available(req: dict) -> None:
    """Send Discord embed notification when a book is fulfilled (best-effort)."""
    try:
        from shelfmark.core.discord_notifications import send_discord_book_available
        send_discord_book_available(
            title=req.get("title", "Unknown"),
            author=req.get("author"),
            requester=req.get("requester_username"),
            cover_url=req.get("cover_url"),
        )
    except Exception as e:
        logger.warning(f"Discord book-available notification failed for #{req.get('id')}: {e}")


def _send_status_notification(
    user_db: UserDB, req: dict, new_status: str, admin_note: str | None = None
) -> None:
    """Send email notification to the requesting user (best-effort, non-blocking)."""
    try:
        user_id = req.get("user_id")
        if not user_id:
            return
        user = user_db.get_user(user_id=user_id)
        if not user or not user.get("email"):
            return
        from shelfmark.core.request_notifications import send_request_notification
        send_request_notification(
            user_email=user["email"],
            request_title=req.get("title", "Unknown"),
            new_status=new_status,
            admin_note=admin_note,
        )
    except Exception as e:
        logger.warning(f"Failed to send notification for request #{req.get('id')}: {e}")


def _requests_enabled() -> bool:
    """Check if the request system should be active (requires auth)."""
    return _get_auth_mode() != "none"


# Module-level guard against concurrent auto-downloads for the same request
_in_flight_downloads: set = set()
_in_flight_lock = threading.Lock()


def _acquire_download_slot(request_id: int) -> bool:
    with _in_flight_lock:
        if request_id in _in_flight_downloads:
            return False
        _in_flight_downloads.add(request_id)
        return True


def _release_download_slot(request_id: int) -> None:
    with _in_flight_lock:
        _in_flight_downloads.discard(request_id)


def register_request_routes(app: Flask, request_db: RequestDB, user_db: UserDB) -> None:
    """Register request management routes on the Flask app."""

    if not _requests_enabled():
        logger.info("Request routes disabled (auth_mode=none)")
        return

    @app.route("/api/requests", methods=["POST"])
    @_require_auth
    def create_request_route():
        """Create a new book request."""
        db_user_id = _get_db_user_id()
        if not db_user_id:
            return jsonify({"error": "User session not found"}), 401

        data = request.get_json() or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "Title is required"}), 400

        content_type = data.get("content_type", "ebook")
        if content_type not in ("ebook", "audiobook"):
            return jsonify({"error": "content_type must be 'ebook' or 'audiobook'"}), 400

        # Duplicate detection: check for active requests by the same user
        provider = data.get("provider")
        provider_id_val = data.get("provider_id")
        existing = request_db.list_requests(user_id=db_user_id, limit=200)
        active_statuses = {"pending", "approved", "downloading"}
        for ex in existing:
            if ex["status"] not in active_statuses:
                continue
            if provider and provider_id_val:
                if ex.get("provider") == provider and ex.get("provider_id") == provider_id_val and ex.get("content_type") == content_type:
                    return jsonify({"error": "You already have an active request for this book"}), 409
            elif ex.get("title", "").lower() == title.lower() and ex.get("content_type") == content_type:
                return jsonify({"error": "You already have an active request for this book"}), 409

        try:
            req = request_db.create_request(
                user_id=db_user_id,
                title=title,
                content_type=content_type,
                author=(data.get("author") or "").strip() or None,
                year=(data.get("year") or "").strip() or None,
                cover_url=data.get("cover_url"),
                description=data.get("description"),
                isbn_10=data.get("isbn_10"),
                isbn_13=data.get("isbn_13"),
                provider=data.get("provider"),
                provider_id=data.get("provider_id"),
                series_name=data.get("series_name"),
                series_position=data.get("series_position"),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        logger.info(f"Request created: #{req['id']} '{title}' by user {db_user_id}")
        _broadcast_request_update(req)
        _send_pushover_new_request(req, user_db)
        _send_discord_new_request(req, user_db)
        return jsonify(req), 201

    @app.route("/api/requests", methods=["GET"])
    @_require_auth
    def list_requests_route():
        """List requests. Admins see all, users see own."""
        status_filter = request.args.get("status")
        try:
            limit = min(int(request.args.get("limit", 100)), 1000)
        except ValueError:
            limit = 100
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            offset = 0

        user_id = None if _is_admin() else _get_db_user_id()

        requests_list = request_db.list_requests(
            user_id=user_id, status=status_filter, limit=limit, offset=offset
        )
        total = request_db.count_requests(user_id=user_id, status=status_filter)

        return jsonify({
            "requests": requests_list,
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    @app.route("/api/requests/counts", methods=["GET"])
    @_require_auth
    def request_counts_route():
        """Get request counts by status for badge display."""
        user_id = None if _is_admin() else _get_db_user_id()
        counts = request_db.get_request_counts(user_id=user_id)

        # Get unviewed count for non-admins
        if not _is_admin():
            unviewed = request_db.get_unviewed_count(user_id)
            counts["unviewed"] = unviewed

        return jsonify(counts)

    @app.route("/api/requests/mark-viewed", methods=["POST"])
    @_require_auth
    def mark_requests_viewed_route():
        """Mark all requests as viewed for the current user."""
        user_id = _get_db_user_id()
        user_db.update_requests_last_viewed(user_id)
        logger.debug(f"User {user_id} marked requests as viewed")
        return jsonify({"success": True})

    @app.route("/api/requests/<int:request_id>", methods=["GET"])
    @_require_auth
    def get_request_route(request_id):
        """Get a single request. Owner or admin only."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        if not _is_admin() and req["user_id"] != _get_db_user_id():
            return jsonify({"error": "Access denied"}), 403

        return jsonify(req)

    @app.route("/api/requests/<int:request_id>", methods=["DELETE"])
    @_require_auth
    def delete_request_route(request_id):
        """Delete/hide a request. Owners delete permanently; admins hide from their view."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        is_admin = _is_admin()
        is_owner = req["user_id"] == _get_db_user_id()

        if not is_admin and not is_owner:
            return jsonify({"error": "Access denied"}), 403

        if is_admin and not is_owner:
            # Admin hiding request from their view (doesn't affect user's list)
            request_db.hide_request_from_admin(request_id)
            logger.info(f"Request #{request_id} hidden from admin view")
            _broadcast_request_update({"id": request_id, "deleted": True})
            return jsonify({"success": True, "action": "hidden"})
        else:
            # Owner permanently deleting their own request
            request_db.delete_request(request_id)
            logger.info(f"Request #{request_id} permanently deleted by owner")
            _broadcast_request_update({"id": request_id, "deleted": True})
            return jsonify({"success": True, "action": "deleted"})

    @app.route("/api/requests/<int:request_id>/approve", methods=["POST"])
    @_require_admin
    def approve_request_route(request_id):
        """Approve a request. Audiobooks stay at 'approved', ebooks trigger auto-download."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        if req["status"] != "pending":
            return jsonify({"error": f"Cannot approve a request with status '{req['status']}'"}), 400

        admin_user_id = _get_db_user_id()

        # Update to approved first
        updated = request_db.update_request_status(
            request_id, "approved", approved_by=admin_user_id
        )
        logger.info(f"Request #{request_id} approved by admin {admin_user_id}")
        _broadcast_request_update(updated)

        # Send notification to requester
        _send_status_notification(user_db, req, "approved")

        # For audiobooks, just stay at "approved" status - admin will manually manage
        content_type = req.get("content_type", "ebook")
        if content_type == "audiobook":
            logger.info(f"Request #{request_id} is audiobook - staying at 'approved' for manual management")
            return jsonify(updated)

        # For ebooks, start auto-download in background thread
        # Capture session data before spawning thread (session unavailable outside request context)
        admin_username = session.get("user_id")

        if _acquire_download_slot(request_id):
            thread = threading.Thread(
                target=_auto_download_request,
                args=(request_db, user_db, request_id, req, admin_user_id, admin_username),
                daemon=True,
            )
            thread.start()
        else:
            logger.info(f"Request #{request_id} already being auto-downloaded, skipping")

        return jsonify(updated)

    @app.route("/api/requests/<int:request_id>/deny", methods=["POST"])
    @_require_admin
    def deny_request_route(request_id):
        """Deny a request with optional admin note. Can be used on any status."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        # Allow deny on any status - admin can reject at any time
        data = request.get_json() or {}
        admin_note = (data.get("admin_note") or "").strip() or None
        admin_user_id = _get_db_user_id()

        updated = request_db.update_request_status(
            request_id, "denied",
            admin_note=admin_note, approved_by=admin_user_id
        )
        logger.info(f"Request #{request_id} denied by admin {admin_user_id} (was {req['status']})")
        _broadcast_request_update(updated)

        # Send notification to requester
        _send_status_notification(user_db, req, "denied", admin_note=admin_note)

        return jsonify(updated)

    @app.route("/api/requests/<int:request_id>/status", methods=["PUT"])
    @_require_admin
    def update_request_status_route(request_id):
        """Admin: manually update request status to any value."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        data = request.get_json() or {}
        new_status = data.get("status")
        if not new_status:
            return jsonify({"error": "status is required"}), 400

        valid_statuses = ["pending", "approved", "denied", "downloading", "fulfilled", "failed", "cancelled"]
        if new_status not in valid_statuses:
            return jsonify({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400

        admin_note = (data.get("admin_note") or "").strip() or None
        admin_user_id = _get_db_user_id()

        updated = request_db.update_request_status(
            request_id, new_status,
            admin_note=admin_note, approved_by=admin_user_id
        )
        logger.info(f"Request #{request_id} status changed to '{new_status}' by admin {admin_user_id} (was {req['status']})")
        _broadcast_request_update(updated)

        # Send notification to requester if status changed significantly
        if new_status in ["approved", "denied", "fulfilled", "failed"]:
            _send_status_notification(user_db, req, new_status, admin_note=admin_note)
        if new_status == "fulfilled":
            updated_req = request_db.get_request(request_id)
            if updated_req:
                _send_discord_book_available(updated_req)

        return jsonify(updated)

    @app.route("/api/requests/<int:request_id>/retry", methods=["POST"])
    @_require_admin
    def retry_request_route(request_id):
        """Retry a failed, cancelled, denied, downloading, or approved request."""
        req = request_db.get_request(request_id)
        if not req:
            return jsonify({"error": "Request not found"}), 404

        if req["status"] not in ("failed", "cancelled", "denied", "downloading", "approved"):
            return jsonify({"error": f"Cannot retry a request with status '{req['status']}'"}), 400

        admin_user_id = _get_db_user_id()

        # Update to approved status (ready for retry)
        updated = request_db.update_request_status(
            request_id, "approved", approved_by=admin_user_id
        )
        logger.info(f"Request #{request_id} retrying by admin {admin_user_id}")

        # If request is missing metadata (from old direct-mode requests), search for it now
        if not updated.get("provider") or not updated.get("provider_id"):
            logger.info(f"Request #{request_id} missing metadata, searching...")
            try:
                from shelfmark.metadata_providers import get_configured_provider
                from shelfmark.config.settings import get_config

                # Get current metadata provider
                settings_config = get_config("settings")
                provider_name = settings_config.get("METADATA_PROVIDER", "openlibrary")
                provider = get_configured_provider(provider_name)

                if provider:
                    # Search using title and author from the request
                    search_query = updated.get("title", "")
                    if updated.get("author"):
                        search_query += f" {updated['author']}"

                    results = provider.search(search_query)
                    if results:
                        # Use the first result and update the request with metadata
                        best_match = results[0]
                        request_db.update_request_metadata(
                            request_id,
                            provider=provider_name,
                            provider_id=best_match.provider_id
                        )
                        # Re-fetch the updated request
                        updated = request_db.get_request(request_id)
                        logger.info(f"Request #{request_id} metadata updated: {provider_name}:{best_match.provider_id}")
                    else:
                        logger.warning(f"Request #{request_id} metadata search returned no results")
            except Exception as e:
                logger.error(f"Failed to fetch metadata for request #{request_id}: {e}")

        _broadcast_request_update(updated)

        # For audiobooks, just stay at "approved" status - admin will manually manage
        content_type = updated.get("content_type", "ebook")
        if content_type == "audiobook":
            logger.info(f"Request #{request_id} is audiobook - staying at 'approved' for manual management")
            return jsonify(updated)

        # For ebooks, start auto-download in background thread
        # Capture session data before spawning thread
        admin_username = session.get("user_id")

        if _acquire_download_slot(request_id):
            thread = threading.Thread(
                target=_auto_download_request,
                args=(request_db, user_db, request_id, updated, admin_user_id, admin_username),
                daemon=True,
            )
            thread.start()
        else:
            logger.info(f"Request #{request_id} already being auto-downloaded, skipping")

        return jsonify(updated)


def _auto_download_request(
    request_db: RequestDB,
    user_db: UserDB,
    request_id: int,
    req: dict,
    admin_user_id: int | None = None,
    admin_username: str | None = None,
) -> None:
    """Search for and queue a download for an approved request.

    Runs in a background thread. Updates the request status to
    'downloading' or 'failed' depending on the outcome.
    """
    def _safe_update_status(status: str, **kwargs) -> None:
        """Update status only if the request still exists."""
        if request_db.get_request(request_id) is not None:
            request_db.update_request_status(request_id, status, **kwargs)
            _broadcast_request_update(request_db.get_request(request_id))
            if status == "fulfilled":
                updated_req = request_db.get_request(request_id)
                if updated_req:
                    _send_discord_book_available(updated_req)

    try:
        from shelfmark.download import orchestrator as backend
        from shelfmark.release_sources import get_source, list_available_sources
        from shelfmark.metadata_providers import (
            get_provider,
            is_provider_registered,
            get_provider_kwargs,
        )
        from shelfmark.core.search_plan import build_release_search_plan

        provider_name = req.get("provider")
        provider_id = req.get("provider_id")

        if not provider_name or not provider_id or not is_provider_registered(provider_name):
            _safe_update_status("failed", admin_note="No metadata provider info")
            return

        # Get book metadata from provider
        kwargs = get_provider_kwargs(provider_name)
        prov = get_provider(provider_name, **kwargs)
        book = prov.get_book(provider_id)
        if not book:
            _safe_update_status("failed", admin_note="Book not found in provider")
            return

        # Search for releases
        content_type = req.get("content_type", "ebook")
        sources_to_search = [src["name"] for src in list_available_sources() if src["enabled"]]
        if not sources_to_search:
            _safe_update_status("failed", admin_note="No release sources available")
            return

        all_releases = []
        for source_name in sources_to_search:
            try:
                source = get_source(source_name)
                plan = build_release_search_plan(book)
                releases = source.search(book, plan, expand_search=True, content_type=content_type)
                all_releases.extend(releases)
            except Exception as e:
                logger.warning(f"Release search failed for {source_name} (request #{request_id}): {e}")

        if not all_releases:
            _safe_update_status("failed", admin_note="No releases found")
            return

        # Pick the first (best) release
        release = all_releases[0]

        # Get admin's user settings for download overrides
        user_overrides = user_db.get_user_settings(admin_user_id) if admin_user_id else {}

        from dataclasses import asdict
        release_data = asdict(release)
        release_data["author"] = book.authors[0] if book.authors else None
        release_data["year"] = str(book.publish_year) if book.publish_year else None
        release_data["preview"] = book.cover_url
        release_data["content_type"] = content_type
        release_data["series_name"] = book.series_name
        release_data["series_position"] = book.series_position

        success, error_msg = backend.queue_release(
            release_data, priority=0,
            user_id=admin_user_id,
            username=admin_username,
            user_overrides=user_overrides,
        )

        if success:
            task_id = release_data.get("source_id", "")
            _safe_update_status("downloading", download_task_id=task_id)
            logger.info(f"Request #{request_id}: download queued (task={task_id})")
        else:
            _safe_update_status("failed", admin_note=error_msg or "Failed to queue download")
            logger.warning(f"Request #{request_id}: failed to queue download: {error_msg}")

    except Exception as e:
        logger.error(f"Auto-download error for request #{request_id}: {e}")
        try:
            _safe_update_status("failed", admin_note=f"Error: {e}")
        except Exception:
            pass
    finally:
        _release_download_slot(request_id)
