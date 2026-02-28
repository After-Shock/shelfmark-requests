"""Tests for ABS API routes."""
import json
from unittest.mock import patch
import pytest


@pytest.fixture
def app():
    """Create a minimal Flask test app with ABS routes registered."""
    from flask import Flask
    from shelfmark.core.abs_routes import register_abs_routes
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test'
    register_abs_routes(app)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestAbsCheck:
    def test_returns_not_owned_when_no_match(self, client):
        with patch('shelfmark.core.abs_routes.abs_client.find_match', return_value=None):
            resp = client.get('/api/abs/check?title=The+Hobbit&author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is False
        assert data['match'] is None

    def test_returns_owned_when_match_found(self, client):
        match = {'id': '1', 'title': 'The Hobbit', 'author': 'Tolkien'}
        with patch('shelfmark.core.abs_routes.abs_client.find_match', return_value=match):
            resp = client.get('/api/abs/check?title=The+Hobbit&author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is True
        assert data['match']['title'] == 'The Hobbit'

    def test_returns_not_owned_when_no_title(self, client):
        resp = client.get('/api/abs/check?author=Tolkien')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['owned'] is False


class TestAbsRefresh:
    def test_refresh_returns_count(self, client):
        with patch('shelfmark.core.abs_routes.abs_client.refresh', return_value=42):
            resp = client.post('/api/abs/refresh')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['ok'] is True
        assert data['count'] == 42

    def test_refresh_requires_admin(self, client):
        with patch('shelfmark.core.abs_routes._get_auth_mode', return_value='none'), \
             patch('shelfmark.core.abs_routes.abs_client.refresh', return_value=0):
            resp = client.post('/api/abs/refresh')
        assert resp.status_code == 200
