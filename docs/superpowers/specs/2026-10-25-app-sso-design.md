# App shortcuts sign users in (Ebooks + Audiobooks SSO)

Date: 2026-10-25 · Branch: `app-sso` (prod stays on `signup-branch` until approved; rollback = redeploy `signup-branch`)

## Goal

A user signed in at books.sullyflix.com who taps the Ebooks or Audiobooks shortcut lands
signed in to Calibre-Web / Audiobookshelf, if that app's account is **linked** (in
`users.provisioned_services`). Everyone else gets the app's normal login page, exactly as today.

Unchanged: typing the app URL directly, password logins, Kobo sync, OPDS, Send-to-Kindle,
Audiobookshelf mobile apps (they gain an optional "Login with Sullyflix" button).

## Facts this design relies on (checked on prod 2026-10-25)

- Calibre-Web 0.6.27. Session = Flask signed cookie (`COOKIE_PREFIX` + `session`, HttpOnly,
  SameSite=Lax) keyed by `flask_settings.flask_session_key` in `app.db`. Its user loader only
  accepts a session whose `_random` (and `_id` session key, if present) matches a `user_session`
  row (`user_id, session_key, random, expiry`). `config_session = 1` → "strong" protection: the
  session's `_id` must equal sha512 of `remote_addr|User-Agent` as Calibre-Web computes it.
- Shelfmark mounts Calibre-Web's `app.db` read-write at `/auth/app.db`.
- Audiobookshelf 2.37.1 supports OIDC. It matches users by stored `authOpenIDSub`, else (with
  `authOpenIDMatchExistingBy = username`) by `preferred_username`, then stores the sub. It refuses
  inactive users. Web flow uses PKCE S256.
- Shelfmark runs one gunicorn (gevent) worker, so short-lived codes can live in memory.

## Shortcut entry point

`GET /api/sso/<service>` (`calibre_web` | `audiobookshelf`), on books.sullyflix.com.
The frontend shortcut links always point here.

- Not signed in, not linked, or user inactive → 302 to the app's plain URL (today's behaviour).
- Linked → start that app's SSO (below).

## Ebooks: hand the browser a real Calibre-Web session

1. `/api/sso/calibre_web` → 302 to `https://<CALIBRE_WEB_URL host>/_sso/login?t=<pass>`.
   The pass is signed with shelfmark's secret (itsdangerous), carries the shelfmark user id,
   and expires after 60 s.
2. A Traefik file-provider router (`Host(ebooks…) && PathPrefix(/_sso/)`, higher priority than
   the Calibre-Web router) sends only that path to shelfmark. File: `/opt/traefik/ebooks-sso.yml`,
   copy in `deploy/traefik/`.
3. Shelfmark verifies the pass, re-checks linked + active, finds the Calibre-Web user by name
   (case-insensitive, must be unique), inserts a `user_session` row, and signs a Flask session
   cookie with Calibre-Web's key containing `_user_id`, `_fresh`, `_id` (strong-mode identifier),
   `_random`. Sets it host-only (Secure, HttpOnly, SameSite=Lax), 302 to `/`.
4. From then on it is an ordinary Calibre-Web login; its own Log Out works.

Failure handling: any mismatch (bad/expired pass, user not found, schema/key missing) logs a
warning prefixed `app-sso:` and 302s to the Calibre-Web login page. Nothing else changes in
Calibre-Web. If shelfmark is down only the handoff path fails.

`remote_addr` for the strong identifier: compute it the way Calibre-Web's vendored `cw_login`
does (first `X-Forwarded-For` entry, else remote addr) from the same request Traefik forwards.
Verified by a live test before the shortcut is switched on.

## Audiobooks: books.sullyflix.com as an OIDC provider

Issuer = `PUBLIC_URL`. Endpoints:

| Endpoint | Behaviour |
|---|---|
| `GET /.well-known/openid-configuration` | Discovery document. |
| `GET /api/oidc/authorize` | Requires `response_type=code`, known `client_id`, exact registered `redirect_uri`, `scope` containing `openid`. Not signed in → `/login?next=<this URL>`. Signed in but Audiobookshelf not linked (or inactive) → small HTML page: "Link your Audiobooks account first" + link to the site. Otherwise issue a single-use code (60 s, bound to client, redirect_uri, user, nonce, PKCE challenge) and 302 to `redirect_uri?code=…&state=…`. |
| `POST /api/oidc/token` | `client_secret_basic` or `client_secret_post`; `grant_type=authorization_code`; code must exist, be unexpired, unused, match client + redirect_uri; PKCE S256 verifier checked when a challenge was given. Returns `access_token` (random, 5 min, memory), `token_type=Bearer`, `expires_in`, `id_token` (RS256; `iss, aud, sub, iat, exp, nonce, preferred_username, name, email`). |
| `GET /api/oidc/userinfo` | Bearer access token → `sub, preferred_username, name, email`. |
| `GET /api/oidc/jwks` | Public key. |

- `sub` = `shelfmark-<users.id>`, never changes.
- The **linked** check is the security boundary: Audiobookshelf trusts `preferred_username`,
  so only users who proved ownership by linking get a code.
- Registered redirect URIs: `https://<ABS host>/auth/openid/callback` and `audiobookshelf://oauth`.
- Secrets live only on prod: RSA key `/config/oidc_signing_key.pem` (generated on first use, 600),
  client config `/config/oidc_clients.json` (600). Never in the repo.
- JWT signing with `authlib.jose` (already a dependency). No authlib authorization-server models.
- Login page honours `?next=` for same-site relative paths only (`/…`, not `//…`).

Audiobookshelf settings (via its admin API, using shelfmark's existing token): add `openid` to
`authActiveAuthMethods`, issuer/endpoints from discovery, client id/secret, signing alg RS256,
button text "Login with Sullyflix", auto-register **off**, match existing by **username**,
auto-launch **off**, mobile redirect `audiobookshelf://oauth`.

`/api/sso/audiobookshelf` for linked users → 302 to Audiobookshelf's OIDC entry URL (exact URL
confirmed from its web client during implementation).

## Files

- `shelfmark/core/app_sso.py` — `/api/sso/<service>`, Ebooks pass + `/_sso/login`.
- `shelfmark/core/oidc_provider.py` — OIDC endpoints, code/token stores, key loading.
- `shelfmark/main.py` — register routes.
- Frontend: shortcut hrefs → `/api/sso/<service>`; LoginPage `next` support.
- `deploy/traefik/ebooks-sso.yml`.
- Tests: `tests/core/test_app_sso.py`, `tests/core/test_oidc_provider.py`.

## Tests

- OIDC: full authorize → token → userinfo; unlinked user refused; wrong PKCE verifier; code reuse;
  unknown redirect_uri; bad client secret; id_token verifies against jwks.
- Ebooks: pass expiry/tamper; cookie built against a temp copy of Calibre-Web's schema decodes
  with Flask's serializer and the session passes the `user_session` check logic; unlinked → plain URL.
- `next`: rejects `//evil` and absolute URLs.

## Rollout / rollback

1. Deploy `app-sso` (code inert until Traefik file + ABS settings exist; shortcuts fall back to
   plain URLs on any failure).
2. Add Traefik file; live-test Ebooks with an admin test account.
3. Configure Audiobookshelf OIDC; live-test with a linked account.
4. Rollback: remove `openid` from Audiobookshelf auth methods, delete `ebooks-sso.yml`,
   redeploy `signup-branch`.

Out of scope: single sign-out across sites; auto-registering Audiobookshelf users via OIDC.
