"""Z-Library EAPI client - the JSON API Z-Library's own mobile apps use.

Z-Library's "DiamWall" protection answers anything without a browser TLS
fingerprint with a 513 "Verifying your browser" page, so every request goes
through curl_cffi impersonating Chrome. No browser or cookie bypass is needed.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from shelfmark.core.config import config

DEFAULT_ACCOUNT_URL = "https://z-library.sk"

_session: Any = None  # curl_cffi Session, logged in
_session_lock = threading.Lock()


class ZlibError(Exception):
    """Z-Library refused or failed a request (login, daily limit, outage)."""


def _base_url() -> str:
    return str(config.get("ZLIB_ACCOUNT_URL") or DEFAULT_ACCOUNT_URL).rstrip("/")


def _json(response: Any) -> dict:
    if "json" not in (response.headers.get("content-type") or ""):
        raise ZlibError(f"Z-Library returned HTTP {response.status_code} instead of JSON")
    return response.json()


def _login() -> Any:
    from curl_cffi import requests as creq

    session = creq.Session(impersonate="chrome")
    data = _json(session.post(
        f"{_base_url()}/eapi/user/login",
        data={"email": config.get("ZLIB_EMAIL", ""), "password": config.get("ZLIB_PASSWORD", "")},
        timeout=30,
    ))
    user = data.get("user") or {}
    if not data.get("success") or not user.get("remix_userkey"):
        raise ZlibError(f"Z-Library login failed: {data.get('error') or 'no session returned'}")
    session.cookies.update({"remix_userid": str(user["id"]), "remix_userkey": user["remix_userkey"]})
    return session


def _api(method: str, path: str, **kwargs: Any) -> dict:
    """Call the EAPI, logging in on first use and once more if the session expired."""
    global _session
    for attempt in range(2):
        with _session_lock:
            if _session is None:
                _session = _login()
            session = _session
        data = _json(session.request(method, _base_url() + path, timeout=30, **kwargs))
        if data.get("success") or attempt:
            return data
        with _session_lock:
            _session = None  # stale login; retry once with a fresh one
    return data


def search(query: str, formats: list[str], limit: int) -> list[dict]:
    fields = [("message", query), ("limit", str(limit))]
    fields += [("extensions[]", fmt) for fmt in formats]
    return _api("POST", "/eapi/book/search", data=fields).get("books") or []


def download_link(book_id: str, book_hash: str) -> str:
    data = _api("GET", f"/eapi/book/{book_id}/{book_hash}/file")
    link = (data.get("file") or {}).get("downloadLink")
    if not link:
        # e.g. "Daily limit reached" on a free account (10/day)
        raise ZlibError(f"Z-Library gave no download link: {data.get('error') or 'unknown error'}")
    return link


def download(
    url: str,
    dest: Path,
    progress_callback: Callable[[float], None],
    is_cancelled: Callable[[], bool],
) -> bool:
    """Stream a file to dest. Returns False if cancelled."""
    with _session_lock:
        session = _session or _login()
    response = session.get(url, stream=True, timeout=120)
    try:
        if response.status_code != 200:
            raise ZlibError(f"Z-Library download failed with HTTP {response.status_code}")
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with dest.open("wb") as f:
            for chunk in response.iter_content():
                if is_cancelled():
                    return False
                f.write(chunk)
                done += len(chunk)
                if total:
                    progress_callback(done * 100 / total)
    finally:
        response.close()
    return True
