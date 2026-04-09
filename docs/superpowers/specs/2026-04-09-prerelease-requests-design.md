# Pre-release Requests Design

**Goal**

Allow users to request unreleased content without creating a dead-end workflow. Requests with a future release date should be held in a dedicated pre-release state, then automatically become normal actionable requests once the release date passes.

**Current State**

The request system already stores `is_released` and `expected_release_date`, and the frontend already displays unreleased metadata in the request sidebar. But unreleased requests still enter the same admin workflow as normal requests. In practice, that forces admins to deny the request and ask the user to resubmit later.

That produces two avoidable problems:

1. The user loses their place and has to remember to return later.
2. Admins are forced to use `denied` for something that is not actually rejected.

## Recommended Approach

Introduce a first-class request status: `prerelease_requested`.

This is the cleanest model because it preserves the existing meaning of `pending` as "actionable now" while making prerelease requests explicit everywhere the product reasons about request state.

## Lifecycle

### Automatic entry

When a user creates a request:

- If the request metadata says `is_released == false`
- And `expected_release_date` is present
- And the release date is in the future

Then the created request should start in `prerelease_requested` instead of `pending`.

If release metadata is absent or ambiguous, the request should continue to enter the existing `pending` path.

### Automatic activation

A periodic backend sweep should detect prerelease requests whose `expected_release_date` has passed and promote them to `pending`.

That transition should:

- update the request row
- broadcast the websocket `request_update`
- notify the requester that their prerelease request is now active

After promotion to `pending`, the request follows the existing workflow unchanged.

### Manual admin controls

Admins should have two explicit controls for edge cases:

- `Move to Pre-release`: converts a normal pending request into `prerelease_requested` and stores or updates the expected release date
- `Activate Now`: converts `prerelease_requested` into `pending` immediately when metadata is wrong or the item becomes available early

## Status Model

Add `prerelease_requested` to the request status enum and database constraint.

Semantics:

- `prerelease_requested`: valid request, accepted into the system, but intentionally withheld from the normal admin action queue until the release date arrives
- `pending`: valid request and ready for normal approval/deny processing now

This avoids the ambiguity that would come from using a separate boolean flag on top of `pending`.

## Backend Design

### Request creation

`POST /api/requests` should continue to accept the current payload shape. The server decides whether the initial status is `pending` or `prerelease_requested` based on release metadata.

No extra user prompt is required for the common case.

### Database

The `requests` table should be extended so `status` accepts `prerelease_requested`.

The existing `expected_release_date` column remains the source of truth for activation timing.

No new table is needed.

### Activation job

Add a lightweight background scheduler in the Flask/backend process that periodically:

- finds requests in `prerelease_requested`
- parses `expected_release_date`
- compares it to current date in a deterministic timezone-safe way
- promotes eligible rows to `pending`

Requirements:

- idempotent if run multiple times
- safe on startup
- tolerant of invalid or missing dates
- logs every automatic transition

### Duplicate handling

Duplicate detection must treat `prerelease_requested` as an active request status. Users should not be able to stack multiple prerelease requests for the same book/audiobook.

### Counts and filters

Request counts should include prerelease as its own status bucket.

Admin and user list endpoints should continue to support `status=<value>`, now including `prerelease_requested`.

### Notifications

Add a requester-facing status notification for the activation event.

Recommended wording:

- prerelease held: optional, not required for MVP
- prerelease activated: required

The important notification is the activation message:

"Your prerelease request is now active and ready for processing."

Admin-side new-request notifications can stay unchanged for MVP.

## Frontend Design

### User view

Users should see prerelease requests clearly separated from ordinary pending requests.

Recommended UI behavior:

- status pill label: `Pre-release`
- subtitle line: `Expected <date>`
- separate section or filter bucket in the requests sidebar

The user should understand:

- the request was accepted
- no further action is needed from them
- it will activate automatically

### Admin view

Admins should see prerelease requests in their own section, not mixed into the standard pending queue.

Recommended admin actions on prerelease cards:

- `Activate Now`
- `Deny`
- optional later: `Edit Date`

Pending cards should remain unchanged except for a new `Move to Pre-release` action when the request was created without reliable release metadata.

### Status styling

Add a distinct visual treatment for `prerelease_requested` that is not confused with denial or normal pending. Use a reserved informational style rather than red or success colors.

## Error Handling

### Missing release date

If `is_released == false` but no `expected_release_date` exists, do not enter prerelease automatically. Keep the request in `pending` and let admin decide.

### Invalid release date

If stored `expected_release_date` cannot be parsed by the activation job:

- leave status unchanged
- log a warning
- keep admin controls available

### Early availability

If an item becomes available before the recorded release date, admin can use `Activate Now`.

## Testing Strategy

### Backend tests

Add coverage for:

- request creation entering `prerelease_requested` automatically
- request creation staying `pending` when release metadata is absent
- duplicate detection treating prerelease as active
- activation job moving eligible rows to `pending`
- activation job ignoring future dates
- notification dispatch on prerelease activation
- manual admin transition routes for prerelease conversion and activation

### Frontend tests

Add coverage for:

- new status typing and rendering
- sidebar grouping/filtering of prerelease requests
- admin action visibility for prerelease vs pending requests
- expected release date display

## Minimal MVP Scope

The smallest version worth shipping is:

1. New backend status `prerelease_requested`
2. Automatic prerelease assignment on request creation when future release metadata is available
3. Periodic automatic promotion to `pending` after release date
4. Requester notification when promotion happens
5. Frontend status display and separate prerelease grouping

Manual admin conversion into prerelease is useful, but can be added in the same feature only if it stays small. If scope needs trimming, automatic prerelease creation and automatic activation are the real value.

## File Impact

Likely backend touchpoints:

- `shelfmark/core/request_db.py`
- `shelfmark/core/request_routes.py`
- `shelfmark/core/request_notifications.py`
- `shelfmark/main.py` or a new request scheduler module
- tests around request DB and request routes

Likely frontend touchpoints:

- `src/frontend/src/types/index.ts`
- `src/frontend/src/components/RequestsSidebar.tsx`
- `src/frontend/src/hooks/useRequests.ts`
- request-related API helpers only if new admin endpoints are added

## Decision Summary

Use a dedicated `prerelease_requested` status, assign it automatically when reliable future release metadata exists, and automatically promote it to `pending` once the release date passes. This gives users a one-step request flow and removes the need for admins to misuse denial as a placeholder state.
