from bs4 import BeautifulSoup

from shelfmark.release_sources.direct_download import _extract_book_metadata


def _metadata_div(inner: str):
    return BeautifulSoup(f"<div><div>{inner}</div></div>", "html.parser").div


def test_stray_text_nodes_do_not_break_metadata_parse():
    # Regression: a bare text node among the rows raised
    # "'NavigableString' object has no attribute 'children'" and failed /api/info.
    md = _metadata_div(
        "\n <div><div>Language</div><div>en</div></div>"
        " stray text "
        "<div><div>Year</div><div>2015</div></div>"
        "<div>lonely</div>"
    )
    assert _extract_book_metadata(md) == {"Language": ["en"], "Year": ["2015"]}


def test_missing_metadata_block_returns_empty():
    assert _extract_book_metadata(None) == {}
    assert _extract_book_metadata(BeautifulSoup("<p>x</p>", "html.parser").p) == {}
