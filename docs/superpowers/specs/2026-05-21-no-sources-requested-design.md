# No Sources Requested Design

**Date:** 2026-05-21

## Overview

Add a new request status, `no_sources_requested`, for cases where staff cannot find the requested item through normal sources but has requested it from the provider. This is an active request state, not a terminal one.

The new state must preserve the current request workflow, remain visible to admins and users, and roll out safely against the production SQLite database stored at `/config/users.db`.

## Status Semantics

`no_sources_requested` means:

- the user request is still active
- direct source search did not produce a usable item
- staff escalated the request externally to the provider
- staff is still waiting on a later outcome

This status is not part of request history. It must remain in the active request list until it becomes `fulfilled`, `failed`, or `cancelled`, or is moved back to `approved`.

## Workflow

Allowed transitions into `no_sources_requested`:

- `pending` -> `no_sources_requested`
- `approved` -> `no_sources_requested`
- `failed` -> `no_sources_requested`

Allowed transitions out of `no_sources_requested`:

- `no_sources_requested` -> `approved`
- `no_sources_requested` -> `fulfilled`
- `no_sources_requested` -> `failed`
- `no_sources_requested` -> `cancelled`

Behavioral requirements:

- entering `no_sources_requested` must not auto-queue any download
- requests in `no_sources_requested` remain in the admin active queue
- `completed_at` must be `NULL` while the request is in `no_sources_requested`
- standard admin note support remains available for extra context

## Backend Changes

Update the request status source of truth in `shelfmark/core/request_db.py`:

- extend `_VALID_STATUSES` to include `no_sources_requested`
- keep `_TERMINAL_STATUSES` unchanged so the new state stays active
- expand the `requests.status` SQLite `CHECK` constraint in `_CREATE_REQUESTS_TABLE_SQL`
- ensure `get_request_counts()` returns a bucket for `no_sources_requested`
- ensure `update_request_status()` clears `completed_at` when moving into `no_sources_requested`

Update `shelfmark/core/request_routes.py`:

- allow `/api/requests/<id>/status` to accept `no_sources_requested`
- preserve existing request update broadcasts and notifications behavior
- do not introduce automatic fulfillment logic for the new state

## Frontend Changes

Update `src/frontend/src/types/index.ts`:

- extend `RequestStatus` with `no_sources_requested`
- extend `RequestCounts` with `no_sources_requested`

Update `src/frontend/src/components/RequestsSidebar.tsx`:

- add `no_sources_requested` to `STATUS_STYLES`
- add an admin dropdown option labeled `No Sources / Requested`
- keep the status in the `Active` view
- keep it out of `HISTORY_STATUSES`
- allow later transitions to `approved`, `fulfilled`, `failed`, and `cancelled`
- keep `Mark Completed` available

Update `src/frontend/src/components/UserDashboard.tsx`:

- add `no_sources_requested` to the status badge map
- use a user-facing label such as `Requested from Provider`
- count it as `In Progress` alongside `approved` and `downloading`
- continue showing `admin_note` where present

## Migration Strategy

Because SQLite cannot alter the existing `CHECK` constraint in place, add a new numbered migration in `RequestDB._run_migrations()` that recreates the `requests` table with the expanded status list and copies existing data forward.

Requirements:

- migration must be forward-only
- migration must preserve all existing request rows and metadata columns
- migration must preserve `completed_at`, `hidden_from_admin`, prerelease fields, and manual-request fields
- migration must not modify unrelated user data in `users.db`

This migration should follow the same table-rebuild pattern already used for previous request status additions in this repository.

## Production Rollout Safety

Production host: `sullyflix-com`

Observed live configuration on 2026-05-21:

- container name: `shelfmark`
- compose working directory: `/opt/shelfmark-requests`
- compose file: `/opt/shelfmark-requests/docker-compose.yml`
- persistent request database on host: `/opt/shelfmark-requests/config/users.db`
- in-container path: `/config/users.db`

Safe rollout procedure:

1. Create a timestamped backup of `/opt/shelfmark-requests/config/users.db` on the host.
2. Optionally copy the DB to a scratch file and validate container startup against that copy first.
3. Deploy updated code and rebuild or restart only the `shelfmark` container.
4. Verify startup completed successfully and the schema migration ran cleanly.
5. Spot-check existing requests and the new status behavior in the UI.

Rollback procedure:

1. Stop the updated `shelfmark` container.
2. Restore the timestamped `users.db` backup.
3. Restart the previous known-good container image or code revision.

## Verification

Automated coverage to add:

- migration test proving an older requests table upgrades cleanly and preserves rows
- request DB status update test proving `no_sources_requested` is accepted
- request DB status update test proving `completed_at` is cleared for `no_sources_requested`
- request counts test proving the new bucket is returned
- route-level or request workflow test proving the status update endpoint accepts the new state

Manual verification:

- move an existing request to `no_sources_requested`
- confirm it remains in the active request list
- confirm it does not appear in history
- confirm the user dashboard displays the new label
- confirm transition from `no_sources_requested` to `fulfilled` works normally
- confirm transition from `no_sources_requested` to `failed` works normally
- confirm production startup still reads existing request data from `/config/users.db`

## Files Expected To Change During Implementation

Backend:

- `shelfmark/core/request_db.py`
- `shelfmark/core/request_routes.py`
- `tests/core/...` request workflow or request DB tests

Frontend:

- `src/frontend/src/types/index.ts`
- `src/frontend/src/components/RequestsSidebar.tsx`
- `src/frontend/src/components/UserDashboard.tsx`

## Non-Goals

This change does not:

- add a separate provider-request tracking subsystem
- add a dedicated new tab for requested-provider items
- add automatic reminders or follow-up polling against providers
- change the existing semantics of `fulfilled`, `failed`, `cancelled`, or prerelease requests
