"""Minimal OpenID Connect provider so Audiobookshelf can sign users in via this site.

Authorization-code flow only, one client (Audiobookshelf, from app_sso.json).
Only users whose Audiobookshelf account is linked get a code: Audiobookshelf
matches the account by preferred_username, and linking is what proved the
account belongs to them.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from html import escape
from typing import Any, Optional
from urllib.parse import quote, urlencode

from flask import Flask, jsonify, redirect, request

from shelfmark.core.app_sso import app_url, current_user, is_linked, load_sso_config
from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

SERVICE = "audiobookshelf"
_CODE_SECONDS = 60
_TOKEN_SECONDS = 300
_ID_TOKEN_SECONDS = 300
# ponytail: in-memory stores, fine for the single gunicorn worker; a restart
# just means retrying a login that was mid-flight.
_codes: dict[str, dict[str, Any]] = {}
_tokens: dict[str, dict[str, Any]] = {}
_signing_key = None


def _issuer() -> str:
    import shelfmark.core.config as core_config

    return str(core_config.config.get("PUBLIC_URL", "") or "").strip().rstrip("/")


def _client(client_id: Optional[str]) -> Optional[dict[str, Any]]:
    """The Audiobookshelf client, if enabled and `client_id` matches."""
    conf = load_sso_config().get(SERVICE) or {}
    base = app_url(SERVICE)
    if not (conf.get("enabled") and conf.get("client_id") and conf.get("client_secret") and base):
        return None
    if not client_id or not hmac.compare_digest(str(client_id), str(conf["client_id"])):
        return None
    return {
        "client_id": conf["client_id"],
        "client_secret": conf["client_secret"],
        "redirect_uris": {f"{base}/auth/openid/callback", f"{base}/auth/openid/mobile-redirect"},
    }


def _get_signing_key():
    """RSA key in /config/oidc_signing_key.pem, created (mode 600) on first use."""
    global _signing_key
    if _signing_key is None:
        from authlib.jose import JsonWebKey

        from shelfmark.config.env import CONFIG_DIR

        path = os.path.join(str(CONFIG_DIR), "oidc_signing_key.pem")
        if not os.path.exists(path):
            pem = JsonWebKey.generate_key("RSA", 2048, is_private=True).as_pem(is_private=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(pem)
        with open(path, "rb") as f:
            _signing_key = JsonWebKey.import_key(f.read(), {"kty": "RSA"})
    return _signing_key


def _public_jwk() -> dict[str, Any]:
    key = _get_signing_key()
    jwk = key.as_dict(is_private=False)
    jwk.update({"use": "sig", "alg": "RS256", "kid": key.thumbprint()})
    return jwk


def _claims(user: dict[str, Any]) -> dict[str, Any]:
    claims = {
        "sub": f"shelfmark-{user['id']}",
        "preferred_username": user["username"],
        "name": user.get("display_name") or user["username"],
    }
    if user.get("email"):
        claims["email"] = user["email"]
    return claims


def _prune(store: dict[str, dict[str, Any]]) -> None:
    now = time.time()
    for k, v in list(store.items()):
        if v["exp"] < now:
            store.pop(k, None)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii", "ignore")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


def _with_query(uri: str, params: dict[str, str]) -> str:
    return uri + ("&" if "?" in uri else "?") + urlencode({k: v for k, v in params.items() if v})


def _not_linked_page() -> tuple[str, int]:
    site = escape(_issuer() or "/")
    return (
        "<!doctype html><meta name=viewport content='width=device-width'>"
        "<title>Link Audiobooks first</title>"
        "<body style='font-family:sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem'>"
        "<h1>Link your Audiobooks account first</h1>"
        "<p>To sign in to Audiobooks from here, your Audiobooks account has to be linked. "
        f"Go to <a href='{site}'>{site}</a>, open <b>&#9776; &rarr; Account &rarr; Library Access</b> "
        "and tap <b>Link Audiobooks</b> or <b>Add Audiobooks</b>.</p>"
        "<p>You can still sign in to Audiobooks with your username and password.</p>",
        403,
    )


def register_oidc_provider_routes(app: Flask, user_db: Any) -> None:
    @app.route("/.well-known/openid-configuration")
    def oidc_discovery():
        issuer = _issuer()
        if not issuer or not (load_sso_config().get(SERVICE) or {}).get("enabled"):
            return jsonify({"error": "not_found"}), 404
        return jsonify({
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/api/oidc/authorize",
            "token_endpoint": f"{issuer}/api/oidc/token",
            "userinfo_endpoint": f"{issuer}/api/oidc/userinfo",
            "jwks_uri": f"{issuer}/api/oidc/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "email"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
            "claims_supported": ["sub", "preferred_username", "name", "email"],
        })

    @app.route("/api/oidc/jwks")
    def oidc_jwks():
        return jsonify({"keys": [_public_jwk()]})

    @app.route("/api/oidc/authorize")
    def oidc_authorize():
        args = request.args
        client = _client(args.get("client_id"))
        redirect_uri = args.get("redirect_uri", "")
        # Never redirect to an unregistered URI, not even with an error.
        if not client or redirect_uri not in client["redirect_uris"]:
            return "Unknown client or redirect_uri", 400
        state = args.get("state", "")
        if args.get("response_type") != "code":
            return redirect(_with_query(redirect_uri, {"error": "unsupported_response_type", "state": state}))
        if "openid" not in args.get("scope", "").split():
            return redirect(_with_query(redirect_uri, {"error": "invalid_scope", "state": state}))
        challenge = args.get("code_challenge", "")
        if challenge and args.get("code_challenge_method", "plain") != "S256":
            return redirect(_with_query(redirect_uri, {"error": "invalid_request", "state": state}))

        user = current_user(user_db)
        if not user:
            return redirect(f"/login?next={quote(request.full_path, safe='')}")
        if not is_linked(user, SERVICE):
            return _not_linked_page()

        _prune(_codes)
        code = secrets.token_urlsafe(32)
        _codes[code] = {
            "client_id": client["client_id"], "redirect_uri": redirect_uri, "user_id": user["id"],
            "nonce": args.get("nonce"), "challenge": challenge, "exp": time.time() + _CODE_SECONDS,
        }
        return redirect(_with_query(redirect_uri, {"code": code, "state": state}))

    @app.route("/api/oidc/token", methods=["POST"])
    def oidc_token():
        form = request.form
        auth = request.authorization
        client_id = (auth.username if auth else None) or form.get("client_id")
        client_secret = (auth.password if auth else None) or form.get("client_secret") or ""
        client = _client(client_id)
        if not client or not hmac.compare_digest(str(client_secret), str(client["client_secret"])):
            return jsonify({"error": "invalid_client"}), 401
        if form.get("grant_type") != "authorization_code":
            return jsonify({"error": "unsupported_grant_type"}), 400

        entry = _codes.pop(form.get("code", ""), None)  # single use
        if (
            not entry
            or entry["exp"] < time.time()
            or entry["client_id"] != client["client_id"]
            or entry["redirect_uri"] != form.get("redirect_uri")
            or (entry["challenge"] and not _pkce_ok(form.get("code_verifier", ""), entry["challenge"]))
        ):
            return jsonify({"error": "invalid_grant"}), 400
        user = user_db.get_user(user_id=entry["user_id"])
        if not is_linked(user, SERVICE):
            return jsonify({"error": "invalid_grant"}), 400

        from authlib.jose import jwt

        now = int(time.time())
        id_claims = {**_claims(user), "iss": _issuer(), "aud": client["client_id"], "iat": now,
                     "exp": now + _ID_TOKEN_SECONDS}
        if entry["nonce"]:
            id_claims["nonce"] = entry["nonce"]
        key = _get_signing_key()
        id_token = jwt.encode({"alg": "RS256", "kid": key.thumbprint()}, id_claims, key).decode()

        _prune(_tokens)
        access_token = secrets.token_urlsafe(32)
        _tokens[access_token] = {"user_id": user["id"], "exp": time.time() + _TOKEN_SECONDS}
        logger.info("oidc: issued Audiobookshelf sign-in for '%s'", user["username"])
        response = jsonify({"access_token": access_token, "token_type": "Bearer",
                            "expires_in": _TOKEN_SECONDS, "id_token": id_token, "scope": "openid"})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/oidc/userinfo", methods=["GET", "POST"])
    def oidc_userinfo():
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        entry = _tokens.get(token)
        user = user_db.get_user(user_id=entry["user_id"]) if entry and entry["exp"] >= time.time() else None
        if not user:
            return jsonify({"error": "invalid_token"}), 401, {"WWW-Authenticate": "Bearer error=\"invalid_token\""}
        return jsonify(_claims(user))
