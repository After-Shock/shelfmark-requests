# Signup Account Provisioning — Audiobookshelf & Calibre-Web

> **Branch:** `signup-branch` (created from `feature/duplicate-request-prevention-design`)
> **Date:** 2026-08-27

**Goal:** When a user signs up on Shelfmark, automatically create matching accounts on their external services — **Audiobookshelf** (audiobooks.sullyflix.com) and **Calibre-Web (Automated)** — using the same username/password. Users select which service accounts they want during signup via toggle buttons.

**Architecture:** New `ABS_USER_SYNC_ENABLED` and `CWA_USER_SYNC_ENABLED` settings toggles. A shared dispatcher (`signup_provisioning.py`) creates accounts on each selected + enabled service after a successful Shelfmark registration. ABS accounts are created via the Audiobookshelf admin REST API; CWA accounts are written directly to the mounted Calibre-Web `app.db` (same mount used by the existing "sync users from CWA" feature). The register endpoint accepts a `services` selection from the frontend, and `/api/auth/check` advertises which services are available so the signup form shows/hides the toggles dynamically.

---

## Status Legend

- [x] Done
- [ ] Not done

---

## Phase 1: Backend — Audiobookshelf provisioning ✅

- [x] **Task 1.1** — New module `shelfmark/core/abs_user_sync.py`
  - `provision_abs_user(username, password, role)` → `POST {AUDIOBOOK_LIBRARY_URL}/api/users` with `{"username", "password", "type"}` using the configured `ABS_API_TOKEN`
  - Checks existing user first via `GET /api/users/username/{username}` (never overwrites)
  - Maps Shelfmark role → ABS type (`admin`/`user`)
  - Handles: 403 (non-admin token), 409 (exists), network errors — all returned as `{"status", "message"}`, never raised
  - `is_enabled()` gate: `ABS_USER_SYNC_ENABLED` + URL + token all set

- [x] **Task 1.2** — Settings toggle `ABS_USER_SYNC_ENABLED` in `shelfmark/config/settings.py` (General tab, under ABS API token)

## Phase 2: Backend — Calibre-Web provisioning ✅

- [x] **Task 2.1** — `provision_cwa_user()` in `shelfmark/core/cwa_user_sync.py`
  - Writes to the mounted CWA database (`CWA_DB_PATH` env or `/auth/app.db` mount)
  - Password hashed as `pbkdf2:sha256:600000` (verifiable by any werkzeug version CWA may run — do NOT use werkzeug default, newer versions emit scrypt)
  - Clones settings columns (locale, sidebar_view, etc.) from an existing CWA user row so the new row matches the installed Calibre-Web schema; falls back to a minimal insert if the table is empty
  - Skips if username exists; returns `{"status", "message"}` result dict
  - `is_provisioning_enabled()` gate: `CWA_USER_SYNC_ENABLED` + app.db mounted

- [x] **Task 2.2** — `CWA_USER_SYNC_ENABLED` checkbox setting in `settings.py` (General tab, under Library URL)

## Phase 3: Backend — Dispatcher + API wiring ✅

- [x] **Task 3.1** — New module `shelfmark/core/signup_provisioning.py`
  - `normalize_service_selection(payload)` — accepts None / list / dict, defaults missing keys to True (backward compatible)
  - `provision_signup_accounts(username, password, email, role, services)` — provisions each selected *and* enabled service; per-service failures never block registration or the other service
  - `get_warnings(results)` — human-readable warnings for the API response

- [x] **Task 3.2** — `POST /api/auth/register` in `main.py`
  - Reads optional `services` field from payload
  - Returns `{"success": true, "warnings": [...]}` (warnings = per-service errors)

- [x] **Task 3.3** — `GET /api/auth/check` in `main.py`
  - Returns `signup_services: {"audiobookshelf": bool, "calibre_web": bool}` (True only when service is enabled **and** configured)

- [x] **Task 3.4** — Admin-created users (`admin_routes.py`) also provision both enabled services (no selection UI; both apply)

## Phase 4: Frontend — Signup service selection ✅

- [x] **Task 4.1** — `types/index.ts`: `signup_services` on auth-check response; `registerUser` accepts `services`
- [x] **Task 4.2** — `useAuth.ts`: expose `signupServices`
- [x] **Task 4.3** — `App.tsx`: pass `signupServices` into `RegisterPage`
- [x] **Task 4.4** — `RegisterPage.tsx`
  - Toggle buttons for **Audiobookshelf** and **Calibre-Web** (labels + descriptions), both default-selected
  - Section hidden entirely when no services enabled
  - On success with warnings → "Account Created" screen listing what failed, with Continue button; clean success → redirect as before

## Phase 5: Tests ✅

- [x] `tests/core/test_abs_user_sync.py` — 8 tests (creation, role mapping, existing user, 403 non-admin token, unreachable server, disabled/unconfigured, is_enabled)
- [x] `tests/core/test_signup_provisioning.py` — 8 tests (CWA creation + template cloning + pbkdf2 hash, admin role, existing user, disabled, missing db, dispatcher selection, warnings, selection normalization)
- [x] TypeScript `tsc --noEmit` passes
- [x] End-to-end smoke test: register endpoint passes selection through, returns warnings, auth-check advertises services

---

## Remaining Work

### Phase 6: Deployment verification

- [ ] **Task 6.1** — Docker build + deploy on production stack; verify settings UI renders the two new toggles
- [ ] **Task 6.2** — Audiobookshelf: switch `ABS_API_TOKEN` to a token generated by an **admin** ABS user (Settings → Users → admin → API Token). Current token is likely a regular user's (used for duplicate detection) → 403 on user creation
- [ ] **Task 6.3** — Confirm CWA `app.db` is mounted into the Shelfmark container at `/auth/app.db` (or set `CWA_DB_PATH`); verify with the existing "Sync users from Calibre-Web" admin feature
- [ ] **Task 6.4** — Run a real signup for each combination: ABS only / CWA only / both / neither; confirm accounts appear in ABS (Settings → Users) and CWA (Users) with working logins

### Phase 7: Post-provisioning gaps (known ABS behavior)

- [ ] **Task 7.1** — Auto-grant library access for new ABS users. ABS API-created users have **no library access** by default; granting requires `GET /api/users/{id}` → modify `libraries_access` → `PUT /api/users/{id}`. Decide which libraries to grant (e.g., all book-type libraries) and add to `abs_user_sync.py`
- [ ] **Task 7.2** — CWA new users land with default (regular) permissions — verify CWA login works with pbkdf2 hash on the deployed CWA version; if CWA is older, confirm it accepts `pbkdf2:sha256:600000` (should, but verify)

### Phase 8: Nice-to-haves

- [ ] **Task 8.1** — Sync password changes: when a user changes their Shelfmark password, offer to update ABS/CWA passwords too
- [ ] **Task 8.2** — Sync user deletion: admin deletes Shelfmark user → optionally delete/disable on ABS/CWA
- [ ] **Task 8.3** — Admin panel user-creation form: service selection checkboxes (currently admin-created users get both enabled services unconditionally)
- [ ] **Task 8.4** — Surface provisioning warnings in the admin user list (e.g., "ABS account missing" indicator with a retry button)
- [ ] **Task 8.5** — Fix pre-existing failing tests in this checkout (`test_admin_users_api.py` × 4, `test_audiobookshelf.py` × 3 — env/dependency issues, fail identically without this branch's changes)

---

## Notes / Gotchas

1. **ABS token must be an admin token** — user creation is admin-only. If signup produces `ABS API token is not an admin token; cannot create users` warnings, this is why.
2. **ABS library access is not inherited** — created users can log in but see nothing until libraries are granted (Task 7.1 automates this; until then it's manual per user in ABS).
3. **CWA DB writes** open the SQLite file with a 10s busy timeout; if CWA holds a long lock, provisioning returns an error (surfaced as a signup warning, never blocks registration).
4. **`services` payload defaults**: clients that don't send `services` get all enabled services provisioned — same behavior as before this feature.
5. Provisioning only runs for **builtin** auth mode registrations (self-registration is builtin-only by design).