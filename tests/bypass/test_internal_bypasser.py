import asyncio


def test_bypass_tries_all_methods_before_abort(monkeypatch):
    """Regression test for issue #524: don't abort before cycling through bypass methods."""
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    calls: list[str] = []

    def _make_method(name: str):
        async def _method(_sb) -> bool:
            calls.append(name)
            return False

        _method.__name__ = name
        return _method

    methods = [_make_method(f"m{i}") for i in range(6)]

    async def _false(*_args, **_kwargs):
        return False

    async def _challenge(*_args, **_kwargs):
        return "ddos_guard"

    async def _sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(internal_bypasser, "BYPASS_METHODS", methods)
    monkeypatch.setattr(internal_bypasser, "_is_bypassed", _false)
    monkeypatch.setattr(internal_bypasser, "_detect_challenge_type", _challenge)
    monkeypatch.setattr(internal_bypasser.asyncio, "sleep", _sleep)
    monkeypatch.setattr(internal_bypasser.random, "uniform", lambda _a, _b: 0)

    assert asyncio.run(internal_bypasser._bypass(object(), max_retries=10)) is False
    assert calls == [f"m{i}" for i in range(6)]


def test_bypass_rejects_chrome_navigation_error_page():
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    class FakePage:
        async def get_title(self):
            return "z-lib.fm"

        async def evaluate(self, _script):
            return "A browser error page that is long enough to otherwise pass"

        async def get_current_url(self):
            return "chrome-error://chromewebdata/"

    assert asyncio.run(internal_bypasser._is_bypassed(FakePage())) is False


def test_extract_cookies_from_cdp_filters_and_stores_ua():
    import time
    import asyncio
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    class FakeCookie:
        def __init__(self, name, value, domain, path, expires, secure=True):
            self.name = name
            self.value = value
            self.domain = domain
            self.path = path
            self.expires = expires
            self.secure = secure

    class FakeCookies:
        async def get_all(self, requests_cookie_format=False):
            assert requests_cookie_format is True
            return [
                FakeCookie("cf_clearance", "abc", "example.com", "/", int(time.time()) + 3600),
                FakeCookie("sessionid", "zzz", "example.com", "/", int(time.time()) + 3600),
            ]

    class FakeDriver:
        cookies = FakeCookies()

    class FakePage:
        async def evaluate(self, script):
            assert script == "navigator.userAgent"
            return "TestUA/1.0"

    internal_bypasser.clear_cf_cookies()
    asyncio.run(
        internal_bypasser._extract_cookies_from_cdp(
            FakeDriver(), FakePage(), "https://www.example.com/path"
        )
    )

    cookies = internal_bypasser.get_cf_cookies_for_domain("example.com")
    assert cookies == {"cf_clearance": "abc"}
    assert internal_bypasser.get_cf_user_agent_for_domain("example.com") == "TestUA/1.0"


def test_extract_cookies_from_cdp_normalizes_session_expiry():
    import time
    import asyncio
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    class FakeCookie:
        def __init__(self, name, value, domain, path, expires, secure=True):
            self.name = name
            self.value = value
            self.domain = domain
            self.path = path
            self.expires = expires
            self.secure = secure

    class FakeCookies:
        async def get_all(self, requests_cookie_format=False):
            assert requests_cookie_format is True
            return [
                FakeCookie("cf_clearance", "abc", "example.com", "/", 0),
            ]

    class FakeDriver:
        cookies = FakeCookies()

    class FakePage:
        async def evaluate(self, script):
            assert script == "navigator.userAgent"
            return "TestUA/1.0"

    internal_bypasser.clear_cf_cookies()
    asyncio.run(
        internal_bypasser._extract_cookies_from_cdp(
            FakeDriver(), FakePage(), "https://example.com"
        )
    )

    stored = internal_bypasser._cf_cookies.get("example.com", {})
    assert stored["cf_clearance"]["expiry"] is None
    assert internal_bypasser.get_cf_cookies_for_domain("example.com") == {"cf_clearance": "abc"}

    # Verify fallback to "expires" key for expiry checks
    internal_bypasser._cf_cookies["example.com"]["cf_clearance"]["expires"] = int(time.time()) - 10
    assert internal_bypasser.get_cf_cookies_for_domain("example.com") == {}


def test_try_with_cached_cookies_uses_ssl_verify(monkeypatch):
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    seen: dict[str, object] = {}

    internal_bypasser.clear_cf_cookies()
    internal_bypasser._cf_cookies["example.com"] = {"cf_clearance": {"value": "abc", "expiry": None}}
    internal_bypasser._cf_user_agents["example.com"] = "UA/1.0"

    monkeypatch.setattr(internal_bypasser, "get_proxies", lambda _url: {})
    monkeypatch.setattr(internal_bypasser, "get_ssl_verify", lambda _url: "VERIFY_SENTINEL")

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_get(url: str, **kwargs):
        seen.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(internal_bypasser.requests, "get", fake_get)

    assert internal_bypasser._try_with_cached_cookies("https://example.com/book", "example.com") == "ok"
    assert seen["verify"] == "VERIFY_SENTINEL"


def test_bypasser_subprocess_runs_from_writable_browser_home(monkeypatch, tmp_path):
    import json
    import shelfmark.bypass.internal_bypasser as internal_bypasser

    browser_home = tmp_path / "browser-home"
    runtime_dir = tmp_path / "runtime"
    captured: dict[str, object] = {}

    monkeypatch.setattr(internal_bypasser, "BROWSER_HOME_DIR", browser_home)
    monkeypatch.setattr(internal_bypasser, "BROWSER_XDG_RUNTIME_DIR", runtime_dir)
    monkeypatch.setenv("PYTHONPATH", "/existing/python/path")

    class FakeProcess:
        returncode = 0

        def __init__(self, args, **kwargs):
            captured["args"] = args
            captured.update(kwargs)

        def communicate(self, stdin, timeout):
            payload = json.loads(stdin)
            with open(payload["result_path"], "w") as fh:
                json.dump({"ok": True, "html": "<html></html>"}, fh)
            return "", ""

    monkeypatch.setattr(internal_bypasser.subprocess, "Popen", FakeProcess)

    assert internal_bypasser._get_via_subprocess("https://example.com", retry=1) == "<html></html>"
    assert captured["cwd"] == str(browser_home)
    assert captured["env"]["HOME"] == str(browser_home)
    python_paths = captured["env"]["PYTHONPATH"].split(internal_bypasser.os.pathsep)
    assert python_paths[0] == str(internal_bypasser.Path(internal_bypasser.__file__).parents[2])
    assert "/existing/python/path" in python_paths
