"""Tests for duplicate active request prevention."""

import os
import tempfile

from shelfmark.core.request_db import RequestDB
from shelfmark.core.user_db import UserDB


def test_same_user_provider_request_matches_existing_title_author_without_provider():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "users.db")
        user_db = UserDB(db_path)
        user_db.initialize()
        user = user_db.create_user("alice", password_hash="hash")
        request_db = RequestDB(db_path)
        request_db.initialize()

        first, first_outcome = request_db.create_or_join_request(
            user_id=user["id"], title="Close to You", author="Nissa Renzo", content_type="ebook"
        )
        second, second_outcome = request_db.create_or_join_request(
            user_id=user["id"], title="Close to You", author="Nissa Renzo", content_type="ebook",
            provider="googlebooks", provider_id="v3UQ0gEACAAJ"
        )

        assert first_outcome == "created"
        assert second_outcome == "already_joined"
        assert second["id"] == first["id"]
        assert request_db.count_requests(user_id=user["id"]) == 1
