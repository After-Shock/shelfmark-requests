"""The cover proxy must not fetch internal hosts (SSRF) — directly or via redirects."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from shelfmark.core.image_cache import ImageCacheService


def _resolve_to(ip: str):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return lambda host, port, *a, **k: [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "192.168.0.1", "172.16.3.4",
    "169.254.169.254",  # cloud metadata
    "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1",
])
def test_blocks_internal_addresses(ip):
    with patch("socket.getaddrinfo", _resolve_to(ip)):
        assert ImageCacheService._prepare_safe_url("http://cover.example/x.jpg") is None


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/a.jpg", "gopher://example.com/",
    "http:\\\\example.com\\a.jpg", "http://example.com\n/a.jpg",
    "http://evil%2f@example.com/", "not a url", "",
])
def test_rejects_malformed_or_non_http(url):
    with patch("socket.getaddrinfo", _resolve_to("93.184.216.34")):
        assert ImageCacheService._prepare_safe_url(url) is None


def test_allows_public_host():
    with patch("socket.getaddrinfo", _resolve_to("93.184.216.34")):
        assert ImageCacheService._prepare_safe_url("https://covers.openlibrary.org/b/id/1-L.jpg")


def test_blocks_redirect_into_lan(tmp_path):
    cache = ImageCacheService(tmp_path)
    redirect = MagicMock(is_redirect=True, headers={"location": "http://router.lan/admin"})

    def resolve(host, *a, **k):
        return _resolve_to("192.168.0.1" if host == "router.lan" else "93.184.216.34")(host, 0)

    with patch("socket.getaddrinfo", resolve), \
            patch("shelfmark.core.image_cache.requests.get", return_value=redirect) as get:
        assert cache.fetch_and_cache("c1", "https://public.example/cover.jpg") is None
    assert get.call_count == 1  # never connected to the LAN host
    assert get.call_args.kwargs["allow_redirects"] is False


def test_blocked_url_is_never_requested(tmp_path):
    cache = ImageCacheService(tmp_path)
    with patch("socket.getaddrinfo", _resolve_to("127.0.0.1")), \
            patch("shelfmark.core.image_cache.requests.get") as get:
        assert cache.fetch_and_cache("c2", "http://localhost:8084/api/admin") is None
    get.assert_not_called()
