# Media issue reports — design

Date: 2026-11-20 · Status: draft for approval · Branch: app-sso

## Intent

Users of books.sullyflix.com should be able to say "this book/audiobook is wrong" about **any** item in
the library — one they requested, one someone else requested, or one that predates Shelfmark — and
have Shelfmark fix it without the admin. Reporting must be painless for users; fixing must be painless
for the admin.

**The admin is only pinged when automation already tried and failed, or when it wants to change
something Shelfmark did not add.**

## Goals

- Report from two places: a finished request in History, and a search result that is already in the library.
- Auto-fix by problem type (table below). Track the report state so the user sees it move.
- Items Shelfmark delivered: fix fully automatically. Items it did not deliver: prepare the fix, admin
  approves with one tap (option C).
- Weekly report limit: **6 per non-admin user**, separate from the 6 request slots, same Monday
  00:00 America/New_York week. Admins unlimited.
- One open report per item (any user). A second user reporting the same open item joins it, free.

## Non-goals

- In-app reading/listening or file inspection (no auto-detecting language/quality from file contents).
- Fixing Calibre metadata other than cover/title/author.
- Re-adding manual approval for requests (see request-workflow-quota memory).

## Anti-goals (failure even if it works)

- Anything that can corrupt or silently lose library data. Every replaced file/cover/metadata is
  archived and restorable; nothing is hard-deleted.
- Removing a torrent Shelfmark did not add (existing rule).
- A report storm causing swap loops: one open report per item, and an item gets at most one
  automatic attempt per problem type; the next report of the same type goes to the admin.
- Pushover noise: no push on report creation; only on "needs you".

## Constraints found on prod

- Audiobooks: Shelfmark writes directly to `/UnRaid/audiobooks` (rw) and has an ABS token
  (`audiobookshelf.py`, `scan_libraries`). Matching via the ABS in-memory cache (`find_match`).
- Ebooks: Shelfmark writes to the import folder `/books` (= `/media/bank/ebookimport`); the running
  Calibre GUI (`calibre` container, linuxserver/calibre) auto-adds into `/media/NASmedia2/ebooks`.
  Shelfmark mounts that library **read-only** (`calibre_library.py`). Calibre's content server
  already runs (port 8081, `autolaunch_server`, `local_write True`).
- Requests do not record what was delivered. Retry exclusion (`_failed_release_ids`,
  `_release_retries` in `request_routes.py`) is in memory only and gone after a request finishes.
- Requests have a `download_task_id`; the task (`DownloadTask`) knows `source`, `task_id`
  (release id), `title`, `format`, `download_path`.

## Approaches (for the ebook write path)

1. **Calibre content server (picked).** Add a `shelfmark` user with write access; Shelfmark calls
   the endpoints `calibredb --with-library http://…` uses (remove book, set metadata/cover). All
   writes go through the running Calibre, so no clash with auto-add. Cost: one-time setup; the
   endpoints are Calibre-internal but `calibredb` depends on them.
2. Calibre-Web admin forms. Rejected: brittle against Calibre-Web updates, writes behind the
   running GUI's back.
3. Mount the library rw and write `metadata.db`. Rejected: two writers on a DB the GUI holds open
   is the classic corruption path; the library is the most important data.

The user picked 1, built in two phases.

## Phases

- **Phase 1:** reports, limit, delivery record, Needs action integration, all audiobook fixes
  (file swap, cover, title/author). Ebook reports go straight to Needs action.
- **Phase 2:** ebook file swaps and cover/title/author fixes through the Calibre content server.

## Problem types and automatic fix

| User picks | Auto-fix |
|---|---|
| Wrong language | Re-download, excluding the delivered release |
| Wrong book / edition (abridged, dramatized, different book) | Re-download, excluding the delivered release |
| Won't open / broken / missing chapters / bad formatting | Re-download, excluding the delivered release and preferring another source |
| Audio problem (quality, narrator, missing parts) | Re-download, excluding the delivered release |
| Wrong cover | Set the cover from Shelfmark's metadata lookup; if that is the image being replaced, ask the library to re-match. Second cover report on the same item → admin |
| Wrong title / author | Re-match details in the library, archive old values |
| Something else (free text, required) | Admin |

All file-replacing fixes are one shared "replace" action; the types differ only in what they
exclude/prefer and in the label the admin sees.

## Delivery record (needed for "avoid the delivered copy")

New table `request_deliveries` in request_db (next migration): `request_id`, `source`,
`release_id` (task_id), `release_title`, `format`, `final_path`, `library` (`abs`|`calibre`),
`library_item_id` (nullable, filled when known), `delivered_at`. Written in
`_sync_request_db_on_terminal` on COMPLETE. An item is "Shelfmark-delivered" iff it has a row here.

**Backfill (user decision 2026-11-20):** the migration creates delivery rows for existing canonical
`fulfilled` requests that have a `download_task_id` (185 on prod at writing): `release_id` =
`download_task_id`, `final_path`/`library_item_id` left NULL and resolved at swap time via
`find_match` (search-style confirmation is not needed: the request's title/author is the key).
Requests fulfilled as "Already in library" have no `download_task_id` and get no row.

Items without a record (added by hand, or fulfilled without a download) have no excluded release: the
re-download excludes nothing but still requires admin approval (option C), so the admin sees what
will be swapped in.

## Report record

New table `media_reports`: `id`, `library` (`abs`|`calibre`), `library_item_id`, `title`, `author`,
`content_type`, `request_id` (nullable), `problem_type`, `note`, `status`, `created_by`,
`created_at`, `updated_at`, `resolution_note`. Join table `media_report_users` for users who joined
an open report. Usage for the limit: `report_quota_usage` ledger, same pattern as
`request_quota_usage` (a report the admin dismisses as invalid does **not** refund — builder call
below — joins never count).

Statuses: `open` → `fixing` → `fixed` | `awaiting_approval` (option C) | `needs_action` → `fixed` |
`dismissed`.

## Flows

- **Report:** user picks a problem type (+ optional note, required for "something else"). Server
  checks the limit atomically (as `create_or_join_request` does), joins an open report on the same
  item if one exists, else creates one.
- **Delivered item, file problem:** create a fixing request internally (reusing
  `_auto_download_request` with an excluded-release set seeded from the delivery record). On
  COMPLETE: move the old file/folder to an archive dir (`/UnRaid/audiobooks/.shelfmark-replaced/
  <report_id>/`), place the new one, ABS rescan, record the new delivery, report → `fixed`.
  No replacement found → `needs_action` + Pushover.
- **Non-delivered item, file problem:** download the replacement into a staging dir, report →
  `awaiting_approval`, Pushover "Fix ready to approve" with Approve/Dismiss in Needs action. Approve
  performs the same swap.
- **Cover / details:** audiobooks via ABS API (set cover from URL; item match). Old cover/details
  saved in the report row for undo. Delivered → automatic; not delivered → awaiting_approval.
- **Ebooks in phase 1:** report → `needs_action` + Pushover.
- **Undo:** admin can restore the archived file/cover/details from the report.

## UI

- History item (fulfilled): "Report a problem" button.
- Search results: library match runs at search time; matches show "In library" + "Report a problem"
  in place of Request.
- Report dialog: problem type list, note, "x of 6 reports left this week".
- User's Requests panel: "Reports" section showing state ("We're on it" / "Fixed" / "Waiting on admin").
  A fixed cover shows "Still wrong?".
- Admin Needs action tab gains report items (needs_action and awaiting_approval) with Approve,
  Dismiss, Undo.
- Users panel: per-user report usage + reset, next to the request limit; default
  `WEEKLY_REPORT_LIMIT` (6) in the users tab config.

## Notifications

- Pushover: only `needs_action` and `awaiting_approval`, and a user reaching the weekly report limit
  (mirrors requests). Nothing on report creation.
- Discord: none for reports (builder call; easy to add later).

## Builder-check answers (Claude's calls)

- **Fixes are not `requests` rows.** A new code path reuses only the release search and queue steps
  of `_auto_download_request`, skipping its already-owned check (the item *is* owned), quota, History,
  and the Discord "book available" post. The fix's download task carries `report_id` so
  `_sync_request_db_on_terminal`-style handling routes completion to the report, not a request.
- **Item identity survives swaps.** A report keys on `(library, content_type, normalized title,
  normalized author)` plus `library_item_id` when known. After a swap, the report and the new
  delivery row are linked to the old one, so "one automatic attempt per problem type" follows the
  chain, not the ABS item id. Ebooks (no id from `calibre_library.find_match`) use the key alone.
- **Replacements download to a staging dir.** Phase 1 adds a per-task output path override. The swap
  is: verify the staged copy → move the old copy to the archive → move the new copy in → ABS rescan.
  Torrent removal for a fix task happens only after the swap is verified (never on the old item's match).
- **Search-originated reports confirm the item.** The dialog shows the matched library item's
  cover/title/author; several matches → the user picks one. A report from search on an item
  without a delivery record goes through admin approval (option C anyway).

- One automatic attempt per item per problem type; repeat → admin.
- Dismissing a report does not refund the report slot.
- Archive dir for replaced audiobooks lives under the library root, hidden folder, so ABS ignores it
  (builder must confirm ABS skips dot-folders, else use a path outside the library).
- No Discord posts for reports.

## Left to the builder

- Exact ABS endpoints for cover-from-URL and item match; Calibre content server endpoint shapes
  (phase 2), auth setup, and container networking to port 8081.
- Where search-time library matching runs without slowing search (both lookups are local/cached).
- Migration numbering, and test layout following `tests/core/test_request_quota_workflow.py`.
