"""A DDoS-Guard-blocked AA mirror must not be retried forever by the bypasser."""

from unittest.mock import patch

import pytest

pytest.importorskip("seleniumbase")
from shelfmark.bypass import internal_bypasser as ib  # noqa: E402


class FakeSelector:
    aa_urls = ["https://annas-archive.pk", "https://annas-archive.gl"]

    def __init__(self):
        self.base = self.aa_urls[0]

    def rewrite(self, url):
        return url.replace("https://annas-archive.pk", self.base)

    def next_mirror_or_rotate_dns(self):
        self.base = self.aa_urls[1]
        return self.base, "mirror"


def _bypass(pages):
    fetched = []

    def fake_get(url, cancel_flag=None):
        fetched.append(url)
        return pages.get(url.split("/md5")[0], "")

    with patch.object(ib, "_try_with_cached_cookies", return_value=None), patch.object(ib, "get", side_effect=fake_get):
        result = ib.get_bypassed_page("https://annas-archive.pk/md5/abc?&check=1", FakeSelector())
    return result, fetched


def test_empty_bypass_result_moves_to_next_mirror():
    result, fetched = _bypass({"https://annas-archive.gl": "<html>ok</html>"})
    assert result == "<html>ok</html>"
    assert fetched == ["https://annas-archive.pk/md5/abc?&check=1", "https://annas-archive.gl/md5/abc?&check=1"]


def test_all_mirrors_blocked_still_raises():
    try:
        _bypass({})
    except ib.requests.exceptions.RequestException:
        pass
    else:
        raise AssertionError("expected a bypass failure")
