# No Sources Requested Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an active `no_sources_requested` request status that admins can assign when no direct source exists but the item has been requested from the provider, while preserving request history behavior and safely migrating the production SQLite database.

**Architecture:** Extend the existing request status model in the SQLite-backed request layer, add a forward-only schema migration that updates the `requests.status` check constraint, and wire the new state through the Flask request routes and React request UI. Reuse the current active/history split so the new state stays visible in active admin and user views without adding a new subsystem.

**Tech Stack:** Flask, SQLite, React, TypeScript, pytest, Vite, Docker Compose

---

## File Structure

### Backend status model and migration

- `shelfmark/core/request_db.py`
  Responsibility: source of truth for valid request statuses, terminal status behavior, request counts, and SQLite schema migrations for the `requests` table stored in `users.db`.
- `shelfmark/core/request_routes.py`
  Responsibility: admin-facing request status transitions and route validation for `/api/requests/<id>/status`.

### Backend regression coverage

- `tests/core/test_request_db_prerelease.py`
  Responsibility: focused request DB status and migration coverage. This is already the closest existing test file for status-addition migrations and `completed_at` behavior.
- `tests/core/test_request_routes_prerelease.py`
  Responsibility: focused request-route transition tests using mocked request DB objects.

### Frontend request model and views

- `src/frontend/src/types/index.ts`
  Responsibility: TypeScript request status union and request counts shape used across the frontend.
- `src/frontend/src/components/RequestsSidebar.tsx`
  Responsibility: admin request status dropdown, active/history filtering, retry/complete controls, and request badge styling.
- `src/frontend/src/components/UserDashboard.tsx`
  Responsibility: user-facing request badges and summary card counts.

### Deployment verification context

- `/opt/shelfmark-requests/docker-compose.yml` on `sullyflix-com`
  Responsibility: live compose entrypoint for rebuilding/restarting only the `shelfmark` container.
- `/opt/shelfmark-requests/config/users.db` on `sullyflix-com`
  Responsibility: production SQLite database that must be backed up before restart.

## Chunk 1: Request DB Status And Migration

### Task 1: Add failing request DB tests for `no_sources_requested`

**Files:**
- Modify: `tests/core/test_request_db_prerelease.py`
- Reference: `shelfmark/core/request_db.py`

- [ ] **Step 1: Add a failing counts-and-listing test for the new status bucket**

```python
def test_get_request_counts_includes_no_sources_requested_bucket(db):
    counts = db.get_request_counts(user_id=1)

    assert counts["no_sources_requested"] == 0
    assert counts["total"] == 0


def test_create_update_list_and_count_no_sources_requested(db):
    req = db.create_request(user_id=1, title="Missing Book", content_type="ebook")

    updated = db.update_request_status(
        req["id"],
        "no_sources_requested",
        admin_note="Requested from provider",
    )

    assert updated is not None
    assert updated["status"] == "no_sources_requested"
    assert updated["admin_note"] == "Requested from provider"

    listed = db.list_requests(user_id=1, status="no_sources_requested")
    assert len(listed) == 1
    assert listed[0]["id"] == req["id"]

    counts = db.get_request_counts(user_id=1)
    assert counts["no_sources_requested"] == 1
    assert counts["total"] == 1
```

- [ ] **Step 2: Add a failing migration test for pre-status schema upgrade**

```python
def test_initialize_migrates_existing_v7_schema_to_no_sources_requested(tmp_path):
    db_path = str(tmp_path / "existing_v7.db")
    conn = sqlite3.connect(db_path)
    _create_users_table(conn)
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    conn.execute(
        """CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending'
                   CHECK(status IN ('pending','approved','denied','downloading','fulfilled','failed','cancelled','prerelease_requested')),
            content_type TEXT NOT NULL DEFAULT 'ebook' CHECK(content_type IN ('ebook','audiobook')),
            title TEXT NOT NULL,
            author TEXT,
            year TEXT,
            cover_url TEXT,
            description TEXT,
            isbn_10 TEXT,
            isbn_13 TEXT,
            provider TEXT,
            provider_id TEXT,
            series_name TEXT,
            series_position REAL,
            admin_note TEXT,
            approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            download_task_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hidden_from_admin INTEGER DEFAULT 0,
            prefer_alternate_version INTEGER DEFAULT 0,
            is_manual_request INTEGER DEFAULT 0,
            is_released INTEGER DEFAULT NULL,
            expected_release_date TEXT DEFAULT NULL,
            completed_at TIMESTAMP DEFAULT NULL
        )"""
    )
    conn.commit()
    conn.close()

    request_db = RequestDB(db_path)
    request_db.initialize()

    req = request_db.create_request(user_id=1, title="Migrated Missing Book")
    updated = request_db.update_request_status(req["id"], "no_sources_requested")

    assert updated is not None
    assert updated["status"] == "no_sources_requested"
    assert updated["completed_at"] is None
```

- [ ] **Step 3: Add a failing `completed_at` regression test for active status re-entry**

```python
def test_no_sources_requested_clears_completed_at(db):
    req = db.create_request(user_id=1, title="Retry Book", content_type="ebook")

    failed = db.update_request_status(req["id"], "failed")
    assert failed is not None
    assert failed["completed_at"] is not None

    reopened = db.update_request_status(req["id"], "no_sources_requested")
    assert reopened is not None
    assert reopened["completed_at"] is None
```

- [ ] **Step 4: Run targeted DB tests and confirm they fail for missing status support**

Run:

```bash
pytest tests/core/test_request_db_prerelease.py -v
```

Expected: FAIL with assertions or `ValueError`/schema-check failures because `no_sources_requested` is not yet valid.

### Task 2: Implement the request DB status and migration changes

**Files:**
- Modify: `shelfmark/core/request_db.py`
- Verify against: `tests/core/test_request_db_prerelease.py`

- [ ] **Step 1: Extend the request status constants**

Implement:

```python
_VALID_STATUSES = (
    "pending",
    "approved",
    "denied",
    "downloading",
    "fulfilled",
    "failed",
    "cancelled",
    "prerelease_requested",
    "no_sources_requested",
)

_TERMINAL_STATUSES = {"fulfilled", "denied", "failed", "cancelled"}
```

- [ ] **Step 2: Update `_CREATE_REQUESTS_TABLE_SQL` to include `no_sources_requested` in the `status` check constraint**

Implement the new `CHECK(status IN (...))` list in the table definition.

- [ ] **Step 3: Add a new numbered migration that rebuilds the `requests` table from schema version 7 to 8**

Implement a migration block following the existing table-rebuild pattern:

```python
if current_version < 8:
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='requests'"
    ).fetchone()
    if table_sql and "'no_sources_requested'" not in table_sql["sql"]:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS requests_new (
                ...
                status TEXT NOT NULL DEFAULT 'pending'
                       CHECK(status IN ('pending','approved','denied','downloading','fulfilled','failed','cancelled','prerelease_requested','no_sources_requested')),
                ...
                completed_at TIMESTAMP DEFAULT NULL
            );
            INSERT INTO requests_new SELECT
                id, user_id, status, content_type, title, author, year,
                cover_url, description, isbn_10, isbn_13, provider, provider_id,
                series_name, series_position, admin_note, approved_by,
                download_task_id, created_at, updated_at, hidden_from_admin,
                prefer_alternate_version, is_manual_request, is_released,
                expected_release_date, completed_at
            FROM requests;
            DROP TABLE requests;
            ALTER TABLE requests_new RENAME TO requests;
        """)
    conn.execute("UPDATE schema_version SET version = 8")
```

- [ ] **Step 4: Confirm `get_request_counts()` and `update_request_status()` need no extra branching beyond the updated constants, except that `completed_at` stays `NULL` for the new active state**

Check that this existing line remains correct after the new constant changes:

```python
sets.append(
    "completed_at = CURRENT_TIMESTAMP" if status in _TERMINAL_STATUSES else "completed_at = NULL"
)
```

- [ ] **Step 5: Re-run the targeted DB tests and confirm they pass**

Run:

```bash
pytest tests/core/test_request_db_prerelease.py -v
```

Expected: PASS for the new bucket, migration, and `completed_at` coverage.

- [ ] **Step 6: Commit the backend DB changes**

Run:

```bash
git add shelfmark/core/request_db.py tests/core/test_request_db_prerelease.py
git commit -m "feat: add no sources requested request status"
```

## Chunk 2: Request Route Validation

### Task 3: Add failing route tests for admin status updates

**Files:**
- Modify: `tests/core/test_request_routes_prerelease.py`
- Reference: `shelfmark/core/request_routes.py`

- [ ] **Step 1: Add a failing route test that accepts the new status**

```python
def test_admin_can_set_no_sources_requested_status(app):
    request_db = app.request_db
    request_db.get_request.return_value = {
        "id": 1,
        "title": "Missing Book",
        "status": "pending",
        "content_type": "ebook",
        "author": "Author",
        "user_id": 1,
    }
    request_db.update_request_status.return_value = {
        "id": 1,
        "title": "Missing Book",
        "status": "no_sources_requested",
        "content_type": "ebook",
        "author": "Author",
        "user_id": 1,
        "admin_note": "Requested from provider",
    }

    with app.test_client() as client:
        _set_user_session(client, is_admin=True)
        with patch("shelfmark.core.request_routes._broadcast_request_update") as mock_broadcast:
            resp = client.put(
                "/api/requests/1/status",
                json={"status": "no_sources_requested", "admin_note": "Requested from provider"},
            )

    assert resp.status_code == 200
    request_db.update_request_status.assert_called_once_with(
        1,
        "no_sources_requested",
        admin_note="Requested from provider",
        approved_by=1,
    )
    mock_broadcast.assert_called_once()
```

- [ ] **Step 2: Add a failing route test that the status does not trigger end-state notification rules**

```python
def test_no_sources_requested_does_not_send_terminal_notification(app):
    request_db = app.request_db
    request_db.get_request.return_value = {
        "id": 1,
        "title": "Missing Book",
        "status": "approved",
        "content_type": "ebook",
        "author": "Author",
        "user_id": 1,
    }
    request_db.update_request_status.return_value = {
        "id": 1,
        "title": "Missing Book",
        "status": "no_sources_requested",
        "content_type": "ebook",
        "author": "Author",
        "user_id": 1,
    }

    with app.test_client() as client:
        _set_user_session(client, is_admin=True)
        with patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._send_status_notification") as mock_notify:
            resp = client.put("/api/requests/1/status", json={"status": "no_sources_requested"})

    assert resp.status_code == 200
    mock_notify.assert_not_called()
```

- [ ] **Step 3: Run targeted route tests and confirm they fail for invalid status handling**

Run:

```bash
pytest tests/core/test_request_routes_prerelease.py -v
```

Expected: FAIL because `update_request_status_route()` still rejects `no_sources_requested`.

### Task 4: Implement the route validation changes

**Files:**
- Modify: `shelfmark/core/request_routes.py`
- Verify against: `tests/core/test_request_routes_prerelease.py`

- [ ] **Step 1: Extend the route-level `valid_statuses` list to include `no_sources_requested`**

Implement:

```python
valid_statuses = [
    "pending",
    "prerelease_requested",
    "approved",
    "denied",
    "downloading",
    "fulfilled",
    "failed",
    "cancelled",
    "no_sources_requested",
]
```

- [ ] **Step 2: Keep the prerelease guard unchanged and confirm no auto-download path is attached to the new state**

The new status should only pass through `request_db.update_request_status(...)` and broadcast updates.

- [ ] **Step 3: Keep notification behavior limited to the existing explicit list**

Confirm this remains true:

```python
if new_status in ["approved", "denied", "fulfilled", "failed"]:
    _send_status_notification(...)
```

- [ ] **Step 4: Re-run the targeted route tests and confirm they pass**

Run:

```bash
pytest tests/core/test_request_routes_prerelease.py -v
```

Expected: PASS for the new status update behavior.

- [ ] **Step 5: Commit the route changes**

Run:

```bash
git add shelfmark/core/request_routes.py tests/core/test_request_routes_prerelease.py
git commit -m "feat: allow no sources requested request status"
```

## Chunk 3: Frontend Types And Request Views

### Task 5: Add failing frontend type/build expectations

**Files:**
- Modify: `src/frontend/src/types/index.ts`
- Modify: `src/frontend/src/components/RequestsSidebar.tsx`
- Modify: `src/frontend/src/components/UserDashboard.tsx`

- [ ] **Step 1: Add the new status to the TypeScript request model first and let the UI fail to compile until the maps are updated**

Implement:

```ts
export type RequestStatus =
  | 'pending'
  | 'prerelease_requested'
  | 'approved'
  | 'denied'
  | 'downloading'
  | 'fulfilled'
  | 'failed'
  | 'cancelled'
  | 'no_sources_requested';

export interface RequestCounts {
  pending: number;
  prerelease_requested: number;
  approved: number;
  denied: number;
  downloading: number;
  fulfilled: number;
  failed: number;
  cancelled?: number;
  no_sources_requested?: number;
  total: number;
  unviewed?: number;
}
```

- [ ] **Step 2: Run the frontend build and confirm the status-style maps are now incomplete**

Run:

```bash
cd src/frontend && npm run build
```

Expected: FAIL with TypeScript errors pointing to missing `no_sources_requested` entries in `STATUS_STYLES` or related request status logic.

### Task 6: Implement the frontend status wiring

**Files:**
- Modify: `src/frontend/src/types/index.ts`
- Modify: `src/frontend/src/components/RequestsSidebar.tsx`
- Modify: `src/frontend/src/components/UserDashboard.tsx`

- [ ] **Step 1: Add `no_sources_requested` badge styling and label to the admin sidebar**

Implement a new `STATUS_STYLES` entry in `RequestsSidebar.tsx`, for example:

```ts
no_sources_requested: {
  bg: '',
  text: '',
  label: 'Requested',
  customStyle: {
    backgroundColor: 'rgba(249, 115, 22, 0.2)',
    color: '#ea580c',
  },
},
```

- [ ] **Step 2: Keep `no_sources_requested` out of history and in active views**

Confirm `HISTORY_STATUSES` stays:

```ts
const HISTORY_STATUSES: RequestStatus[] = ['fulfilled', 'denied', 'failed', 'cancelled'];
```

No additional history filtering should include `no_sources_requested`.

- [ ] **Step 3: Add the new admin dropdown option**

Implement:

```tsx
<option value="no_sources_requested">No Sources / Requested</option>
```

- [ ] **Step 4: Update sidebar interaction rules so the new state behaves as active, not retry-history**

Verify and adjust the booleans around:

```ts
const isRetryable = ...
const isDeniable = ...
const canMarkCompleted = ...
```

Target behavior:
- `no_sources_requested` remains active
- `Mark Completed` remains available
- later manual status moves to `approved`, `fulfilled`, `failed`, or `cancelled` are still possible through the dropdown

- [ ] **Step 5: Add the new status to the user dashboard badge map and in-progress summary**

Implement:

```ts
no_sources_requested: {
  bg: 'bg-orange-500/20',
  text: 'text-orange-700 dark:text-orange-300',
  label: 'Requested from Provider',
},
```

and update the in-progress count:

```ts
const inProgressCount =
  (counts.approved || 0) +
  (counts.downloading || 0) +
  (counts.no_sources_requested || 0);
```

- [ ] **Step 6: Re-run the frontend build and confirm it passes**

Run:

```bash
cd src/frontend && npm run build
```

Expected: PASS with updated request status typing and UI maps.

- [ ] **Step 7: Commit the frontend changes**

Run:

```bash
git add src/frontend/src/types/index.ts src/frontend/src/components/RequestsSidebar.tsx src/frontend/src/components/UserDashboard.tsx
git commit -m "feat: show no sources requested request status"
```

## Chunk 4: Integrated Verification And Deployment

### Task 7: Run full local verification

**Files:**
- Modify only if verification exposes issues in:
  - `shelfmark/core/request_db.py`
  - `shelfmark/core/request_routes.py`
  - `tests/core/test_request_db_prerelease.py`
  - `tests/core/test_request_routes_prerelease.py`
  - `src/frontend/src/types/index.ts`
  - `src/frontend/src/components/RequestsSidebar.tsx`
  - `src/frontend/src/components/UserDashboard.tsx`

- [ ] **Step 1: Run the targeted backend tests together**

Run:

```bash
pytest tests/core/test_request_db_prerelease.py tests/core/test_request_routes_prerelease.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the frontend build again from a clean working directory**

Run:

```bash
cd src/frontend && npm run build
```

Expected: PASS.

- [ ] **Step 3: Review the diff and confirm only intended files changed**

Run:

```bash
git status --short
git diff -- shelfmark/core/request_db.py shelfmark/core/request_routes.py tests/core/test_request_db_prerelease.py tests/core/test_request_routes_prerelease.py src/frontend/src/types/index.ts src/frontend/src/components/RequestsSidebar.tsx src/frontend/src/components/UserDashboard.tsx
```

Expected: only the request-status implementation files are changed, with unrelated working tree changes still preserved.

- [ ] **Step 4: Create a final focused commit if needed**

Run:

```bash
git add shelfmark/core/request_db.py shelfmark/core/request_routes.py tests/core/test_request_db_prerelease.py tests/core/test_request_routes_prerelease.py src/frontend/src/types/index.ts src/frontend/src/components/RequestsSidebar.tsx src/frontend/src/components/UserDashboard.tsx
git commit -m "feat: add no sources requested workflow"
```

### Task 8: Deploy safely to `sullyflix-com`

**Files / Systems:**
- Remote host: `sullyflix-com`
- Remote compose file: `/opt/shelfmark-requests/docker-compose.yml`
- Remote persistent DB: `/opt/shelfmark-requests/config/users.db`

- [ ] **Step 1: Back up the production DB with a timestamp before restarting anything**

Run:

```bash
ssh sullyflix-com '
  ts=$(date +%Y%m%d-%H%M%S) &&
  cp /opt/shelfmark-requests/config/users.db /opt/shelfmark-requests/config/users.db.bak-$ts &&
  echo /opt/shelfmark-requests/config/users.db.bak-$ts
'
```

Expected: prints the exact backup path.

- [ ] **Step 2: Deploy the updated repo contents to `/opt/shelfmark-requests` using the project’s normal sync method**

Possible command if the host pulls directly from git:

```bash
ssh sullyflix-com 'cd /opt/shelfmark-requests && git status --short && git pull --ff-only'
```

If deployment uses a different sync path, substitute the established production method instead of inventing one.

- [ ] **Step 3: Rebuild and restart only the `shelfmark` container**

Run:

```bash
ssh sullyflix-com 'cd /opt/shelfmark-requests && docker compose up -d --build shelfmark'
```

Expected: `shelfmark` recreated or restarted successfully.

- [ ] **Step 4: Verify the container is healthy and startup migration completed**

Run:

```bash
ssh sullyflix-com '
  docker ps --filter name=shelfmark --format "table {{.Names}}\t{{.Status}}" &&
  docker logs --tail 200 shelfmark
'
```

Expected: container is `Up` and logs show normal startup without SQLite migration errors.

- [ ] **Step 5: Smoke-check the running app and the migrated DB**

Run:

```bash
ssh sullyflix-com '
  sqlite3 /opt/shelfmark-requests/config/users.db "SELECT COUNT(*) FROM requests;" &&
  sqlite3 /opt/shelfmark-requests/config/users.db ".schema requests" | grep no_sources_requested
'
```

Expected: request rows still exist and the schema contains `no_sources_requested` in the status check constraint.

- [ ] **Step 6: Perform a UI smoke test for the new status**

Manual checks:
- move a request to `No Sources / Requested`
- confirm it stays under `Active`
- confirm it does not move into `History`
- confirm the user dashboard shows `Requested from Provider`
- confirm later transition to `fulfilled` or `failed` still works

## Notes

- No existing frontend test harness was found under `src/frontend/src`, so this plan uses `npm run build` as the required frontend verification gate.
- The repository already has unrelated modified and untracked files. Do not revert them. Stage only the files listed in each task.
- This session has subagent support in the harness, but delegated plan review was not auto-run because that requires explicit user authorization for sub-agents in this environment.
