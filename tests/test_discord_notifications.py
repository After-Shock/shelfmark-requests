"""Tests for Discord webhook notifications."""
import json
from unittest.mock import MagicMock, patch, call
import pytest


def test_build_new_request_embed_basic():
    from shelfmark.core.discord_notifications import build_new_request_embed
    embed = build_new_request_embed(
        title="Dune",
        author="Frank Herbert",
        requester="alice",
        content_type="ebook",
        cover_url=None,
    )
    assert embed["title"] == "🔖 New Book Request"
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Title"] == "Dune"
    assert fields["Author"] == "Frank Herbert"
    assert fields["Requested by"] == "alice"
    assert fields["Type"] == "ebook"
    assert "thumbnail" not in embed


def test_build_new_request_embed_with_cover():
    from shelfmark.core.discord_notifications import build_new_request_embed
    embed = build_new_request_embed(
        title="Dune", author=None, requester="bob",
        content_type="audiobook", cover_url="https://example.com/cover.jpg"
    )
    assert embed.get("thumbnail") == {"url": "https://example.com/cover.jpg"}


def test_build_new_request_embed_rejects_non_http_cover():
    from shelfmark.core.discord_notifications import build_new_request_embed
    embed = build_new_request_embed(
        title="Dune", author=None, requester="bob",
        content_type="ebook", cover_url="javascript:alert(1)"
    )
    assert "thumbnail" not in embed


def test_build_book_available_embed():
    from shelfmark.core.discord_notifications import build_book_available_embed
    embed = build_book_available_embed(
        title="Foundation",
        author="Isaac Asimov",
        requester="charlie",
        cover_url=None,
    )
    assert embed["title"] == "📗 Book Now Available"
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert fields["Title"] == "Foundation"
    assert fields["Author"] == "Isaac Asimov"
    assert fields["Requested by"] == "charlie"


def test_send_discord_new_request_disabled(monkeypatch):
    from shelfmark.core import discord_notifications
    monkeypatch.setattr(discord_notifications, "_is_enabled", lambda: False)
    from shelfmark.core.discord_notifications import send_discord_new_request
    result = send_discord_new_request("Dune", author="Frank Herbert", requester="alice")
    assert result is False


def test_send_discord_new_request_no_webhook(monkeypatch):
    from shelfmark.core import discord_notifications
    monkeypatch.setattr(discord_notifications, "_is_enabled", lambda: True)
    monkeypatch.setattr(discord_notifications, "_get_webhook_url", lambda: None)
    from shelfmark.core.discord_notifications import send_discord_new_request
    result = send_discord_new_request("Dune", author=None, requester="alice")
    assert result is False


def test_send_discord_new_request_notify_disabled(monkeypatch):
    from shelfmark.core import discord_notifications
    monkeypatch.setattr(discord_notifications, "_is_enabled", lambda: True)
    monkeypatch.setattr(discord_notifications, "_get_webhook_url", lambda: "https://discord.com/api/webhooks/123/token")
    monkeypatch.setattr(discord_notifications, "_get_notify_new_request", lambda: False)
    from shelfmark.core.discord_notifications import send_discord_new_request
    result = send_discord_new_request("Dune", author=None, requester="alice")
    assert result is False


def test_send_discord_new_request_fires_http(monkeypatch):
    from shelfmark.core import discord_notifications
    import urllib.request as urllib_request
    monkeypatch.setattr(discord_notifications, "_is_enabled", lambda: True)
    monkeypatch.setattr(discord_notifications, "_get_webhook_url", lambda: "https://discord.com/api/webhooks/123/token")
    monkeypatch.setattr(discord_notifications, "_get_notify_new_request", lambda: True)

    posted_payloads = []

    class FakeResp:
        def read(self): return b""
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=10):
        posted_payloads.append(json.loads(req.data))
        return FakeResp()

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)

    from shelfmark.core.discord_notifications import send_discord_new_request
    result = send_discord_new_request("Dune", author="Frank Herbert", requester="alice", content_type="ebook")
    assert result is True
    assert len(posted_payloads) == 1
    assert posted_payloads[0]["embeds"][0]["title"] == "🔖 New Book Request"


def test_send_discord_book_available_fires(monkeypatch):
    from shelfmark.core import discord_notifications
    import urllib.request as urllib_request
    monkeypatch.setattr(discord_notifications, "_is_enabled", lambda: True)
    monkeypatch.setattr(discord_notifications, "_get_webhook_url", lambda: "https://discord.com/api/webhooks/123/token")
    monkeypatch.setattr(discord_notifications, "_get_notify_book_available", lambda: True)

    posted_payloads = []

    class FakeResp:
        def read(self): return b""
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=10):
        posted_payloads.append(json.loads(req.data))
        return FakeResp()

    monkeypatch.setattr(urllib_request, "urlopen", fake_urlopen)

    from shelfmark.core.discord_notifications import send_discord_book_available
    result = send_discord_book_available("Foundation", author="Asimov", requester="charlie")
    assert result is True
    assert posted_payloads[0]["embeds"][0]["title"] == "📗 Book Now Available"


def test_test_discord_connection_no_url():
    from shelfmark.core.discord_notifications import test_discord_connection
    result = test_discord_connection({})
    assert result["success"] is False
    assert "required" in result["message"].lower() or "url" in result["message"].lower()


def test_test_discord_connection_invalid_url():
    from shelfmark.core.discord_notifications import test_discord_connection
    result = test_discord_connection({"DISCORD_WEBHOOK_URL": "https://notdiscord.com/webhook"})
    assert result["success"] is False
