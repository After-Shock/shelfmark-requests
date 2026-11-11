# Pre-release auto-approval implementation plan

**Goal:** Keep unreleased requests exclusively in Pre-release and automatically approve/process them at 9 AM America/New_York on release day, preserving admin push notifications.

**Architecture:** Active filtering excludes prerelease_requested. The existing minute-aligned scheduler atomically claims each due canonical pre-release group, marks it released/approved, and invokes an injected download callback wired in main.py. The callback uses the existing download reservation and worker, backfilling metadata when needed. One push announces the automatic approval and group members receive approval emails. Missed release times are processed on the next scan after restart; completed transitions cannot repeat.

**Tech stack:** SQLite, Flask/Python scheduler, React, pytest, Vitest.

- [x] Add failing scheduler tests for 9 AM winter/summer boundaries, automatic approval, group deduplication, repeat scans, callback and push behavior; add UI separation tests.
- [x] Implement atomic group approval and background download callback, wire scheduler, preserve notifications and error isolation.
- [x] Exclude pre-releases from Active and update explanatory text.
- [x] Run request backend tests, frontend tests/typecheck/build; review the changes.
- [ ] Deploy to the existing production stack, verify health, ensure current future pre-release remains on hold and test the scheduled workflow against an isolated database in the deployed image (without sending notifications or queuing real downloads).

## Validation

- Watched the new tests fail on the original pending transition and overlapping Active filter before implementing.
- 184 request-related backend tests pass, including winter/summer 9 AM UTC offsets, repeat scans, concurrent scanner claims, stale rescheduling, linked groups, missed-time catchup and worker reservations/cleanup.
- 21 frontend tests and TypeScript/Vite production build pass.
- Corrected an existing flaky concurrency test: its barrier now follows the initial read, so both requests consistently exercise the intended simultaneous stale-snapshot scenario.
- Production database backup prepared: `/opt/shelfmark-requests/config/backups/users-before-prerelease-auto-approval-20261111T234253Z.db`.
- Rollback image: `shelfmark-dev:before-prerelease-auto-approval-20261111`.

- Review found a notification ordering race. Fixed it by sending approval emails and the admin push before starting the worker; a regression test verifies email → push → processing order.
- Focused re-review passed with no further issues.
