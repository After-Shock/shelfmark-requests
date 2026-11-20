"""Tests for the Audiobookshelf paths, multi-match and edit endpoints used by issue reports."""
import sqlite3
from unittest.mock import MagicMock, patch

from shelfmark.core import audiobookshelf
from shelfmark.core.audiobookshelf import ABSClient, local_path_for, local_root_for


def _cfg(values):
    return patch.object(audiobookshelf.config, "get", side_effect=lambda k, d=None: values.get(k, d))


def _resp(status=200, payload=None):
    r = MagicMock(status_code=status)
    r.json.return_value = payload or {}
    r.raise_for_status.side_effect = None if status < 400 else Exception(f"HTTP {status}")
    return r


def test_cache_keeps_path():
    creds = {"AUDIOBOOK_LIBRARY_URL": "http://abs", "ABS_API_TOKEN": "t"}
    item = {"id": "i1", "path": "/Audiobooks/A/B",
            "media": {"metadata": {"title": "B", "authorName": "A", "seriesName": ""}}}
    responses = [_resp(payload={"libraries": [{"id": "l1", "mediaType": "book"}]}),
                 _resp(payload={"results": [item]})]
    client = ABSClient()
    with _cfg(creds), patch.object(audiobookshelf.http_requests, "get", side_effect=responses):
        assert client.refresh() == 1
    assert client._cache[0]["path"] == "/Audiobooks/A/B"
    assert client._cache[0]["cover"] == "http://abs/api/items/i1/cover"


def test_find_matches_returns_all_hits():
    client = ABSClient()
    client._cache = [{"id": str(i), "title": "The Hobbit", "author": "Tolkien"} for i in range(7)]
    client._cache.append({"id": "x", "title": "Other", "author": "Tolkien"})
    assert len(client.find_matches("The Hobbit", "Tolkien")) == 5
    assert len(client.find_matches("The Hobbit", "Tolkien", limit=2)) == 2
    assert client.find_match("The Hobbit", "Tolkien")["id"] == "0"
    assert client.find_matches("Nope", "Tolkien") == []


def test_local_path_for_maps_prefix():
    cfg = {"ABS_PATH_MAPPINGS": "garbage\n\n =x\n/Audiobooks = /UnRaid/audiobooks \n"
           "/UnRaid/audiobooks-children=/UnRaid/audiobooks-children"}
    with _cfg(cfg):
        assert str(local_path_for("/Audiobooks/A/B")) == "/UnRaid/audiobooks/A/B"
        assert str(local_root_for("/Audiobooks/A/B")) == "/UnRaid/audiobooks"
        assert str(local_path_for("/UnRaid/audiobooks-children/K/B")) == "/UnRaid/audiobooks-children/K/B"
        assert str(local_root_for("/UnRaid/audiobooks-children/K/B")) == "/UnRaid/audiobooks-children"
        assert local_path_for("/audiobooks/A") is None
        assert local_path_for("/AudiobooksX/A") is None
        assert local_path_for("/Audiobooks/../etc") is None
        assert local_root_for("/Audiobooks/../etc") is None
    with _cfg({}):
        assert local_path_for("/Audiobooks/A/B") is None


def test_get_item_404_returns_none():
    creds = {"AUDIOBOOK_LIBRARY_URL": "http://abs", "ABS_API_TOKEN": "t"}
    with _cfg(creds), patch.object(audiobookshelf.http_requests, "get", return_value=_resp(404)) as g:
        assert ABSClient().get_item("i1") is None
    assert g.call_args.args[0] == "http://abs/api/items/i1"
    assert g.call_args.kwargs["params"] == {"expanded": 1}


def test_get_item_other_error_raises():
    creds = {"AUDIOBOOK_LIBRARY_URL": "http://abs", "ABS_API_TOKEN": "t"}
    with _cfg(creds), patch.object(audiobookshelf.http_requests, "get", return_value=_resp(500)):
        try:
            ABSClient().get_item("i1")
        except Exception:
            return
    raise AssertionError("expected raise")


def test_edit_endpoints_send_expected_payloads():
    creds = {"AUDIOBOOK_LIBRARY_URL": "http://abs", "ABS_API_TOKEN": "t"}
    c = ABSClient()
    with _cfg(creds), patch.object(audiobookshelf.http_requests, "post", return_value=_resp()) as post, \
            patch.object(audiobookshelf.http_requests, "patch", return_value=_resp()) as patch_:
        c.set_cover_url("i1", "http://img/c.jpg")
        c.match_item("i1", "T", "A")
        c.match_item("i1", "T", "A", override_details=False)
        c.update_metadata("i1", {"title": "T", "authors": [{"name": "A"}, {"name": "B"}]})
    assert post.call_args_list[0].args[0] == "http://abs/api/items/i1/cover"
    assert post.call_args_list[0].kwargs["json"] == {"url": "http://img/c.jpg"}
    assert post.call_args_list[1].args[0] == "http://abs/api/items/i1/match"
    assert post.call_args_list[1].kwargs["json"] == {
        "title": "T", "author": "A", "overrideCover": True, "overrideDetails": True}
    assert post.call_args_list[2].kwargs["json"]["overrideDetails"] is False
    assert patch_.call_args.args[0] == "http://abs/api/items/i1/media"
    assert patch_.call_args.kwargs["json"] == {"metadata": {"title": "T", "authors": [{"name": "A"}, {"name": "B"}]}}


def test_calibre_find_matches_has_id_and_find_match_compatible(tmp_path, monkeypatch):
    from shelfmark.core import calibre_library
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT);"
        "CREATE TABLE authors(id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE books_authors_link(id INTEGER PRIMARY KEY, book INT, author INT);"
        "INSERT INTO books VALUES (7,'The Hobbit'),(9,'The Hobbit');"
        "INSERT INTO authors VALUES (1,'Tolkien');"
        "INSERT INTO books_authors_link(book,author) VALUES (7,1),(9,1);")
    conn.commit()
    conn.close()
    monkeypatch.setenv("CALIBRE_LIBRARY_DB_PATH", str(db))
    assert [m["id"] for m in calibre_library.find_matches("The Hobbit", "Tolkien")] == [7, 9]
    first = calibre_library.find_match("The Hobbit", "Tolkien")
    assert first["title"] == "The Hobbit" and first["author"] == "Tolkien"
    assert calibre_library.find_match("Nope", "") is None
