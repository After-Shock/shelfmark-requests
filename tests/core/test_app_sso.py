"""Library shortcuts sign linked users in: Calibre-Web cookie handoff and the OIDC provider for Audiobookshelf."""

import base64
import hashlib
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

import shelfmark.config.env as env
import shelfmark.core.app_sso as app_sso
import shelfmark.core.cwa_user_sync as cwa_user_sync
import shelfmark.core.oidc_provider as oidc_provider
from shelfmark.core.user_db import UserDB

CWA = "https://ebooks.example.com"
ABS = "https://audiobooks.example.com"
SITE = "https://books.example.com"
CALLBACK = f"{ABS}/auth/openid/callback"
SSO_CONFIG = {
    "calibre_web": {"enabled": True},
    "audiobookshelf": {"enabled": True, "client_id": "abs", "client_secret": "s3cret"},
}


@pytest.fixture
def cwa_db(tmp_path):
    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE flask_settings (id INTEGER PRIMARY KEY, flask_session_key BLOB);
        CREATE TABLE user (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE user_session (id INTEGER PRIMARY KEY, user_id INTEGER, session_key VARCHAR,
                                   random VARCHAR, expiry INTEGER);
    """)
    conn.execute("INSERT INTO flask_settings (flask_session_key) VALUES (?)", (b"k" * 32,))
    conn.execute("INSERT INTO user (id, name) VALUES (7, 'Dave')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def site(tmp_path, monkeypatch, cwa_db):
    """Returns (client, user_db, dave, erin): dave has both apps linked, erin none."""
    user_db = UserDB(str(tmp_path / "users.db"))
    user_db.initialize()
    dave = user_db.create_user(username="dave", role="user", email="dave@example.com")
    user_db.update_user(dave["id"], provisioned_services="calibre_web,audiobookshelf")
    erin = user_db.create_user(username="erin", role="user")

    urls = {"calibre_web": CWA, "audiobookshelf": ABS}
    for mod in (app_sso, oidc_provider):
        monkeypatch.setattr(mod, "app_url", lambda s: urls[s])
        monkeypatch.setattr(mod, "load_sso_config", lambda: SSO_CONFIG)
    monkeypatch.setattr(oidc_provider, "_issuer", lambda: SITE)
    monkeypatch.setattr(env, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(oidc_provider, "_signing_key", None)
    monkeypatch.setattr(cwa_user_sync, "_get_cwa_db_path", lambda: str(cwa_db))

    app = Flask(__name__)
    app.secret_key = "test"
    app_sso.register_app_sso_routes(app, user_db)
    oidc_provider.register_oidc_provider_routes(app, user_db)
    return app.test_client(), user_db, user_db.get_user(user_id=dave["id"]), erin


def sign_in(client, user):
    with client.session_transaction() as sess:
        sess["user_id"], sess["db_user_id"] = user["username"], user["id"]


# --- shortcuts / Calibre-Web -------------------------------------------------

def test_shortcut_sends_unlinked_and_signed_out_users_to_the_plain_app(site):
    client, _, _, erin = site
    assert client.get("/api/sso/calibre_web").location == CWA
    sign_in(client, erin)
    assert client.get("/api/sso/calibre_web").location == CWA
    assert client.get("/api/sso/audiobookshelf").location == ABS


def test_audiobooks_shortcut_starts_abs_openid_login(site):
    client, _, dave, _ = site
    sign_in(client, dave)
    loc = client.get("/api/sso/audiobookshelf").location
    assert loc.startswith(f"{ABS}/auth/openid?callback=")
    assert parse_qs(urlsplit(loc).query)["callback"] == [f"{ABS}/audiobookshelf/login"]


def test_calibre_web_handoff_sets_a_session_calibre_web_accepts(site, cwa_db):
    client, _, dave, _ = site
    sign_in(client, dave)
    handoff = client.get("/api/sso/calibre_web").location
    assert handoff.startswith(f"{CWA}/_sso/login?t=")
    path = handoff[len(CWA):]

    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.2", "User-Agent": "Phone/1.0"}
    assert client.get(path, base_url=SITE).status_code == 404  # never on this site's host
    resp = client.get(path, base_url=CWA, headers=headers)
    assert resp.location == f"{CWA}/"
    set_cookie = resp.headers["Set-Cookie"]
    assert "Secure" in set_cookie and "HttpOnly" in set_cookie
    cookie = set_cookie.split(";")[0].split("=", 1)[1]

    signer = Flask("cwa")
    signer.secret_key = b"k" * 32
    data = SecureCookieSessionInterface().get_signing_serializer(signer).loads(cookie)
    expected_id = hashlib.sha512(b"b'203.0.113.9'|b'Phone/1.0'").hexdigest()
    assert data["_user_id"] == "7" and data["_id"] == expected_id and data["_permanent"] is True
    # Calibre-Web's load_user() needs this exact row.
    conn = sqlite3.connect(cwa_db)
    rows = conn.execute("SELECT user_id, session_key, random FROM user_session").fetchall()
    assert rows == [(7, expected_id, data["_random"])]

    # The pass is single use.
    assert client.get(path, base_url=CWA, headers=headers).location == f"{CWA}/login"


def test_calibre_web_handoff_rejects_tampered_pass(site):
    client, _, _, _ = site
    assert client.get("/_sso/login?t=garbage", base_url=CWA).location == f"{CWA}/login"


# --- OIDC provider ---------------------------------------------------------

def authorize(client, **overrides):
    params = {"client_id": "abs", "redirect_uri": CALLBACK, "response_type": "code",
              "scope": "openid profile email", "state": "st", "nonce": "n1"}
    params.update(overrides)
    return client.get("/api/oidc/authorize", query_string=params)


def pkce_pair():
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def exchange(client, code, **overrides):
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK}
    form.update(overrides)
    return client.post("/api/oidc/token", data=form, headers={
        "Authorization": "Basic " + base64.b64encode(b"abs:s3cret").decode()})


def test_full_oidc_flow_for_a_linked_user(site):
    from authlib.jose import JsonWebKey, jwt

    client, _, dave, _ = site
    verifier, challenge = pkce_pair()
    resp = authorize(client, code_challenge=challenge, code_challenge_method="S256")
    assert resp.location.startswith("/login?next=%2Fapi%2Foidc%2Fauthorize")  # not signed in yet

    sign_in(client, dave)
    resp = authorize(client, code_challenge=challenge, code_challenge_method="S256")
    q = parse_qs(urlsplit(resp.location).query)
    assert resp.location.startswith(CALLBACK) and q["state"] == ["st"]

    assert exchange(client, q["code"][0], code_verifier="wrong").json["error"] == "invalid_grant"
    resp = authorize(client, code_challenge=challenge, code_challenge_method="S256")
    code = parse_qs(urlsplit(resp.location).query)["code"][0]
    tokens = exchange(client, code, code_verifier=verifier).json
    assert exchange(client, code, code_verifier=verifier).json["error"] == "invalid_grant"  # single use

    jwks = JsonWebKey.import_key_set(client.get("/api/oidc/jwks").json)
    claims = jwt.decode(tokens["id_token"], jwks)
    claims.validate()
    assert claims["iss"] == SITE and claims["aud"] == "abs" and claims["nonce"] == "n1"
    assert claims["sub"] == f"shelfmark-{dave['id']}" and claims["preferred_username"] == "dave"

    info = client.get("/api/oidc/userinfo", headers={"Authorization": f"Bearer {tokens['access_token']}"}).json
    assert info == {"sub": f"shelfmark-{dave['id']}", "preferred_username": "dave",
                    "name": "dave", "email": "dave@example.com"}
    assert client.get("/api/oidc/userinfo", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_unlinked_user_gets_no_code(site):
    client, _, _, erin = site
    sign_in(client, erin)
    resp = authorize(client)
    assert resp.status_code == 403 and b"Link your Audiobooks account first" in resp.data


def test_unknown_client_or_redirect_uri_never_redirects(site):
    client, _, dave, _ = site
    sign_in(client, dave)
    assert authorize(client, redirect_uri="https://evil.example/cb").status_code == 400
    assert authorize(client, client_id="other").status_code == 400


def test_token_endpoint_checks_client_secret_and_redirect_uri(site):
    client, _, dave, _ = site
    sign_in(client, dave)
    code = parse_qs(urlsplit(authorize(client).location).query)["code"][0]
    bad = client.post("/api/oidc/token", data={"grant_type": "authorization_code", "code": code,
                                               "redirect_uri": CALLBACK, "client_id": "abs",
                                               "client_secret": "wrong"})
    assert bad.status_code == 401
    assert exchange(client, code, redirect_uri=f"{ABS}/auth/openid/mobile-redirect").status_code == 400


def test_discovery_document(site):
    client, _, _, _ = site
    doc = client.get("/.well-known/openid-configuration").json
    assert doc["issuer"] == SITE and doc["token_endpoint"] == f"{SITE}/api/oidc/token"
