# Admin library account controls

## Goal

In Settings → Users, an administrator can inspect and manually link existing Ebooks and Audiobooks accounts, then optionally set one supplied password on requests and linked libraries. Existing external accounts retain their IDs, usernames, history and settings.

## Approach

Add a Library accounts section to the existing user editor. Each service shows its linked account's username, email when available, and availability. An account picker shows existing accounts, prioritizing username and email matches. Suggestions are never automatically linked. The admin reviews the selected account and applies Link account; no external password is needed for this administrative operation. Unlink removes the association without deleting an external account or resetting its password.

Store explicit service/account-ID associations, with unique ownership per external account. This supports different usernames without renaming accounts. The alternative of keeping username-only links is smaller but cannot resolve the case encountered in this session without renaming accounts. Automatically linking by email is ambiguous when multiple requests accounts share an email; do not use it for these controls.

## Persistence and compatibility

Introduce a user-library-account mapping containing requests user ID, service, stable external account ID and display username. Enforce one account per service per requests user and one owner per external service/account ID. Foreign keys remove associations when a requests user is deleted, without deleting external accounts.

Existing provisioned_services links continue working. Resolve explicit mappings first; retain existing unique username resolution for legacy links. On explicit selection reject accounts already owned through either explicit mappings or legacy links. Treat account IDs as authoritative, refresh names from the service, and fail closed if a mapped account disappears. Do not fall back to a different same-named account when an explicit mapping exists.

All consumers must resolve the same external identity: library status, self-service linking, account creation checks, password changes, emailed reset summaries, automatic linking, Ebooks shortcut sessions and Audiobooks OIDC. Preserve the existing requests user ID as OIDC subject. Detect an existing Audiobooks OIDC association to another requests identity and reject linking with an actionable conflict instead of claiming success or taking over that association. Review deployed Audiobooks behavior before implementing that integration.

## Password behavior

Linking alone does not alter any passwords. Add Set shared password with new-password and confirmation fields. The supplied password can be a known current password or a newly chosen password; stored requests passwords cannot be recovered. Validate with existing rules, update the local requests password and attempt every linked library independently. Existing admin password changes use the same resolver and result reporting.

Return and display per-service updated, skipped or failed results. A remote failure does not undo a successful local password change; state which passwords changed and allow retry with the supplied password. Never persist plaintext passwords, expose password hashes or include secrets in logs. Clear password inputs after submission. Restrict local password changes to supported local-password users.

## API and UI boundaries

Use admin-only endpoints for inspecting account links and candidates and for linking/unlinking. Resolve and validate the selected external ID server-side; do not trust client usernames or match suggestions. Return only account identity/status fields, never full external user objects containing tokens. Reject invalid services, missing users, disabled services, duplicate ownership and inaccessible accounts without changing links. Recheck ownership within the write transaction; database uniqueness is the concurrency backstop.

Keep the user editor usable if one service is unavailable. Show loading, empty, failed and successful states separately for each library. Disable repeated submissions while an operation is pending. Show a concrete review of requests username and selected library username before applying account changes or password updates. Refresh status after each operation and show partial failures visibly.

## Scope

This feature manages account associations and password synchronization. Merging requests users, migrating listening history, renaming library accounts, deleting library users and creating new library accounts are outside these new controls. Existing self-service creation remains available and must reject duplicate accounts clearly instead of exposing SQLite constraint messages.

## Verification and rollout

Use failing tests first for admin authorization, mappings between different usernames, ownership conflicts including legacy owners, missing/stale external accounts, concurrent ownership, unlinking, unchanged passwords during linking, password targeting and partial failures. Cover Ebooks SSO and Audiobooks OIDC mapping behavior and regressions for legacy links and self-service flows. UI tests cover identity display, explicit selection, review, busy states and partial results. Run relevant backend tests, frontend tests, TypeScript checks and production build. Review changes before completion. Back up production SQLite before deploying its additive migration and smoke-check account status without altering real user passwords.

## Approval

Approved by the user, including the option for a password reset after linking to unify credentials.

## Approved implementation clarifications

The user approved this design and explicitly accepts a password reset after linking to unify credentials. Link and password update are always separate operations. Non-builtin users cannot use the shared-password operation; reject before writes. Unlink clears both explicit association and legacy service flag, and can execute while a library is down. An explicit selection supersedes the same user's legacy identity; claims by other users, including legacy claims, are rejected with ownership rechecked under the database write lock. All claim paths use this ownership check.

Canonical IDs are decimal Calibre-Web IDs and opaque Audiobookshelf IDs; external account identities remain authoritative and must resolve uniquely. Deletions and unavailable services retain mapping metadata; explicit mappings never fall back by username. Account ID reuse in a restored external database requires administrator relinking rather than automatic fallback. Audiobooks OIDC keeps shelfmark-<requests ID>; conflicting existing external subject associations are rejected, never reassigned. All external password operations target resolved IDs. API request/response, result statuses and idempotence are specified in the implementation plan.


## Verified integration constraints

Deployed Calibre-Web IDs are SQLite AUTOINCREMENT primary keys, and Audiobookshelf IDs are UUIDs. Both remain stable across username changes and are not reused through normal account creation; manual external database restoration/replacement requires administrator review of stored links.

The deployed Audiobookshelf API exposes hasOpenIDLink but hides the subject. New claims reject an already-bound account unless its association is verifiably safe; existing identical explicit associations are idempotent. Established legacy links remain trusted for backward compatibility, while new legacy claims receive the stricter conflict check. Audiobookshelf resolves subject before username. Retired account metadata therefore persists across local unlink/replacement and blocks new links or SSO while a former account may intercept the same subject. The operator must clear the old OpenID association in Audiobookshelf before switching accounts; this feature never silently reassigns subjects.

Account-control endpoints deliberately require an authenticated local admin identity even in no-auth mode, because these operations can change external account access and credentials. The existing general admin API keeps its compatibility contract. The duplicate legacy password form is replaced in the UI by the shared-password action; the existing admin update endpoint retains backwards compatibility and adds per-service password_results alongside warning strings.
