"""Is an ebook already in the Calibre library? Reads Calibre's metadata.db read-only."""

from __future__ import annotations

import difflib
import os
import re
import sqlite3
from typing import Any, Optional

from shelfmark.core.audiobookshelf import _normalize, _titles_match

_DEFAULT_DB_PATH = "/calibre-library/metadata.db"


def _main_title(title: str) -> str:
    """Title without its subtitle ("Daggermouth: A Dark Dystopian Romance" -> "Daggermouth")."""
    return title.split(":", 1)[0]


def find_match(title: str, author: str) -> Optional[dict[str, Any]]:
    """First of find_matches, or None."""
    return next(iter(find_matches(title, author, limit=1)), None)


def find_matches(title: str, author: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return up to `limit` library books matching title (and author, when given).

    None when the library isn't mounted. Errors reading it propagate; callers fail open.
    """
    path = os.getenv("CALIBRE_LIBRARY_DB_PATH", _DEFAULT_DB_PATH)
    if not os.path.isfile(path):
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        # ponytail: full scan per request (~10k books, a few ms); index titles if the library grows a lot.
        rows = conn.execute(
            "SELECT b.id, b.title, group_concat(a.name, '&') FROM books b "
            "LEFT JOIN books_authors_link l ON l.book = b.id "
            "LEFT JOIN authors a ON a.id = l.author GROUP BY b.id"
        ).fetchall()
    finally:
        conn.close()

    norm_author = _normalize(author or "")
    found: list[dict[str, Any]] = []
    for book_id, item_title, item_authors in rows:
        if not (_titles_match(title, item_title or "")
                or _titles_match(_main_title(title), _main_title(item_title or ""))):
            continue
        names = [_normalize(a) for a in re.split(r"[&,;/]", item_authors or "") if a.strip()]
        # Same 0.70 author threshold as the Audiobookshelf check.
        if not norm_author or not names or any(
            difflib.SequenceMatcher(None, norm_author, n).ratio() >= 0.70 for n in names
        ):
            found.append({
                "id": book_id,
                "title": item_title,
                "author": " & ".join(n.strip() for n in (item_authors or "").split("&")),
            })
            if len(found) >= limit:
                break
    return found
