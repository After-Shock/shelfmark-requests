# Shared Duplicate Request Prevention Design

**Date:** 2026-07-15

## Goal

Prevent new duplicate non-terminal requests while allowing multiple users to track and receive notifications for the same title. Preserve one request row per interested user, link those rows into a shared group, and expose only one actionable request to administrators and download processing.

Existing duplicate rows are not consolidated. The new behavior applies to submissions made after deployment.

## Current Behavior

`POST /api/requests` currently checks only the submitting user's requests. It rejects a match when that user already has a request in `pending`, `approved`, `downloading`, or `prerelease_requested`. Another user can create a separate request for the same title, and `no_sources_requested` is not treated as active.

The check occurs before `RequestDB.create_request()`, so matching and insertion are not one atomic database operation.

## Request Group Model

Add a nullable `canonical_request_id` column to `requests` as a self-reference to `requests.id`.

- A canonical request has `canonical_request_id = NULL`.
- A joined user's row has `canonical_request_id` set to the canonical request's ID.
- Every user retains a request row, preserving existing per-user list behavior and ownership checks.
- Only canonical rows are actionable in admin queues, counts, download processing, and automatic request workers.
- API representations of canonical requests include `requester_count`, counting the canonical row plus active linked rows.
- Linked rows copy the canonical metadata and current status when created.

The database migration adds the column and supporting index without merging or rewriting existing request groups.

## Duplicate Identity

Two submissions match only when their `content_type` is the same. Ebook and audiobook requests remain independent.

Matching precedence:

1. If both submissions contain a provider and provider ID, compare normalized provider plus exact normalized provider ID.
2. Otherwise compare normalized title and normalized author.

Text normalization trims leading and trailing whitespace, collapses internal whitespace, and applies Unicode-aware case folding. Missing authors normalize to an empty value. Provider identity takes precedence when available, preventing title variations from splitting requests sourced from the same provider record.

## Active and Terminal Statuses

Users join an existing request when its canonical row has any non-terminal status:

- `pending`
- `prerelease_requested`
- `approved`
- `downloading`
- `no_sources_requested`

A new canonical request may be created after a prior matching group reaches a terminal status:

- `fulfilled`
- `denied`
- `failed`
- `cancelled`

## Atomic Create-or-Join Flow

Replace the route-level duplicate loop with `RequestDB.create_or_join_request(...)`.

The method runs under the existing database lock and a single write transaction:

1. Validate and normalize request identity.
2. Search matching non-terminal canonical rows.
3. If the submitting user already owns an active row in the group, return that row without inserting or notifying.
4. If another user's canonical request matches, insert a linked row with copied canonical metadata and current status.
5. Otherwise insert a new canonical row.
6. Commit before websocket broadcasts or external notifications.

If multiple pre-existing canonical rows match, the oldest non-terminal canonical row is selected for the new join. Existing duplicate groups remain separate, consistent with the decision not to auto-merge existing data.

### API Responses

- New canonical request: HTTP `201`, normal request payload, `joined_existing: false`.
- New linked row: HTTP `200`, the submitting user's row, `joined_existing: true`.
- Same-user repeat: HTTP `200`, the existing row, `already_joined: true`.
- Existing validation and library conflicts retain their current `400` or `409` responses.

The same-user path is idempotent so double-clicks and client retries cannot create additional rows.

## Status Synchronization

All workflow status changes target a request group transactionally.

- The canonical row is updated first.
- Every non-cancelled linked row receives the same workflow status, admin note, handler, task ID, completion timestamp, and other group-level workflow fields relevant to that transition.
- A failed update rolls back the whole group operation.
- Direct status mutation of a linked row is rejected or redirected to its canonical row, except for the user's own cancellation/removal flow.

Websocket updates are emitted after commit for every affected user-visible row. Admin-facing broadcasts identify the canonical request only.

## Cancellation, Deletion, and Canonical Promotion

A user's cancellation or deletion removes only that user's interest.

- Deleting a linked row does not affect the canonical request or other users.
- If the canonical requester leaves and active linked users remain, promote the oldest active linked row to canonical and repoint every remaining linked row to the promoted ID in one transaction.
- The promoted row retains the group's workflow state and processing metadata.
- If the final interested user leaves, cancel or delete the final request according to the existing endpoint semantics.
- Admin cancellation remains a group-level action and synchronizes cancellation to every active row.

Promotion must preserve download task references, prerelease metadata, admin notes, and current processing state.

## Lists, Counts, and Processing

User-facing request lists continue filtering by `user_id`, so each interested user sees their own row.

Admin and worker queries must exclude rows where `canonical_request_id IS NOT NULL` unless a query explicitly needs group members. This applies to:

- admin request lists and status counts;
- pending and approved work queues;
- prerelease processing;
- automatic search/download processing;
- stale-request or retry jobs;
- webhook and availability handlers that select actionable requests.

Canonical API rows expose `requester_count`. The initial implementation does not expose other users' names to regular users.

## Notifications

- New-request Discord/admin notifications fire only when a new canonical request is created.
- Joining an existing request does not create another admin notification.
- Status, failure, fulfillment, and book-available notifications fan out to every active user row in the group.
- A user who removed their interest receives no later group notifications.
- Notification fan-out occurs after the group transaction commits; failure to send one notification does not roll back request state or prevent attempts for other users.

## Frontend Behavior

The existing request list can continue displaying each user's row.

- HTTP `201` displays the existing successful submission message.
- HTTP `200` with `joined_existing: true` displays “Joined existing request.”
- HTTP `200` with `already_joined: true` displays “You are already tracking this request.”
- The local request cache is refreshed or updated with the returned user-owned row so the action button immediately reflects the requested state.
- Admin screens render only canonical requests and may display `requester_count` as demand context.

## Error Handling and Concurrency

Create, join, group update, promotion, and final-user removal are transactional. The implementation must not leave orphaned links, multiple promoted canonicals, or partially synchronized statuses.

The application-level lock prevents races within the process. The write transaction must also acquire SQLite write ownership before matching so concurrent application workers cannot both observe no match and insert separate canonicals.

Malformed or dangling `canonical_request_id` values are treated as data-integrity errors and logged; they are not silently converted into new groups.

## Z-Library Mirror Assessment

The local settings file does not override `ZLIB_PRIMARY_URL` or `ZLIB_ADDITIONAL_URLS`. Built-in defaults are:

- `https://z-lib.fm`
- `https://z-lib.gs`
- `https://z-lib.id`

On 2026-07-15, `.fm` resolved but returned HTTP 503 to a direct request, while `.gs` and `.id` did not resolve from the development host. The `.fm` result may be a challenge response handled by the project's pinned Chromium/bypasser path.

No unverified replacement URL will be added. Implementation verification will exercise the actual bypasser/download flow against `.fm`. Mirror configuration changes are in scope only if that end-to-end check fails and a trustworthy endpoint can be independently verified; otherwise the duplicate-request change leaves mirror settings untouched.

## Testing

### Database tests

- migration adds `canonical_request_id` and its index;
- provider identity takes precedence over metadata fallback;
- normalized title/author matching works across case and whitespace differences;
- ebook and audiobook remain separate;
- every non-terminal status joins and every terminal status permits a new canonical;
- same-user repeats are idempotent;
- cross-user submissions create linked rows;
- concurrent submissions produce one canonical group;
- group updates are atomic;
- linked deletion leaves the group active;
- canonical deletion promotes the oldest active linked row;
- final-user removal terminates the group;
- rollback preserves the prior group on an injected failure.

### Route and integration tests

- `POST /api/requests` returns the specified `201`/`200` response shapes;
- only canonical creation sends a new-request admin notification;
- user lists contain each user's own row;
- admin lists/counts contain one canonical item with the correct `requester_count`;
- status and availability notifications reach all active interested users;
- websocket updates reflect synchronized rows;
- existing Audiobookshelf duplicate-library and alternate-version behavior remains unchanged.

### Frontend tests

- new, joined, and already-tracking responses display distinct messages;
- returned rows update request state and disable duplicate submission;
- API errors continue using existing error presentation.

### Runtime verification

- submit the same ebook as two users and observe one admin item plus two user-visible rows;
- advance the canonical request and observe both users update and receive notifications;
- remove each user in both canonical-first and linked-first order;
- exercise the configured Z-Library mirror through the real pinned Chromium/bypasser path before deciding whether any URL change is required.

## Out of Scope

- merging duplicate requests that existed before deployment;
- exposing requester identities to other regular users;
- redesigning the Requests UI;
- adding unverified Z-Library mirrors;
- changing the meaning of existing request statuses.
