# Media Issue Reports — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users report problems with any library item; audiobook problems are fixed automatically
(file swap, cover, details), everything else lands in the admin's Needs action queue.

**Architecture:** Reports, deliveries and the report ledger live in `users.db` (request_db migration 12)
with their queries in a new `shelfmark/core/report_db.py`. A new `shelfmark/core/report_fixes.py`
decides and runs fixes, reusing the release search extracted from `_auto_download_request`. Fix
downloads are ordinary download tasks with a staging destination and a `report_id`; their completion
is routed to the report instead of a request.

**Tech Stack:** Python 3 / Flask / SQLite, React + TypeScript (Vite, vitest), Audiobookshelf REST API.

**Spec:** `docs/superpowers/specs/2026-11-20-media-issue-reports-design.md` (read it first; Phase 1 only).

## Global Constraints

- Report limit: `WEEKLY_REPORT_LIMIT` default **6**, 0–100, per non-admin user; admins unlimited; week = Monday 00:00 America/New_York (`request_quota.week_bounds`). Joins never count. Dismissing does not refund.
- One open report per item (statuses `open`, `fixing`, `awaiting_approval`, `needs_action` are "open").
- Option C: Shelfmark-delivered items fix automatically; others wait for admin approval. Ebooks (Phase 1) → `needs_action`.
- One automatic attempt per item per problem type; a repeat goes to `needs_action`.
- Nothing is hard-deleted: replaced files go to `<parent of ABS local prefix>/.shelfmark-replaced/<report_id>/`, staging is `<parent>/.shelfmark-staging/<report_id>/` (prod: `/UnRaid/.shelfmark-replaced`, `/UnRaid/.shelfmark-staging` — same filesystem as `/UnRaid/audiobooks`, outside every ABS library root).
- Only remove torrents Shelfmark added; a fix task's torrent is removed only after its swap is verified.
- Pushover only for `needs_action`, `awaiting_approval` and "weekly report limit reached". No Discord for reports.
- Fix downloads never create `requests` rows, never touch request quota, History, or "book available" Discord.
- Tests run in the image: `docker run --rm -u $(id -u) -e HOME=/tmp -v $PWD:/src -w /src --entrypoint python3 shelfmark-dev -m pytest -q -p no:cacheprovider <paths>`; frontend: `cd src/frontend && node_modules/.bin/tsc --noEmit && node_modules/.bin/vitest run`.
- Prod deploy only via `~/bin/shelfmark-release --deploy` (verified backup first). Version → **1.14.0**.

## Review Focus

1. Book lives in ABS's `/audiobooks` (union mount, not under `ABS_PATH_PREFIX`) → file problems go to `needs_action` with "Shelfmark can't replace files in this library"; covers/details still auto-fix. (Task 4 test `test_unmapped_abs_path_goes_to_admin`.)
2. Staged download is empty, has no audio file, or ABS later lists nothing → no swap, old copy untouched, `needs_action`. (Task 5 `test_staged_copy_without_audio_is_not_swapped`.)
3. Swap fails halfway (old moved to archive, new move raises) → old copy moved back, `needs_action`. (Task 5 `test_swap_rolls_back_when_new_move_fails`.)
4. Shelfmark restarts while a report is `fixing` (task gone) → on startup it becomes `needs_action` with "Interrupted by a restart". (Task 5 `test_interrupted_fix_moves_to_needs_action`.)
5. ABS item deleted since the report (API 404) → `needs_action`, no exception escapes the worker. (Task 6 `test_missing_abs_item_goes_to_admin`.)

---

### Task 1: Schema, report store, delivery backfill

**Files:**
- Modify: `shelfmark/core/request_db.py` (new SQL constants near `_CREATE_QUOTA_USAGE_TABLE_SQL`; migration `current_version < 12` after migration 11)
- Create: `shelfmark/core/report_db.py`
- Test: `tests/core/test_report_db.py`; update `tests/core/test_request_db_groups.py` expected version 11 → 12

**Interfaces:**
- Produces tables:
  - `request_deliveries(id PK, request_id INT NULL REFERENCES requests(id) ON DELETE SET NULL, report_id INT NULL, source TEXT, release_id TEXT, release_title TEXT, format TEXT, final_path TEXT, library TEXT CHECK IN ('abs','calibre'), library_item_id TEXT, item_key TEXT, delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)`
  - `media_reports(id PK, item_key TEXT NOT NULL, library TEXT, library_item_id TEXT, content_type TEXT, title TEXT, author TEXT, provider TEXT, provider_id TEXT, request_id INT NULL, problem_type TEXT CHECK IN ('wrong_language','wrong_edition','broken_file','audio_problem','wrong_cover','wrong_details','other'), note TEXT, status TEXT CHECK IN ('open','fixing','awaiting_approval','needs_action','fixed','dismissed'), auto_attempted INT DEFAULT 0, created_by INT REFERENCES users(id) ON DELETE SET NULL, task_id TEXT, undo_json TEXT, resolution_note TEXT, created_at, updated_at)`; partial unique index on `item_key` WHERE status IN the four open statuses.
  - `media_report_users(report_id, user_id, PRIMARY KEY both)`; `report_quota_usage(report_id PK, user_id, created_at)`.
  - Backfill: one `request_deliveries` row per canonical `fulfilled` request with non-empty `download_task_id` (`release_id`=`download_task_id`, `library`='abs' if audiobook else 'calibre', `item_key` from `item_key()` below, paths NULL).
- Produces in `report_db.py`:
  - `item_key(library: str, content_type: str, title: str, author: str) -> str` — `"|".join` of library, content_type, `audiobookshelf._normalize(title)`, `_normalize(author)`.
  - `class ReportLimitReached(Exception)`
  - `create_or_join_report(request_db, *, user_id: int, fields: dict, quota_limit: int|None, quota_since: str|None) -> tuple[dict, bool]` — returns `(report, joined)`; atomic under `request_db._lock` + `BEGIN IMMEDIATE`; joining an open report on the same `item_key` adds `media_report_users` and costs nothing; a new report checks `report_quota_usage` since `quota_since` and raises `ReportLimitReached` at the limit, else inserts the ledger row.
  - `get_report(request_db, report_id) -> dict|None`, `update_report(request_db, report_id, **fields) -> dict` (bumps `updated_at`), `list_reports(request_db, *, user_id: int|None=None, statuses: list[str]|None=None) -> list[dict]` (user_id = created_by OR joined), `count_report_usage(request_db, user_id, since) -> int`, `had_auto_attempt(request_db, item_key, problem_type) -> bool`.
  - `record_delivery(request_db, **fields) -> None`, `deliveries_for_key(request_db, item_key) -> list[dict]` (newest first).

- [ ] **Step 1: Write failing tests** in `tests/core/test_report_db.py` (temp-file `RequestDB` as in `test_request_quota_workflow.py`):
  - `test_migration_12_backfills_deliveries`: seed v11 DB with fulfilled audiobook request `download_task_id='abc'`, a fulfilled request with NULL task id, and a linked (canonical_request_id set) one → after init exactly 1 delivery, `release_id=='abc'`, `library=='abs'`.
  - `test_second_reporter_joins_for_free`: user A creates, user B same `item_key` → `joined is True`, same id, `count_report_usage(B)==0`.
  - `test_report_limit`: limit 6, six creates on distinct keys succeed, seventh raises `ReportLimitReached`; usage before `quota_since` is ignored.
  - `test_closed_report_allows_new_one`: status `fixed` → a new create on same key yields a new id.
- [ ] **Step 2: Run** `... pytest tests/core/test_report_db.py` → FAIL (module missing).
- [ ] **Step 3: Implement** migration 12 and `report_db.py`.
- [ ] **Step 4: Run** `... pytest tests/core/test_report_db.py tests/core/test_request_db_groups.py` → PASS.
- [ ] **Step 5: Commit** `feat(reports): schema, report store, delivery backfill`.

### Task 2: Report limit settings, user columns, delivery recording

**Files:**
- Modify: `shelfmark/config/users_settings.py` (`WEEKLY_REPORT_LIMIT` NumberField, same shape as `WEEKLY_REQUEST_LIMIT`, label "Weekly report limit", description "Problem reports each non-admin user can make per week (Monday to Sunday, US Eastern).")
- Modify: `shelfmark/core/user_db.py` (columns `weekly_report_limit INTEGER NULL`, `report_limit_reset_at TIMESTAMP NULL` in the same migration helper as the request columns; `weekly_report_limit` in `_ALLOWED_UPDATE_COLUMNS`; `reset_report_limits(user_id=None)`)
- Modify: `shelfmark/core/request_quota.py`
- Modify: `shelfmark/main.py` `_sync_request_db_on_terminal` COMPLETE branch
- Test: `tests/core/test_report_quota.py`; extend `tests/core/test_terminal_request_sync.py`

**Interfaces:**
- Produces: `request_quota.report_quota_for(request_db, user: dict, now=None) -> dict|None` — same dict shape as `quota_for` (`limit, used, remaining, is_default, resets_at`), using `WEEKLY_REPORT_LIMIT`, `weekly_report_limit`, `report_limit_reset_at`, `report_db.count_report_usage`. Refactor `limit_for`/`counting_since` to take `kind: str = "request"` rather than duplicating them.
- Produces: on COMPLETE of a request task, `report_db.record_delivery(request_id=…, source=task.source, release_id=task.task_id, release_title=task.title, format=task.format, final_path=task.download_path, library=…, item_key=…)`. Look the task up via `orchestrator` the same way other terminal handling does; a missing task still records `release_id` from the request's `download_task_id`.

- [ ] **Step 1: Failing tests:** `test_report_quota_default_six`, `test_report_quota_admin_unlimited`, `test_report_reset_restarts_count`, `test_request_quota_unchanged` (existing behavior pinned); in terminal-sync tests `test_complete_records_delivery` (row with task source/title/path) and `test_denied_complete_records_nothing`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** those files plus `tests/core/test_request_quota_workflow.py` → PASS.
- [ ] **Step 5: Commit** `feat(reports): weekly report limit and delivery record`.

### Task 3: Audiobookshelf client — paths, multi-match, cover/details, path mapping

**Files:**
- Modify: `shelfmark/core/audiobookshelf.py`
- Modify: audiobookshelf settings (where `AUDIOBOOK_LIBRARY_URL`/`ABS_API_TOKEN` are declared): add TextFields `ABS_PATH_PREFIX` ("Audiobookshelf path", e.g. `/Audiobooks`) and `ABS_LOCAL_PATH_PREFIX` ("Same folder inside Shelfmark", e.g. `/UnRaid/audiobooks`). Both empty → file swaps disabled.
- Modify: `shelfmark/core/calibre_library.py` (add `find_matches`, same criteria as `find_match`, all hits, max 5; `find_match` returns `find_matches(...)[0]` or None)
- Test: `tests/core/test_audiobookshelf_reports.py`

**Interfaces:**
- Cache items gain `'path'` (ABS item `path`) and `'cover'` (`/api/items/<id>/cover` URL, no token).
- `ABSClient.find_matches(title, author, limit=5) -> list[dict]`; `find_match` = first of these.
- `ABSClient.get_item(item_id) -> dict|None` (GET `/api/items/<id>?expanded=1`; 404 → None; other errors raise).
- `ABSClient.set_cover_url(item_id, url) -> None` (POST `/api/items/<id>/cover` JSON `{"url": url}`).
- `ABSClient.match_item(item_id, title, author) -> None` (POST `/api/items/<id>/match` JSON `{"title","author","overrideCover": true, "overrideDetails": true}`).
- `ABSClient.update_details(item_id, title, author) -> None` (PATCH `/api/items/<id>/media` JSON `{"metadata": {"title": title, "authors": [{"name": author}]}}`).
- `local_path_for(abs_path: str) -> Path|None` (module function): prefix swap when `abs_path` is under `ABS_PATH_PREFIX`, else None.
- Builder verifies the three endpoint shapes against the running ABS (`curl` with the token from settings) and adjusts payloads; tests mock HTTP.

- [ ] **Step 1: Failing tests:** `test_cache_keeps_path`, `test_find_matches_returns_all_hits`, `test_local_path_for_maps_prefix` (`/Audiobooks/A/B` → `/UnRaid/audiobooks/A/B`; `/audiobooks/A` → None; empty settings → None), `test_get_item_404_returns_none`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** plus existing `tests/**/test_audiobookshelf*.py` → PASS.
- [ ] **Step 5: Commit** `feat(abs): item paths, multi-match and edit endpoints`.

### Task 4: Report API and triage

**Files:**
- Create: `shelfmark/core/report_routes.py` (registered next to request routes in `main.py`; same `_require_auth`/`_require_admin` helpers and Pushover helper `_send_pushover` from `request_routes`)
- Create: `shelfmark/core/report_fixes.py` (triage only in this task)
- Test: `tests/core/test_report_routes.py`

**Interfaces:**
- `GET /api/library/matches?title=&author=&content_type=` → `{"matches": [{"library","library_item_id","title","author","cover"}]}` (ABS for audiobook, Calibre for ebook; Calibre items have `library_item_id` = Calibre book id if `find_matches` returns it, else null).
- `POST /api/reports` body `{library, library_item_id?, content_type, title, author, provider?, provider_id?, request_id?, problem_type, note?}` → 201 `{report, joined, quota}`; 429 `{error, quota}` at the limit; 400 if `problem_type=='other'` and no note, or unknown type; 409 never (join instead). When `request_id` is given the caller must own it (or be admin). On remaining hitting 0 → Pushover "Weekly Report Limit Reached".
- `GET /api/reports` → the caller's reports (created or joined), newest first, each with `status`, `problem_type`, `resolution_note`.
- `report_fixes.triage(request_db, user_db, report_id) -> None` — runs in a background thread after create (not after join). Decision, first match wins:
  1. `content_type=='ebook'` → `needs_action` ("Ebook fixes aren't automatic yet").
  2. `problem_type=='other'` → `needs_action`.
  3. `had_auto_attempt(item_key, problem_type)` → `needs_action` ("Already tried automatically once").
  4. delivered = `deliveries_for_key(item_key)` non-empty.
  5. Cover/details types → `fix_metadata` (Task 6) if delivered else `awaiting_approval` with the prepared change in `undo_json`.
  6. File types: ABS item path not mappable (`local_path_for` None) → `needs_action` ("Shelfmark can't replace files in this library"); else `start_file_fix` (Task 5) with `auto_swap=delivered`.
  Every transition to `needs_action`/`awaiting_approval` sends Pushover heading "Report Needs Manual Action" / "Report Fix Ready to Approve" with title, problem and note.

- [ ] **Step 1: Failing tests:** `test_report_create_and_join`, `test_report_429_at_limit_with_quota`, `test_other_requires_note`, `test_cannot_report_someone_elses_request_id`, `test_ebook_report_goes_to_needs_action_with_push`, `test_unmapped_abs_path_goes_to_admin`, `test_second_auto_attempt_goes_to_admin`, `test_not_delivered_cover_waits_for_approval`, `test_no_push_on_create`. Mock `start_file_fix`/`fix_metadata` and ABS.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(reports): report API and triage`.

### Task 5: File fix — staged re-download and swap

**Files:**
- Modify: `shelfmark/core/request_routes.py` — extract the release search/filter/order part of `_auto_download_request` (from `sources_to_search` through building `candidates`) into `find_release_candidates(book, content_type: str, excluded_ids: set[str], log_ref: str) -> tuple[list[dict], str|None]` (candidates as release dicts, or a failure note). `_auto_download_request` calls it; behavior unchanged.
- Modify: `shelfmark/core/report_fixes.py`
- Modify: `shelfmark/download/clients/base_handler.py` `post_process_cleanup`: when `task.output_args.get("report_id")`, store `(client, download_id)` in a module dict `deferred_torrent_cleanup[task.task_id]` instead of starting `_scan_abs_then_remove_torrent`.
- Modify: `shelfmark/main.py` terminal hook: before request handling, if the task's `output_args` has `report_id`, call `report_fixes.on_fix_task_terminal(task, status)` and return.
- Modify: `shelfmark/main.py` startup (next to `resume_interrupted_requests`): `report_fixes.fail_interrupted_fixes(request_db)`.
- Test: `tests/core/test_report_file_fix.py`

**Interfaces:**
- `start_file_fix(request_db, user_db, report_id, auto_swap: bool) -> None`: book from `provider`/`provider_id` (else request's), excluded = `release_id`s of `deliveries_for_key`; for `broken_file` also prefer candidates whose `source` differs from the latest delivery's (stable sort). No candidates → `needs_action` with the note. Else queue the first candidate via `backend.queue_release` with `output_args={"destination": str(staging_dir), "report_id": id}` (extend `queue_release` with an optional `output_args: dict|None` that merges into the task's), set `status='fixing'`, `auto_attempted=1`, `task_id`. Retry later candidates on ERROR, like `retry_next_release`, keyed by `report_id`.
- `on_fix_task_terminal(task, status)`: ERROR → next candidate or `needs_action`. COMPLETE → verify staging holds ≥1 file with an extension in `SUPPORTED_AUDIOBOOK_FORMATS`; fail → `needs_action`, staging kept. `auto_swap` → `swap_in(report)`; else `awaiting_approval` (staged copy stays for the admin).
- `swap_in(request_db, report) -> None`: resolve current ABS item → local path; `os.replace` old dir → `archive_dir/<name>`; move staged book dir → old dir's parent; on any exception after the first move, move the old dir back and go `needs_action`. Then `abs_client.scan_libraries()`, record delivery (`report_id`, new release), `undo_json={"archived": …, "placed": …}`, status `fixed`, then run deferred torrent cleanup via `_scan_abs_then_remove_torrent` for that task.
- `fail_interrupted_fixes(request_db)`: reports in `fixing` → `needs_action`, note "Interrupted by a restart".

- [ ] **Step 1: Failing tests** (tmp dirs as library/staging/archive, mocked ABS + backend): `test_fix_excludes_delivered_release`, `test_broken_file_prefers_other_source`, `test_no_candidates_goes_to_admin`, `test_complete_swaps_and_archives`, `test_staged_copy_without_audio_is_not_swapped`, `test_swap_rolls_back_when_new_move_fails`, `test_not_delivered_waits_for_approval_with_staged_copy`, `test_torrent_removed_only_after_swap`, `test_interrupted_fix_moves_to_needs_action`, `test_fix_creates_no_request_rows_and_no_discord`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.**
- [ ] **Step 4: Run** this file plus `tests/core/` and `tests/download/` (extraction must not change request behavior) → PASS.
- [ ] **Step 5: Commit** `feat(reports): staged audiobook re-download and swap`.

### Task 6: Cover and details fixes

**Files:** Modify `shelfmark/core/report_fixes.py`; Test `tests/core/test_report_metadata_fix.py`

**Interfaces:**
- `fix_metadata(request_db, report_id) -> None`: `get_item` (None → `needs_action` "No longer in Audiobookshelf"). Save `{"cover_path": media.coverPath, "title": …, "author": …}` to `undo_json` first. `wrong_cover`: provider cover URL (book lookup) differs from the request's stored `cover_url` that the user saw → `set_cover_url`; else `match_item`. `wrong_details`: `match_item`. Status `fixed`, `resolution_note` "Cover updated" / "Details updated".
- `undo(request_db, report_id) -> None` (used by Task 7): file fix → move `placed` to archive, `archived` back, rescan; metadata → restore title/author via `update_details` (cover restore: `set_cover_url` is not possible for a local path — note says "previous cover kept at <path>"; builder call to restore through ABS's local cover endpoint if it exists).

- [ ] **Step 1: Failing tests:** `test_cover_uses_provider_url_when_different`, `test_cover_rematches_when_same_image`, `test_details_rematch_saves_undo_first`, `test_missing_abs_item_goes_to_admin`.
- [ ] **Step 2–4:** run → FAIL, implement, run → PASS.
- [ ] **Step 5: Commit** `feat(reports): automatic cover and details fixes`.

### Task 7: Admin actions and admin views

**Files:** Modify `shelfmark/core/report_routes.py`, `shelfmark/core/admin_routes.py` (serialize `report_quota`; `PUT /api/admin/users/<id>` accepts `weekly_report_limit`; `GET/PUT /api/admin/report-limits`, `POST /api/admin/report-limits/reset {user_id?}` mirroring the request-limit routes), `shelfmark/core/request_routes.py` counts route (`report_quota` for non-admins, `reports_needing_action` for admins); Test `tests/core/test_report_admin.py`

**Interfaces:**
- `GET /api/admin/reports?status=needs_action,awaiting_approval` (admin).
- `POST /api/admin/reports/<id>/approve` → `awaiting_approval` only: staged file → `swap_in`; metadata → apply prepared change. `POST …/dismiss {note?}` → `dismissed` (staging dir moved to archive, not deleted; no refund). `POST …/undo` → `fixed` only → `undo`, status `needs_action`, note "Undone by admin". `POST …/retry` → `needs_action` → re-run `start_file_fix(auto_swap=True)` ignoring `had_auto_attempt`.

- [ ] **Step 1: Failing tests:** `test_approve_swaps_staged_copy`, `test_dismiss_keeps_slot_used_and_archives_staging`, `test_undo_restores_archived_copy`, `test_non_admin_forbidden`, `test_report_limit_routes_mirror_request_limits`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(reports): admin approve, dismiss, undo, limits`.

### Task 8: Frontend

**Files:** `src/frontend/src/types/index.ts` (`MediaReport`, `ProblemType`, `LibraryMatch`, `report_quota` on counts), `src/frontend/src/services/api.ts` (`getLibraryMatches`, `createReport`, `getMyReports`, admin report + report-limit calls), create `src/frontend/src/components/ReportProblemModal.tsx` (+ `.test.tsx`), modify `RequestsSidebar.tsx`, `BookActionButton.tsx`, `settings/UsersPanel.tsx`, `App.tsx`.

**Behavior (copy is fixed):**
- Problem labels: "Wrong language", "Wrong book or edition", "Won't open / broken / bad formatting", "Audio problem", "Wrong cover", "Wrong title or author", "Something else".
- Modal: shows the matched item (cover, title, author); several matches → user picks one first; footer "x of 6 reports left this week" (from quota); note required for "Something else"; 429 → "You've used all your reports this week. They reset Monday."
- History item with status `fulfilled`: "Report a problem" button.
- Search: when the book is in the library (call `getLibraryMatches` lazily per visible result in `BookActionButton`, cache by title|author|type), show "In library" + "Report a problem" instead of Request.
- Sidebar "Reports" section for users: status text `open`/`fixing` → "We're on it", `awaiting_approval`/`needs_action` → "Waiting on admin", `fixed` → "Fixed" (+ "Still wrong?" on cover fixes, which opens the modal preset to Wrong cover), `dismissed` → "Closed".
- Admin Needs action tab lists report items alongside failed requests with Approve (awaiting_approval), Retry (needs_action file types), Dismiss, and Undo on recently fixed (last 7 days, under History).
- Users panel: report limit card beside the request limit card; per-user "x/y reports this week" with Reset; limit field in edit view.

- [ ] **Step 1: Failing tests:** `ReportProblemModal.test.tsx` — requires note for Something else; shows "2 of 6 reports left this week"; picker shown for 2 matches; 429 message. `RequestsSidebar.test.tsx` — fulfilled item shows "Report a problem"; report statuses map to the copy above.
- [ ] **Step 2–4:** vitest FAIL → implement → `tsc --noEmit` + vitest PASS.
- [ ] **Step 5: Commit** `feat(reports): report UI, reports section, admin queue`.

### Task 9: Release

**Files:** `VERSION`, `pyproject.toml`, `src/frontend/package.json`, `package-lock.json`, `tests/test_version.py` → 1.14.0.

- [ ] **Step 1:** Full backend suite, frontend checks, e2e against throwaway containers (18084/18085, scratch config) → all pass; record counts.
- [ ] **Step 2:** Flow check on the throwaway container with a fake ABS (or mocked): report a delivered audiobook → swapped and archived; report an unmapped one → Needs action.
- [ ] **Step 3:** Set prod settings `ABS_PATH_PREFIX=/Audiobooks`, `ABS_LOCAL_PATH_PREFIX=/UnRaid/audiobooks` (via settings UI after deploy).
- [ ] **Step 4:** Commit, push `app-sso`, `~/bin/shelfmark-release --deploy`; verify schema 12, delivery backfill count (expect 185), no errors in logs; note rollback tag.
- [ ] **Step 5:** Update memory `request-workflow-quota.md` (deny cancels download; reports feature pointer).
