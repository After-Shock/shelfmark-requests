"""Hardcover pacing, 429 backoff, and rejected-sort fallback (ported from upstream 4554868 / dfcd7c9)."""

from unittest.mock import MagicMock, patch

import pytest

from shelfmark.metadata_providers import hardcover
from shelfmark.metadata_providers.hardcover import HardcoverProvider, _TokenBucket


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _resp(status=200, json=None, headers=None):
    r = MagicMock(status_code=status, headers=headers or {})
    r.json.return_value = json if json is not None else {"data": {}}
    r.raise_for_status.return_value = None
    return r


@pytest.fixture
def provider():
    """Provider with a fake session and a no-wait limiter, so tests never sleep for real."""
    clock = FakeClock()
    with patch.object(hardcover, "_rate_limiter", _TokenBucket(5, 0.8, clock=clock, sleep=clock.sleep)):
        p = HardcoverProvider(api_key="test-key")
        p.session = MagicMock()
        yield p, clock


def test_bucket_allows_burst_then_paces():
    clock = FakeClock()
    bucket = _TokenBucket(5, 0.8, clock=clock, sleep=clock.sleep)
    for _ in range(5):
        bucket.acquire()
    assert clock.slept == []
    bucket.acquire()  # sixth request waits for a refill
    assert clock.slept and clock.slept[0] == pytest.approx(1 / 0.8)


def test_429_is_retried_honouring_retry_after(provider):
    p, clock = provider
    p.session.post.side_effect = [_resp(429, headers={"Retry-After": "3"}), _resp(json={"data": {"ok": 1}})]
    assert p._execute_query("q", {}) == {"ok": 1}
    assert p.session.post.call_count == 2
    assert sum(clock.slept) >= 3  # the penalty held the next request back


def test_gives_up_after_three_429s(provider):
    p, _ = provider
    p.session.post.return_value = _resp(429, headers={"Retry-After": "1"})
    assert p._execute_query("q", {}) is None  # logged as rate limited, not "no such book" silently
    assert p.session.post.call_count == 3


def test_long_retry_after_is_not_waited_out(provider):
    p, clock = provider
    p.session.post.return_value = _resp(429, headers={"Retry-After": "3600"})  # spent daily quota
    assert p._execute_query("q", {}) is None
    assert p.session.post.call_count == 1
    assert sum(clock.slept) < 30


def test_rejected_sort_retries_without_sort_and_sticks(provider):
    p, _ = provider
    hardcover._sort_fallback_until = 0.0
    rejected = _resp(json={"data": {"search": {"results": None}}})
    ok = _resp(json={"data": {"search": {"results": {"hits": [], "found": 0}}}})
    p.session.post.side_effect = [rejected, ok, ok]

    assert p._execute_search_query("q", {"sort": "bad_field:desc"}) == {"search": {"results": {"hits": [], "found": 0}}}
    assert p.session.post.call_args_list[1].kwargs["json"]["variables"]["sort"] == ""

    p._execute_search_query("q", {"sort": "bad_field:desc"})  # within the TTL: no doomed request
    assert p.session.post.call_args_list[2].kwargs["json"]["variables"]["sort"] == ""
    hardcover._sort_fallback_until = 0.0


def test_genuinely_empty_search_is_not_a_rejection(provider):
    p, _ = provider
    hardcover._sort_fallback_until = 0.0
    p.session.post.return_value = _resp(json={"data": {"search": {"results": {"hits": [], "found": 0}}}})
    assert p._execute_search_query("q", {"sort": "activities_count:desc"}) is not None
    assert p.session.post.call_count == 1
