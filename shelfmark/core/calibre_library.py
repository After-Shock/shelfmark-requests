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
    """Return the first library book matching title (and author, when given), or None.

    None when the library isn't mounted. Errors reading it propagate; callers fail open.
    """
    path = os.getenv("CALIBRE_LIBRARY_DB_PATH", _DEFAULT_DB_PATH)
    if not os.path.isfile(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        # ponytail: full scan per request (~10k books, a few ms); index titles if the library grows a lot.
        rows = conn.execute(
            "SELECT b.title, group_concat(a.name, '&') FROM books b "
            "LEFT JOIN books_authors_link l ON l.book = b.id "
            "LEFT JOIN authors a ON a.id = l.author GROUP BY b.id"
        ).fetchall()
    finally:
        conn.close()

    norm_author = _normalize(author or "")
    for item_title, item_authors in rows:
        if not (_titles_match(title, item_title or "")
                or _titles_match(_main_title(title), _main_title(item_title or ""))):
            continue
        names = [_normalize(a) for a in re.split(r"[&,;/]", item_authors or "") if a.strip()]
        # Same 0.70 author threshold as the Audiobookshelf check.
        if not norm_author or not names or any(
            difflib.SequenceMatcher(None, norm_author, n).ratio() >= 0.70 for n in names
        ):
            return {"title": item_title, "author": " & ".join(n.strip() for n in (item_authors or "").split("&"))}
    return None
