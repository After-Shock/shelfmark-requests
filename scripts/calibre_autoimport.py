"""Import new Shelfmark ebooks into Calibre, fill missing metadata, run Modify ePub.

Runs inside the linuxserver/calibre container and goes through Calibre's
content server, so it is safe while the GUI has the library open. Metadata is
downloaded with Calibre's sources but only fills empty fields (and the cover if
there is none). Hardcover is set to ignore tags (its are mood/content-warning
labels), so tags come from Google, Kobo or Amazon. Modify ePub uses the options last saved in its GUI dialog, after
the metadata step so the jacket picks it up. Host crontab:

  */5 * * * * docker exec -u abc calibre flock -n /tmp/autoimport.lock calibre-debug -e /config/autoimport.py >> /opt/calibre/autoimport.log 2>&1

Imported files are deleted from the import folder; files Calibre rejects as
duplicates are moved to duplicates/. Names listed in the ignore file are left
alone (the backlog that was imported by hand before this script existed).
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import time

from calibre.ebooks.metadata.opf2 import OPF, metadata_to_opf
from calibre.utils.config import JSONConfig
from calibre.utils.date import is_date_undefined
from calibre.utils.logging import Log

IMPORT_DIR = "/ebookimport"
DUPLICATES_DIR = os.path.join(IMPORT_DIR, "duplicates")
LIBRARY = "http://localhost:8081"
IGNORE_FILE = "/config/autoimport.ignore"
SETTLE_SECONDS = 120  # skip files Shelfmark may still be writing
FETCH_ATTEMPTS = 3
TAG_SOURCES = ("Google", "Kobo Metadata", "Amazon.com")


def calibredb(*args):
    return subprocess.run(
        ["calibredb", *args, "--with-library", LIBRARY],
        capture_output=True, text=True, check=True, cwd="/tmp",
    ).stdout


def export_book(book_id, tdir):
    os.makedirs(tdir)
    calibredb("export", "--single-dir", "--to-dir", tdir, "--template", "book",
              "--formats", "epub", str(book_id))
    paths = {ext: os.path.join(tdir, f"book.{ext}") for ext in ("epub", "opf", "jpg")}
    return {ext: path if os.path.exists(path) else None for ext, path in paths.items()}


def read_opf(data, tdir):
    return OPF(io.BytesIO(data), tdir).to_book_metadata()


def fetch(mi, tdir, plugin=None, cover=None, attempts=FETCH_ATTEMPTS, wait=20):
    """Download metadata for mi from all sources, or just `plugin`. None if nothing found."""
    args = ["fetch-ebook-metadata", "--opf", "--timeout", "60", "--title", mi.title,
            "--authors", " & ".join(mi.authors)]
    if cover:
        args += ["--cover", cover]
    if plugin:
        args += ["--allowed-plugin", plugin]
    if mi.identifiers.get("isbn"):
        args += ["--isbn", mi.identifiers["isbn"]]
    for attempt in range(attempts):
        if attempt:
            time.sleep(wait)  # Google Books and Kobo intermittently answer "0 results"
        result = subprocess.run(args, capture_output=True, cwd="/tmp")
        if not result.returncode and b"<package" in result.stdout:
            return read_opf(result.stdout, tdir)
    return None


def _key(text):
    return re.sub(r"[^a-z0-9]", "", re.split(r"[:(\[]", text or "")[0].lower())


def same_book(mi, found):
    """Single sources match loosely (Kobo has returned a different "Anathema")."""
    surnames = lambda m: {_key(a.split()[-1]) for a in m.authors if a.split()}  # noqa: E731
    return _key(mi.title) == _key(found.title) and bool(surnames(mi) & surnames(found))


def lookup_tags(mi, tdir):
    """Tags from the first non-Hardcover source that returns the same book."""
    for plugin in TAG_SOURCES:
        found = fetch(mi, tdir, plugin=plugin, attempts=2, wait=10)
        if found and found.tags and same_book(mi, found):
            return found.tags, plugin
    return None, None


def fill_missing_metadata(book_id, exported, tdir):
    with open(exported["opf"], "rb") as f:
        mi = read_opf(f.read(), tdir)
    cover = os.path.join(tdir, "fetched-cover.jpg")
    found = fetch(mi, tdir, cover=cover)
    filled = []
    if found:
        for field in ("comments", "tags", "publisher", "series", "languages"):
            if not getattr(mi, field) and getattr(found, field):
                setattr(mi, field, getattr(found, field))
                filled.append(field)
        if "series" in filled:
            mi.series_index = found.series_index
        if is_date_undefined(mi.pubdate) and not is_date_undefined(found.pubdate):
            mi.pubdate = found.pubdate
            filled.append("pubdate")
        for key, value in found.identifiers.items():
            if key not in mi.identifiers:
                mi.set_identifier(key, value)
                filled.append(key)
    else:
        print("  no metadata found online")
    if not mi.tags:
        # The merged result only carries the best match's tags; ask tag sources directly.
        tags, plugin = lookup_tags(mi, tdir)
        if tags:
            mi.tags = tags
            filled.append(f"tags ({plugin})")
    if filled:
        mi.cover = None
        merged = os.path.join(tdir, "merged.opf")
        with open(merged, "wb") as f:
            f.write(metadata_to_opf(mi))
        calibredb("set_metadata", str(book_id), merged)
    if not exported["jpg"] and os.path.exists(cover):
        calibredb("set_metadata", str(book_id), "--field", f"cover:{cover}")
        filled.append("cover")
    print(f"  filled missing metadata: {', '.join(filled) or 'none missing'}")
    return bool(filled)


def modify_epub_in_library(book_id, title, exported):
    from calibre_plugins.modify_epub.modify import modify_epub

    options = JSONConfig("gui").get("modify epub plugin:options dialog:settings")
    if not options:
        print(f"  no saved Modify ePub options; skipped modify for {title}")
        return
    if modify_epub(Log(Log.WARN), title, exported["epub"], exported["opf"], exported["jpg"], options):
        calibredb("add_format", str(book_id), exported["epub"])
        print(f"  modified epub for book {book_id}")


def process_book(book_id, title):
    with tempfile.TemporaryDirectory() as tdir:
        exported = export_book(book_id, os.path.join(tdir, "before"))
        try:
            if fill_missing_metadata(book_id, exported, tdir):
                # Re-export so Modify ePub embeds the downloaded metadata and cover
                exported = export_book(book_id, os.path.join(tdir, "after"))
        except Exception as e:
            print(f"  metadata download failed for book {book_id}: {e}")
        modify_epub_in_library(book_id, title, exported)


def main():
    try:
        with open(IGNORE_FILE) as f:
            ignored = set(f.read().splitlines())
    except FileNotFoundError:
        ignored = set()

    for name in sorted(os.listdir(IMPORT_DIR)):
        path = os.path.join(IMPORT_DIR, name)
        if (name in ignored or not name.lower().endswith(".epub") or not os.path.isfile(path)
                or time.time() - os.path.getmtime(path) < SETTLE_SECONDS):
            continue
        stamp = time.strftime("%F %T")
        try:
            out = calibredb("add", path)
        except subprocess.CalledProcessError as e:
            # Content server down (GUI closed?) - leave the file for the next run
            print(f"{stamp} add failed for {name}: {e.stderr.strip()}")
            continue
        match = re.search(r"Added book ids: (\d+)", out)
        if not match:
            os.makedirs(DUPLICATES_DIR, exist_ok=True)
            shutil.move(path, os.path.join(DUPLICATES_DIR, name))
            print(f"{stamp} duplicate, moved to duplicates/: {name}")
            continue
        book_id = int(match.group(1))
        print(f"{stamp} added {name} as book {book_id}")
        try:
            process_book(book_id, name)
        except Exception as e:
            print(f"  post-import step failed for book {book_id}: {e}")
        os.remove(path)


main()
