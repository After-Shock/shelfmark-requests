# Audiobookshelf Duplicate Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Check the Audiobookshelf library before allowing audiobook requests, and annotate search results with "Already in library" badges.

**Architecture:** A new `ABSClient` singleton holds an in-memory cache of all ABS library items, refreshed every hour via a daemon thread. A `/api/abs/check` endpoint queries the cache; a submission guard in `request_routes.py` blocks duplicate requests with a 409. The frontend fires parallel ABS checks after search results load and shows badges on matching audiobooks.

**Tech Stack:** Python `difflib` (stdlib), `requests` library (already used throughout), React + TypeScript frontend (Vite/Tailwind).

---

## Context

- Design doc: `docs/plans/2026-02-28-audiobookshelf-design.md`
- Auth pattern: `_require_auth` / `_require_admin` decorators defined locally in `request_routes.py` — copy the same pattern into `abs_routes.py`
- Config access: `from shelfmark.core.config import config; config.get('KEY', default)`
- Settings field types: `PasswordField(key=..., label=..., description=..., placeholder=...)` from `shelfmark.core.settings_registry`
- Existing `AUDIOBOOK_LIBRARY_URL` TextField is at `shelfmark/config/settings.py` line ~368-372
- `create_request_route()` duplicate check is at `shelfmark/core/request_routes.py` lines ~203-215
- Route registration happens in `shelfmark/main.py` around line 140 (after `register_request_routes`)

---

## Task 1: ABSClient module

**Files:**
- Create: `shelfmark/core/audiobookshelf.py`
- Create: `tests/core/test_audiobookshelf.py`

### Step 1: Write the failing tests

```python
# tests/core/test_audiobookshelf.py
"""Tests for the Audiobookshelf library client."""
from unittest.mock import MagicMock, patch
import pytest
from shelfmark.core.audiobookshelf import ABSClient, _normalize


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert _normalize("Hello, World!") == "hello world"

    def test_handles_empty(self):
        assert _normalize("") == ""


class TestABSClientFindMatch:
    def _client_with_cache(self, items):
        client = ABSClient()
        client._cache = items
        return client

    def test_exact_title_author_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": "J.R.R. Tolkien"},
        ])
        match = client.find_match("The Hobbit", "J.R.R. Tolkien")
        assert match is not None
        assert match["title"] == "The Hobbit"

    def test_case_insensitive_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "the hobbit", "author": "tolkien"},
        ])
        assert client.find_match("The Hobbit", "Tolkien") is not None

    def test_fuzzy_title_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit: An Unexpected Journey", "author": "Tolkien"},
        ])
        # Title similarity > 0.85 threshold — "The Hobbit" vs long title may not match
        # But "The Hobbit A Novel" vs "The Hobbit An Unexpected Journey" should be close
        client._cache = [{"id": "1", "title": "The Hobbit A Novel", "author": "Tolkien"}]
        assert client.find_match("The Hobbit", "Tolkien") is not None

    def test_no_match_different_book(self):
        client = self._client_with_cache([
            {"id": "1", "title": "Lord of the Rings", "author": "Tolkien"},
        ])
        assert client.find_match("Harry Potter", "Rowling") is None

    def test_no_match_low_author_similarity(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": "Someone Else"},
        ])
        # Title matches but author doesn't
        assert client.find_match("The Hobbit", "Tolkien") is None

    def test_empty_cache_returns_none(self):
        client = ABSClient()
        client._cache = []
        with patch.object(client, 'refresh', return_value=0):
            with patch.object(client, 'is_configured', return_value=False):
                result = client.find_match("Any Book", "Any Author")
        assert result is None

    def test_no_author_title_match_only(self):
        """If no author info on either side, title match alone is sufficient."""
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": ""},
        ])
        assert client.find_match("The Hobbit", "") is not None


class TestABSClientRefresh:
    def test_refresh_populates_cache(self):
        client = ABSClient()
        mock_response_libraries = MagicMock()
        mock_response_libraries.json.return_value = {
            "libraries": [{"id": "lib1", "mediaType": "book"}]
        }
        mock_response_items = MagicMock()
        mock_response_items.json.return_value = {
            "results": [
                {"id": "item1", "media": {"metadata": {"title": "The Hobbit", "authorName": "Tolkien"}}}
            ]
        }
        with patch("shelfmark.core.audiobookshelf.http_requests.get") as mock_get:
            mock_get.side_effect = [mock_response_libraries, mock_response_items]
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token123")):
                count = client.refresh()
        assert count == 1
        assert client._cache[0]["title"] == "The Hobbit"

    def test_refresh_skips_non_book_libraries(self):
        client = ABSClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "libraries": [
                {"id": "lib1", "mediaType": "music"},
                {"id": "lib2", "mediaType": "podcast"},
            ]
        }
        with patch("shelfmark.core.audiobookshelf.http_requests.get", return_value=mock_resp):
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token")):
                count = client.refresh()
        assert count == 0

    def test_refresh_fails_open_on_error(self):
        client = ABSClient()
        with patch("shelfmark.core.audiobookshelf.http_requests.get", side_effect=Exception("timeout")):
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token")):
                count = client.refresh()
        assert count == 0

    def test_is_configured_false_when_no_token(self):
        client = ABSClient()
        with patch("shelfmark.core.audiobookshelf.config.get", return_value=""):
            assert client.is_configured() is False
```

### Step 2: Run tests to confirm they fail

```bash
cd /home/plex/shelfmark-requests/shelfmark-requests
python -m pytest tests/core/test_audiobookshelf.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'shelfmark.core.audiobookshelf'`

### Step 3: Implement `shelfmark/core/audiobookshelf.py`

```python
"""Audiobookshelf library client with in-memory cache for duplicate detection."""

import difflib
import logging
import re
import threading
import time
from typing import Any, Optional

import requests as http_requests

from shelfmark.core.config import config

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL = 3600  # 1 hour


def _normalize(s: str) -> str:
    """Lowercase and strip punctuation for fuzzy comparison."""
    return re.sub(r'[^\w\s]', '', s.lower()).strip()


class ABSClient:
    """Audiobookshelf API client with in-memory library cache."""

    def __init__(self) -> None:
        self._cache: list[dict[str, Any]] = []
        self._cache_lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None

    def is_configured(self) -> bool:
        """Return True if both URL and API token are set."""
        url = config.get('AUDIOBOOK_LIBRARY_URL', '') or ''
        token = config.get('ABS_API_TOKEN', '') or ''
        return bool(url.strip() and token.strip())

    def _get_credentials(self) -> tuple[Optional[str], Optional[str]]:
        url = (config.get('AUDIOBOOK_LIBRARY_URL', '') or '').rstrip('/')
        token = config.get('ABS_API_TOKEN', '') or ''
        return (url or None, token or None)

    def refresh(self) -> int:
        """Fetch all audiobook items from ABS and update the cache. Returns item count."""
        url, token = self._get_credentials()
        if not url or not token:
            return 0

        headers = {'Authorization': f'Bearer {token}'}
        try:
            resp = http_requests.get(f'{url}/api/libraries', headers=headers, timeout=10)
            resp.raise_for_status()
            libraries = resp.json().get('libraries', [])

            items: list[dict[str, Any]] = []
            for lib in libraries:
                if lib.get('mediaType') != 'book':
                    continue
                lib_id = lib['id']
                resp = http_requests.get(
                    f'{url}/api/libraries/{lib_id}/items',
                    headers=headers,
                    params={'minified': 1, 'limit': 0},
                    timeout=30,
                )
                resp.raise_for_status()
                for item in resp.json().get('results', []):
                    meta = (item.get('media') or {}).get('metadata') or {}
                    title = meta.get('title') or ''
                    author = meta.get('authorName') or ''
                    if title:
                        items.append({
                            'id': item.get('id', ''),
                            'title': title,
                            'author': author,
                        })

            with self._cache_lock:
                self._cache = items
            logger.info("ABS cache refreshed: %d items", len(items))
            return len(items)

        except Exception as exc:
            logger.warning("Failed to refresh ABS library cache: %s", exc)
            return 0

    def find_match(self, title: str, author: str) -> Optional[dict[str, Any]]:
        """Return first ABS item fuzzy-matching title+author, or None (fail open)."""
        if not self.is_configured():
            return None

        with self._cache_lock:
            cache = list(self._cache)

        if not cache:
            self.refresh()
            with self._cache_lock:
                cache = list(self._cache)

        norm_title = _normalize(title)
        norm_author = _normalize(author or '')

        for item in cache:
            item_title = _normalize(item.get('title', ''))
            item_author = _normalize(item.get('author', ''))

            title_ratio = difflib.SequenceMatcher(None, norm_title, item_title).ratio()
            if title_ratio < 0.85:
                continue

            if not norm_author or not item_author:
                return item

            author_ratio = difflib.SequenceMatcher(None, norm_author, item_author).ratio()
            if author_ratio >= 0.70:
                return item

        return None

    def start_background_refresh(self) -> None:
        """Start a daemon thread that refreshes the cache every hour."""
        if self._refresh_thread and self._refresh_thread.is_alive():
            return

        def _loop() -> None:
            self.refresh()
            while True:
                time.sleep(_REFRESH_INTERVAL)
                self.refresh()

        self._refresh_thread = threading.Thread(
            target=_loop, daemon=True, name='abs-cache-refresh'
        )
        self._refresh_thread.start()


# Module-level singleton
abs_client = ABSClient()
```

### Step 4: Run tests to confirm they pass

```bash
python -m pytest tests/core/test_audiobookshelf.py -v
```

Expected: All tests pass.

### Step 5: Commit

```bash
git add shelfmark/core/audiobookshelf.py tests/core/test_audiobookshelf.py
git commit -m "feat: add ABSClient with in-memory cache and fuzzy matching"
```

---

## Task 2: ABS_API_TOKEN setting

**Files:**
- Modify: `shelfmark/config/settings.py` (after the `AUDIOBOOK_LIBRARY_URL` TextField block, around line 372)

### Step 1: Find the exact insertion point

Open `shelfmark/config/settings.py` and locate the `AUDIOBOOK_LIBRARY_URL` field. It ends with `placeholder="http://audiobookshelf:8080",` followed by `),`. Insert the new field immediately after that closing `),`.

### Step 2: Add the field

Add this block directly after the `AUDIOBOOK_LIBRARY_URL` closing `),`:

```python
        PasswordField(
            key="ABS_API_TOKEN",
            label="Audiobookshelf API Token",
            description="API token for duplicate detection. Find it in ABS Settings → Users → your user → API Token.",
            placeholder="",
        ),
```

### Step 3: Verify the app starts without errors

```bash
docker compose build shelfmark 2>&1 | tail -5
docker compose up -d shelfmark
sleep 15
docker compose logs shelfmark 2>&1 | grep -i "error\|traceback" | grep -v dbus | head -5
```

Expected: No Python errors in logs.

### Step 4: Commit

```bash
git add shelfmark/config/settings.py
git commit -m "feat: add ABS_API_TOKEN setting for Audiobookshelf integration"
```

---

## Task 3: ABS routes + main.py wiring

**Files:**
- Create: `shelfmark/core/abs_routes.py`
- Modify: `shelfmark/main.py` (after `register_request_routes` call, around line 141)

### Step 1: Write failing tests

```python
# tests/core/test_abs_routes.py
"""Tests for ABS API routes."""
import json
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def app():
    """Create a minimal Flask test app with ABS routes registered."""
    from flask import Flask
    from shelfmark.core.abs_routes import register_abs_routes
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test'
    register_abs_routes(app)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def with_session(client, **session_data):
    """Context manager to set session data."""
    with client.session_transaction() as sess:
        sess.update(session_data)


class TestAbsCheck:
    def test_returns_not_owned_when_unconfigured(self, client):
        with patch('shelfmark.core.abs_routes.abs_client.find_match', return_value=None):
            resp = client.get('/api/abs/check?title=The+Hobbit&author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is False
        assert data['match'] is None

    def test_returns_owned_when_match_found(self, client):
        match = {'id': '1', 'title': 'The Hobbit', 'author': 'Tolkien'}
        with patch('shelfmark.core.abs_routes.abs_client.find_match', return_value=match):
            resp = client.get('/api/abs/check?title=The+Hobbit&author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is True
        assert data['match']['title'] == 'The Hobbit'

    def test_returns_not_owned_when_no_title(self, client):
        resp = client.get('/api/abs/check?author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is False


class TestAbsRefresh:
    def test_refresh_requires_admin(self, client):
        resp = client.post('/api/abs/refresh')
        # With no auth mode set, admin is granted freely (auth_mode == "none")
        assert resp.status_code == 200

    def test_refresh_returns_count(self, client):
        with patch('shelfmark.core.abs_routes.abs_client.refresh', return_value=42):
            resp = client.post('/api/abs/refresh')
        data = json.loads(resp.data)
        assert data['ok'] is True
        assert data['count'] == 42
```

### Step 2: Run tests to confirm failure

```bash
python -m pytest tests/core/test_abs_routes.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'shelfmark.core.abs_routes'`

### Step 3: Create `shelfmark/core/abs_routes.py`

```python
"""ABS duplicate-check and cache-refresh API routes."""

import logging
from functools import wraps

from flask import Flask, jsonify, request, session

from shelfmark.core.audiobookshelf import abs_client
from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)


def _get_auth_mode() -> str:
    try:
        from shelfmark.core.settings_registry import load_config_file
        return load_config_file("security").get("AUTH_METHOD", "none")
    except Exception:
        return "none"


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if _get_auth_mode() != "none" and "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def _require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_mode = _get_auth_mode()
        if auth_mode != "none":
            if "user_id" not in session:
                return jsonify({"error": "Authentication required"}), 401
            if not session.get("is_admin", False):
                return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


def register_abs_routes(app: Flask) -> None:
    """Register /api/abs/* routes."""

    @app.route("/api/abs/check", methods=["GET"])
    @_require_auth
    def abs_check():
        title = (request.args.get("title") or "").strip()
        author = (request.args.get("author") or "").strip()

        if not title:
            return jsonify({"owned": False, "match": None})

        match = abs_client.find_match(title, author)
        if match:
            return jsonify({
                "owned": True,
                "match": {"title": match["title"], "author": match["author"]},
            })
        return jsonify({"owned": False, "match": None})

    @app.route("/api/abs/refresh", methods=["POST"])
    @_require_admin
    def abs_refresh():
        count = abs_client.refresh()
        return jsonify({"ok": True, "count": count})
```

### Step 4: Wire into `main.py`

Find the block around line 140 where `register_request_routes` is called:

```python
    register_request_routes(app, request_db, user_db)
```

Add immediately after it (still inside the `try` block):

```python
    from shelfmark.core.abs_routes import register_abs_routes
    from shelfmark.core.audiobookshelf import abs_client
    register_abs_routes(app)
    abs_client.start_background_refresh()
```

### Step 5: Run tests

```bash
python -m pytest tests/core/test_abs_routes.py -v
```

Expected: All pass.

### Step 6: Commit

```bash
git add shelfmark/core/abs_routes.py shelfmark/main.py tests/core/test_abs_routes.py
git commit -m "feat: add /api/abs/check and /api/abs/refresh routes"
```

---

## Task 4: Submission guard in request_routes.py

**Files:**
- Modify: `shelfmark/core/request_routes.py` (inside `create_request_route`, before the `request_db.create_request(...)` call)

### Step 1: Locate the insertion point

In `shelfmark/core/request_routes.py`, inside `create_request_route()`, find this block (around line 203-215):

```python
        existing = request_db.list_requests(user_id=db_user_id, limit=200)
        active_statuses = {"pending", "approved", "downloading"}
        for ex in existing:
            ...
```

The ABS check should go **after** the `content_type` validation (line ~200) and **before** the existing duplicate check. Insert it there.

### Step 2: Write the test

Add to `tests/core/test_audiobookshelf.py` (or create `tests/core/test_request_routes_abs.py`):

```python
# tests/core/test_request_routes_abs.py
"""Test the ABS submission guard in create_request_route."""
import json
from unittest.mock import MagicMock, patch
import pytest


def _make_app(request_db, user_db):
    from flask import Flask
    from shelfmark.core.request_routes import register_request_routes
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test'
    register_request_routes(app, request_db, user_db)
    return app


@pytest.fixture
def app():
    request_db = MagicMock()
    request_db.list_requests.return_value = []
    request_db.create_request.return_value = {
        "id": 1, "title": "The Hobbit", "status": "pending",
        "content_type": "audiobook", "author": "Tolkien",
        "user_id": 1,
    }
    user_db = MagicMock()
    user_db.get_user.return_value = {"id": 1, "username": "testuser"}
    return _make_app(request_db, user_db)


class TestAbsSubmissionGuard:
    def test_audiobook_request_blocked_when_in_abs(self, app):
        match = {"id": "abs1", "title": "The Hobbit", "author": "Tolkien"}
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes.abs_client.find_match', return_value=match):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                })
        assert resp.status_code == 409
        data = json.loads(resp.data)
        assert 'Already in your Audiobookshelf' in data['error']
        assert data['abs_match']['title'] == 'The Hobbit'

    def test_audiobook_request_allowed_when_not_in_abs(self, app):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes.abs_client.find_match', return_value=None):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                })
        assert resp.status_code == 200

    def test_ebook_request_skips_abs_check(self, app):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes.abs_client.find_match') as mock_find:
                resp = client.post('/api/requests', json={
                    'title': 'Some Ebook',
                    'author': 'Author',
                    'content_type': 'ebook',
                })
        mock_find.assert_not_called()
```

### Step 3: Run to confirm failure

```bash
python -m pytest tests/core/test_request_routes_abs.py -v 2>&1 | head -20
```

Expected: Tests fail (no guard implemented yet).

### Step 4: Add the guard to `request_routes.py`

In `create_request_route()`, after the `content_type` validation block (around line 200) and before the `existing = request_db.list_requests(...)` duplicate check, add:

```python
        # ABS duplicate check for audiobooks (fail open if ABS unreachable)
        if content_type == "audiobook":
            try:
                from shelfmark.core.audiobookshelf import abs_client
                abs_match = abs_client.find_match(title, author or "")
                if abs_match:
                    return jsonify({
                        "error": "Already in your Audiobookshelf library",
                        "abs_match": {
                            "title": abs_match["title"],
                            "author": abs_match["author"],
                        },
                    }), 409
            except Exception as e:
                logger.warning(f"ABS duplicate check failed (skipping): {e}")
```

### Step 5: Run tests

```bash
python -m pytest tests/core/test_request_routes_abs.py -v
```

Expected: All pass.

### Step 6: Commit

```bash
git add shelfmark/core/request_routes.py tests/core/test_request_routes_abs.py
git commit -m "feat: block audiobook requests already present in Audiobookshelf library"
```

---

## Task 5: Frontend — ABS check API function + badge in search results

**Files:**
- Modify: `src/frontend/src/services/api.ts` (add `checkAbsOwned` function)
- Modify: `src/frontend/src/types/index.ts` (add `abs_owned?: boolean` to Book)
- Modify: `src/frontend/src/hooks/useSearch.ts` (fire ABS checks after results load)
- Modify: `src/frontend/src/components/BookActionButton.tsx` (show In Library badge)

### Step 1: Add `abs_owned` to the Book type

In `src/frontend/src/types/index.ts`, find the `Book` interface (line 17). Add after `subtitle?`:

```typescript
  abs_owned?: boolean;      // True if this audiobook is already in ABS library
```

### Step 2: Add `checkAbsOwned` to `api.ts`

In `src/frontend/src/services/api.ts`, add to the `API` object (in the object literal around line 9):

```typescript
  absCheck: `${API_BASE}/abs/check`,
```

Then add the function (near the end of the file, before the last export):

```typescript
export const checkAbsOwned = async (
  title: string,
  author: string
): Promise<{ owned: boolean; match: { title: string; author: string } | null }> => {
  const params = new URLSearchParams({ title, author });
  return fetchJSON(`${API.absCheck}?${params.toString()}`);
};
```

### Step 3: Fire ABS checks in `useSearch.ts` after results load

In `src/frontend/src/hooks/useSearch.ts`, add the import at the top:

```typescript
import { checkAbsOwned } from '../services/api';
```

Find where `setBooks(result.books)` is called (around line 154) in the universal search path. After each `setBooks(...)` call that sets audiobook search results, add a call to `_checkAbsOwnership`. Do the same for the direct search `setBooks(results)` call (line ~186).

Add this helper function inside the `useSearch` hook body, before the `return` statement:

```typescript
  const _checkAbsOwnership = useCallback(async (books: Book[]) => {
    if (contentType !== 'audiobook') return;
    const checks = books.map(async (book) => {
      try {
        const result = await checkAbsOwned(book.title, book.author || '');
        if (result.owned) {
          setBooks(prev =>
            prev.map(b => b.id === book.id ? { ...b, abs_owned: true } : b)
          );
        }
      } catch {
        // Fail silently — ABS check is best-effort
      }
    });
    await Promise.allSettled(checks);
  }, [contentType, setBooks]);
```

Then call it after each `setBooks(result.books)` or `setBooks(results)`:

```typescript
// After setBooks(result.books) in universal path:
setBooks(result.books);
_checkAbsOwnership(result.books);  // fire-and-forget

// After setBooks(results) in direct search path:
setBooks(results);
_checkAbsOwnership(results);  // fire-and-forget
```

**Note:** `useSearch` needs `contentType` passed in. Check the hook signature — if `contentType` is already a parameter, use it directly. If not, it will need to be added. Check `src/frontend/src/App.tsx` line ~99 to see how `useSearch` is called:

```tsx
const {
  books,
  setBooks,
  ...
} = useSearch({ ... contentType, ... });
```

If `contentType` is already passed, you're done. If not, add it to the hook's parameters and destructure it from the props object.

### Step 4: Add the badge in `BookActionButton.tsx`

In `src/frontend/src/components/BookActionButton.tsx`, find the non-admin Request button block (around line 44):

```tsx
if (showRequestButton && !isAdmin && onRequest) {
  // ... returns Request button
}
```

Replace it with:

```tsx
if (showRequestButton && !isAdmin && onRequest) {
  const sizeClasses = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm';
  const sulleyBlue = '#00BCD4';
  const sulleyBlueHover = '#00ACC1';

  if (book.abs_owned) {
    return (
      <span
        className={`${sizeClasses} rounded font-medium text-white inline-block`}
        style={{ backgroundColor: '#6B7280' }}
        title="Already in your Audiobookshelf library"
      >
        In Library
      </span>
    );
  }

  return (
    <button
      onClick={() => onRequest(book)}
      className={`${sizeClasses} rounded font-medium text-white transition-colors ${fullWidth ? 'w-full' : ''} ${className || ''}`}
      style={{
        backgroundColor: sulleyBlue,
        boxShadow: '0 2px 8px rgba(0, 188, 212, 0.3)',
        ...style
      }}
      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = sulleyBlueHover}
      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = sulleyBlue}
    >
      Request
    </button>
  );
}
```

### Step 5: Handle 409 error in `App.tsx`

In `src/frontend/src/App.tsx`, find the `handleRequest` function (around line 612). Update the catch block:

```tsx
  } catch (error) {
    console.error('Request failed:', error);
    // Check for ABS duplicate (409)
    if (error instanceof Error && error.message.includes('Already in your Audiobookshelf')) {
      showToast('This audiobook is already in your Audiobookshelf library', 'error');
    } else {
      showToast(error instanceof Error ? error.message : 'Failed to submit request', 'error');
    }
  }
```

### Step 6: Build frontend

```bash
cd /home/plex/shelfmark-requests/shelfmark-requests/src/frontend
npm run build 2>&1 | tail -20
```

Expected: Build succeeds with no TypeScript errors.

### Step 7: Commit

```bash
cd /home/plex/shelfmark-requests/shelfmark-requests
git add src/frontend/src/
git commit -m "feat: show 'In Library' badge on audiobooks already in Audiobookshelf"
```

---

## Task 6: Docker build and end-to-end test

### Step 1: Rebuild Docker image

```bash
cd /home/plex/shelfmark-requests/shelfmark-requests
docker compose build shelfmark 2>&1 | tail -5
```

Expected: Build completes successfully.

### Step 2: Start and check logs

```bash
docker compose up -d shelfmark
sleep 15
docker compose logs shelfmark 2>&1 | grep -v "dbus\|DEPRECATED\|object_proxy" | tail -20
```

Expected: No errors. You should see `abs-cache-refresh` thread start if ABS is configured.

### Step 3: Verify API endpoints

```bash
# Login
curl -s -c /tmp/sm-cookies.txt -X POST http://localhost:8084/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"Kasper56","password":"admin123"}'

# Check ABS (should return not owned when unconfigured)
curl -s -b /tmp/sm-cookies.txt \
  "http://localhost:8084/api/abs/check?title=The+Hobbit&author=Tolkien"
```

Expected: `{"match": null, "owned": false}`

### Step 4: Verify settings page shows ABS_API_TOKEN

Open http://localhost:8084 → Settings → General tab. Confirm "Audiobookshelf API Token" field appears below the "Audiobook Library URL" field.

### Step 5: Commit

If no issues:

```bash
git add -A
git commit -m "chore: verify ABS integration end-to-end in Docker"
```

Then push:

```bash
git push origin main
```
