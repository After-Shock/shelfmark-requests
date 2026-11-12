"""The destination guard behind the direct-download fetchers (ported from upstream f837506)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shelfmark.core import mirrors
from shelfmark.download import http, network


def _resolve_to(monkeypatch, table: dict) -> None:
    def fake_getaddrinfo(host, *_args, **_kwargs):
        if host not in table:
            raise network.socket.gaierror(-2, "Name or service not known")
        return [(None, None, None, None, (table[host], 0))]

    monkeypatch.setattr(network, "_system_getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
def no_mirrors(monkeypatch):
    monkeypatch.setattr(mirrors, "_get_config", lambda: {})


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.17.0.2", "192.168.1.5", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
])
def test_non_public_addresses_are_refused(monkeypatch, address):
    _resolve_to(monkeypatch, {"evil.example": address})
    with pytest.raises(network.UnsafeDestinationError):
        network.ensure_public_destination("https://evil.example/x")


def test_literal_ip_hosts_are_refused():
    with pytest.raises(network.UnsafeDestinationError):
        network.ensure_public_destination("http://127.0.0.1:8080/")


def test_one_private_answer_among_public_ones_is_refused(monkeypatch):
    monkeypatch.setattr(network, "_system_getaddrinfo", lambda *_a, **_k: [
        (None, None, None, None, ("93.184.216.34", 0)),
        (None, None, None, None, ("10.0.0.5", 0)),
    ])
    with pytest.raises(network.UnsafeDestinationError):
        network.ensure_public_destination("https://mixed.example/")


def test_public_and_unresolvable_hosts_pass(monkeypatch):
    _resolve_to(monkeypatch, {"ok.example": "93.184.216.34", "v6.example": "2606:2800:220:1::1"})
    network.ensure_public_destination("https://ok.example/book")
    network.ensure_public_destination("https://v6.example/book")
    network.ensure_public_destination("https://does-not-resolve.example/book")


def test_other_schemes_are_refused():
    with pytest.raises(network.UnsafeDestinationError):
        network.ensure_public_destination("file:///etc/passwd")


def test_configured_mirror_on_a_private_address_is_allowed(monkeypatch):
    monkeypatch.setattr(mirrors, "_get_config", lambda: {"LIBGEN_ADDITIONAL_URLS": "http://lan-mirror.home"})
    _resolve_to(monkeypatch, {"lan-mirror.home": "192.168.1.20"})
    network.ensure_public_destination("http://lan-mirror.home/book")


def test_redirect_hook_checks_each_hop(monkeypatch):
    _resolve_to(monkeypatch, {"ok.example": "93.184.216.34", "internal.example": "10.0.0.9"})
    hook = network.REDIRECT_GUARD_HOOKS["response"][0]

    def hop(location):
        return SimpleNamespace(is_redirect=True, url="https://ok.example/a", headers={"Location": location})

    hook(hop("/b"))
    with pytest.raises(network.UnsafeDestinationError):
        hook(hop("http://internal.example/secret"))
    with pytest.raises(network.UnsafeDestinationError):
        hook(hop("http://127.0.0.1/"))
    hook(SimpleNamespace(is_redirect=False, url="https://ok.example/a", headers={}))


# --- wiring: the fetchers refuse before connecting, and pass the redirect hook ---------------

def test_html_get_page_refuses_lan_target_without_connecting():
    with patch.object(http, "requests") as fake_requests:
        assert http.html_get_page("http://192.168.0.1/admin", retry=1) == ""
    fake_requests.get.assert_not_called()


def test_download_url_refuses_lan_target_without_connecting():
    with patch.object(http, "requests") as fake_requests:
        assert http.download_url("http://10.0.0.2/book.epub") is None
    fake_requests.get.assert_not_called()


def test_download_url_passes_redirect_guard_hook(monkeypatch):
    _resolve_to(monkeypatch, {"files.example": "93.184.216.34"})
    with patch.object(http, "requests") as fake_requests:
        fake_requests.exceptions = http.requests.exceptions
        fake_requests.get.side_effect = network.UnsafeDestinationError("redirected into the LAN")
        assert http.download_url("https://files.example/book.epub") is None
    assert fake_requests.get.call_count == 1  # blocked hop is not retried
    assert fake_requests.get.call_args.kwargs["hooks"] is network.REDIRECT_GUARD_HOOKS
