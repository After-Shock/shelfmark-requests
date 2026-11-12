"""Apprise notifications use this instance's logo when PUBLIC_URL is set."""

from unittest.mock import patch

from shelfmark.core import notifications


def _with_public_url(value):
    return patch("shelfmark.core.config.config.get", side_effect=lambda k, d=None: value if k == "PUBLIC_URL" else d)


def test_uses_public_url_logo():
    with _with_public_url("https://books.example.com/"):
        assert notifications._apprise_logo_url() == "https://books.example.com/logo.png"


def test_falls_back_to_upstream_logo_without_public_url():
    for value in ("", None, "books.example.com"):
        with _with_public_url(value):
            assert notifications._apprise_logo_url() == notifications._APPRISE_LOGO_URL
