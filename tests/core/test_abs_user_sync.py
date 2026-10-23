"""
Tests for Audiobookshelf user provisioning.

When a user signs up on Shelfmark, a matching account should be created on the
configured Audiobookshelf server (same username/password).
"""

import types

import pytest

import shelfmark.core.abs_user_sync as abs_user_sync


class FakeResponse:
    def __init__(self, status_code, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise abs_user_sync.http_requests.HTTPError(self.text)


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def configured(monkeypatch):
    """Configure the sync module with fake ABS credentials, enabled."""
    monkeypatch.setattr(
        abs_user_sync,
        "config",
        FakeConfig(
            {
                "AUDIOBOOK_LIBRARY_URL": "https://audiobooks.sullyflix.com",
                "ABS_API_TOKEN": "test-token",
                "ABS_USER_SYNC_ENABLED": True,
            }
        ),
    )


def test_skipped_when_disabled():
    """Sync is a no-op when the toggle is off."""
    abs_user_sync.config = FakeConfig(
        {
            "AUDIOBOOK_LIBRARY_URL": "https://audiobooks.sullyflix.com",
            "ABS_API_TOKEN": "test-token",
            "ABS_USER_SYNC_ENABLED": False,
        }
    )
    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "skipped"


def test_skipped_when_unconfigured():
    """Sync is skipped when ABS URL/token are missing."""
    abs_user_sync.config = FakeConfig({"ABS_USER_SYNC_ENABLED": True})
    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "skipped"


def test_creates_user_enabled_with_explicit_access(configured, monkeypatch):
    """New ABS users are created enabled, with all libraries and explicit content."""
    calls = []
    gets = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(200)

    def fake_get(url, **k):
        gets.append(url)
        if url.endswith("/api/users"):
            return FakeResponse(200, payload={"users": [{"id": "user-1", "username": "alice"}] if len(gets) > 1 else []})
        return FakeResponse(200, payload={"id": "user-1", "isActive": True,
                                          "permissions": {"accessAllLibraries": True, "accessExplicitContent": True}})

    def no_patch(*a, **k):
        raise AssertionError("ABS honored the create payload; no PATCH needed")

    monkeypatch.setattr(abs_user_sync.http_requests, "get", fake_get)
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)
    monkeypatch.setattr(abs_user_sync.http_requests, "patch", no_patch)

    result = abs_user_sync.provision_abs_user("alice", "pw1234", role="user")

    assert result["status"] == "created"
    [call] = calls
    assert call["url"] == "https://audiobooks.sullyflix.com/api/users"
    assert call["headers"]["Authorization"] == "Bearer test-token"
    body = call["json"]
    assert (body["username"], body["password"], body["type"]) == ("alice", "pw1234", "user")
    assert body["isActive"] is True
    assert body["permissions"]["accessExplicitContent"] is True
    assert body["permissions"]["accessAllLibraries"] is True


def test_admin_role_maps_to_admin_type(configured, monkeypatch):
    """Shelfmark admins map to ABS admin accounts."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(200, payload={"users": []}))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)

    abs_user_sync.provision_abs_user("bob", "pw1234", role="admin")
    assert captured["json"]["type"] == "admin"


def test_existing_user_not_touched(configured, monkeypatch):
    """If the username already exists on ABS, nothing is changed."""
    posts = []

    def fake_post(url, **k):
        posts.append(url)
        return FakeResponse(200)

    # ABS compares usernames case-insensitively, so "Alice" is the same account.
    users = {"users": [{"id": "u1", "username": "Alice"}]}
    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(200, payload=users))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)

    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "exists"
    assert posts == []


def test_non_admin_token_reports_error(configured, monkeypatch):
    """A 403 from ABS means the token isn't an admin token."""
    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(200, payload={"users": []}))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", lambda url, **k: FakeResponse(403))

    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "error"
    assert "admin" in result["message"].lower()


def test_unreachable_server_reports_error(configured, monkeypatch):
    """Network errors are reported, not raised."""
    monkeypatch.setattr(
        abs_user_sync.http_requests,
        "get",
        lambda url, **k: (_ for _ in ()).throw(abs_user_sync.http_requests.ConnectionError("boom")),
    )

    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "error"


def test_new_user_created_disabled_is_patched_on(configured, monkeypatch):
    """If ABS ignores the create settings, the user is PATCHed enabled with explicit access."""
    gets = []
    patches = []

    def fake_get(url, **k):
        gets.append(url)
        if url.endswith("/api/users"):
            return FakeResponse(200, payload={"users": [{"id": "u1", "username": "austin"}] if len(gets) > 1 else []})
        return FakeResponse(200, payload={"id": "u1", "isActive": False,
                                          "permissions": {"download": True, "accessAllLibraries": True,
                                                          "accessExplicitContent": False}})

    def fake_patch(url, headers=None, json=None, timeout=None):
        patches.append((url, json))
        return FakeResponse(200)

    monkeypatch.setattr(abs_user_sync.http_requests, "get", fake_get)
    monkeypatch.setattr(abs_user_sync.http_requests, "post", lambda url, **k: FakeResponse(201))
    monkeypatch.setattr(abs_user_sync.http_requests, "patch", fake_patch)

    assert abs_user_sync.provision_abs_user("austin", "pw1234")["status"] == "created"
    [(url, body)] = patches
    assert url == "https://audiobooks.sullyflix.com/api/users/u1"
    assert body["isActive"] is True
    assert body["permissions"]["accessExplicitContent"] is True
    assert body["permissions"]["download"] is True  # existing permissions kept


def test_password_update_uses_patch(configured, monkeypatch):
    """ABS has no PUT /api/users/:id; password changes must PATCH just the password."""
    patches = []
    monkeypatch.setattr(abs_user_sync.http_requests, "get",
                        lambda url, **k: FakeResponse(200, payload={"users": [{"id": "u1", "username": "Alice"}]}))
    monkeypatch.setattr(abs_user_sync.http_requests, "patch",
                        lambda url, headers=None, json=None, timeout=None: patches.append((url, json)) or FakeResponse(200))

    assert abs_user_sync.update_abs_password("alice", "new-pw")["status"] == "updated"
    assert patches == [("https://audiobooks.sullyflix.com/api/users/u1", {"password": "new-pw"})]


def test_is_enabled(configured):
    assert abs_user_sync.is_enabled() is True
