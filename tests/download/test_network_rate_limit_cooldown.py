"""Per-host 429 cooldown (ported from upstream calibrain/shelfmark ddc26f0)."""

from unittest.mock import patch

import pytest

from shelfmark.bypass import internal_bypasser
from shelfmark.download import http, network


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(network.time, "monotonic", c)
    return c


def test_ladder_escalates_only_after_a_full_wait(clock):
    url = "https://annas-archive.gl/search?q=x"
    assert network.note_rate_limited(url) == 120.0
    clock.now += 60
    assert network.note_rate_limited(url) == pytest.approx(60.0)  # same episode: no escalation
    assert network.is_host_cooling_down(url)

    clock.now += 61  # window over, throttled again -> next step
    assert network.note_rate_limited(url) == 300.0
    clock.now += 301
    assert network.note_rate_limited(url) == 600.0


def test_long_clear_gap_restarts_the_ladder(clock):
    url = "https://annas-archive.gl/"
    network.note_rate_limited(url)
    clock.now += 120 + 1800 + 1
    assert network.note_rate_limited(url) == 120.0


def test_cooldown_expires(clock):
    url = "https://annas-archive.pk/"
    network.note_rate_limited(url)
    clock.now += 121
    assert network.host_cooldown_remaining(url) == 0.0


@pytest.fixture
def three_mirrors(monkeypatch):
    urls = ["https://annas-archive.gl", "https://annas-archive.pk", "https://annas-archive.gd"]
    monkeypatch.setattr(network, "_ensure_initialized", lambda: None)
    monkeypatch.setattr(network, "_save_state", lambda **_k: None)
    monkeypatch.setattr(network, "is_aa_auto_mode", lambda: True)
    monkeypatch.setattr(network, "_aa_urls", list(urls))
    monkeypatch.setattr(network, "_aa_base_url", urls[0])
    monkeypatch.setattr(network, "_current_aa_url_index", 0)
    return urls


def test_rotation_skips_a_cooling_mirror(three_mirrors):
    network.note_rate_limited(three_mirrors[1] + "/search")
    sel = network.AAMirrorSelector()
    new_base, action = sel.next_mirror_or_rotate_dns()
    assert (new_base, action) == (three_mirrors[2], "mirror")


def test_rotation_still_moves_when_every_mirror_is_cooling(three_mirrors):
    for u in three_mirrors:
        network.note_rate_limited(u)
    sel = network.AAMirrorSelector()
    assert sel.next_mirror_or_rotate_dns() == (three_mirrors[1], "mirror")


def test_bypasser_fails_fast_when_every_mirror_is_cooling(three_mirrors):
    for u in three_mirrors:
        network.note_rate_limited(u)
    with patch.object(internal_bypasser, "get") as chrome_solve, \
            patch.object(internal_bypasser, "_try_with_cached_cookies") as cached:
        with pytest.raises(network.RateLimitedError):
            internal_bypasser.get_bypassed_page("https://annas-archive.gl/search?q=dune")
    chrome_solve.assert_not_called()
    cached.assert_not_called()


def test_rate_limited_error_is_a_handled_bypasser_error():
    assert issubclass(network.RateLimitedError, http._BYPASSER_ERRORS)


def test_download_url_429_arms_the_cooldown():
    response = http.requests.Response()
    response.status_code = 429
    err = http.requests.exceptions.HTTPError(response=response)
    with patch.object(http.requests, "get") as fake_get:
        fake_get.return_value.raise_for_status.side_effect = err
        assert http.download_url("https://files.example/book.epub") is None
    assert network.is_host_cooling_down("https://files.example/other")


# --- regression: a 429 outside rotation must not leave searches on the throttled mirror --------
# (Seen in e2e: the 429 landed on a cached-cookie retry, the current mirror stayed .gl, every new
# search hit .gl's challenge and the bypasser failed fast -> AA search dark for the cooldown.)

def test_new_requests_move_off_a_cooling_current_mirror(three_mirrors):
    network.note_rate_limited(three_mirrors[0])  # current mirror throttled, no rotation happened
    sel = network.AAMirrorSelector()
    assert sel.rewrite(three_mirrors[0] + "/search?q=dune") == three_mirrors[1] + "/search?q=dune"
    # and the switch is shared with later selectors
    assert network.AAMirrorSelector().current_base == three_mirrors[1]


def test_bypass_uses_a_breathing_mirror_instead_of_failing(three_mirrors):
    network.note_rate_limited(three_mirrors[0])
    with patch.object(internal_bypasser, "_try_with_cached_cookies", return_value=None), \
            patch.object(internal_bypasser, "get", return_value="<html>results</html>") as chrome_solve:
        assert internal_bypasser.get_bypassed_page(three_mirrors[0] + "/search?q=dune") == "<html>results</html>"
    assert chrome_solve.call_args.args[0] == three_mirrors[1] + "/search?q=dune"


def test_locked_mirror_is_not_switched(three_mirrors, monkeypatch):
    monkeypatch.setattr(network, "is_aa_auto_mode", lambda: False)
    network.note_rate_limited(three_mirrors[0])
    sel = network.AAMirrorSelector()
    assert sel.rewrite(three_mirrors[0] + "/x") == three_mirrors[0] + "/x"
