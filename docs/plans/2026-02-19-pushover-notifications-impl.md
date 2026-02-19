# Pushover Admin Notifications + Test Suite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Pushover push notifications to alert the admin when a new book request is submitted, then build a comprehensive test suite covering the request system, notifications, and core utilities.

**Architecture:** New `shelfmark/core/pushover_notifications.py` module (mirrors existing email pattern), settings fields added to General tab, helper wired into `create_request_route`. Tests use pytest + unittest.mock with in-memory SQLite and Flask test client.

**Tech Stack:** Python stdlib `urllib.request` for Pushover HTTP POST, pytest, unittest.mock, Flask test client, in-memory SQLite.

---

## Task 1: Pushover notifications module (TDD)

**Files:**
- Create: `tests/core/test_pushover_notifications.py`
- Create: `shelfmark/core/pushover_notifications.py`

---

**Step 1: Write the failing tests**

Create `tests/core/test_pushover_notifications.py`:

```python
"""Tests for Pushover admin notifications."""

from unittest.mock import MagicMock, patch


class TestSendNewRequestPushover:
    """Tests for send_new_request_pushover()."""

    def test_returns_false_when_disabled(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=False):
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")
        assert result is False

    def test_returns_false_when_user_key_missing(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=True), \
             patch("shelfmark.core.pushover_notifications._get_credentials", return_value=(None, "token")):
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")
        assert result is False

    def test_returns_false_when_token_missing(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=True), \
             patch("shelfmark.core.pushover_notifications._get_credentials", return_value=("userkey", None)):
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")
        assert result is False

    def test_sends_correct_payload_ebook(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status":1}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=True), \
             patch("shelfmark.core.pushover_notifications._get_credentials", return_value=("ukey", "tok")), \
             patch("urllib.request.urlopen", return_value=mock_response) as mock_post:
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")

        assert result is True
        call_args = mock_post.call_args[0][0]
        import urllib.parse
        body = urllib.parse.parse_qs(call_args.data.decode())
        assert body["token"] == ["tok"]
        assert body["user"] == ["ukey"]
        assert body["title"] == ["New Request"]
        assert "Dune" in body["message"][0]
        assert "Frank Herbert" in body["message"][0]
        assert "alice" in body["message"][0]
        assert "Ebook" in body["message"][0]

    def test_sends_correct_payload_audiobook(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status":1}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=True), \
             patch("shelfmark.core.pushover_notifications._get_credentials", return_value=("ukey", "tok")), \
             patch("urllib.request.urlopen", return_value=mock_response) as mock_post:
            result = send_new_request_pushover("The Hobbit", None, None, "audiobook")

        assert result is True
        call_args = mock_post.call_args[0][0]
        import urllib.parse
        body = urllib.parse.parse_qs(call_args.data.decode())
        assert "Audiobook" in body["message"][0]
        # No author or requester line when absent
        assert "By " not in body["message"][0]
        assert "Requested by" not in body["message"][0]

    def test_returns_false_on_http_error(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover
        import urllib.error

        with patch("shelfmark.core.pushover_notifications._is_enabled", return_value=True), \
             patch("shelfmark.core.pushover_notifications._get_credentials", return_value=("ukey", "tok")), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")
        assert result is False

    def test_never_raises(self):
        from shelfmark.core.pushover_notifications import send_new_request_pushover

        with patch("shelfmark.core.pushover_notifications._is_enabled", side_effect=Exception("boom")):
            result = send_new_request_pushover("Dune", "Frank Herbert", "alice", "ebook")
        assert result is False


class TestTestPushoverConnection:
    """Tests for test_pushover_connection() settings callback."""

    def test_returns_success_dict_on_ok(self):
        from shelfmark.core.pushover_notifications import test_pushover_connection

        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status":1}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        current_values = {"PUSHOVER_USER_KEY": "ukey", "PUSHOVER_API_TOKEN": "tok"}
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = test_pushover_connection(current_values)

        assert result["success"] is True
        assert "message" in result

    def test_returns_failure_when_credentials_missing(self):
        from shelfmark.core.pushover_notifications import test_pushover_connection

        result = test_pushover_connection({"PUSHOVER_USER_KEY": "", "PUSHOVER_API_TOKEN": ""})
        assert result["success"] is False
        assert "message" in result

    def test_returns_failure_on_http_error(self):
        from shelfmark.core.pushover_notifications import test_pushover_connection
        import urllib.error

        current_values = {"PUSHOVER_USER_KEY": "ukey", "PUSHOVER_API_TOKEN": "tok"}
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            result = test_pushover_connection(current_values)

        assert result["success"] is False
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_pushover_notifications.py -v
```

Expected: `ImportError` — module does not exist yet.

---

**Step 3: Implement `shelfmark/core/pushover_notifications.py`**

```python
"""Pushover push notifications for admin: fires when a new book request is submitted."""

import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


def _is_enabled() -> bool:
    try:
        import shelfmark.core.config as core_config
        return bool(core_config.config.get("PUSHOVER_ENABLED", False))
    except Exception:
        return False


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    try:
        import shelfmark.core.config as core_config
        user_key = core_config.config.get("PUSHOVER_USER_KEY", "") or None
        api_token = core_config.config.get("PUSHOVER_API_TOKEN", "") or None
        return user_key, api_token
    except Exception:
        return None, None


def send_new_request_pushover(
    title: str,
    author: Optional[str] = None,
    requester: Optional[str] = None,
    content_type: str = "ebook",
) -> bool:
    """Send a Pushover notification to the admin when a new request is created.

    Args:
        title: Book title.
        author: Book author (optional).
        requester: Username of the requesting user (optional).
        content_type: "ebook" or "audiobook".

    Returns:
        True if sent successfully, False otherwise. Never raises.
    """
    try:
        if not _is_enabled():
            return False

        user_key, api_token = _get_credentials()
        if not user_key or not api_token:
            logger.warning("Cannot send Pushover notification: user key or API token not configured")
            return False

        content_label = "Audiobook" if content_type == "audiobook" else "Ebook"
        lines = [f"{content_label}: {title}"]
        if author:
            lines.append(f"By {author}")
        if requester:
            lines.append(f"Requested by {requester}")
        message = "\n".join(lines)

        payload = urllib.parse.urlencode({
            "token": api_token,
            "user": user_key,
            "title": "New Request",
            "message": message,
            "priority": "0",
        }).encode()

        req = urllib.request.Request(
            _PUSHOVER_API_URL,
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

        logger.info(f"Pushover notification sent for new request: {title!r}")
        return True

    except Exception as e:
        logger.warning(f"Failed to send Pushover notification: {e}")
        return False


def test_pushover_connection(current_values: dict) -> dict:
    """Test Pushover connectivity using current form values (including unsaved changes).

    Used as a settings ActionButton callback.
    """
    user_key = (current_values.get("PUSHOVER_USER_KEY") or "").strip()
    api_token = (current_values.get("PUSHOVER_API_TOKEN") or "").strip()

    if not user_key or not api_token:
        return {"success": False, "message": "User Key and API Token are required"}

    try:
        payload = urllib.parse.urlencode({
            "token": api_token,
            "user": user_key,
            "title": "Shelfmark Test",
            "message": "Pushover is configured correctly.",
            "priority": "0",
        }).encode()

        req = urllib.request.Request(
            _PUSHOVER_API_URL,
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

        return {"success": True, "message": "Test notification sent"}

    except Exception as e:
        return {"success": False, "message": f"Pushover test failed: {e}"}
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/core/test_pushover_notifications.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add shelfmark/core/pushover_notifications.py tests/core/test_pushover_notifications.py
git commit -m "feat: add Pushover admin notification module with tests"
```

---

## Task 2: Pushover settings UI

**Files:**
- Modify: `shelfmark/config/settings.py` — add fields to `general_settings()`

**Step 1: Locate the insertion point**

In `general_settings()` (around line 402), after the `NOTIFY_REQUESTS_VIA_EMAIL` `CheckboxField`, add these four items. Also add the import at the top of the function.

**Step 2: Add the settings fields**

In `shelfmark/config/settings.py`, find this block at the bottom of the `general_settings()` return list:

```python
        CheckboxField(
            key="NOTIFY_REQUESTS_VIA_EMAIL",
            label="Email Request Notifications",
            description="Send email notifications to users when their book requests are approved, denied, fulfilled, or failed. Uses the SMTP settings from the Downloads tab.",
            default=False,
        ),
    ]
```

Replace with:

```python
        CheckboxField(
            key="NOTIFY_REQUESTS_VIA_EMAIL",
            label="Email Request Notifications",
            description="Send email notifications to users when their book requests are approved, denied, fulfilled, or failed. Uses the SMTP settings from the Downloads tab.",
            default=False,
        ),
        CheckboxField(
            key="PUSHOVER_ENABLED",
            label="Pushover Admin Notifications",
            description="Send a Pushover push notification to the admin when a new book request is submitted.",
            default=False,
        ),
        TextField(
            key="PUSHOVER_USER_KEY",
            label="User Key",
            description="Your Pushover user key from pushover.net/dashboard.",
            show_when={"field": "PUSHOVER_ENABLED", "value": True},
        ),
        PasswordField(
            key="PUSHOVER_API_TOKEN",
            label="API Token",
            description="Your Pushover application API token from pushover.net/apps.",
            show_when={"field": "PUSHOVER_ENABLED", "value": True},
        ),
        ActionButton(
            key="test_pushover",
            label="Send Test Notification",
            description="Send a test Pushover notification to verify your configuration.",
            style="primary",
            callback=test_pushover_connection,
            show_when={"field": "PUSHOVER_ENABLED", "value": True},
        ),
    ]
```

Also add this import near the top of `settings.py` alongside the other config imports (after `from shelfmark.config.email_settings import test_email_connection`):

```python
from shelfmark.core.pushover_notifications import test_pushover_connection
```

**Step 3: Verify the app still imports cleanly**

```bash
python -c "from shelfmark.config import settings; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add shelfmark/config/settings.py
git commit -m "feat: add Pushover settings to General tab"
```

---

## Task 3: Wire Pushover into request creation (TDD)

**Files:**
- Modify: `shelfmark/core/request_routes.py`
- Create: `tests/core/test_request_routes.py`

**Step 1: Write the failing test for Pushover firing on request creation**

Create `tests/core/test_request_routes.py`:

```python
"""Integration tests for request management API routes."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask

from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "shelfmark.db")


@pytest.fixture
def user_db(db_path):
    db = UserDB(db_path)
    db.initialize()
    return db


@pytest.fixture
def request_db(db_path, user_db):
    """RequestDB shares the same SQLite file as UserDB."""
    db = RequestDB(db_path)
    db.initialize()
    return db


@pytest.fixture
def sample_user(user_db):
    return user_db.create_user(username="alice", email="alice@example.com")


@pytest.fixture
def app(user_db, request_db):
    from shelfmark.core.request_routes import register_request_routes

    test_app = Flask(__name__)
    test_app.config["SECRET_KEY"] = "test-secret"
    test_app.config["TESTING"] = True

    with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
        register_request_routes(test_app, request_db, user_db)

    return test_app


@pytest.fixture
def user_client(app, sample_user):
    """Authenticated non-admin client."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = sample_user["username"]
        sess["db_user_id"] = sample_user["id"]
        sess["is_admin"] = False
    return client


@pytest.fixture
def admin_user(user_db):
    return user_db.create_user(username="admin", role="admin")


@pytest.fixture
def admin_client(app, admin_user):
    """Authenticated admin client."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = admin_user["username"]
        sess["db_user_id"] = admin_user["id"]
        sess["is_admin"] = True
    return client


# ---------------------------------------------------------------------------
# POST /api/requests
# ---------------------------------------------------------------------------

class TestCreateRequest:
    def test_creates_request_returns_201(self, user_client):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_pushover_new_request"):
            resp = user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Dune"
        assert data["status"] == "pending"

    def test_pushover_called_on_new_request(self, user_client):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_pushover_new_request") as mock_pushover:
            user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})
        mock_pushover.assert_called_once()

    def test_returns_400_when_title_missing(self, user_client):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = user_client.post("/api/requests", json={"content_type": "ebook"})
        assert resp.status_code == 400

    def test_returns_400_for_invalid_content_type(self, user_client):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = user_client.post("/api/requests", json={"title": "Dune", "content_type": "magazine"})
        assert resp.status_code == 400

    def test_duplicate_detection_returns_409(self, user_client):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_pushover_new_request"):
            user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})
            resp = user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})
        assert resp.status_code == 409

    def test_requires_authentication(self, app):
        unauthenticated = app.test_client()
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = unauthenticated.post("/api/requests", json={"title": "Dune"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/requests
# ---------------------------------------------------------------------------

class TestListRequests:
    def test_admin_sees_all_requests(self, admin_client, user_client, request_db, sample_user):
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_pushover_new_request"):
            user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})
            user_client.post("/api/requests", json={"title": "Foundation", "content_type": "ebook"})

        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = admin_client.get("/api/requests")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 2

    def test_user_sees_only_own_requests(self, user_client, admin_user, app, request_db):
        other_user_id = admin_user["id"]
        request_db.create_request(user_id=other_user_id, title="Other Book")

        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_pushover_new_request"):
            user_client.post("/api/requests", json={"title": "Dune", "content_type": "ebook"})

        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = user_client.get("/api/requests")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["requests"][0]["title"] == "Dune"


# ---------------------------------------------------------------------------
# DELETE /api/requests/<id>
# ---------------------------------------------------------------------------

class TestDeleteRequest:
    def test_owner_can_delete_own_request(self, user_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"):
            resp = user_client.delete(f"/api/requests/{req['id']}")
        assert resp.status_code == 200
        assert resp.get_json()["action"] == "deleted"

    def test_admin_hides_request_not_owned(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"):
            resp = admin_client.delete(f"/api/requests/{req['id']}")
        assert resp.status_code == 200
        assert resp.get_json()["action"] == "hidden"

    def test_non_owner_cannot_delete(self, admin_client, request_db, sample_user, app):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        other = app.test_client()
        with other.session_transaction() as sess:
            sess["user_id"] = "stranger"
            sess["db_user_id"] = 9999
            sess["is_admin"] = False
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = other.delete(f"/api/requests/{req['id']}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/requests/<id>/approve and /deny
# ---------------------------------------------------------------------------

class TestApproveAndDeny:
    def test_approve_sets_status(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune", content_type="audiobook")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_status_notification"):
            resp = admin_client.post(f"/api/requests/{req['id']}/approve")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "approved"

    def test_approve_non_pending_returns_400(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.update_request_status(req["id"], "fulfilled")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"):
            resp = admin_client.post(f"/api/requests/{req['id']}/approve")
        assert resp.status_code == 400

    def test_deny_sets_status_and_sends_notification(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_status_notification") as mock_notify:
            resp = admin_client.post(f"/api/requests/{req['id']}/deny", json={"admin_note": "Not available"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "denied"
        mock_notify.assert_called_once()

    def test_only_admin_can_approve(self, user_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"):
            resp = user_client.post(f"/api/requests/{req['id']}/approve")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /api/requests/<id>/status
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    def test_valid_status_update(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_status_notification"):
            resp = admin_client.put(
                f"/api/requests/{req['id']}/status",
                json={"status": "fulfilled"}
            )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "fulfilled"

    def test_invalid_status_returns_400(self, admin_client, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with patch("shelfmark.core.request_routes._get_auth_mode", return_value="builtin"), \
             patch("shelfmark.core.request_routes._broadcast_request_update"):
            resp = admin_client.put(
                f"/api/requests/{req['id']}/status",
                json={"status": "nonexistent"}
            )
        assert resp.status_code == 400
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_request_routes.py::TestCreateRequest::test_pushover_called_on_new_request -v
```

Expected: `AttributeError` — `_send_pushover_new_request` does not exist yet.

**Step 3: Add `_send_pushover_new_request` helper and call it in `request_routes.py`**

In `shelfmark/core/request_routes.py`, add the helper function after the existing `_send_status_notification` function (around line 98):

```python
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
```

Then in `create_request_route`, after `_broadcast_request_update(req)` (around line 181), add:

```python
        _send_pushover_new_request(req, user_db)
```

**Step 4: Run all request routes tests**

```bash
pytest tests/core/test_request_routes.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add shelfmark/core/request_routes.py tests/core/test_request_routes.py
git commit -m "feat: wire Pushover notification into request creation with tests"
```

---

## Task 4: RequestDB unit tests

**Files:**
- Create: `tests/core/test_request_db.py`

**Step 1: Write the tests**

Create `tests/core/test_request_db.py`:

```python
"""Tests for SQLite request database."""

import os
import tempfile

import pytest


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "shelfmark.db")


@pytest.fixture
def user_db(db_path):
    from shelfmark.core.user_db import UserDB
    db = UserDB(db_path)
    db.initialize()
    return db


@pytest.fixture
def request_db(db_path, user_db):
    from shelfmark.core.request_db import RequestDB
    db = RequestDB(db_path)
    db.initialize()
    return db


@pytest.fixture
def sample_user(user_db):
    return user_db.create_user(username="alice", email="alice@example.com")


class TestRequestDBInitialization:
    def test_initialize_creates_requests_table(self, request_db, db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='requests'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_initialize_is_idempotent(self, db_path, user_db):
        from shelfmark.core.request_db import RequestDB
        db = RequestDB(db_path)
        db.initialize()
        db.initialize()  # Should not raise


class TestCreateRequest:
    def test_create_minimal_request(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        assert req["id"] is not None
        assert req["title"] == "Dune"
        assert req["status"] == "pending"
        assert req["content_type"] == "ebook"

    def test_create_request_with_all_fields(self, request_db, sample_user):
        req = request_db.create_request(
            user_id=sample_user["id"],
            title="Dune",
            content_type="audiobook",
            author="Frank Herbert",
            year="1965",
            isbn_13="9780441013593",
            provider="openlibrary",
            provider_id="OL123M",
            series_name="Dune Chronicles",
            series_position=1.0,
        )
        assert req["author"] == "Frank Herbert"
        assert req["content_type"] == "audiobook"
        assert req["series_name"] == "Dune Chronicles"

    def test_create_request_invalid_content_type_raises(self, request_db, sample_user):
        with pytest.raises(ValueError, match="Invalid content_type"):
            request_db.create_request(user_id=sample_user["id"], title="Dune", content_type="magazine")

    def test_create_request_includes_requester_username(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        assert req["requester_username"] == "alice"

    def test_cover_url_sanitized(self, request_db, sample_user):
        req = request_db.create_request(
            user_id=sample_user["id"],
            title="Dune",
            cover_url="javascript:alert(1)",
        )
        assert req["cover_url"] is None

    def test_cover_url_http_accepted(self, request_db, sample_user):
        req = request_db.create_request(
            user_id=sample_user["id"],
            title="Dune",
            cover_url="https://example.com/cover.jpg",
        )
        assert req["cover_url"] == "https://example.com/cover.jpg"


class TestGetRequest:
    def test_get_existing_request(self, request_db, sample_user):
        created = request_db.create_request(user_id=sample_user["id"], title="Dune")
        fetched = request_db.get_request(created["id"])
        assert fetched["title"] == "Dune"

    def test_get_nonexistent_request_returns_none(self, request_db):
        assert request_db.get_request(9999) is None


class TestListRequests:
    def test_list_all_requests(self, request_db, sample_user):
        request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.create_request(user_id=sample_user["id"], title="Foundation")
        results = request_db.list_requests()
        assert len(results) == 2

    def test_list_by_user_id(self, request_db, user_db, sample_user):
        other = user_db.create_user(username="bob")
        request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.create_request(user_id=other["id"], title="Foundation")
        results = request_db.list_requests(user_id=sample_user["id"])
        assert len(results) == 1
        assert results[0]["title"] == "Dune"

    def test_list_by_status(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.update_request_status(req["id"], "fulfilled")
        request_db.create_request(user_id=sample_user["id"], title="Foundation")
        results = request_db.list_requests(status="pending")
        assert len(results) == 1
        assert results[0]["title"] == "Foundation"

    def test_admin_view_excludes_hidden(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.hide_request_from_admin(req["id"])
        results = request_db.list_requests()  # Admin view, user_id=None
        assert len(results) == 0

    def test_user_view_includes_hidden_from_admin(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.hide_request_from_admin(req["id"])
        results = request_db.list_requests(user_id=sample_user["id"])
        assert len(results) == 1


class TestUpdateRequestStatus:
    def test_update_status(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        updated = request_db.update_request_status(req["id"], "approved")
        assert updated["status"] == "approved"

    def test_update_with_admin_note(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        updated = request_db.update_request_status(req["id"], "denied", admin_note="Not found")
        assert updated["admin_note"] == "Not found"

    def test_invalid_status_raises(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        with pytest.raises(ValueError, match="Invalid status"):
            request_db.update_request_status(req["id"], "nonexistent")

    def test_all_valid_statuses_accepted(self, request_db, sample_user):
        statuses = ["approved", "denied", "downloading", "fulfilled", "failed", "cancelled", "pending"]
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        for status in statuses:
            updated = request_db.update_request_status(req["id"], status)
            assert updated["status"] == status


class TestCountRequests:
    def test_count_all(self, request_db, sample_user):
        request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.create_request(user_id=sample_user["id"], title="Foundation")
        assert request_db.count_requests() == 2

    def test_count_by_status(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        request_db.update_request_status(req["id"], "fulfilled")
        request_db.create_request(user_id=sample_user["id"], title="Foundation")
        assert request_db.count_requests(status="pending") == 1
        assert request_db.count_requests(status="fulfilled") == 1

    def test_get_request_counts_returns_all_statuses(self, request_db, sample_user):
        counts = request_db.get_request_counts()
        assert "pending" in counts
        assert "fulfilled" in counts
        assert "total" in counts


class TestDeleteAndHide:
    def test_delete_request(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        result = request_db.delete_request(req["id"])
        assert result is True
        assert request_db.get_request(req["id"]) is None

    def test_delete_nonexistent_returns_false(self, request_db):
        assert request_db.delete_request(9999) is False

    def test_hide_from_admin(self, request_db, sample_user):
        req = request_db.create_request(user_id=sample_user["id"], title="Dune")
        result = request_db.hide_request_from_admin(req["id"])
        assert result is True
        # Still retrievable directly
        assert request_db.get_request(req["id"]) is not None
        # But excluded from admin list
        assert len(request_db.list_requests()) == 0


class TestGetUnviewedCount:
    def test_unviewed_count_before_any_view(self, request_db, sample_user):
        request_db.create_request(user_id=sample_user["id"], title="Dune")
        count = request_db.get_unviewed_count(sample_user["id"])
        assert count == 1

    def test_unviewed_count_after_mark_viewed(self, request_db, user_db, sample_user):
        request_db.create_request(user_id=sample_user["id"], title="Dune")
        user_db.update_requests_last_viewed(sample_user["id"])
        count = request_db.get_unviewed_count(sample_user["id"])
        assert count == 0
```

**Step 2: Run tests**

```bash
pytest tests/core/test_request_db.py -v
```

Expected: All tests PASS (no new implementation needed — RequestDB already exists).

**Step 3: Commit**

```bash
git add tests/core/test_request_db.py
git commit -m "test: add RequestDB unit tests"
```

---

## Task 5: Email notification unit tests

**Files:**
- Create: `tests/core/test_request_notifications.py`

**Step 1: Write the tests**

Create `tests/core/test_request_notifications.py`:

```python
"""Tests for SMTP request status notifications."""

from unittest.mock import MagicMock, patch


class TestIsNotificationEnabled:
    def test_returns_false_when_disabled(self):
        from shelfmark.core.request_notifications import _is_notification_enabled

        with patch("shelfmark.core.request_notifications.shelfmark.core.config") as mock_cfg:
            mock_cfg.config.get.return_value = False
            # Reimport to get fresh module state
            import importlib
            import shelfmark.core.request_notifications as mod
            importlib.reload(mod)

    def test_returns_false_on_import_error(self):
        from shelfmark.core.request_notifications import _is_notification_enabled
        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=False):
            from shelfmark.core.request_notifications import send_request_notification
            result = send_request_notification("user@example.com", "Dune", "approved")
        assert result is False


class TestSendRequestNotification:
    def test_returns_false_when_disabled(self):
        from shelfmark.core.request_notifications import send_request_notification
        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=False):
            result = send_request_notification("user@example.com", "Dune", "approved")
        assert result is False

    def test_returns_false_when_email_empty(self):
        from shelfmark.core.request_notifications import send_request_notification
        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True):
            result = send_request_notification("", "Dune", "approved")
        assert result is False

    def test_returns_false_when_smtp_not_configured(self):
        from shelfmark.core.request_notifications import send_request_notification
        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True), \
             patch("shelfmark.core.request_notifications._get_smtp_config", return_value=None):
            result = send_request_notification("user@example.com", "Dune", "approved")
        assert result is False

    def test_sends_email_for_approved_status(self):
        from shelfmark.core.request_notifications import send_request_notification

        mock_smtp = MagicMock()
        mock_smtp.from_addr = "shelfmark@example.com"

        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True), \
             patch("shelfmark.core.request_notifications._get_smtp_config", return_value=mock_smtp), \
             patch("shelfmark.core.request_notifications.send_email_message") as mock_send:
            result = send_request_notification("user@example.com", "Dune", "approved")

        assert result is True
        mock_send.assert_called_once()
        call_msg = mock_send.call_args[0][1]
        assert "Approved" in call_msg["Subject"]
        assert "Dune" in call_msg["Subject"]

    def test_email_includes_admin_note(self):
        from shelfmark.core.request_notifications import send_request_notification

        mock_smtp = MagicMock()
        mock_smtp.from_addr = "shelfmark@example.com"

        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True), \
             patch("shelfmark.core.request_notifications._get_smtp_config", return_value=mock_smtp), \
             patch("shelfmark.core.request_notifications.send_email_message") as mock_send:
            send_request_notification("user@example.com", "Dune", "denied", admin_note="Not available")

        call_msg = mock_send.call_args[0][1]
        body = call_msg.get_payload()
        assert "Not available" in body

    def test_all_statuses_have_messages(self):
        from shelfmark.core.request_notifications import STATUS_MESSAGES
        for status in ("approved", "denied", "fulfilled", "failed"):
            assert status in STATUS_MESSAGES
            assert len(STATUS_MESSAGES[status]) > 0

    def test_returns_false_on_smtp_exception(self):
        from shelfmark.core.request_notifications import send_request_notification

        mock_smtp = MagicMock()
        mock_smtp.from_addr = "shelfmark@example.com"

        with patch("shelfmark.core.request_notifications._is_notification_enabled", return_value=True), \
             patch("shelfmark.core.request_notifications._get_smtp_config", return_value=mock_smtp), \
             patch("shelfmark.core.request_notifications.send_email_message", side_effect=Exception("SMTP fail")):
            result = send_request_notification("user@example.com", "Dune", "approved")
        assert result is False
```

**Step 2: Run tests**

```bash
pytest tests/core/test_request_notifications.py -v
```

Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/core/test_request_notifications.py
git commit -m "test: add email request notification unit tests"
```

---

## Task 6: Settings on_save validator tests

**Files:**
- Create: `tests/config/test_settings_validators.py`

**Step 1: Write the tests**

Create `tests/config/test_settings_validators.py`:

```python
"""Tests for settings on_save validators in config/settings.py."""


class TestOnSaveDownloads:
    """Tests for _on_save_downloads validator."""

    def _call(self, values):
        from shelfmark.config.settings import _on_save_downloads
        return _on_save_downloads(values)

    def test_folder_mode_passes_without_smtp(self):
        result = self._call({"BOOKS_OUTPUT_MODE": "folder"})
        assert not result.get("error")

    def test_rename_template_with_slash_rejected(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "folder",
            "FILE_ORGANIZATION": "rename",
            "TEMPLATE_RENAME": "Author/Title",
        })
        assert result["error"] is True
        assert "/" in result["message"]

    def test_organize_template_with_slash_accepted(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "folder",
            "FILE_ORGANIZATION": "organize",
            "TEMPLATE_ORGANIZE": "{Author}/{Title}",
        })
        assert not result.get("error")

    def test_email_mode_requires_smtp_host(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "email",
            "EMAIL_SMTP_HOST": "",
            "EMAIL_RECIPIENTS": [{"nickname": "Me", "email": "me@example.com"}],
            "EMAIL_FROM": "shelfmark@example.com",
        })
        assert result["error"] is True

    def test_email_mode_rejects_invalid_recipient_email(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "email",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_RECIPIENTS": [{"nickname": "Me", "email": "not-an-email"}],
            "EMAIL_FROM": "from@example.com",
        })
        assert result["error"] is True

    def test_email_mode_rejects_duplicate_nicknames(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "email",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_RECIPIENTS": [
                {"nickname": "eReader", "email": "a@example.com"},
                {"nickname": "eReader", "email": "b@example.com"},
            ],
            "EMAIL_FROM": "from@example.com",
        })
        assert result["error"] is True

    def test_email_mode_rejects_invalid_port(self):
        result = self._call({
            "BOOKS_OUTPUT_MODE": "email",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_SMTP_PORT": 99999,
            "EMAIL_RECIPIENTS": [{"nickname": "Me", "email": "me@example.com"}],
            "EMAIL_FROM": "from@example.com",
        })
        assert result["error"] is True

    def test_email_mode_rejects_password_without_username(self):
        # username set but no password — should fail
        result = self._call({
            "BOOKS_OUTPUT_MODE": "email",
            "EMAIL_SMTP_HOST": "smtp.example.com",
            "EMAIL_SMTP_PORT": 587,
            "EMAIL_SMTP_SECURITY": "starttls",
            "EMAIL_SMTP_USERNAME": "user@example.com",
            "EMAIL_SMTP_PASSWORD": "",
            "EMAIL_FROM": "from@example.com",
            "EMAIL_RECIPIENTS": [{"nickname": "Me", "email": "me@example.com"}],
            "EMAIL_ATTACHMENT_SIZE_LIMIT_MB": 25,
            "EMAIL_SMTP_TIMEOUT_SECONDS": 60,
        })
        assert result["error"] is True


class TestOnSaveAdvanced:
    """Tests for _on_save_advanced validator (path mappings)."""

    def _call(self, values):
        from shelfmark.config.settings import _on_save_advanced
        return _on_save_advanced(values)

    def test_no_mappings_passes(self):
        result = self._call({})
        assert not result.get("error")

    def test_valid_mapping_passes(self):
        result = self._call({
            "PROWLARR_REMOTE_PATH_MAPPINGS": [
                {"host": "qbittorrent", "remotePath": "/downloads", "localPath": "/data/downloads"}
            ]
        })
        assert not result.get("error")
        assert len(result["values"]["PROWLARR_REMOTE_PATH_MAPPINGS"]) == 1

    def test_incomplete_mapping_entry_is_skipped(self):
        result = self._call({
            "PROWLARR_REMOTE_PATH_MAPPINGS": [
                {"host": "qbittorrent", "remotePath": "", "localPath": "/data"}
            ]
        })
        assert not result.get("error")
        assert result["values"]["PROWLARR_REMOTE_PATH_MAPPINGS"] == []

    def test_relative_local_path_rejected(self):
        result = self._call({
            "PROWLARR_REMOTE_PATH_MAPPINGS": [
                {"host": "qbittorrent", "remotePath": "/downloads", "localPath": "relative/path"}
            ]
        })
        assert result["error"] is True

    def test_non_list_mappings_rejected(self):
        result = self._call({"PROWLARR_REMOTE_PATH_MAPPINGS": "not a list"})
        assert result["error"] is True


class TestOnSaveMirrors:
    """Tests for _on_save_mirrors URL normalization."""

    def _call(self, values):
        from shelfmark.config.settings import _on_save_mirrors
        return _on_save_mirrors(values)

    def test_no_urls_skips_processing(self):
        result = self._call({})
        assert not result.get("error")

    def test_normalizes_url_list(self):
        result = self._call({"AA_MIRROR_URLS": ["annas-archive.org", "https://annas-archive.se"]})
        assert not result.get("error")
        urls = result["values"]["AA_MIRROR_URLS"]
        assert all(u.startswith("https://") for u in urls)

    def test_auto_value_stripped(self):
        result = self._call({"AA_MIRROR_URLS": ["auto", "https://annas-archive.se"]})
        urls = result["values"]["AA_MIRROR_URLS"]
        assert "auto" not in urls

    def test_empty_list_falls_back_to_defaults(self):
        result = self._call({"AA_MIRROR_URLS": []})
        assert not result.get("error")
        urls = result["values"]["AA_MIRROR_URLS"]
        assert len(urls) > 0
```

**Step 2: Run tests**

```bash
pytest tests/config/test_settings_validators.py -v
```

Expected: All tests PASS.

**Step 3: Commit**

```bash
git add tests/config/test_settings_validators.py
git commit -m "test: add settings on_save validator tests"
```

---

## Task 7: Run the full test suite and verify

**Step 1: Run all new tests together**

```bash
pytest tests/core/test_pushover_notifications.py \
       tests/core/test_request_routes.py \
       tests/core/test_request_db.py \
       tests/core/test_request_notifications.py \
       tests/config/test_settings_validators.py \
       -v
```

Expected: All tests PASS.

**Step 2: Run the full suite to check for regressions**

```bash
pytest -m "not e2e and not integration" -v
```

Expected: All tests PASS. No regressions.

**Step 3: Final commit if any fixes needed**

```bash
git add -p
git commit -m "fix: resolve any test suite issues"
```

---

## Summary of files changed

| Action | File |
|--------|------|
| Create | `shelfmark/core/pushover_notifications.py` |
| Modify | `shelfmark/config/settings.py` |
| Modify | `shelfmark/core/request_routes.py` |
| Create | `tests/core/test_pushover_notifications.py` |
| Create | `tests/core/test_request_routes.py` |
| Create | `tests/core/test_request_db.py` |
| Create | `tests/core/test_request_notifications.py` |
| Create | `tests/config/test_settings_validators.py` |
