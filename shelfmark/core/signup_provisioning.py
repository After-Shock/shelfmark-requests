"""Create matching accounts on configured services when a Shelfmark user signs up.

Supports two integrations, each with its own settings toggle:

- Audiobookshelf (ABS_USER_SYNC_ENABLED, via abs_user_sync)
- Calibre-Web / CWA (CWA_USER_SYNC_ENABLED, via cwa_user_sync)

Provisioning is best-effort: a failure for one service never blocks the
Shelfmark account itself or the other service.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

# Keys used in signup service selections (API payload) -> (module, function).
_SERVICE_KEYS = ("audiobookshelf", "calibre_web")


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
    return {key: True for key in _SERVICE_KEYS}


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
        services: Which services to provision. Defaults to all.

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
    labels = {"audiobookshelf": "Audiobookshelf", "calibre_web": "Calibre-Web"}
    for service, result in results.items():
        if result["status"] == "error":
            label = labels.get(service, service)
            warnings.append(f"{label}: {result['message']}")
    return warnings