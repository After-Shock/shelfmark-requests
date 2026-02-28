# Design: Audiobookshelf Duplicate Detection

**Date:** 2026-02-28
**Scope:** Check user's Audiobookshelf library for existing audiobooks before allowing requests; annotate search results with ownership status.

---

## Goals

1. Prevent users from requesting audiobooks already in the ABS library
2. Surface "Already in library" indicators in search results before the user even clicks Request
3. Fail open — if ABS is unreachable or unconfigured, requests proceed normally

---

## Section 1: Backend — ABS Client + Settings + Submission Guard

### New module: `core/audiobookshelf.py`

Standalone ABS API client with in-memory library cache.

**Class: `ABSClient`**

- Reads `AUDIOBOOK_LIBRARY_URL` and `ABS_API_TOKEN` from config at init
- On first use (lazy), fetches all audiobook library items:
  - `GET /api/libraries` → find libraries with `mediaType == "book"` (ABS uses "book" for audiobooks)
  - `GET /api/libraries/{id}/items?limit=0` per library → collect all items
  - Normalises each item to `{title, author, asin, isbn}` and stores in memory
- Background daemon thread refreshes cache every 60 minutes
- `find_match(title, author) -> dict | None`
  - Normalises inputs: lowercase, strip punctuation
  - For each cached item: `difflib.SequenceMatcher` title similarity ≥ 0.85 AND author similarity ≥ 0.70
  - Returns first matched item dict or `None`
  - All exceptions caught → return `None` (fail open)
- `refresh()` — public method to force cache reload (used by admin endpoint)
- `is_configured() -> bool` — returns True if both URL and token are set

### Settings

One new field in `config/settings.py`, General tab, directly below `AUDIOBOOK_LIBRARY_URL`:

| Key | Type | Label |
|---|---|---|
| `ABS_API_TOKEN` | PasswordField | "Audiobookshelf API Token" |

### Submission guard

In `request_routes.py` `create_request_route()`, after validating `content_type == "audiobook"` and before `create_request()`:

```python
match = abs_client.find_match(title, author)
if match:
    return jsonify({
        "error": "Already in your Audiobookshelf library",
        "abs_match": {"title": match["title"], "author": match["author"]}
    }), 409
```

If ABS is unconfigured or `find_match` returns `None`, proceed as normal.

---

## Section 2: Search Annotation API

### `GET /api/abs/check`

**Query params:** `title`, `author`
**Auth:** logged-in user
**Response:**
```json
{"owned": true, "match": {"title": "...", "author": "..."}}
{"owned": false, "match": null}
```

- Queries in-memory cache only (no live ABS call per request)
- Returns `{"owned": false, "match": null}` if ABS unconfigured or cache empty

### `POST /api/abs/refresh`

**Auth:** admin only
**Response:** `{"ok": true, "count": 1234}`

Force-refreshes the ABS cache. Useful after adding new audiobooks to ABS.

Both endpoints registered via a new `register_abs_routes(app, abs_client)` call in `main.py`.

---

## Section 3: Frontend

### Search result badge

- After search results render, fire `GET /api/abs/check` in parallel for each **audiobook** result (skip ebooks entirely)
- On response: if `owned == true`, overlay an "Already in library" pill on the result
- Pill links to `AUDIOBOOK_LIBRARY_URL` if configured
- Calls are fire-and-forget — results appear immediately, badges appear when checks resolve

### Submission block

- If backend returns HTTP 409, show inline error below the submit button:
  `"This audiobook is already in your Audiobookshelf library"` with a link to `AUDIOBOOK_LIBRARY_URL`
- No change to ebook flow

---

## Files Touched

| File | Change |
|---|---|
| `core/audiobookshelf.py` | New — ABS client + cache |
| `config/settings.py` | Add `ABS_API_TOKEN` field |
| `core/abs_routes.py` | New — `/api/abs/check` and `/api/abs/refresh` |
| `core/request_routes.py` | Add submission guard for audiobook content_type |
| `main.py` | Init `ABSClient`, register abs routes |
| `src/frontend/...` | Search result badge + 409 error handling |

## Files Not Touched

- `core/request_db.py`
- `core/request_notifications.py`
- `core/pushover_notifications.py`
- `core/discord_notifications.py`
- `release_sources/annasarchive/`
