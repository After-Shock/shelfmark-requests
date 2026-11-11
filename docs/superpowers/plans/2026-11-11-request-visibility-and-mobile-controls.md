# Request visibility and mobile controls implementation plan

**Goal:** Keep active requests visible, reserve removal for History, share pre-release requests with all authenticated users, and keep Apply reachable on narrow screens.

**Design:** Preserve canonical request groups and existing tracking. Lists, totals and status counts use the same visibility rule: own requests plus pre-release canonical requests where the viewer has no pre-release member already. Shared rows grant read access only. Admin lists ignore old hidden flags for active rows. History removal retains current owner/admin semantics. Reject DELETE for nonterminal requests on the server. Status/date/Apply controls stack to fit narrow request cards at every viewport size. Admin History removals stay hidden and totals/counts follow the same rule.

**Tech stack:** Flask, SQLite, React, Tailwind, pytest, Vitest.

## Work

- [x] Add regression tests for shared visibility, deduplication, counts, status transitions, hidden active recovery and protected deletion. Run to confirm failures.
- [x] Implement consistent database visibility and route protections; preserve private non-pre-release requests.
- [x] Restrict row X to History. Make status controls fit narrow cards and safe viewport height.
- [x] Run request backend tests, frontend tests/typecheck/build and browser layout checks.
- [x] Review changes, back up production SQLite, restore hidden active rows, deploy tested changes, and verify production health and restored visibility.

## Recovery evidence

Read-only production inspection found hidden active IDs 220, 407, 408 (pending) and 461 (Peculiar Stars, prerelease_requested, release date 2026-11-17). Restore visibility without changing statuses, ownership, release dates or tracking membership. Back up with SQLite's backup API before changing data.

## Verification and recovery

- 174 request-related backend tests passed, including active DELETE rejection for owners/admins, shared pre-release visibility, deduplication, privacy after activation, restored hidden rows and History badge consistency.
- 19 frontend tests passed; TypeScript and production Vite build passed.
- Chromium and WebKit browser checks at 320, 375, 393, 402, 440 and 1280 px: status dropdown/date/Apply remain inside the viewport, Apply successfully calls both status actions, removal X appears only in History.
- Live SQLite backup: `/opt/shelfmark-requests/config/backups/users-before-request-visibility-20261111T232635Z.db`.
- Restored `hidden_from_admin=0` for active IDs 220, 407, 408 and 461. SQLite quick_check returned ok. All other fields preserved.

## Rollout

- Independent review found no blocking defects; corrected a stale admin-visibility comment.
- Deployed implementation commit `6dd0c21` on the production `app-sso` branch with a rebuilt `shelfmark-dev` image.
- Kept rollback image tag `shelfmark-dev:before-request-visibility-20261111`.
- Production container reports healthy and `/api/health` returns `{"status":"ok"}`.
- Read-only route smoke checks against production data passed for all 30 user accounts: all see the single current pre-release (Peculiar Stars), totals/counts match, private non-pre-release rows stay private, and all four recovered IDs appear in the admin list.
