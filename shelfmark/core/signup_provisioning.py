"""Create matching accounts on configured services when a Shelfmark user signs up.

Supports two integrations, each with its own settings toggle:

- Audiobookshelf (ABS_USER_SYNC_ENABLED, via abs_user_sync)
- Calibre-Web / CWA (CWA_USER_SYNC_ENABLED, via cwa_user_sync)

Provisioning is best-effort: a failure for one service never blocks the
Shelfmark account itself or the other service.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

# Keys used in signup service selections (API payload) -> (module, function).
_SERVICE_KEYS = ("audiobookshelf", "calibre_web")
_SERVICE_LABELS = {"audiobookshelf": "Audiobookshelf", "calibre_web": "Calibre-Web"}

# Explicit "every service" selection, for callers with no per-service UI
# (e.g. admin user creation). Read-only; never mutate.
ALL_SERVICES = {key: True for key in _SERVICE_KEYS}


# Usernames that Shelfmark, Audiobookshelf and Calibre-Web all handle safely.
# '@' and '+' are allowed because signing up with an email address as the
# username is common here; what this blocks is the path-mangling set
# ('/', '?', '#', '\\', whitespace) plus control characters.
_SIGNUP_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@+-]{2,64}$")


def validate_signup_username(username: str) -> Optional[str]:
    """Return an error message for a bad signup username, or None if it is fine.

    New signups only. Existing Shelfmark accounts are never re-checked against
    this rule - they keep whatever username they already have, and logging in
    does not go through here.
    """
    if _SIGNUP_USERNAME_RE.match(username):
        return None
    return (
        "Username must be 2-64 characters, using only letters, numbers "
        "and the characters . _ - + @"
    )


def normalize_service_selection(data: Any) -> Dict[str, bool]:
    """Normalize a signup service selection from an API payload.

    Accepts None (select none), a list of keys, or a dict of flags.
    Missing keys default to False so signup creates no external accounts unless
    the user explicitly selects them.
    """
    if data is None:
        return {key: False for key in _SERVICE_KEYS}
    if isinstance(data, (list, tuple)):
        return {key: key in data for key in _SERVICE_KEYS}
    if isinstance(data, dict):
        return {key: bool(data.get(key, False)) for key in _SERVICE_KEYS}
    # Unrecognised payload shape: select nothing. Creating accounts on other
    # people's servers is not the safe default for a malformed request.
    logger.warning("Ignoring signup service selection of unexpected type %s", type(data).__name__)
    return {key: False for key in _SERVICE_KEYS}


def provision_signup_accounts(
    username: str,
    password: str,
    email: Optional[str] = None,
    role: str = "user",
    services: Optional[Dict[str, bool]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Provision accounts on each selected, enabled service.

    Args:
        username: The Shelfmark username to mirror.
        password: The plaintext password chosen during signup.
        email: Optional email (used by Calibre-Web).
        role: Shelfmark role ('admin' or 'user').
        services: Which services to provision. Defaults to none - pass
            ALL_SERVICES for callers without a per-service selection UI.

    Returns:
        Map of service key -> sync result dict with 'status' and 'message'.
    """
    from shelfmark.core.abs_user_sync import is_enabled as abs_enabled, provision_abs_user
    from shelfmark.core.cwa_user_sync import (
        is_provisioning_enabled as cwa_enabled,
        provision_cwa_user,
    )

    selection = services if services is not None else {key: False for key in _SERVICE_KEYS}
    results: Dict[str, Dict[str, Any]] = {}

    if selection.get("audiobookshelf") and abs_enabled():
        results["audiobookshelf"] = provision_abs_user(username, password, role=role)
    elif selection.get("audiobookshelf"):
        results["audiobookshelf"] = {"status": "skipped", "message": "Audiobookshelf sync not enabled/configured"}

    if selection.get("calibre_web") and cwa_enabled():
        results["calibre_web"] = provision_cwa_user(username, password, email=email, role=role)
    elif selection.get("calibre_web"):
        results["calibre_web"] = {"status": "skipped", "message": "Calibre-Web sync not enabled/configured"}

    for service, result in results.items():
        if result["status"] == "error":
            logger.warning("Account sync failed for '%s' (%s): %s", username, service, result["message"])
        else:
            logger.info("Account sync for '%s' (%s): %s", username, service, result["status"])

    return results


def get_warnings(results: Dict[str, Dict[str, Any]]) -> List[str]:
    """Extract human-readable warnings from provisioning results."""
    warnings: List[str] = []
    for service, result in results.items():
        if result["status"] == "error":
            label = _SERVICE_LABELS.get(service, service)
            warnings.append(f"{label}: {result['message']}")
    return warnings


def parse_provisioned_services(value: Any) -> set:
    """Parse a users.provisioned_services value into a set of service keys."""
    if not value:
        return set()
    return {part.strip() for part in str(value).split(",") if part.strip() in _SERVICE_KEYS}


def record_provisioned_services(
    user_db: Any, user_id: int, results: Dict[str, Dict[str, Any]]
) -> None:
    """Remember which external accounts Shelfmark actually created for a user.

    Only 'created' counts. A service reporting 'exists' means the account was
    already there and we left it alone - claiming ownership of it would let a
    later password change overwrite a password Shelfmark never set.
    """
    created = {service for service, result in results.items() if result.get("status") == "created"}
    if not created:
        return
    user = user_db.get_user(user_id=user_id) or {}
    merged = parse_provisioned_services(user.get("provisioned_services")) | created
    user_db.update_user(int(user_id), provisioned_services=",".join(sorted(merged)))


def set_password(user_db: Any, user: Dict[str, Any], password: str) -> Dict[str, Dict[str, Any]]:
    """Store a new local password and push it to the services we provisioned.

    Single chokepoint for password changes. Any caller that hashes and writes a
    password itself will silently drift the user's Audiobookshelf/Calibre-Web
    accounts out of sync, so route every password change through here.

    Only services recorded in users.provisioned_services are updated. Users who
    predate signup provisioning have no record, so their external accounts -
    which Shelfmark did not create - are never touched.

    Returns a map of service key -> result dict, for get_warnings().
    """
    from werkzeug.security import generate_password_hash

    from shelfmark.core.abs_user_sync import update_abs_password
    from shelfmark.core.cwa_user_sync import update_cwa_password

    user_db.update_user(int(user["id"]), password_hash=generate_password_hash(password))

    username = user["username"]
    provisioned = parse_provisioned_services(user.get("provisioned_services"))
    if not provisioned:
        logger.info("No Shelfmark-provisioned services for '%s'; password change stays local", username)
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    for service, updater in (
        ("audiobookshelf", update_abs_password),
        ("calibre_web", update_cwa_password),
    ):
        if service not in provisioned:
            continue
        try:
            results[service] = updater(username, password)
        except Exception as e:
            logger.warning("Unexpected error updating %s password for '%s': %s", service, username, e)
            results[service] = {"status": "error", "message": "Unexpected error updating password"}

    for service, result in results.items():
        if result["status"] == "error":
            logger.warning("Password sync failed for '%s' (%s): %s", username, service, result["message"])
    return results