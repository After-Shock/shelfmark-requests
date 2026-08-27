"""
Tests for Audiobookshelf user provisioning.

When a user signs up on Shelfmark, a matching account should be created on the
configured Audiobookshelf server (same username/password).
"""

import types

import pytest

import shelfmark.core.abs_user_sync as abs_user_sync


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {}


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


def test_creates_user(configured, monkeypatch):
    """A new signup results in a user creation call to the ABS API."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(200)

    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(404))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)

    result = abs_user_sync.provision_abs_user("alice", "pw1234", role="user")

    assert result["status"] == "created"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://audiobooks.sullyflix.com/api/users"
    assert calls[0]["json"] == {"username": "alice", "password": "pw1234", "type": "user"}
    assert calls[0]["headers"]["Authorization"] == "Bearer test-token"


def test_admin_role_maps_to_admin_type(configured, monkeypatch):
    """Shelfmark admins map to ABS admin accounts."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(404))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)

    abs_user_sync.provision_abs_user("bob", "pw1234", role="admin")
    assert captured["json"]["type"] == "admin"


def test_existing_user_not_touched(configured, monkeypatch):
    """If the username already exists on ABS, nothing is changed."""
    posts = []

    def fake_post(url, **k):
        posts.append(url)
        return FakeResponse(200)

    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(200))
    monkeypatch.setattr(abs_user_sync.http_requests, "post", fake_post)

    result = abs_user_sync.provision_abs_user("alice", "pw1234")
    assert result["status"] == "exists"
    assert posts == []


def test_non_admin_token_reports_error(configured, monkeypatch):
    """A 403 from ABS means the token isn't an admin token."""
    monkeypatch.setattr(abs_user_sync.http_requests, "get", lambda url, **k: FakeResponse(404))
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


def test_is_enabled(configured):
    assert abs_user_sync.is_enabled() is True
