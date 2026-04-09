from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import Mock, patch

import pytest


def _as_response(result: Any):
    if isinstance(result, tuple) and len(result) == 2:
        resp, status = result
        resp.status_code = status
        return resp
    return result


@pytest.fixture(scope="module")
def main_module():
    fake_bs4 = types.ModuleType("bs4")
    fake_bs4.BeautifulSoup = object
    fake_bs4.NavigableString = object
    fake_bs4.Tag = object
    sys.modules.setdefault("bs4", fake_bs4)

    import shelfmark.download.orchestrator as orchestrator

    with patch.object(orchestrator, "start"):
        sys.modules.pop("shelfmark.main", None)
        import shelfmark.main as main

        importlib.reload(main)
        return main


class TestProxyAuthDefaults:
    def test_proxy_auth_new_user_without_admin_group_is_not_admin(self, main_module):
        fake_user_db = Mock()
        fake_user_db.get_user.return_value = None
        observed_session: dict[str, Any] = {}

        with patch.object(main_module, "get_auth_mode", return_value="proxy"):
            with patch.object(main_module, "user_db", fake_user_db):
                with patch.object(
                    main_module,
                    "upsert_external_user",
                    return_value=({"id": 7, "username": "proxyuser", "role": "user"}, "created"),
                ):
                    with patch(
                        "shelfmark.core.settings_registry.load_config_file",
                        return_value={"PROXY_AUTH_USER_HEADER": "X-Auth-User"},
                    ):
                        with main_module.app.test_request_context(
                            "/api/search",
                            headers={"X-Auth-User": "proxyuser"},
                        ):
                            result = main_module.proxy_auth_middleware()
                            observed_session = dict(main_module.session)

        assert result is None
        assert observed_session.get("user_id") == "proxyuser"
        assert observed_session.get("is_admin") is False
        assert observed_session.get("db_user_id") == 7


class TestQueueScoping:
    def test_post_download_queues_same_as_get(self, main_module):
        with patch.object(main_module, "get_auth_mode", return_value="builtin"):
            with patch.object(main_module, "_resolve_policy_mode_for_current_user", return_value=None):
                with patch.object(main_module.backend, "queue_book", return_value=(True, None)) as mock_queue_book:
                    with main_module.app.test_client() as client:
                        with client.session_transaction() as session:
                            session["user_id"] = "alice"
                            session["db_user_id"] = 5
                            session["is_admin"] = False
                        resp = client.post("/api/download?id=book-123&priority=2")
                        data = resp.get_json()

        assert resp.status_code == 200
        assert data == {"status": "queued", "priority": 2}
        mock_queue_book.assert_called_once_with(
            "book-123",
            2,
            user_id=5,
            username="alice",
        )

    def test_non_admin_cannot_change_another_users_priority(self, main_module):
        with patch.object(main_module, "get_auth_mode", return_value="builtin"):
            with patch.object(main_module.backend, "book_queue") as mock_book_queue:
                mock_book_queue.get_task.return_value = Mock(user_id=99, username="other-user")
                with main_module.app.test_request_context(
                    "/api/queue/task-123/priority",
                    method="PUT",
                    json={"priority": 10},
                ):
                    main_module.session["user_id"] = "alice"
                    main_module.session["db_user_id"] = 5
                    main_module.session["is_admin"] = False
                    resp = _as_response(main_module.api_set_priority("task-123"))
                    data = resp.get_json()

        assert resp.status_code == 403
        assert data["code"] == "download_not_owned"

    def test_non_admin_only_sees_their_queue_order(self, main_module):
        scoped_queue = [{"id": "mine"}]
        with patch.object(main_module, "get_auth_mode", return_value="builtin"):
            with patch.object(main_module.backend, "queue_status", return_value={"pending": {"mine": {}}}):
                with patch.object(main_module.backend, "get_queue_order", return_value=[{"id": "mine"}, {"id": "other"}]):
                    with patch.object(main_module, "_resolve_status_scope", return_value=(False, 5, True)):
                        with main_module.app.test_request_context("/api/queue/order"):
                            main_module.session["user_id"] = "alice"
                            main_module.session["db_user_id"] = 5
                            main_module.session["is_admin"] = False
                            resp = _as_response(main_module.api_queue_order())
                            data = resp.get_json()

        assert resp.status_code == 200
        assert data == {"queue": scoped_queue}

    def test_non_admin_only_sees_their_active_downloads(self, main_module):
        with patch.object(main_module, "get_auth_mode", return_value="builtin"):
            with patch.object(main_module.backend, "get_active_downloads", return_value=["mine", "other"]):
                with patch.object(main_module.backend, "queue_status", return_value={"downloading": {"mine": {}}}):
                    with patch.object(main_module, "_resolve_status_scope", return_value=(False, 5, True)):
                        with main_module.app.test_request_context("/api/downloads/active"):
                            main_module.session["user_id"] = "alice"
                            main_module.session["db_user_id"] = 5
                            main_module.session["is_admin"] = False
                            resp = _as_response(main_module.api_active_downloads())
                            data = resp.get_json()

        assert resp.status_code == 200
        assert data == {"active_downloads": ["mine"]}


class TestCoverProxyValidation:
    def test_cover_proxy_rejects_private_address_targets(self, main_module):
        encoded = "aHR0cDovLzEyNy4wLjAuMTo4MDgwL2NvdmVyLnBuZw=="

        with main_module.app.test_request_context(f"/api/covers/test-id?url={encoded}"):
            resp = _as_response(main_module.api_cover("test-id"))
            data = resp.get_json()

        assert resp.status_code == 400
        assert "invalid" in data["error"].lower()
