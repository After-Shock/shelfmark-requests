"""ISBN embedding into EPUB OPF metadata."""

import os
import zipfile

from shelfmark.download.postprocess.epub import embed_isbn

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)
OPF2 = (
    '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
    '<dc:title>Book</dc:title><dc:identifier id="id">uuid:1</dc:identifier>{extra}</metadata></package>'
)
OPF3 = (
    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
    '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:title>Book</dc:title><dc:identifier id="id">uuid:1</dc:identifier></metadata></package>'
)


def _epub(path, opf):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")  # stored
        z.writestr("META-INF/container.xml", CONTAINER, zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, zipfile.ZIP_DEFLATED)
    return path


def _opf(path):
    with zipfile.ZipFile(path) as z:
        return z.read("OEBPS/content.opf").decode()


def test_epub2_gets_scheme_identifier_and_stays_valid(tmp_path):
    book = _epub(tmp_path / "b.epub", OPF2.format(extra=""))
    assert embed_isbn(book, "978-0-316-17567-8")
    assert '<dc:identifier opf:scheme="ISBN">9780316175678</dc:identifier></metadata>' in _opf(book)
    with zipfile.ZipFile(book) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert not list(tmp_path.glob("*.tmp"))


def test_epub3_without_opf_prefix_gets_urn_identifier(tmp_path):
    book = _epub(tmp_path / "b.epub", OPF3)
    assert embed_isbn(book, "0316175676")
    assert "<dc:identifier>urn:isbn:0316175676</dc:identifier>" in _opf(book)


def test_existing_isbn_and_bad_input_leave_file_alone(tmp_path):
    has_isbn = OPF2.format(extra='<dc:identifier opf:scheme="ISBN">9781111111111</dc:identifier>')
    book = _epub(tmp_path / "b.epub", has_isbn)
    assert not embed_isbn(book, "9780316175678")
    assert _opf(book) == has_isbn
    assert not embed_isbn(_epub(tmp_path / "c.epub", OPF3), "not-an-isbn")


def test_hardlinked_original_is_not_modified(tmp_path):
    original = _epub(tmp_path / "torrent.epub", OPF3)
    library = tmp_path / "library.epub"
    os.link(original, library)
    assert embed_isbn(library, "9780316175678")
    assert "isbn" in _opf(library) and "isbn" not in _opf(original)
