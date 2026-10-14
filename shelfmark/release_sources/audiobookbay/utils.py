"""Utility functions for AudiobookBay integration."""

import re
from typing import Optional

# WordPress texturizes punctuation on output only, so ABB's search matches the
# stored ASCII form and ANDs its terms: one curly apostrophe in a query empties
# the whole result set. Map typographic forms back before searching/comparing.
_ASCII_PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "\u00b4": "'", "`": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u2212": "-", "\ufe58": "-", "\ufe63": "-", "\uff0d": "-",
    "\u2026": "...",
})


def normalize_search_punctuation(text: str) -> str:
    """Replace typographic punctuation with the ASCII forms ABB stores."""
    return text.translate(_ASCII_PUNCTUATION) if text else text


def normalize_hostname(raw: Optional[str]) -> str:
    """Normalize a user-supplied hostname for URL construction.

    Strips whitespace, scheme prefixes, trailing slashes, and paths so that
    values like "https://audiobookbay.lu/" or " audiobookbay.lu/ " all
    resolve to "audiobookbay.lu".
    """
    if not raw or not isinstance(raw, str):
        return ""
    cleaned = raw.strip()
    # Strip scheme
    for prefix in ("https://", "http://"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    # Strip path and trailing slashes
    cleaned = cleaned.split("/")[0].strip()
    return cleaned


def parse_size(size_str: Optional[str]) -> Optional[int]:
    """Parse size string to bytes.

    Args:
        size_str: Size string (e.g., "1.5 GB", "500 MB", "11.68 GBs")

    Returns:
        Size in bytes, or None if parsing fails
    """
    if not size_str:
        return None

    # Match number and unit, handling "GBs" as well as "GB" (case-insensitive)
    match = re.search(r"([\d.]+)\s*([BKMGT]B?)S?", size_str.upper())
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2)

    multipliers = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }

    return int(value * multipliers.get(unit, 1))
