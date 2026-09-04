"""DDoS-Guard answers AA slow_download URLs with a redirect-to-self cookie
handshake. The stateless redirect loop can't satisfy it, so it must hand off to
the bypasser rather than raising TooManyRedirects."""
import requests

from shelfmark.download import http as H

URL = "https://annas-archive.gl/slow_download/deadbeef/0/4"


class SelfRedirect:
    """Every request 302s back to the same URL, forever."""
    status_code = 302
    is_redirect = True
    url = URL
    text = ""

    def __init__(self):
        self.headers = {"Location": URL}

    def raise_for_status(self):
        pass


def _patch(monkey, *, bypass_enabled=True):
    calls = {"gets": 0, "bypassed": []}

    def fake_get(url, **kwargs):
        calls["gets"] += 1
        assert calls["gets"] < 50, "redirect loop never terminated"
        return SelfRedirect()

    monkey["requests_get"] = fake_get
    H.requests.get = fake_get
    H._is_cf_bypass_enabled = lambda: bypass_enabled
    # Real cookie lookup would drag in the Chromium bypasser.
    H._apply_cf_bypass = lambda url, headers: {}
    H.network.should_rotate_dns_for_url = lambda url: True
    H.network.is_aa_auto_mode = lambda: False

    def fake_bypass(target_url, selector, cancel_flag):
        calls["bypassed"].append(target_url)
        return "<html>bypassed</html>"

    H.get_bypassed_page = fake_bypass
    return calls


def main():
    saved = (H.requests.get, H._is_cf_bypass_enabled, H.get_bypassed_page,
             H.network.should_rotate_dns_for_url, H.network.is_aa_auto_mode,
             H._apply_cf_bypass)
    try:
        # Bypass available: the loop bails out to the bypasser and returns its page.
        calls = _patch({}, bypass_enabled=True)
        html = H.html_get_page(URL, retry=1, success_delay=0)
        assert html == "<html>bypassed</html>", html
        assert calls["bypassed"] == [URL], calls["bypassed"]

        # Bypass disabled: still gives up rather than looping forever.
        calls = _patch({}, bypass_enabled=False)
        html = H.html_get_page(URL, retry=1, success_delay=0)
        assert html == "", html
        assert calls["bypassed"] == [], calls["bypassed"]

        # Explicit opt-out of the fallback must not sneak into the bypasser.
        calls = _patch({}, bypass_enabled=True)
        html = H.html_get_page(URL, retry=1, success_delay=0, allow_bypasser_fallback=False)
        assert calls["bypassed"] == [], calls["bypassed"]

        print("ok")
    finally:
        (H.requests.get, H._is_cf_bypass_enabled, H.get_bypassed_page,
         H.network.should_rotate_dns_for_url, H.network.is_aa_auto_mode,
         H._apply_cf_bypass) = saved


if __name__ == "__main__":
    main()
