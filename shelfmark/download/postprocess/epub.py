"""Write a known ISBN into an EPUB so library tools (Calibre) match it exactly."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

_ROOTFILE = re.compile(rb'full-path="([^"]+)"')
_METADATA_CLOSE = re.compile(rb"</(?:[\w-]+:)?metadata>")
_IDENTIFIER = re.compile(rb"<(?:[\w-]+:)?identifier\b[^>]*>[^<]*")


def embed_isbn(path: Path, isbn: str) -> bool:
    """Add a dc:identifier ISBN to the EPUB's OPF. Returns True if the file changed.

    EPUBs that already carry an ISBN are left alone. The file is rewritten to a
    temp file and swapped in, so a hardlinked torrent original is never touched.
    """
    isbn = re.sub(r"[^0-9Xx]", "", isbn or "").upper()
    if len(isbn) not in (10, 13):
        return False

    with zipfile.ZipFile(path) as zin:
        rootfile = _ROOTFILE.search(zin.read("META-INF/container.xml"))
        if not rootfile:
            return False
        opf_name = rootfile.group(1).decode()
        opf = zin.read(opf_name)
        close = _METADATA_CLOSE.search(opf)
        if (
            not close
            or b"xmlns:dc=" not in opf
            or any(b"isbn" in m.group(0).lower() for m in _IDENTIFIER.finditer(opf))
        ):
            return False

        if b"xmlns:opf=" in opf:
            identifier = f'<dc:identifier opf:scheme="ISBN">{isbn}</dc:identifier>'
        else:
            identifier = f"<dc:identifier>urn:isbn:{isbn}</dc:identifier>"
        opf = opf[: close.start()] + identifier.encode() + opf[close.start():]

        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".epub.tmp")
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as zout:
                for item in zin.infolist():  # keeps order and per-entry compression (mimetype first, stored)
                    zout.writestr(item, opf if item.filename == opf_name else zin.read(item))
            shutil.copymode(path, tmp)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    return True
