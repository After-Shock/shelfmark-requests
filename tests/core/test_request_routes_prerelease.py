import json
from unittest.mock import MagicMock, patch

import pytest


def _make_app(request_db, user_db):
    from flask import Flask
    from shelfmark.core.request_routes import register_request_routes

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.request_db = request_db
    app.user_db = user_db
    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
        register_request_routes(app, request_db, user_db)
    return app


@pytest.fixture
def app():
    request_db = MagicMock()
    request_db.list_requests.return_value = []
    request_db.create_request.return_value = {
        "id": 1,
        "title": "Future Book",
        "status": "pending",
        "content_type": "ebook",
        "author": "Future Author",
        "user_id": 1,
        "expected_release_date": None,
        "is_released": False,
    }
    request_db.update_request_status.return_value = {
        "id": 1,
        "title": "Future Book",
        "status": "prerelease_requested",
        "content_type": "ebook",
        "author": "Future Author",
        "user_id": 1,
        "expected_release_date": "2099-01-01",
        "is_released": False,
    }
    request_db.update_request_metadata.return_value = {
        "id": 1,
        "title": "Future Book",
        "status": "pending",
        "content_type": "ebook",
        "author": "Future Author",
        "user_id": 1,
        "expected_release_date": "2099-01-01",
        "is_released": False,
        "completed_at": None,
    }
    request_db.get_request.return_value = {
        "id": 1,
        "title": "Future Book",
        "status": "prerelease_requested",
        "content_type": "ebook",
        "author": "Future Author",
        "user_id": 1,
        "expected_release_date": "2099-01-01",
        "is_released": False,
        "completed_at": None,
    }
    user_db = MagicMock()
    user_db.get_user.return_value = {"id": 1, "username": "testuser", "email": "user@example.com"}
    return _make_app(request_db, user_db)


def _set_user_session(client, *, db_user_id=1, user_id="testuser", is_admin=False):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["db_user_id"] = db_user_id
        sess["is_admin"] = is_admin


class TestCreatePrereleaseRequests:
    def test_create_request_future_release_becomes_prerelease(self, app):
        request_db = app.request_db
        with app.test_client() as client:
            _set_user_session(client)
            with patch("shelfmark.core.request_routes.abs_client.find_match", return_value=None), \
                 patch("shelfmark.core.request_routes._send_pushover_new_request"), \
                 patch("shelfmark.core.request_routes._send_discord_new_request"), \
                 patch("shelfmark.core.request_routes._broadcast_request_update"):
                resp = client.post("/api/requests", json={
                    "title": "Future Book",
                    "author": "Future Author",
                    "content_type": "ebook",
                    "is_released": False,
                    "expected_release_date": "2099-01-01",
                })

        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["status"] == "prerelease_requested"
        request_db.update_request_metadata.assert_called_once_with(
            1, expected_release_date="2099-01-01"
        )
        request_db.update_request_status.assert_called_once()

    def test_create_request_past_release_stays_pending(self, app):
        request_db = app.request_db
        with app.test_client() as client:
            _set_user_session(client)
            with patch("shelfmark.core.request_routes.abs_client.find_match", return_value=None), \
                 patch("shelfmark.core.request_routes._send_pushover_new_request"), \
                 patch("shelfmark.core.request_routes._send_discord_new_request"), \
                 patch("shelfmark.core.request_routes._broadcast_request_update"):
                resp = client.post("/api/requests", json={
                    "title": "Released Book",
                    "author": "Author",
                    "content_type": "ebook",
                    "is_released": False,
                    "expected_release_date": "2000-01-01",
                })

        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["status"] == "pending"
        request_db.update_request_status.assert_not_called()

    def test_duplicate_prerelease_request_is_blocked(self, app):
        request_db = app.request_db
        request_db.list_requests.return_value = [{
            "id": 7,
            "title": "Future Book",
            "status": "prerelease_requested",
            "content_type": "ebook",
            "provider": "googlebooks",
            "provider_id": "abc123",
        }]

        with app.test_client() as client:
            _set_user_session(client)
            with patch("shelfmark.core.request_routes.abs_client.find_match", return_value=None):
                resp = client.post("/api/requests", json={
                    "title": "Future Book",
                    "author": "Future Author",
                    "content_type": "ebook",
                    "provider": "googlebooks",
                    "provider_id": "abc123",
                    "is_released": False,
                    "expected_release_date": "2099-01-01",
                })

        assert resp.status_code == 409
        assert "active request" in json.loads(resp.data)["error"].lower()


class TestAdminPrereleaseTransitions:
    def test_activate_prerelease_request_moves_to_pending(self, app):
        request_db = app.request_db
        request_db.update_request_status.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "pending",
            "content_type": "ebook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": True,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            with patch("shelfmark.core.request_routes._broadcast_request_update") as mock_broadcast, \
                 patch("shelfmark.core.request_routes._send_status_notification") as mock_notify:
                resp = client.post("/api/requests/1/activate")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "pending"
        assert data["expected_release_date"] is None
        assert data["is_released"] is True
        request_db.update_request_metadata.assert_called_once_with(
            1,
            is_released=True,
            clear_expected_release_date=True,
        )
        request_db.update_request_status.assert_called_once_with(1, "pending", approved_by=1)
        mock_broadcast.assert_called_once()
        mock_notify.assert_called_once()

    def test_list_requests_exposes_completed_at_for_history(self, app):
        request_db = app.request_db
        request_db.list_requests.return_value = [{
            "id": 4,
            "title": "Completed Book",
            "status": "fulfilled",
            "content_type": "audiobook",
            "author": "Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": True,
            "completed_at": "2026-05-05 13:00:00",
            "created_at": "2026-05-01 10:00:00",
            "updated_at": "2026-05-05 13:00:00",
            "requester_username": "testuser",
            "requester_display_name": "Test User",
        }]
        request_db.count_requests.return_value = 1

        with app.test_client() as client:
            _set_user_session(client)
            resp = client.get("/api/requests")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["requests"][0]["completed_at"] == "2026-05-05 13:00:00"
        request_db.list_requests.assert_called_once_with(
            user_id=None,
            status=None,
            limit=100,
            offset=0,
            include_hidden_completed_for_admin=True,
        )

    def test_admin_list_requests_includes_hidden_completed_history(self, app):
        request_db = app.request_db
        request_db.list_requests.return_value = []
        request_db.count_requests.return_value = 0

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            resp = client.get("/api/requests")

        assert resp.status_code == 200
        request_db.list_requests.assert_called_once_with(
            user_id=None,
            status=None,
            limit=100,
            offset=0,
            include_hidden_completed_for_admin=True,
        )

    def test_move_pending_request_to_prerelease(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "pending",
            "content_type": "ebook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": False,
        }

        request_db.update_request_status.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "prerelease_requested",
            "content_type": "ebook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": "2099-01-01",
            "is_released": False,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            with patch("shelfmark.core.request_routes._broadcast_request_update") as mock_broadcast:
                resp = client.post("/api/requests/1/move-to-prerelease", json={
                    "expected_release_date": "2099-01-01",
                })

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "prerelease_requested"
        request_db.update_request_metadata.assert_called_once_with(
            1,
            expected_release_date="2099-01-01",
            is_released=False,
            hidden_from_admin=False,
        )
        request_db.update_request_status.assert_called_once_with(1, "prerelease_requested", approved_by=1)
        mock_broadcast.assert_called_once()

    def test_move_approved_request_to_prerelease(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "approved",
            "content_type": "audiobook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": False,
        }

        request_db.update_request_status.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "prerelease_requested",
            "content_type": "audiobook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": "2099-01-01",
            "is_released": False,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            with patch("shelfmark.core.request_routes._broadcast_request_update"):
                resp = client.post("/api/requests/1/move-to-prerelease", json={
                    "expected_release_date": "2099-01-01",
                })

        assert resp.status_code == 200
        request_db.update_request_status.assert_called_once_with(1, "prerelease_requested", approved_by=1)

    def test_move_pending_request_to_prerelease_rejects_non_future_date(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "pending",
            "content_type": "ebook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": False,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            resp = client.post("/api/requests/1/move-to-prerelease", json={
                "expected_release_date": "2000-01-01",
            })

        assert resp.status_code == 400
        assert "future date" in json.loads(resp.data)["error"].lower()
        request_db.update_request_metadata.assert_not_called()
        request_db.update_request_status.assert_not_called()

    def test_status_route_rejects_direct_prerelease_transition(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Future Book",
            "status": "pending",
            "content_type": "ebook",
            "author": "Future Author",
            "user_id": 1,
            "expected_release_date": None,
            "is_released": False,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            resp = client.put("/api/requests/1/status", json={
                "status": "prerelease_requested",
            })

        assert resp.status_code == 400
        assert "move-to-prerelease" in json.loads(resp.data)["error"]

    def test_admin_can_set_no_sources_requested_status(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Missing Book",
            "status": "pending",
            "content_type": "ebook",
            "author": "Author",
            "user_id": 1,
        }
        request_db.update_request_status.return_value = {
            "id": 1,
            "title": "Missing Book",
            "status": "no_sources_requested",
            "content_type": "ebook",
            "author": "Author",
            "user_id": 1,
            "admin_note": "Requested from provider",
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            with patch("shelfmark.core.request_routes._broadcast_request_update") as mock_broadcast:
                resp = client.put(
                    "/api/requests/1/status",
                    json={"status": "no_sources_requested", "admin_note": "Requested from provider"},
                )

        assert resp.status_code == 200
        request_db.update_request_status.assert_called_once_with(
            1,
            "no_sources_requested",
            admin_note="Requested from provider",
            approved_by=1,
        )
        mock_broadcast.assert_called_once()

    def test_no_sources_requested_does_not_send_terminal_notification(self, app):
        request_db = app.request_db
        request_db.get_request.return_value = {
            "id": 1,
            "title": "Missing Book",
            "status": "approved",
            "content_type": "ebook",
            "author": "Author",
            "user_id": 1,
        }
        request_db.update_request_status.return_value = {
            "id": 1,
            "title": "Missing Book",
            "status": "no_sources_requested",
            "content_type": "ebook",
            "author": "Author",
            "user_id": 1,
        }

        with app.test_client() as client:
            _set_user_session(client, is_admin=True)
            with patch("shelfmark.core.request_routes._broadcast_request_update"), \
                 patch("shelfmark.core.request_routes._send_status_notification") as mock_notify:
                resp = client.put("/api/requests/1/status", json={"status": "no_sources_requested"})

        assert resp.status_code == 200
        mock_notify.assert_not_called()
        request_db.update_request_status.assert_called_once_with(
            1,
            "no_sources_requested",
            admin_note=None,
            approved_by=1,
        )
