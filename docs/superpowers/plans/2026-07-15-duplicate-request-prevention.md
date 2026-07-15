# Shared Duplicate Request Prevention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent new duplicate non-terminal requests while allowing each interested user to track and receive notifications through a linked request row.

**Architecture:** Add a nullable self-reference from linked request rows to one canonical request. Centralize matching, insertion, status propagation, deletion, and canonical promotion in `RequestDB` transactions; routes and workers operate on canonical rows while user lists retain each user's linked row. The frontend distinguishes created, joined, and already-tracked outcomes.

**Tech Stack:** Python 3, Flask, SQLite, pytest, React, TypeScript, Vite, Vitest, Docker, Chromium/SeleniumBase bypasser.

## Global Constraints

- Preserve all existing uncommitted changes in `Dockerfile`, `shelfmark/core/request_routes.py`, `tests/core/test_audiobookshelf.py`, and `tests/core/test_request_routes_prerelease.py`; never reset, checkout, or overwrite those files wholesale.
- Do not merge upstream `main`; this fork's request schema intentionally differs from upstream.
- Match provider plus provider ID first; otherwise use Unicode case-folded, trimmed, whitespace-collapsed title plus author; always keep ebook and audiobook separate.
- Join `pending`, `prerelease_requested`, `approved`, `downloading`, and `no_sources_requested`; allow a new canonical after `fulfilled`, `denied`, `failed`, or `cancelled`.
- Do not merge duplicate rows that existed before deployment.
- Send new-request admin/Discord notifications only for a newly created canonical request.
- Fan status and availability notifications out to every active interested user.
- Do not add or advertise unverified Z-Library domains.
- Before committing frontend changes, run `src/frontend/node_modules/.bin/tsc --noEmit`; the Docker build treats unused TypeScript declarations as errors.
- Run product-source changes through the project verification skill before the final implementation commit.

## File Structure

- Modify `shelfmark/core/request_db.py` — schema version 9, request identity normalization, atomic create-or-join, canonical filtering, group status synchronization, member lookup, deletion, and canonical promotion.
- Modify `shelfmark/core/request_routes.py` — create/join responses, canonical admin behavior, group-aware deletion, notification fan-out, and integration with existing prerelease changes.
- Verify `shelfmark/core/prerelease_requests.py`; its `list_requests(status="prerelease_requested", user_id=None)` path should inherit canonical-only behavior from `RequestDB`, so leave the file unchanged when the focused worker test passes.
- Modify `src/frontend/src/types/index.ts` — linked-request and creation-outcome fields.
- Modify `src/frontend/src/App.tsx` — distinct created/joined/already-tracked messages.
- Create `src/frontend/src/utils/requestOutcome.ts` — pure response-to-message selection used by the UI and unit tests.
- Modify `src/frontend/package.json` and `src/frontend/package-lock.json` — add Vitest and a test script.
- Create `src/frontend/src/utils/requestOutcome.test.ts` — frontend outcome tests.
- Create `tests/core/test_request_db_groups.py` — migration, matching, concurrency, synchronization, and promotion tests.
- Create `tests/core/test_request_routes_duplicates.py` — route response, admin visibility, deletion, broadcast, and notification tests.
- Modify `tests/core/test_request_routes_prerelease.py` only by adding focused regression assertions around canonical rows; preserve its current uncommitted prerelease coverage.
- Modify `tests/core/test_request_notifications.py` only if notification helper behavior itself changes; route-level fan-out belongs in the new duplicate route test file.
- Do not modify mirror defaults unless the final real bypasser verification establishes that the configured primary is unusable and the user separately approves a verified replacement.

---

### Task 1: Add the Linked-Request Schema and Canonical Query Contract

**Files:**
- Modify: `shelfmark/core/request_db.py:18-304`
- Create: `tests/core/test_request_db_groups.py`

**Interfaces:**
- Produces: `canonical_request_id: Optional[int]` and `requester_count: int` on serialized request dictionaries.
- Produces: canonical-only admin/worker behavior from `list_requests` when `user_id=None`, plus canonical-only `count_requests` and `get_request_counts` results.
- Preserves: `list_requests(user_id=42)` returning user 42's canonical or linked rows.

- [ ] **Step 1: Write failing schema and filtering tests**

```python
# tests/core/test_request_db_groups.py
import sqlite3

from shelfmark.core.request_db import RequestDB


def _create_user(conn: sqlite3.Connection, username: str) -> int:
    cursor = conn.execute(
        "INSERT INTO users (username, role) VALUES (?, 'user')",
        (username,),
    )
    conn.commit()
    return cursor.lastrowid


def test_schema_v9_adds_canonical_request_id_and_index(tmp_path):
    db = RequestDB(str(tmp_path / "requests.db"))
    with db._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(requests)")}
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert "canonical_request_id" in columns
    assert "idx_requests_canonical_request_id" in indexes
    assert version == 9


def test_admin_lists_exclude_linked_rows_but_user_lists_include_them(request_db, two_users):
    canonical = request_db.create_request(user_id=two_users[0], title="Dune", author="Frank Herbert")
    linked = request_db.create_request(
        user_id=two_users[1],
        title="Dune",
        author="Frank Herbert",
        canonical_request_id=canonical["id"],
    )
    assert [row["id"] for row in request_db.list_requests(user_id=None)] == [canonical["id"]]
    assert [row["id"] for row in request_db.list_requests(user_id=two_users[1])] == [linked["id"]]
    assert request_db.get_request(canonical["id"])["requester_count"] == 2
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python3 -m pytest tests/core/test_request_db_groups.py -v`

Expected: FAIL because schema version 9, `canonical_request_id`, and canonical filtering do not exist.

- [ ] **Step 3: Add schema version 9 and serialization support**

Update both the initial `CREATE TABLE requests` definition and migration chain:

```python
# shelfmark/core/request_db.py
canonical_request_id INTEGER REFERENCES requests(id) ON DELETE SET NULL,
```

```python
if current_version < 9:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
    if "canonical_request_id" not in columns:
        conn.execute(
            "ALTER TABLE requests ADD COLUMN canonical_request_id "
            "INTEGER REFERENCES requests(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_canonical_request_id "
        "ON requests(canonical_request_id)"
    )
    conn.execute("UPDATE schema_version SET version = 9")
```

Extend `create_request` with `canonical_request_id: Optional[int] = None`, include it in the insert, and add a correlated requester count to `_get_request` and list projections:

```sql
1 + (
    SELECT COUNT(*) FROM requests linked
    WHERE linked.canonical_request_id = requests.id
      AND linked.status NOT IN ('fulfilled','denied','failed','cancelled')
) AS requester_count
```

Linked rows should expose the canonical group's count by resolving `COALESCE(requests.canonical_request_id, requests.id)` in the count subquery.

- [ ] **Step 4: Add canonical-only conditions to admin and worker queries**

When `user_id is None`, append `canonical_request_id IS NULL` in `list_requests`, `count_requests`, and `get_request_counts`. Do not append it for user-specific queries.

```python
if user_id is None:
    conditions.append("canonical_request_id IS NULL")
else:
    conditions.append("user_id = ?")
    params.append(user_id)
```

- [ ] **Step 5: Run database tests**

Run: `python3 -m pytest tests/core/test_request_db_groups.py tests/core/test_request_db_prerelease.py tests/core/test_request_db_alternate_version.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the schema/query contract**

```bash
git add shelfmark/core/request_db.py tests/core/test_request_db_groups.py
git commit -m "feat: add linked request schema"
```

---

### Task 2: Implement Atomic Create-or-Join Matching

**Files:**
- Modify: `shelfmark/core/request_db.py:305-427`
- Modify: `tests/core/test_request_db_groups.py`

**Interfaces:**
- Produces: `CreateRequestOutcome = Literal["created", "joined", "already_joined"]`.
- Produces: `RequestDB.create_or_join_request` returning `tuple[Dict[str, Any], CreateRequestOutcome]` and accepting the metadata parameters shown in Step 4.
- Consumes: schema and canonical filtering from Task 1.

- [ ] **Step 1: Write failing identity, status, and idempotency tests**

```python
import threading


def test_provider_identity_precedes_title_fallback(request_db, two_users):
    first, outcome = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert",
        content_type="ebook", provider="GoogleBooks", provider_id="gb-1",
    )
    second, second_outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune: Deluxe", author="F. Herbert",
        content_type="ebook", provider="googlebooks", provider_id="gb-1",
    )
    assert outcome == "created"
    assert second_outcome == "joined"
    assert second["canonical_request_id"] == first["id"]


def test_same_user_repeat_is_idempotent(request_db, user_id):
    first, _ = request_db.create_or_join_request(
        user_id=user_id, title="  THE   HOBBIT ", author="J.R.R. Tolkien"
    )
    repeated, outcome = request_db.create_or_join_request(
        user_id=user_id, title="the hobbit", author="j.r.r. tolkien"
    )
    assert outcome == "already_joined"
    assert repeated["id"] == first["id"]


def test_content_types_do_not_join(request_db, two_users):
    ebook, _ = request_db.create_or_join_request(
        user_id=two_users[0], title="Dune", author="Frank Herbert", content_type="ebook"
    )
    audiobook, outcome = request_db.create_or_join_request(
        user_id=two_users[1], title="Dune", author="Frank Herbert", content_type="audiobook"
    )
    assert outcome == "created"
    assert audiobook["canonical_request_id"] is None
    assert audiobook["id"] != ebook["id"]
```

Parameterize all nine statuses so the five non-terminal statuses join and the four terminal statuses create a new canonical.

- [ ] **Step 2: Run the tests and verify failure**

Run: `python3 -m pytest tests/core/test_request_db_groups.py -k 'identity or repeat or content_types or status' -v`

Expected: FAIL because `create_or_join_request` is absent.

- [ ] **Step 3: Add normalization and matching helpers**

```python
from typing import Literal
import unicodedata

CreateRequestOutcome = Literal["created", "joined", "already_joined"]
_ACTIVE_GROUP_STATUSES = {
    "pending", "prerelease_requested", "approved", "downloading", "no_sources_requested",
}


def _normalize_match_text(value: Optional[str]) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.strip().casefold().split())


def _same_request_identity(existing: Dict[str, Any], *, title: str, author: Optional[str],
                           content_type: str, provider: Optional[str],
                           provider_id: Optional[str]) -> bool:
    if existing["content_type"] != content_type:
        return False
    if provider and provider_id and existing.get("provider") and existing.get("provider_id"):
        return (
            _normalize_match_text(existing["provider"]) == _normalize_match_text(provider)
            and existing["provider_id"].strip() == provider_id.strip()
        )
    return (
        _normalize_match_text(existing.get("title")) == _normalize_match_text(title)
        and _normalize_match_text(existing.get("author")) == _normalize_match_text(author)
    )
```

- [ ] **Step 4: Implement one locked `BEGIN IMMEDIATE` create-or-join transaction**

```python
def create_or_join_request(self, *, user_id: int, title: str,
                           content_type: str = "ebook", author: Optional[str] = None,
                           **metadata: Any) -> tuple[Dict[str, Any], CreateRequestOutcome]:
    with self._lock:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            candidates = conn.execute(
                "SELECT * FROM requests WHERE canonical_request_id IS NULL "
                "AND content_type = ? AND status IN (?,?,?,?,?) ORDER BY created_at, id",
                (content_type, *sorted(_ACTIVE_GROUP_STATUSES)),
            ).fetchall()
            canonical = next(
                (dict(row) for row in candidates if _same_request_identity(
                    dict(row), title=title, author=author, content_type=content_type,
                    provider=metadata.get("provider"), provider_id=metadata.get("provider_id")
                )),
                None,
            )
            # Return an existing member, insert a linked copy, or insert a canonical.
            # Use private connection-scoped insert/fetch helpers so the public lock is not re-entered.
            conn.commit()
            return result, outcome
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

Copy canonical metadata and status for a joined row; do not send notifications in this persistence method.

- [ ] **Step 5: Add a two-thread race test**

Use a `threading.Barrier(2)` to start two calls for different users against the same file-backed database. Assert one `created`, one `joined`, one canonical row, and two total user rows.

- [ ] **Step 6: Run the complete group test file**

Run: `python3 -m pytest tests/core/test_request_db_groups.py -v`

Expected: PASS, including the race test.

- [ ] **Step 7: Commit atomic matching**

```bash
git add shelfmark/core/request_db.py tests/core/test_request_db_groups.py
git commit -m "feat: create or join active requests atomically"
```

---

### Task 3: Synchronize Group Status and Promote Canonicals

**Files:**
- Modify: `shelfmark/core/request_db.py:501-760`
- Modify: `tests/core/test_request_db_groups.py`

**Interfaces:**
- Produces: `RequestDB.get_request_group(request_id: int, active_only: bool = False) -> List[Dict[str, Any]]`.
- Changes: `update_request_status` resolves a linked ID to its canonical ID and updates every non-cancelled row atomically.
- Produces: `RequestDB.delete_user_request(request_id: int, user_id: int) -> Optional[Dict[str, Any]]`, returning the remaining/promoted canonical or `None` when the group is empty.

- [ ] **Step 1: Write failing synchronization and promotion tests**

```python
def test_group_status_update_changes_all_active_rows(grouped_requests):
    db, canonical, linked = grouped_requests
    updated = db.update_request_status(
        linked["id"], "approved", admin_note="Queued", approved_by=99,
        download_task_id="task-1",
    )
    rows = db.get_request_group(canonical["id"])
    assert updated["id"] == canonical["id"]
    assert {row["status"] for row in rows} == {"approved"}
    assert {row["admin_note"] for row in rows} == {"Queued"}
    assert {row["download_task_id"] for row in rows} == {"task-1"}


def test_deleting_canonical_promotes_oldest_linked_member(grouped_requests):
    db, canonical, linked = grouped_requests
    remaining = db.delete_user_request(canonical["id"], canonical["user_id"])
    assert remaining["id"] == linked["id"]
    assert remaining["canonical_request_id"] is None
    assert db.get_request(canonical["id"]) is None
```

Add tests for deleting a linked row, deleting the final row, repointing a third member, preserving prerelease/download metadata, and rollback after an injected SQL failure.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python3 -m pytest tests/core/test_request_db_groups.py -k 'status_update or deleting or rollback' -v`

Expected: FAIL because group operations do not exist.

- [ ] **Step 3: Add canonical resolution and member lookup**

```python
def _canonical_id_for_row(conn: sqlite3.Connection, request_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT id, canonical_request_id FROM requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not row:
        return None
    return row["canonical_request_id"] or row["id"]


def get_request_group(self, request_id: int, active_only: bool = False) -> List[Dict[str, Any]]:
    # Resolve the canonical ID, then select id = canonical OR canonical_request_id = canonical.
```

- [ ] **Step 4: Make `update_request_status` group-atomic**

Within one lock and `BEGIN IMMEDIATE`, resolve the canonical ID and update:

```sql
UPDATE requests
SET status = ?, admin_note = ?, approved_by = ?, download_task_id = ?,
    completed_at = ?, updated_at = CURRENT_TIMESTAMP
WHERE (id = ? OR canonical_request_id = ?)
  AND status != 'cancelled'
```

Return the refreshed canonical row. Preserve the existing valid-status validation and completion timestamp rules.

- [ ] **Step 5: Implement group-aware deletion and promotion**

```python
def delete_user_request(self, request_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    with self._lock:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = conn.execute(
                "SELECT * FROM requests WHERE id = ? AND user_id = ?", (request_id, user_id)
            ).fetchone()
            if not target:
                conn.rollback()
                return None
            canonical_id = target["canonical_request_id"] or target["id"]
            conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))
            if request_id == canonical_id:
                replacement = conn.execute(
                    "SELECT id FROM requests WHERE canonical_request_id = ? "
                    "ORDER BY created_at, id LIMIT 1", (canonical_id,)
                ).fetchone()
                if replacement:
                    new_id = replacement["id"]
                    conn.execute("UPDATE requests SET canonical_request_id = NULL WHERE id = ?", (new_id,))
                    conn.execute(
                        "UPDATE requests SET canonical_request_id = ? "
                        "WHERE canonical_request_id = ?", (new_id, canonical_id)
                    )
            conn.commit()
            return self._get_request(conn, new_id if replacement else canonical_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

Use initialized local variables so linked-row and final-row paths cannot reference an unset replacement.

- [ ] **Step 6: Run group and existing DB tests**

Run: `python3 -m pytest tests/core/test_request_db_groups.py tests/core/test_request_db_prerelease.py tests/core/test_request_db_alternate_version.py -v`

Expected: PASS.

- [ ] **Step 7: Commit group lifecycle support**

```bash
git add shelfmark/core/request_db.py tests/core/test_request_db_groups.py
git commit -m "feat: synchronize linked request groups"
```

---

### Task 4: Integrate Create, Lists, Admin Actions, and Deletion Routes

**Files:**
- Modify: `shelfmark/core/request_routes.py:341-795`
- Create: `tests/core/test_request_routes_duplicates.py`
- Modify: `tests/core/test_request_routes_prerelease.py`

**Interfaces:**
- Consumes: `create_or_join_request`, group-aware `update_request_status`, and `delete_user_request` from Tasks 2–3.
- Produces: POST response flags `joined_existing` and `already_joined`.
- Preserves: existing Audiobookshelf checks, alternate-version warnings, manual request fields, prerelease detection, metadata backfill, and automatic prerelease movement.

- [ ] **Step 1: Write failing create route tests**

```python
def test_second_user_joins_existing_request(app, request_db, users):
    with app.test_client() as client:
        login(client, users[0])
        first = client.post("/api/requests", json={"title": "Dune", "author": "Frank Herbert"})
        login(client, users[1])
        second = client.post("/api/requests", json={"title": "dune", "author": "frank herbert"})
    assert first.status_code == 201
    assert first.get_json()["joined_existing"] is False
    assert second.status_code == 200
    assert second.get_json()["joined_existing"] is True
    assert second.get_json()["canonical_request_id"] == first.get_json()["id"]


def test_same_user_repeat_returns_existing_row(app, user):
    # POST twice and assert 200, already_joined=True, and one row for that user.
```

Add tests proving only canonical rows appear to admins, both users see their own rows, `requester_count == 2`, and only canonical creation invokes `_send_discord_new_request`/Pushover.

- [ ] **Step 2: Run route tests and verify failure**

Run: `python3 -m pytest tests/core/test_request_routes_duplicates.py -v`

Expected: FAIL because the route still performs a per-user pre-check and always inserts directly.

- [ ] **Step 3: Replace the route-level duplicate loop**

At `request_routes.py:386-435`, retain all pre-existing validation and ABS logic, then call:

```python
req, outcome = request_db.create_or_join_request(
    user_id=db_user_id,
    title=title,
    content_type=content_type,
    author=author or None,
    year=(data.get("year") or "").strip() or None,
    cover_url=data.get("cover_url"),
    description=data.get("description"),
    isbn_10=data.get("isbn_10"),
    isbn_13=data.get("isbn_13"),
    provider=data.get("provider"),
    provider_id=data.get("provider_id"),
    series_name=data.get("series_name"),
    series_position=data.get("series_position"),
    prefer_alternate_version=prefer_alternate_version,
    is_manual_request=is_manual_request,
    is_released=is_released,
)
```

Only run new-request broadcasts, Discord, and Pushover when `outcome == "created"`. Apply the existing `start_as_prerelease` metadata/status path before notification, preserving the current uncommitted prerelease logic.

```python
response_data = dict(req)
response_data["joined_existing"] = outcome == "joined"
response_data["already_joined"] = outcome == "already_joined"
status_code = 201 if outcome == "created" else 200
return jsonify(response_data), status_code
```

- [ ] **Step 4: Make DELETE use `delete_user_request`**

Keep existing authorization checks, then replace direct deletion with the group-aware method. Broadcast the removed request ID to the departing user and the promoted canonical row, when present, to admins/remaining users.

- [ ] **Step 5: Verify admin transitions remain canonical and synchronized**

Add route tests that call approve, deny, generic status, activate, move-to-prerelease, and retry on canonical IDs and assert both user rows change. Add one test calling an admin action with a linked ID and assert the returned row is canonical.

- [ ] **Step 6: Add prerelease regression assertions without replacing existing edits**

Append tests to `tests/core/test_request_routes_prerelease.py` proving a linked prerelease row is excluded from the worker/admin queue and receives the canonical activation transition. Do not rewrite its fixtures or the current metadata-backfill tests.

- [ ] **Step 7: Run route regressions**

Run: `python3 -m pytest tests/core/test_request_routes_duplicates.py tests/core/test_request_routes_abs.py tests/core/test_request_routes_prerelease.py -v`

Expected: PASS.

- [ ] **Step 8: Commit route integration**

```bash
git add shelfmark/core/request_routes.py tests/core/test_request_routes_duplicates.py tests/core/test_request_routes_prerelease.py
git commit -m "feat: join duplicate requests in API"
```

---

### Task 5: Fan Notifications Out and Keep Workers Canonical-Only

**Files:**
- Modify: `shelfmark/core/request_routes.py:222-301, 538-795`
- Modify: `shelfmark/core/prerelease_requests.py:50-99` only if explicit filtering is required
- Modify: `tests/core/test_request_routes_duplicates.py`
- Modify: `tests/core/test_request_notifications.py` only for changed helper expectations

**Interfaces:**
- Produces: `_send_group_status_notifications(request_db, user_db, request_id, status_override=None)`.
- Consumes: `RequestDB.get_request_group(request_id, active_only=True)`.
- Preserves: one Discord book-available event per canonical request.

- [ ] **Step 1: Write failing notification fan-out tests**

```python
def test_status_notification_fans_out_to_all_active_users(
    app, request_db, user_db, grouped_requests
):
    with patch("shelfmark.core.request_routes.send_request_notification") as send:
        _send_group_status_notifications(
            request_db, user_db, grouped_requests.canonical_id, "fulfilled"
        )
    assert {call.args[0] for call in send.call_args_list} == {
        "first@example.com", "second@example.com"
    }


def test_removed_user_does_not_receive_group_notification(
    request_db, user_db, grouped_requests
):
    db, canonical, linked = grouped_requests
    db.delete_user_request(linked["id"], linked["user_id"])
    with patch("shelfmark.core.request_routes.send_request_notification") as send:
        _send_group_status_notifications(db, user_db, canonical["id"], "fulfilled")
    assert [call.args[0] for call in send.call_args_list] == ["first@example.com"]
```

Add a test that one failed send does not prevent the remaining recipients from being attempted.

- [ ] **Step 2: Run notification tests and verify failure**

Run: `python3 -m pytest tests/core/test_request_routes_duplicates.py -k notification -v`

Expected: FAIL because the current helper looks up only `req["user_id"]`.

- [ ] **Step 3: Implement the group notification helper**

```python
def _send_group_status_notifications(
    request_db: RequestDB,
    user_db: UserDB,
    request_id: int,
    status_override: str | None = None,
) -> None:
    members = request_db.get_request_group(request_id, active_only=True)
    for member in members:
        user = user_db.get_user(user_id=member["user_id"])
        email = (user or {}).get("email")
        if not email:
            continue
        try:
            send_request_notification(
                email,
                member["title"],
                status_override or member["status"],
                member.get("admin_note"),
            )
        except Exception as exc:
            logger.warning("Request notification failed for user %s: %s", member["user_id"], exc)
```

Replace single-user calls after approve, deny, activate, fulfillment, and failure transitions. Call after transaction commit.

- [ ] **Step 4: Verify canonical worker filtering**

Add a prerelease worker test with one canonical and one linked `prerelease_requested` row. Assert `process_prerelease_requests` processes the canonical once. If Task 1's `list_requests(user_id=None)` guarantees this, leave `prerelease_requests.py` unchanged; otherwise add `canonical_only=True` to its query using an explicit `RequestDB` parameter rather than filtering in Python.

- [ ] **Step 5: Run notification and worker tests**

Run: `python3 -m pytest tests/core/test_request_routes_duplicates.py tests/core/test_request_notifications.py tests/core/test_prerelease_requests.py -v`

Expected: PASS.

- [ ] **Step 6: Commit notification fan-out**

```bash
git add shelfmark/core/request_routes.py shelfmark/core/prerelease_requests.py tests/core/test_request_routes_duplicates.py tests/core/test_request_notifications.py tests/core/test_prerelease_requests.py
git commit -m "feat: notify all linked requesters"
```

Only stage files that actually changed.

---

### Task 6: Add Frontend Outcome Types, Messages, and Tests

**Files:**
- Modify: `src/frontend/src/types/index.ts:330-366`
- Create: `src/frontend/src/utils/requestOutcome.ts`
- Create: `src/frontend/src/utils/requestOutcome.test.ts`
- Modify: `src/frontend/src/App.tsx:647-709`
- Modify: `src/frontend/package.json`
- Modify: `src/frontend/package-lock.json`

**Interfaces:**
- Produces: `getRequestOutcomeMessage(response, title) -> { message: string; type: 'success' | 'info' }`.
- Consumes: `CreateBookRequestResponse.joined_existing` and `.already_joined`.

- [ ] **Step 1: Add Vitest through the Node 20 build environment**

Run from the repository root:

```bash
docker run --rm -v "$PWD/src/frontend:/frontend" -w /frontend node:20-alpine \
  npm install --save-dev vitest
```

Then add this package script:

```json
"test": "vitest run"
```

Expected: `package.json` and `package-lock.json` contain Vitest.

- [ ] **Step 2: Write failing outcome tests**

```typescript
// src/frontend/src/utils/requestOutcome.test.ts
import { describe, expect, it } from 'vitest';
import { getRequestOutcomeMessage } from './requestOutcome';

const response = { id: 1, title: 'Dune' } as never;

describe('getRequestOutcomeMessage', () => {
  it('reports a joined request', () => {
    expect(getRequestOutcomeMessage({ ...response, joined_existing: true }, 'Dune')).toEqual({
      message: 'Joined existing request: Dune', type: 'success',
    });
  });

  it('reports an idempotent repeat', () => {
    expect(getRequestOutcomeMessage({ ...response, already_joined: true }, 'Dune')).toEqual({
      message: 'You are already tracking this request: Dune', type: 'info',
    });
  });

  it('preserves the alternate-version warning', () => {
    expect(getRequestOutcomeMessage({ ...response, warning: 'alternate' }, 'Dune').type).toBe('info');
  });
});
```

- [ ] **Step 3: Run the test and verify failure**

Run: `src/frontend/node_modules/.bin/vitest run src/utils/requestOutcome.test.ts`

Expected: FAIL because the utility and response fields do not exist.

- [ ] **Step 4: Extend request types**

```typescript
export interface BookRequest {
  // existing fields
  canonical_request_id?: number | null;
  requester_count?: number;
}

export interface CreateBookRequestResponse extends BookRequest {
  warning?: string;
  joined_existing?: boolean;
  already_joined?: boolean;
}
```

- [ ] **Step 5: Implement and use the pure message selector**

```typescript
// src/frontend/src/utils/requestOutcome.ts
import type { CreateBookRequestResponse } from '../types';

export const getRequestOutcomeMessage = (
  response: CreateBookRequestResponse,
  title: string,
): { message: string; type: 'success' | 'info' } => {
  if (response.warning) {
    return {
      message: 'Standard version already in library — request submitted for graphic/dramatized version.',
      type: 'info',
    };
  }
  if (response.already_joined) {
    return { message: `You are already tracking this request: ${title}`, type: 'info' };
  }
  if (response.joined_existing) {
    return { message: `Joined existing request: ${title}`, type: 'success' };
  }
  return { message: `Requested: ${title}`, type: 'success' };
};
```

Use it in both `handleRequest` and `handleManualRequest`:

```typescript
const outcome = getRequestOutcomeMessage(result, book.title);
showToast(outcome.message, outcome.type);
```

- [ ] **Step 6: Run frontend tests and strict typecheck**

Run: `src/frontend/node_modules/.bin/vitest run`

Run: `src/frontend/node_modules/.bin/tsc --noEmit`

Expected: both PASS with no unused-variable errors.

- [ ] **Step 7: Commit frontend behavior**

```bash
git add src/frontend/package.json src/frontend/package-lock.json \
  src/frontend/src/types/index.ts src/frontend/src/utils/requestOutcome.ts \
  src/frontend/src/utils/requestOutcome.test.ts src/frontend/src/App.tsx
git commit -m "feat: show shared request outcomes"
```

---

### Task 7: Run Full Regression, Concurrency, and Build Verification

**Files:**
- Modify only files required to fix failures uncovered by this task.

**Interfaces:**
- Verifies all prior task contracts together.

- [ ] **Step 1: Run the focused backend suite**

Run:

```bash
python3 -m pytest \
  tests/core/test_request_db_groups.py \
  tests/core/test_request_routes_duplicates.py \
  tests/core/test_request_routes_abs.py \
  tests/core/test_request_routes_prerelease.py \
  tests/core/test_request_notifications.py \
  tests/core/test_prerelease_requests.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the complete backend test suite**

Run: `python3 -m pytest -q`

Expected: PASS. If unrelated pre-existing failures occur, record the exact test and failure before changing code.

- [ ] **Step 3: Run frontend tests, typecheck, and production build**

Run:

```bash
src/frontend/node_modules/.bin/vitest run
src/frontend/node_modules/.bin/tsc --noEmit
src/frontend/node_modules/.bin/vite build
```

Expected: all PASS.

- [ ] **Step 4: Build the Docker image with the existing Chromium pin**

Run: `docker compose -f docker-compose.yml build`

Expected: frontend `tsc && vite build` succeeds and Chromium `149.0.7827.196-1~deb13u1` installs from the configured snapshot.

- [ ] **Step 5: Review the diff for accidental overwrites**

Run:

```bash
git diff --check
git diff --stat
```

Confirm the pre-existing Chromium pin, Audiobookshelf matching tests, and prerelease metadata/backfill changes remain present.

- [ ] **Step 6: Commit regression fixes when this task changed files**

Inspect `git status --short`, then stage only affected feature files from this exact list:

```bash
git add shelfmark/core/request_db.py shelfmark/core/request_routes.py \
  shelfmark/core/prerelease_requests.py tests/core/test_request_db_groups.py \
  tests/core/test_request_routes_duplicates.py tests/core/test_request_routes_prerelease.py \
  tests/core/test_request_notifications.py tests/core/test_prerelease_requests.py \
  src/frontend/src/types/index.ts src/frontend/src/App.tsx \
  src/frontend/src/utils/requestOutcome.ts src/frontend/src/utils/requestOutcome.test.ts \
  src/frontend/package.json src/frontend/package-lock.json
git commit -m "test: cover shared request regressions"
```

Skip the commit when `git status --short` shows no changes produced by this task.

---

### Task 8: Exercise the Real User Flow and Conditionally Verify Z-Library

**Files:**
- Modify: `.local/config/settings.json` only if a separately verified and user-approved mirror replacement is required.
- Do not commit local settings.

**Interfaces:**
- Verifies the deployed API, websocket/UI state, notifications, canonical promotion, and existing bypasser path.

- [ ] **Step 1: Recreate the local container**

Run:

```bash
docker compose -f docker-compose.yml up -d --force-recreate
```

Expected: container `shelfmark` becomes healthy on port `8084`.

- [ ] **Step 2: Verify create, join, and admin deduplication with two authenticated users**

Use two browser sessions or authenticated API sessions:

1. User A requests an ebook.
2. User B requests the same provider record.
3. User A repeats the request.
4. Confirm User A sees the canonical row, User B sees a linked row, and admin sees one row with `requester_count = 2`.
5. Confirm UI messages are “Requested,” “Joined existing request,” and “already tracking,” respectively.

Expected: no duplicate admin work item and no duplicate new-request Discord notification.

- [ ] **Step 3: Verify synchronization and notification fan-out**

Approve and advance the canonical request. Confirm both user rows update through websocket/refetch and both configured user emails receive status/availability notifications. Confirm the Discord book-available event fires once.

- [ ] **Step 4: Verify both deletion orders**

Exercise linked-first deletion, then recreate the group and exercise canonical-first deletion. Confirm canonical-first promotes the oldest linked row and final-user deletion removes the group.

- [ ] **Step 5: Verify the configured Z-Library path through the container**

First confirm the configured primary:

```bash
docker exec shelfmark python3 -c \
  "from shelfmark.core.mirrors import get_zlib_primary_url; print(get_zlib_primary_url())"
```

Then exercise an ordinary Z-Library-backed search/download through the application so it uses `InternalBypasser.get()` and pinned Chromium rather than a direct `curl`/`urllib` request.

Expected: a direct HTTP 503 is acceptable only if the real bypasser succeeds. If it succeeds, make no mirror changes.

- [ ] **Step 6: Stop on unverified mirror candidates**

If the real bypasser fails because the domain is unreachable rather than because of application code, report the exact DNS/TLS/HTTP/browser error. Do not add a replacement URL until its ownership and safety can be independently verified and the user approves the configuration change.

- [ ] **Step 7: Run the project verification skill and record evidence**

Invoke the project `verify` skill to drive the affected create/join/admin/cancel flow end-to-end. Record observed HTTP statuses, row IDs/canonical IDs, requester count, notification attempts, and bypasser result.

- [ ] **Step 8: Commit final verified product fixes when runtime testing changed files**

Inspect `git status --short`, stage only the feature files changed to correct an observed runtime failure, and commit them:

```bash
git add shelfmark/core/request_db.py shelfmark/core/request_routes.py \
  shelfmark/core/prerelease_requests.py src/frontend/src/types/index.ts \
  src/frontend/src/App.tsx src/frontend/src/utils/requestOutcome.ts \
  tests/core/test_request_db_groups.py tests/core/test_request_routes_duplicates.py
git commit -m "fix: complete shared request verification"
```

Skip the commit when runtime verification requires no code changes.
