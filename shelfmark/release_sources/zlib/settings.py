"""Z-Library search settings registration."""

from __future__ import annotations

from shelfmark.core.settings_registry import (
    CheckboxField,
    NumberField,
    PasswordField,
    SettingsField,
    TextField,
    register_settings,
)
from shelfmark.release_sources.zlib.client import DEFAULT_ACCOUNT_URL

_ENABLED = {"field": "ZLIB_SEARCH_ENABLED", "value": True}


@register_settings("zlib_config", "Z-Library Search", icon="download", order=47)
def zlib_config_settings() -> list[SettingsField]:
    """Z-Library search configuration settings."""
    return [
        CheckboxField(
            key="ZLIB_SEARCH_ENABLED",
            label="Enable Z-Library Search",
            description=(
                "Search and download from Z-Library with your account. Free accounts "
                "are limited to 10 downloads per day."
            ),
            default=False,
        ),
        TextField(
            key="ZLIB_ACCOUNT_URL",
            label="Z-Library URL",
            description="Domain your account logs in on.",
            default=DEFAULT_ACCOUNT_URL,
            show_when=_ENABLED,
        ),
        TextField(key="ZLIB_EMAIL", label="Email", default="", show_when=_ENABLED),
        PasswordField(key="ZLIB_PASSWORD", label="Password", default="", show_when=_ENABLED),
        NumberField(
            key="ZLIB_SEARCH_MAX_RESULTS",
            label="Max Results",
            description="Maximum number of results to request per search (1-50).",
            default=10,
            min_value=1,
            max_value=50,
            show_when=_ENABLED,
        ),
    ]
