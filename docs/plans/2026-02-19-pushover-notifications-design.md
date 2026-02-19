# Pushover Admin Notifications + Test Suite Design

**Date:** 2026-02-19

## Overview

Add Pushover push notifications to alert the admin when a new book request is submitted. Extend with a comprehensive test suite covering the request system, settings, notifications, and core utilities.

## Feature: Pushover Admin Notifications

### New module: `shelfmark/core/pushover_notifications.py`

Two public functions:

**`send_new_request_pushover(title, author, requester, content_type)`**
1. Return `False` immediately if `PUSHOVER_ENABLED` is falsy in config
2. Read `PUSHOVER_USER_KEY` and `PUSHOVER_API_TOKEN` from config — return `False` if either missing
3. POST to `https://api.pushover.net/1/messages.json` with:
   - `title`: `"New Request"`
   - `message`: `"{content_type_label}: {title}\nBy {author}\nRequested by {requester}"` (author/requester omitted when absent)
   - `priority`: `0` (normal)
4. Log success or failure; return `True`/`False`; never raise

**`test_pushover_connection(current_values)`**
- Mirrors `test_email_connection` — accepts unsaved form values, sends a test notification
- Returns `{"success": True/False, "message": "..."}` for the settings Test button callback

Implementation uses stdlib `urllib.request` — no new dependencies.

### Settings UI: `config/settings.py` (General tab, Notifications heading)

Four additions under the existing `notifications_heading`:

| Field | Type | Key | Default |
|---|---|---|---|
| Pushover Admin Notifications | `CheckboxField` | `PUSHOVER_ENABLED` | `False` |
| User Key | `TextField` | `PUSHOVER_USER_KEY` | — |
| API Token | `PasswordField` | `PUSHOVER_API_TOKEN` | — |
| Send Test Notification | `ActionButton` | `test_pushover` | — |

`PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN`, and `test_pushover` use `show_when: PUSHOVER_ENABLED = True`.

### Integration: `request_routes.py`

In `create_request_route`, after `_broadcast_request_update(req)`:

```python
_send_pushover_new_request(req, user_db)
```

New private helper `_send_pushover_new_request(req, user_db)`:
- Pulls requester username from `user_db.get_user(user_id=req["user_id"])`
- Calls `send_new_request_pushover(title, author, requester, content_type)`
- Non-blocking, swallows all exceptions, logs warnings on failure
- Same pattern as existing `_send_status_notification`

---

## Feature: Test Suite

### Structure

```
tests/
  conftest.py                        # Flask test client, in-memory SQLite, shared fixtures
  test_pushover_notifications.py     # Pushover unit tests
  test_request_notifications.py      # Email notification unit tests
  test_request_routes.py             # Request API route integration tests
  test_request_db.py                 # RequestDB unit tests
  test_settings_registry.py          # Settings field/registry unit tests
  test_models.py                     # Core model validation tests
  test_naming.py                     # Naming template rendering tests
  test_utils.py                      # URL normalization and utility tests
```

### `conftest.py`
- Flask app fixture with auth disabled (`AUTH_METHOD=none`) and in-memory DB
- `request_db` and `user_db` fixtures
- Sample request and user fixtures

### `test_pushover_notifications.py`
- Returns `False` when `PUSHOVER_ENABLED=False`
- Returns `False` when user key or token missing
- Correct payload sent (title, message, rich fields present/absent)
- Returns `False` on HTTP error (mocked)
- `test_pushover_connection` returns success/failure dict

### `test_request_notifications.py`
- Returns `False` when `NOTIFY_REQUESTS_VIA_EMAIL=False`
- Returns `False` when SMTP not configured
- Correct email content for each status (approved/denied/fulfilled/failed)
- Admin note included when provided

### `test_request_routes.py`
- `POST /api/requests` — creates request, returns 201
- `POST /api/requests` — duplicate detection returns 409
- `POST /api/requests` — missing title returns 400
- `GET /api/requests` — admin sees all, user sees own
- `DELETE /api/requests/<id>` — owner deletes, admin hides
- `POST /api/requests/<id>/approve` — status → approved, Pushover fires
- `POST /api/requests/<id>/deny` — status → denied, email fires
- `PUT /api/requests/<id>/status` — valid/invalid status transitions
- WebSocket broadcast called on create/update

### `test_request_db.py`
- Create, get, list, delete, hide requests
- `update_request_status` persists correctly
- `count_requests` and `get_request_counts` return accurate counts
- `get_unviewed_count` reflects last-viewed timestamp

### `test_settings_registry.py`
- Fields produce correct serialized schema
- `show_when` conditions respected
- `on_save` validators: downloads (SMTP validation), advanced (path mappings), mirrors (URL normalization)

### `test_models.py`
- Model field types and defaults

### `test_naming.py`
- Template variable substitution: `{Author}`, `{Title}`, `{Year}`, `{Series}`, etc.
- Optional prefix/suffix syntax `{Vol. SeriesPosition - }` outputs nothing when field empty
- Path separator handling for organize mode

### `test_utils.py`
- `normalize_http_url` — scheme injection, trailing slash, special values
- Other utility functions

### Tooling
- **Framework:** `pytest`
- **Mocking:** `unittest.mock` — no real network or disk I/O
- **DB:** in-memory SQLite for all DB tests
- **No new runtime dependencies**
