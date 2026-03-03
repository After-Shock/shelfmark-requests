# tests/core/test_request_routes_abs.py
"""Test the ABS submission guard in create_request_route."""
import json
from unittest.mock import MagicMock, patch
import pytest


def _make_app(request_db, user_db):
    from flask import Flask
    from shelfmark.core.request_routes import register_request_routes
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test'
    with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'):
        register_request_routes(app, request_db, user_db)
    return app


@pytest.fixture
def app():
    request_db = MagicMock()
    request_db.list_requests.return_value = []
    request_db.create_request.return_value = {
        "id": 1, "title": "The Hobbit", "status": "pending",
        "content_type": "audiobook", "author": "Tolkien",
        "user_id": 1,
    }
    user_db = MagicMock()
    user_db.get_user.return_value = {"id": 1, "username": "testuser"}
    return _make_app(request_db, user_db)


class TestAbsSubmissionGuard:
    def test_audiobook_request_blocked_when_in_abs(self, app):
        match = {"id": "abs1", "title": "The Hobbit", "author": "Tolkien"}
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match', return_value=match):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                })
        assert resp.status_code == 409
        data = json.loads(resp.data)
        assert 'Already in your Audiobookshelf' in data['error']
        assert data['abs_match']['title'] == 'The Hobbit'

    def test_audiobook_request_allowed_when_not_in_abs(self, app):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match', return_value=None):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                })
        assert resp.status_code == 201

    def test_ebook_request_skips_abs_check(self, app):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match') as mock_find:
                resp = client.post('/api/requests', json={
                    'title': 'Some Ebook',
                    'author': 'Author',
                    'content_type': 'ebook',
                })
        mock_find.assert_not_called()


class TestAlternateVersionFlag:
    """Tests for prefer_alternate_version flag behavior with ABS check."""

    def test_alternate_version_flag_bypasses_abs_block(self, app):
        """When prefer_alternate_version=True and ABS has a match, request is created with a warning."""
        match = {"id": "abs1", "title": "The Hobbit", "author": "Tolkien"}
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match', return_value=match):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                    'prefer_alternate_version': True,
                })
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert 'warning' in data
        assert 'already in library' in data['warning'].lower()

    def test_alternate_version_flag_false_still_blocks(self, app):
        """When prefer_alternate_version=False (default), ABS match still returns 409."""
        match = {"id": "abs1", "title": "The Hobbit", "author": "Tolkien"}
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match', return_value=match):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                    'prefer_alternate_version': False,
                })
        assert resp.status_code == 409

    def test_prefer_alternate_version_stored_on_request(self, app):
        """prefer_alternate_version=True is passed through without ABS match."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 'testuser'
                sess['db_user_id'] = 1
                sess['is_admin'] = False
            with patch('shelfmark.core.request_routes._get_auth_mode', return_value='builtin'), \
                 patch('shelfmark.core.request_routes.abs_client.find_match', return_value=None):
                resp = client.post('/api/requests', json={
                    'title': 'The Hobbit',
                    'author': 'Tolkien',
                    'content_type': 'audiobook',
                    'prefer_alternate_version': True,
                })
        assert resp.status_code == 201
        # No warning when ABS has no match
        data = json.loads(resp.data)
        assert 'warning' not in data
