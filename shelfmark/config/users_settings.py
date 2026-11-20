"""Users settings tab registration.

This registers a 'users' tab in the settings sidebar.
The actual user management is handled by a custom frontend component
that talks to /api/admin/users endpoints.
"""

from shelfmark.core.settings_registry import (
    CustomComponentField,
    HeadingField,
    NumberField,
    register_settings,
)


_USERS_HEADING_DESCRIPTION_BY_AUTH_MODE = {
    "builtin": (
        "Create and manage user accounts directly. Passwords are stored locally and users sign in "
        "with their username and password."
    ),
    "oidc": (
        "Users sign in through your identity provider. New accounts can be created automatically on "
        "first login when auto-provisioning is enabled, or you can pre-create users here and they\u2019ll "
        "be linked by email on first sign-in."
    ),
    "proxy": (
        "Users are authenticated by your reverse proxy. Accounts are automatically created on first "
        "sign-in. If a local user with a matching username already exists, it will be linked instead."
    ),
    "cwa": (
        "User accounts are synced from your Calibre-Web database. Users are matched by email, and new "
        "accounts are created here when new CWA users are found."
    ),
    "none": "Authentication is disabled. Anyone can access Shelfmark without signing in.",
    "default": "Authentication is disabled. Anyone can access Shelfmark without signing in.",
}


@register_settings("users", "Users & Requests", icon="users", order=6)
def users_settings():
    """User management tab - rendered as a custom component on the frontend."""
    return [
        HeadingField(
            key="users_heading",
            title="Users",
            description=_USERS_HEADING_DESCRIPTION_BY_AUTH_MODE["default"],
            description_by_auth_mode=_USERS_HEADING_DESCRIPTION_BY_AUTH_MODE,
        ),
        CustomComponentField(
            key="users_management",
            component="users_management",
        ),
        # Edited from the Users panel (it replaces this tab's normal renderer).
        NumberField(
            key="WEEKLY_REQUEST_LIMIT",
            label="Weekly request limit",
            description="New requests each non-admin user can make per week (Monday to Sunday, US Eastern).",
            default=6,
            min_value=0,
            max_value=100,
            env_supported=False,
        ),
        NumberField(
            key="WEEKLY_REPORT_LIMIT",
            label="Weekly report limit",
            description="Problem reports each non-admin user can make per week (Monday to Sunday, US Eastern).",
            default=6,
            min_value=0,
            max_value=100,
            env_supported=False,
        ),
    ]
