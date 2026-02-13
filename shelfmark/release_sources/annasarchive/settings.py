"""Anna's Archive settings registration.

Registers Anna's Archive release source settings for the settings UI.
"""

from shelfmark.core.settings_registry import (
    ActionButton,
    CheckboxField,
    HeadingField,
    TextField,
    PasswordField,
    register_settings,
)


def _test_annasarchive_api():
    """Test Anna's Archive API connection."""
    from shelfmark.core.config import config
    import requests

    api_key = config.get("AA_DONATOR_KEY", "").strip()
    if not api_key:
        return {"success": False, "message": "API key not configured"}

    base_url = config.get("ANNASARCHIVE_API_BASE_URL", "").strip() or "https://annas-archive.li"

    try:
        # Try ping endpoint
        response = requests.get(f"{base_url}/dyn/api/ping", timeout=10)
        if response.status_code == 200:
            return {"success": True, "message": f"Successfully connected to {base_url}"}
        else:
            return {"success": False, "message": f"Server returned {response.status_code}"}
    except requests.Timeout:
        return {"success": False, "message": "Connection timed out"}
    except requests.RequestException as e:
        return {"success": False, "message": f"Connection failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


@register_settings(
    name="annasarchive_source",
    display_name="Anna's Archive (API)",
    icon="download",
    order=57,
)
def annasarchive_source_settings():
    """Define Anna's Archive release source settings."""
    return [
        HeadingField(
            key="heading",
            title="Anna's Archive (API Source)",
            description=(
                "Search and download books using Anna's Archive JSON API. "
                "This source uses the official API for fast, reliable downloads. "
                "Requires a donator API key from Anna's Archive. "
                "Get your key at: https://annas-archive.li/account/keys"
            ),
            link_url="https://annas-archive.li/account/keys",
            link_text="Get API Key",
        ),

        PasswordField(
            key="AA_DONATOR_KEY",
            label="API Key (Donator Key)",
            description="Your Anna's Archive donator API key. Required for API access.",
            placeholder="Enter your donator key...",
            env_supported=True,
        ),

        TextField(
            key="ANNASARCHIVE_API_BASE_URL",
            label="API Base URL",
            description="Anna's Archive API base URL. Change if the primary mirror is down. Common mirrors: .li, .gs, .se",
            placeholder="https://annas-archive.li",
            default="https://annas-archive.li",
            env_supported=True,
        ),

        ActionButton(
            key="test_connection",
            label="Test API Connection",
            description="Verify Anna's Archive API is accessible with your key",
            style="primary",
            callback=_test_annasarchive_api,
        ),

        CheckboxField(
            key="ANNASARCHIVE_API_ENABLED",
            label="Enable Anna's Archive API Source",
            description="Enable Anna's Archive as a separate release source (requires API key)",
            default=False,
            env_supported=True,
        ),

        HeadingField(
            key="info_heading",
            title="About This Source",
            description=(
                "This is a separate Anna's Archive source that uses the official JSON API "
                "for fast, reliable downloads. It works independently from the 'Direct Download' "
                "source which uses web scraping. Enable this for faster, more reliable results."
            ),
        ),
    ]
