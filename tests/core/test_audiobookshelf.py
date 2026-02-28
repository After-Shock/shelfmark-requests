"""Tests for the Audiobookshelf library client."""
from unittest.mock import MagicMock, patch
import pytest
from shelfmark.core.audiobookshelf import ABSClient, _normalize


class TestNormalize:
    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert _normalize("Hello, World!") == "hello world"

    def test_handles_empty(self):
        assert _normalize("") == ""


class TestABSClientFindMatch:
    def _client_with_cache(self, items):
        client = ABSClient()
        client._cache = items
        return client

    def test_exact_title_author_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": "J.R.R. Tolkien"},
        ])
        match = client.find_match("The Hobbit", "J.R.R. Tolkien")
        assert match is not None
        assert match["title"] == "The Hobbit"

    def test_case_insensitive_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "the hobbit", "author": "tolkien"},
        ])
        assert client.find_match("The Hobbit", "Tolkien") is not None

    def test_fuzzy_title_match(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit A Novel", "author": "Tolkien"},
        ])
        assert client.find_match("The Hobbit", "Tolkien") is not None

    def test_no_match_different_book(self):
        client = self._client_with_cache([
            {"id": "1", "title": "Lord of the Rings", "author": "Tolkien"},
        ])
        assert client.find_match("Harry Potter", "Rowling") is None

    def test_no_match_low_author_similarity(self):
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": "Someone Else"},
        ])
        assert client.find_match("The Hobbit", "Tolkien") is None

    def test_empty_cache_returns_none(self):
        client = ABSClient()
        client._cache = []
        with patch.object(client, 'refresh', return_value=0):
            with patch.object(client, 'is_configured', return_value=False):
                result = client.find_match("Any Book", "Any Author")
        assert result is None

    def test_no_author_title_match_only(self):
        """If no author info on either side, title match alone is sufficient."""
        client = self._client_with_cache([
            {"id": "1", "title": "The Hobbit", "author": ""},
        ])
        assert client.find_match("The Hobbit", "") is not None


class TestABSClientRefresh:
    def test_refresh_populates_cache(self):
        client = ABSClient()
        mock_response_libraries = MagicMock()
        mock_response_libraries.json.return_value = {
            "libraries": [{"id": "lib1", "mediaType": "book"}]
        }
        mock_response_items = MagicMock()
        mock_response_items.json.return_value = {
            "results": [
                {"id": "item1", "media": {"metadata": {"title": "The Hobbit", "authorName": "Tolkien"}}}
            ]
        }
        with patch("shelfmark.core.audiobookshelf.http_requests.get") as mock_get:
            mock_get.side_effect = [mock_response_libraries, mock_response_items]
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token123")):
                count = client.refresh()
        assert count == 1
        assert client._cache[0]["title"] == "The Hobbit"

    def test_refresh_skips_non_book_libraries(self):
        client = ABSClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "libraries": [
                {"id": "lib1", "mediaType": "music"},
                {"id": "lib2", "mediaType": "podcast"},
            ]
        }
        with patch("shelfmark.core.audiobookshelf.http_requests.get", return_value=mock_resp):
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token")):
                count = client.refresh()
        assert count == 0

    def test_refresh_fails_open_on_error(self):
        client = ABSClient()
        with patch("shelfmark.core.audiobookshelf.http_requests.get", side_effect=Exception("timeout")):
            with patch.object(client, "_get_credentials", return_value=("http://abs:8080", "token")):
                count = client.refresh()
        assert count == 0

    def test_is_configured_false_when_no_token(self):
        client = ABSClient()
        with patch("shelfmark.core.audiobookshelf.config.get", return_value=""):
            assert client.is_configured() is False
