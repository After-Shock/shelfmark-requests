"""Library-app shortcuts that sign linked users straight in.

The Ebooks / Audiobooks shortcuts point at /api/sso/<service>. Users whose
account on that app is linked (provisioned_services) are signed in; everyone
else is sent to the app's plain URL, exactly as before.

- Calibre-Web: we hand the browser a real Calibre-Web session cookie. Traefik
  routes https://<calibre-web host>/_sso/ to us so the cookie lands on the
  Calibre-Web host. The cookie mirrors what Calibre-Web's cw_login.login_user()
  stores, plus a user_session row its user loader requires.
- Audiobookshelf: its built-in OpenID Connect login, with this site as the
  provider (see oidc_provider.py).

Switched on per app in /config/app_sso.json (mode 600, never in the repo):
  {"calibre_web": {"enabled": true},
   "audiobookshelf": {"enabled": true, "client_id": "...", "client_secret": "..."}}
"""

import json
import os
import sqlite3
import time
from hashlib import sha512
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from flask import Flask, abort, redirect, request, session
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadData, URLSafeTimedSerializer

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

_APP_URL_KEYS = {"calibre_web": "CALIBRE_WEB_URL", "audiobookshelf": "AUDIOBOOK_LIBRARY_URL"}
_PASS_SALT = "app-sso-calibre-web"
_PASS_MAX_AGE = 60
# Calibre-Web keeps sessions 31 days (ub.store_user_session).
_CWA_SESSION_SECONDS = 31 * 24 * 3600
# ponytail: in-memory, fine for the single gunicorn worker; passes live 60 s.
_used_passes: dict[str, float] = {}


def load_sso_config() -> dict[str, Any]:
    from shelfmark.config.env import CONFIG_DIR

    try:
        with open(os.path.join(str(CONFIG_DIR), "app_sso.json")) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("app-sso: could not read app_sso.json: %s", e)
        return {}


def sso_enabled(service: str) -> bool:
    return bool((load_sso_config().get(service) or {}).get("enabled"))


def app_url(service: str) -> str:
    import shelfmark.core.config as core_config

    return str(core_config.config.get(_APP_URL_KEYS[service], "") or "").strip().rstrip("/")


def current_user(user_db: Any) -> Optional[dict[str, Any]]:
    """The signed-in requests-site user, or None."""
    if "user_id" not in session:
        return None
    try:
        return user_db.get_user(user_id=int(session.get("db_user_id")))
    except (TypeError, ValueError):
        return None


def is_linked(user: Optional[dict[str, Any]], service: str) -> bool:
    from shelfmark.core.signup_provisioning import parse_provisioned_services

    return bool(user) and service in parse_provisioned_services(user.get("provisioned_services"))


def _pass_serializer(secret_key: Any) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=_PASS_SALT)


def _cw_login_identifier(req: Any) -> str:
    """Calibre-Web's session identifier: cw_login.utils._create_identifier, verbatim.

    It formats bytes objects into the string (b'1.2.3.4'|b'Mozilla/...'), so we do too.
    """
    address = req.headers.get("X-Forwarded-For", req.remote_addr)
    if address is not None:
        address = address.encode("utf-8").split(b",")[0].strip()
    user_agent = req.headers.get("User-Agent")
    if user_agent is not None:
        user_agent = user_agent.encode("utf-8")
    return sha512(f"{address}|{user_agent}".encode("utf8")).hexdigest()


def make_calibre_web_session_cookie(db_path: str, username: str, req: Any) -> Optional[str]:
    """Create a Calibre-Web login for `username`; return the signed session cookie value."""
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        key_row = conn.execute("SELECT flask_session_key FROM flask_settings").fetchone()
        users = conn.execute("SELECT id FROM user WHERE lower(name) = lower(?)", (username,)).fetchall()
        if not key_row or not key_row[0] or len(users) != 1:
            logger.warning("app-sso: no unique Calibre-Web user '%s' or no session key", username)
            return None
        cwa_user_id = users[0][0]
        ident = _cw_login_identifier(req)
        random = os.urandom(10).hex()
        conn.execute(
            "INSERT INTO user_session (user_id, session_key, random, expiry) VALUES (?, ?, ?, ?)",
            (cwa_user_id, ident, random, int(time.time()) + _CWA_SESSION_SECONDS),
        )
        conn.commit()
    finally:
        conn.close()

    signer_app = Flask("calibre-web-session")
    signer_app.secret_key = key_row[0]
    serializer = SecureCookieSessionInterface().get_signing_serializer(signer_app)
    # _permanent: an IP/User-Agent change then only marks the session non-fresh
    # instead of logging out (cw_login _session_protection_failed, strong mode).
    return serializer.dumps({
        "_user_id": str(cwa_user_id),
        "_fresh": True,
        "_id": ident,
        "_random": random,
        "_permanent": True,
    })


def _claim_pass(token: str) -> bool:
    now = time.time()
    for t, exp in list(_used_passes.items()):
        if exp < now:
            _used_passes.pop(t, None)
    if token in _used_passes:
        return False
    _used_passes[token] = now + _PASS_MAX_AGE
    return True


def register_app_sso_routes(app: Flask, user_db: Any) -> None:
    @app.route("/api/sso/<service>")
    def app_sso_start(service: str):
        if service not in _APP_URL_KEYS:
            abort(404)
        plain = app_url(service)
        if not plain:
            abort(404)
        user = current_user(user_db)
        if not sso_enabled(service) or not is_linked(user, service):
            return redirect(plain)
        if service == "calibre_web":
            token = _pass_serializer(app.secret_key).dumps(user["id"])
            return redirect(f"{plain}/_sso/login?t={quote(token)}")
        return redirect(f"{plain}/auth/openid?callback={quote(plain + '/login', safe='')}")

    @app.route("/_sso/login")
    def app_sso_calibre_web_login():
        """Reached on the Calibre-Web host via Traefik; sets Calibre-Web's session cookie."""
        from shelfmark.core.cwa_user_sync import _get_cwa_db_path

        plain = app_url("calibre_web")
        # Only on the Calibre-Web host: the cookie is named "session" and must
        # never be set on this site.
        if not plain or request.host.lower() != (urlsplit(plain).hostname or "").lower():
            abort(404)
        login_page = f"{plain}/login"
        token = request.args.get("t", "")
        try:
            user_id = _pass_serializer(app.secret_key).loads(token, max_age=_PASS_MAX_AGE)
        except BadData:
            return redirect(login_page)
        if not _claim_pass(token):
            return redirect(login_page)
        user = user_db.get_user(user_id=user_id)
        db_path = _get_cwa_db_path()
        if not sso_enabled("calibre_web") or not is_linked(user, "calibre_web") or not db_path:
            return redirect(login_page)
        try:
            cookie = make_calibre_web_session_cookie(db_path, user["username"], request)
        except sqlite3.Error as e:
            logger.warning("app-sso: Calibre-Web session for '%s' failed (schema changed?): %s", user["username"], e)
            cookie = None
        if not cookie:
            return redirect(login_page)
        logger.info("app-sso: signed '%s' in to Calibre-Web", user["username"])
        response = redirect(f"{plain}/")
        response.set_cookie(
            "session", cookie, max_age=_CWA_SESSION_SECONDS, path="/",
            secure=True, httponly=True, samesite="Lax",
        )
        return response
