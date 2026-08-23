import requests


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        headers: dict | None = None,
        text: str = "",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.url = url

    @property
    def is_redirect(self) -> bool:  # requests.Response compatibility
        return self.status_code in (301, 302, 303, 307, 308) and bool(self.headers.get("Location"))

    def raise_for_status(self) -> None:  # requests.Response compatibility
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


class _DummySelector:
    """Minimal AA selector stub for unit testing http.html_get_page()."""

    def __init__(self, bases: list[str]) -> None:
        self._bases = bases
        self._index = 0
        self.current_base = bases[0]
        self.attempts_this_dns = 0

    def rewrite(self, url: str) -> str:
        for base in self._bases:
            if url.startswith(base):
                return url.replace(base, self.current_base, 1)
        return url

    def next_mirror_or_rotate_dns(self, allow_dns: bool = True) -> tuple[str | None, str]:
        self.attempts_this_dns += 1
        self._index = (self._index + 1) % len(self._bases)
        self.current_base = self._bases[self._index]
        return self.current_base, "mirror"


def test_html_get_page_aa_cross_host_redirect_rotates_mirror(monkeypatch):
    import shelfmark.download.http as http

    # Avoid bypasser imports in unit tests.
    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: False)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.li")
    monkeypatch.setattr(http.network, "is_aa_auto_mode", lambda: True)

    calls: list[dict] = []

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, "allow_redirects": kwargs.get("allow_redirects")})
        if url.startswith("https://annas-archive.li/"):
            return _FakeResponse(302, headers={"Location": "https://annas-archive.pm/search?q=test"})
        if url.startswith("https://annas-archive.gl/"):
            return _FakeResponse(200, text="OK")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(http.requests, "get", fake_get)

    selector = _DummySelector(["https://annas-archive.li", "https://annas-archive.gl"])
    html = http.html_get_page(
        "https://annas-archive.li/search?q=test",
        selector=selector,
        retry=2,
        allow_bypasser_fallback=False,
    )

    assert html == "OK"
    assert calls[0]["allow_redirects"] is False  # AA redirects handled manually
    assert calls[0]["url"].startswith("https://annas-archive.li/")
    assert calls[1]["url"].startswith("https://annas-archive.gl/")  # rotated away from redirect target


def test_html_get_page_aa_same_host_redirect_is_followed(monkeypatch):
    import shelfmark.download.http as http

    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: False)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.li")
    monkeypatch.setattr(http.network, "is_aa_auto_mode", lambda: True)

    calls: list[dict] = []

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, "allow_redirects": kwargs.get("allow_redirects")})
        if url == "https://annas-archive.li/search?q=test":
            return _FakeResponse(302, headers={"Location": "/search?q=test&page=1"})
        if url == "https://annas-archive.li/search?q=test&page=1":
            return _FakeResponse(200, text="OK2")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(http.requests, "get", fake_get)

    selector = _DummySelector(["https://annas-archive.li"])
    html = http.html_get_page(
        "https://annas-archive.li/search?q=test",
        selector=selector,
        retry=1,
        allow_bypasser_fallback=False,
    )

    assert html == "OK2"
    assert [c["url"] for c in calls] == [
        "https://annas-archive.li/search?q=test",
        "https://annas-archive.li/search?q=test&page=1",
    ]
    assert all(c["allow_redirects"] is False for c in calls)


def test_html_get_page_aa_challenge_redirect_switches_to_bypasser(monkeypatch):
    import shelfmark.download.http as http

    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: True)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http, "get_ssl_verify", lambda _url: True)
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.gl")
    monkeypatch.setattr(http.network, "is_aa_auto_mode", lambda: True)

    request_calls: list[str] = []
    bypass_calls: list[str] = []

    def fake_get(url: str, **kwargs):
        request_calls.append(url)
        return _FakeResponse(
            302,
            headers={"Location": "https://annas-archive.gl/md5/abc123?&check=1"},
        )

    def fake_bypass(url: str, _selector, _cancel_flag):
        bypass_calls.append(url)
        return "BYPASSED"

    monkeypatch.setattr(http.requests, "get", fake_get)
    monkeypatch.setattr(http, "get_bypassed_page", fake_bypass)

    url = "https://annas-archive.gl/md5/abc123"
    selector = _DummySelector(["https://annas-archive.gl"])
    assert http.html_get_page(url, retry=1, selector=selector) == "BYPASSED"
    assert request_calls == [url]
    assert bypass_calls == [f"{url}?&check=1"]


def test_html_get_page_locked_aa_does_not_fail_over_on_cross_host_redirect(monkeypatch):
    import shelfmark.download.http as http

    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: False)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.li")
    monkeypatch.setattr(http.network, "is_aa_auto_mode", lambda: False)

    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        if url.startswith("https://annas-archive.li/"):
            return _FakeResponse(302, headers={"Location": "https://annas-archive.pm/search?q=test"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(http.requests, "get", fake_get)

    selector = _DummySelector(["https://annas-archive.li", "https://annas-archive.gl"])
    html = http.html_get_page(
        "https://annas-archive.li/search?q=test",
        selector=selector,
        retry=2,
        allow_bypasser_fallback=False,
    )

    assert html == ""
    assert calls == ["https://annas-archive.li/search?q=test"]


def test_html_get_page_returns_response_url_when_requested(monkeypatch):
    import shelfmark.download.http as http

    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: False)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http, "get_ssl_verify", lambda _url: True)
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.li")
    monkeypatch.setattr(http.network, "should_rotate_dns_for_url", lambda _url: False)

    def fake_get(url: str, **kwargs):
        return _FakeResponse(200, text="OK", url=f"{url}&final=1")

    monkeypatch.setattr(http.requests, "get", fake_get)

    result = http.html_get_page(
        "https://annas-archive.li/search?q=test",
        include_response_url=True,
    )

    assert result == ("OK", "https://annas-archive.li/search?q=test&final=1")


def test_html_get_page_uses_ssl_verify_for_requests(monkeypatch):
    import shelfmark.download.http as http

    monkeypatch.setattr(http, "_is_cf_bypass_enabled", lambda: False)
    monkeypatch.setattr(http, "get_proxies", lambda _url: {})
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(http.network, "get_aa_base_url", lambda: "https://annas-archive.li")
    monkeypatch.setattr(http.network, "should_rotate_dns_for_url", lambda _url: False)
    monkeypatch.setattr(http, "get_ssl_verify", lambda _url: "VERIFY_SENTINEL")

    seen: dict[str, object] = {}

    def fake_get(url: str, **kwargs):
        seen.update(kwargs)
        return _FakeResponse(200, text="OK", url=url)

    monkeypatch.setattr(http.requests, "get", fake_get)

    assert http.html_get_page("https://annas-archive.li/search?q=test") == "OK"
    assert seen["verify"] == "VERIFY_SENTINEL"
