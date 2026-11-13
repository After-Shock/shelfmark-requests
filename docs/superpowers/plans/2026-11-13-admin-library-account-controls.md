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
- [ ] Spec review then quality review.

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
- [ ] Spec review then quality review.

## Chunk 3: Verification and delivery

- [ ] Run relevant backend suite and frontend checks. Verify additive migration with a disposable copy of production DB; no external mutations during smoke check.
- [ ] Review entire feature, resolve important findings, commit changes and merge into local app-sso branch, preserving unrelated files.
- [ ] Deploy to existing production stack after verified build, with SQLite backup; verify health and readonly user-link inspection. Never change real passwords for tests.
