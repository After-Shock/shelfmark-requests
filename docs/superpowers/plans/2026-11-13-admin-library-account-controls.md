# Admin Library Account Controls Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development. Steps use checkbox syntax for tracking.

**Goal:** Admins can inspect and explicitly link existing library accounts and set one supplied password on requests and linked apps, with individual results.

**Architecture:** A persistent external-account mapping/resolver extends legacy provisioned_services links. Dedicated admin endpoints feed a focused component in the existing user editor; all account consumers share identity resolution.

**Tech Stack:** Flask, SQLite, Python requests, React/TypeScript, pytest, Vitest.

## Chunk 1: Backend and integration

Files: add shelfmark/core/library_accounts.py and tests/core/test_admin_library_accounts.py; modify user_db.py, admin_routes.py, signup_provisioning.py, self_user_routes.py, password_reset.py, app_sso.py, oidc_provider.py and service sync helpers as needed.

- [x] Write failing tests for admin authorization; explicit different-name mappings; legacy ownership; unlink suppression; stable-ID targeting; missing and unavailable accounts; no password changes during linking; validation; per-service password results; legacy self-service and SSO compatibility.
- [x] Run the new tests with `python3 -m pytest tests/core/test_admin_library_accounts.py -q`; confirm expected failures.
- [x] Add additive mapping storage with unique ownership, legacy compatibility and safe transactional link/unlink. ID is canonical string (decimal Calibre ID, opaque ABS UUID). Preserve mappings across outages; missing mappings fail closed. Link/unlink changes only associations, not external identities/passwords. Clear legacy flag on unlink; explicit self-link conflicts do not override mappings. Reject non-builtin shared-password actions before any writes.
- [x] Implement the API contract below and integrate resolver in status, reset, password sync and SSO. Preserve OIDC subject and reject conflicting external OIDC links. Remote passwords target resolved IDs. Do not disclose tokens/hashes. Log admin changes without secrets.
- [x] Run relevant existing and new tests; fix regressions.
- [x] Spec review then quality review.

### API contract

`GET /api/admin/users/<id>/library-accounts`: `{services: {calibre_web: Service, audiobookshelf: Service}}`.

Service: `{offered: boolean, linked: boolean, account: Account|null, candidates: Account[], error?: string, state?: string}`. Account: `{id: string, username: string, email: string|null, owner_user_id?: number|null, owner_username?: string|null}`. Candidates include claimed identities with ownership so UI can show and disable them. Unavailable services have an error and retain the displayed association when possible. Missing account is represented by state `missing`; retain association so it can be unlinked.

`PUT /api/admin/users/<id>/library-accounts/<service>` body `{account_id: string}`: `{success: true}`; idempotent for same selection. Returns JSON `{error}` with 400 invalid input/nonoffered, 404 missing, 409 claimed/conflicting identity, 503 unavailable.

`DELETE` same endpoint unlinks, no body: `{success: true}`. Idempotent; works even when external app unavailable.

`POST /api/admin/users/<id>/library-accounts/password` body `{password: string, confirmation: string}`: `{results: {requests: Result, calibre_web?: Result, audiobookshelf?: Result}}`. Result: `{status: 'updated'|'skipped'|'error', message?: string}`. HTTP 200 reports partial results; validation/auth fails before any writes. Requests updated first, each linked app attempted independently. Never echo password.

## Chunk 2: User editor UI

Files: add src/frontend/src/components/settings/AdminLibraryAccounts.tsx and test file; modify services/api.ts and UsersPanel.tsx.

- [x] Write failing UI tests for linked usernames/emails, select and review before linking, ownership conflict, unlink, password confirmation and partial results.
- [x] Run `npm test -- AdminLibraryAccounts.test.tsx` and confirm failures for missing feature.
- [x] Add typed API functions matching contract. Focused component loads services independently from user editor metadata, surfaces unavailable state, reviews link/unlink choices with exact identities, disables busy controls, refreshes after changes, and offers separate Set shared password action for builtin users. Clear password after submission; show partial results. Candidate list never auto-selects.
- [x] Mount component in user edit screen. Fix existing admin Save Changes to surface password warnings rather than show unconditional success.
- [x] Run `npm test`, `npm run typecheck`, `npm run build`.
- [x] Spec review then quality review.

## Chunk 3: Verification and delivery

- [x] Run relevant backend suite and frontend checks. Verify additive migration with a disposable copy of production DB; no external mutations during smoke check.
- [x] Review entire feature, resolve important findings, commit changes and merge into local app-sso branch, preserving unrelated files.
- [x] Deploy to existing production stack after verified build, with SQLite backup; verify health and readonly user-link inspection. Never change real passwords for tests.


## Verification and deployment record

- Reviewed implementation code: `99a1e30` (feature commit `0ff73bb`, OIDC error-boundary fix `99a1e30`). Spec compliance and independent code quality reviews passed after resolving findings.
- Backend: 196-test relevant combined suite passed; four additional OIDC race regressions passed within the final 53-test OIDC/account-control run. The merged branch passed 33 focused backend tests.
- Frontend: all 36 tests passed, TypeScript and Vite production build passed. Desktop and 390px mobile layouts inspected.
- Additive migration on an isolated production SQLite copy preserved fingerprints of every existing table, with foreign-key and integrity checks passing. Image smoke verified unauthenticated denial and authenticated inspection of Katie's two existing links and 69 requests.
- Production database backup: `/opt/shelfmark-requests/config/backups/users-before-admin-library-controls-20261113T183459Z.db`.
- Rollback image retained as `shelfmark-dev:before-admin-library-controls`. Deployed image `sha256:1423a747d3a096669dde1c31c5157dd8e58149e9dfbda6f8bad063c56a15c0a4` was built from the full feature image plus the reviewed OIDC fix overlay, preserving the already-built frontend and runtime dependencies.
- Production health returned ok, live authenticated admin inspection returned HTTP 200, unauthenticated access was denied, both Katie links remained present, SQLite integrity passed, and public HTML served `index-hD2Nui1r.js` containing the new controls.
- No real user passwords were changed by verification or rollout.
