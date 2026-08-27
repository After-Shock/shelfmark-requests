"""Provision matching Audiobookshelf accounts for new Shelfmark users.

When a user signs up on Shelfmark, we mirror the account onto the configured
Audiobookshelf server so they can log in there with the same username/password.

Requires the ABS API token in settings to belong to an admin account on the
Audiobookshelf server, since user creation is an admin-only API call.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests as http_requests

from shelfmark.core.config import config
from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)


def _get_credentials() -> tuple[Optional[str], Optional[str]]:
    """Return (base_url, api_token) from settings, or (None, None) if not configured."""
    url = (config.get("AUDIOBOOK_LIBRARY_URL", "") or "").strip().rstrip("/")
    token = (config.get("ABS_API_TOKEN", "") or "").strip()
    return (url or None, token or None)


def is_enabled() -> bool:
    """Return True if ABS user sync is enabled and fully configured."""
    url, token = _get_credentials()
    return bool(url and token and bool(config.get("ABS_USER_SYNC_ENABLED", False)))


def _abs_user_exists(base_url: str, token: str, username: str) -> Optional[bool]:
    """Check if a user already exists on the ABS server. None = check failed."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = http_requests.get(
            f"{base_url}/api/users/username/{username}",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        if resp.status_code == 404:
            return False
        logger.warning(
            "ABS user lookup for '%s' returned unexpected status %d",
            username,
            resp.status_code,
        )
        return None
    except http_requests.RequestException as e:
        logger.warning("ABS user lookup failed for '%s': %s", username, e)
        return None


def _get_all_library_ids(base_url: str, token: str) -> list[str]:
    """Return all library IDs visible to the configured admin token."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_requests.get(f"{base_url}/api/libraries", headers=headers, timeout=10)
    resp.raise_for_status()
    return [str(lib["id"]) for lib in resp.json().get("libraries", []) if lib.get("id")]


def _grant_all_libraries(base_url: str, token: str, username: str) -> Dict[str, Any]:
    """Grant a user access to every ABS library.

    ABS has used different field names across releases; update the field already
    present on the user object when possible, and default to librariesAccessible.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    lookup = http_requests.get(f"{base_url}/api/users/username/{username}", headers=headers, timeout=10)
    if lookup.status_code != 200:
        return {"status": "error", "message": "Audiobookshelf account created, but user lookup failed while granting libraries"}

    user = lookup.json() or {}
    user_id = user.get("id")
    if not user_id:
        return {"status": "error", "message": "Audiobookshelf account created, but returned user had no id"}

    detail = http_requests.get(f"{base_url}/api/users/{user_id}", headers=headers, timeout=10)
    if detail.status_code == 200:
        user = detail.json() or user

    library_ids = _get_all_library_ids(base_url, token)
    if not library_ids:
        return {"status": "created", "message": "Audiobookshelf account created; no libraries found to grant"}

    access_key = "librariesAccessible"
    for candidate in ("librariesAccessible", "libraries_access", "librariesAccess"):
        if candidate in user:
            access_key = candidate
            break
    user[access_key] = library_ids

    resp = http_requests.put(f"{base_url}/api/users/{user_id}", headers=headers, json=user, timeout=15)
    if resp.status_code in (200, 204):
        return {"status": "created", "message": "Audiobookshelf account created with all library access"}
    logger.warning("ABS library grant for '%s' failed with status %d: %s", username, resp.status_code, resp.text[:500])
    return {"status": "error", "message": "Audiobookshelf account created, but granting library access failed"}


def provision_abs_user(username: str, password: str, role: str = "user") -> Dict[str, Any]:
    """Create a matching user on the Audiobookshelf server.

    Args:
        username: The Shelfmark username to mirror.
        password: The plaintext password chosen during signup.
        role: Shelfmark role ('admin' or 'user'). Maps to ABS account type.

    Returns:
        Dict with keys:
          - status: 'created' | 'exists' | 'skipped' | 'error'
          - message: human-readable detail for logging/UI
    """
    base_url, token = _get_credentials()
    if not base_url or not token:
        return {"status": "skipped", "message": "Audiobookshelf URL or API token not configured"}
    if not bool(config.get("ABS_USER_SYNC_ENABLED", False)):
        return {"status": "skipped", "message": "ABS user sync is disabled"}

    # If the user already exists on ABS, don't touch their account.
    exists = _abs_user_exists(base_url, token, username)
    if exists:
        return {"status": "exists", "message": f"User '{username}' already exists on Audiobookshelf"}
    if exists is None:
        return {"status": "error", "message": "Could not verify existing users on Audiobookshelf"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "username": username,
        "password": password,
        "type": "admin" if role == "admin" else "user",
    }
    try:
        resp = http_requests.post(f"{base_url}/api/users", headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            logger.info("Created Audiobookshelf account for user '%s'", username)
            try:
                return _grant_all_libraries(base_url, token, username)
            except http_requests.RequestException as e:
                logger.warning("ABS library grant for '%s' failed: %s", username, e)
                return {
                    "status": "error",
                    "message": "Audiobookshelf account created, but granting library access failed",
                }
        if resp.status_code == 403:
            logger.error(
                "Audiobookshelf rejected user creation for '%s' (403). "
                "The configured ABS API token likely does not belong to an admin account.",
                username,
            )
            return {
                "status": "error",
                "message": "ABS API token is not an admin token; cannot create users",
            }
        if resp.status_code == 409:
            return {"status": "exists", "message": f"User '{username}' already exists on Audiobookshelf"}
        logger.error(
            "Audiobookshelf user creation for '%s' failed with status %d: %s",
            username,
            resp.status_code,
            resp.text[:500],
        )
        return {"status": "error", "message": f"ABS returned status {resp.status_code}"}
    except http_requests.RequestException as e:
        logger.error("Audiobookshelf user creation for '%s' failed: %s", username, e)
        return {"status": "error", "message": "Could not reach Audiobookshelf server"}
