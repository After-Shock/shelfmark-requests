"""
Tests for signup account provisioning across services.

Covers:
- Calibre-Web (CWA) account creation via the mounted app.db
- The signup_provisioning dispatcher (service selection, enablement checks)
"""

import os
import sqlite3
import tempfile

import pytest

import shelfmark.core.cwa_user_sync as cwa_user_sync
import shelfmark.core.signup_provisioning as signup_provisioning

# Schema mirrors Calibre-Web's `user` table (subset, nullable extras included)
CWA_SCHEMA = """
CREATE TABLE user (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(64) NOT NULL,
    email VARCHAR(120),
    password VARCHAR(255),
    kindle_mail VARCHAR(120),
    locale VARCHAR(2),
    timezone VARCHAR(64),
    sidebar_view INTEGER,
    default_language VARCHAR(3),
    series_view VARCHAR(10),
    denied_tags VARCHAR,
    allowed_tags VARCHAR,
    denied_column_value VARCHAR,
    allowed_column_value VARCHAR,
    view_settings VARCHAR,
    kobo_only_shelves_sync SMALLINT,
    kobo_token VARCHAR(255),
    role SMALLINT
)
"""


@pytest.fixture
def cwa_db(tmp_path, monkeypatch):
    """A Calibre-Web app.db with one existing (admin) user, plus env wiring."""
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(CWA_SCHEMA)
    # A pre-existing CWA admin acts as the template row for new users.
    conn.execute(
        "INSERT INTO user (name, email, password, locale, default_language, sidebar_view, role) "
        "VALUES ('admin', 'admin@example.com', 'hashed', 'en', 'en', 63, 1)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("CWA_DB_PATH", str(db_path))

    import shelfmark.config.env as env

    monkeypatch.setattr(env, "CWA_DB_PATH", db_path)

    class FakeConfig:
        def __init__(self, values=None):
            self.values = values or {}

        def get(self, key, default=None):
            return self.values.get(key, default)

    monkeypatch.setattr(
        cwa_user_sync,
        "config",
        FakeConfig({"CWA_USER_SYNC_ENABLED": True}),
    )
    monkeypatch.setattr(signup_provisioning, "_get_config_for_test", FakeConfig, raising=False)
    yield db_path


def _get_user(conn, name):
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM user WHERE name = ?", (name,)).fetchone()


def test_provision_cwa_user_created(cwa_db):
    result = cwa_user_sync.provision_cwa_user("alice", "pw1234", email="alice@example.com")

    assert result["status"] == "created"
    conn = sqlite3.connect(cwa_db)
    row = conn.execute("SELECT name, email, password, role, sidebar_view FROM user WHERE name = 'alice'").fetchone()
    conn.close()
    assert row[0] == "alice"
    assert row[1] == "alice@example.com"
    # pbkdf2 hash format Calibre-Web can verify
    assert row[2].startswith("pbkdf2:sha256")
    assert row[3] == 0  # regular user, not admin
    # sidebar settings cloned from the template admin row
    assert row[4] == 63


def test_provision_cwa_user_admin_role(cwa_db):
    result = cwa_user_sync.provision_cwa_user("boss", "pw1234", role="admin")
    assert result["status"] == "created"
    conn = sqlite3.connect(cwa_db)
    role = conn.execute("SELECT role FROM user WHERE name = 'boss'").fetchone()[0]
    conn.close()
    assert role == 1


def test_provision_cwa_user_existing(cwa_db):
    first = cwa_user_sync.provision_cwa_user("alice", "pw1234")
    assert first["status"] == "created"
    second = cwa_user_sync.provision_cwa_user("alice", "different")
    assert second["status"] == "exists"
    conn = sqlite3.connect(cwa_db)
    count = conn.execute("SELECT COUNT(*) FROM user WHERE name = 'alice'").fetchone()[0]
    conn.close()
    assert count == 1


def test_provision_cwa_user_disabled(tmp_path, monkeypatch):
    import shelfmark.config.env as env

    monkeypatch.setattr(env, "CWA_DB_PATH", tmp_path / "app.db")

    class FakeConfig:
        def get(self, key, default=None):
            return False

    monkeypatch.setattr(cwa_user_sync, "config", FakeConfig)
    result = cwa_user_sync.provision_cwa_user("alice", "pw1234")
    assert result["status"] == "skipped"


def test_provision_cwa_user_no_db(tmp_path, monkeypatch):
    import shelfmark.config.env as env

    monkeypatch.setattr(env, "CWA_DB_PATH", tmp_path / "missing.db")

    class FakeConfig:
        def get(self, key, default=None):
            return True

    monkeypatch.setattr(cwa_user_sync, "config", FakeConfig)
    result = cwa_user_sync.provision_cwa_user("alice", "pw1234")
    assert result["status"] == "skipped"


def test_dispatcher_respects_selection(monkeypatch):
    """Only selected, enabled services are provisioned."""
    calls = []

    import shelfmark.core.abs_user_sync as abs_module
    import shelfmark.core.cwa_user_sync as cwa_module

    # The dispatcher imports these by attribute at call time, so patching the
    # module attributes works.
    monkeypatch.setattr(abs_module, "is_enabled", lambda: True)
    monkeypatch.setattr(
        abs_module,
        "provision_abs_user",
        lambda username, password, role="user": calls.append(("abs", username))
        or {"status": "created", "message": "ok"},
    )
    monkeypatch.setattr(cwa_module, "is_provisioning_enabled", lambda: True)
    monkeypatch.setattr(
        cwa_module,
        "provision_cwa_user",
        lambda username, password, email=None, role="user": calls.append(("cwa", username))
        or {"status": "created", "message": "ok"},
    )

    # Both selected -> both called
    results = signup_provisioning.provision_signup_accounts(
        "alice", "pw1234", services={"audiobookshelf": True, "calibre_web": True}
    )
    assert ("abs", "alice") in calls
    assert ("cwa", "alice") in calls
    assert signup_provisioning.get_warnings(results) == []

    # Only CWA selected -> only CWA called
    calls.clear()
    signup_provisioning.provision_signup_accounts(
        "bob", "pw1234", services={"audiobookshelf": False, "calibre_web": True}
    )
    assert calls == [("cwa", "bob")]


def test_get_warnings_includes_errors():
    results = {
        "audiobookshelf": {"status": "created", "message": "ok"},
        "calibre_web": {"status": "error", "message": "db not mounted"},
    }
    warnings = signup_provisioning.get_warnings(results)
    assert warnings == ["Calibre-Web: db not mounted"]


def test_normalize_service_selection():
    assert signup_provisioning.normalize_service_selection(None) == {
        "audiobookshelf": False,
        "calibre_web": False,
    }
    assert signup_provisioning.normalize_service_selection(["calibre_web"]) == {
        "audiobookshelf": False,
        "calibre_web": True,
    }
    assert signup_provisioning.normalize_service_selection({"audiobookshelf": False}) == {
        "audiobookshelf": False,
        "calibre_web": False,
    }

def test_all_services_provisions_everything(monkeypatch):
    """ALL_SERVICES is what callers with no per-service UI (admin create) pass."""
    calls = []

    import shelfmark.core.abs_user_sync as abs_module
    import shelfmark.core.cwa_user_sync as cwa_module

    monkeypatch.setattr(abs_module, "is_enabled", lambda: True)
    monkeypatch.setattr(
        abs_module,
        "provision_abs_user",
        lambda username, password, role="user": calls.append(("abs", username))
        or {"status": "created", "message": "ok"},
    )
    monkeypatch.setattr(cwa_module, "is_provisioning_enabled", lambda: True)
    monkeypatch.setattr(
        cwa_module,
        "provision_cwa_user",
        lambda username, password, email=None, role="user": calls.append(("cwa", username))
        or {"status": "created", "message": "ok"},
    )

    signup_provisioning.provision_signup_accounts(
        "carol", "pw1234", services=signup_provisioning.ALL_SERVICES
    )
    assert sorted(calls) == [("abs", "carol"), ("cwa", "carol")]


def test_set_password_writes_hash_and_syncs_both_services(monkeypatch):
    """Password changes must hit the local DB and both external services."""
    from werkzeug.security import check_password_hash

    import shelfmark.core.abs_user_sync as abs_module
    import shelfmark.core.cwa_user_sync as cwa_module

    synced = []
    monkeypatch.setattr(
        abs_module,
        "update_abs_password",
        lambda username, password: synced.append(("abs", username, password))
        or {"status": "updated", "message": "ok"},
    )
    monkeypatch.setattr(
        cwa_module,
        "update_cwa_password",
        lambda username, password: synced.append(("cwa", username, password))
        or {"status": "error", "message": "db not mounted"},
    )

    written = {}

    class FakeUserDB:
        def update_user(self, user_id, **fields):
            written.update({"id": user_id, **fields})

    results = signup_provisioning.set_password(
        FakeUserDB(),
        {"id": 7, "username": "dave", "provisioned_services": "audiobookshelf,calibre_web"},
        "newpw1234",
    )

    assert written["id"] == 7
    assert check_password_hash(written["password_hash"], "newpw1234")
    assert sorted(synced) == [
        ("abs", "dave", "newpw1234"),
        ("cwa", "dave", "newpw1234"),
    ]
    # A failing service surfaces as a warning, never as an exception.
    assert signup_provisioning.get_warnings(results) == ["Calibre-Web: db not mounted"]


def test_set_password_survives_a_throwing_service(monkeypatch):
    import shelfmark.core.abs_user_sync as abs_module
    import shelfmark.core.cwa_user_sync as cwa_module

    def boom(username, password):
        raise RuntimeError("ABS exploded")

    monkeypatch.setattr(abs_module, "update_abs_password", boom)
    monkeypatch.setattr(
        cwa_module,
        "update_cwa_password",
        lambda username, password: {"status": "updated", "message": "ok"},
    )

    class FakeUserDB:
        def update_user(self, user_id, **fields):
            pass

    results = signup_provisioning.set_password(
        FakeUserDB(),
        {"id": 1, "username": "erin", "provisioned_services": "audiobookshelf,calibre_web"},
        "newpw1234",
    )
    assert results["audiobookshelf"]["status"] == "error"
    assert results["calibre_web"]["status"] == "updated"


def test_normalize_service_selection_fails_closed():
    """A malformed payload must select nothing, never everything."""
    for junk in ("yes", 1, object()):
        assert signup_provisioning.normalize_service_selection(junk) == {
            "audiobookshelf": False,
            "calibre_web": False,
        }


def test_validate_signup_username():
    # Email-address usernames are a real pattern in production, so they stay legal.
    for ok in ("dave", "d_a-v.e", "a1", "katie.erb15@gmail.com", "d+tag@x.io", "x" * 64):
        assert signup_provisioning.validate_signup_username(ok) is None
    for bad in ("a", "x" * 65, "eve/../admin", "eve?x=1", "eve#1", "ev e", "ev\\e", ""):
        assert signup_provisioning.validate_signup_username(bad) is not None


def test_abs_lookup_url_encodes_username():
    """A '/' in a username must not change which ABS path is requested."""
    import shelfmark.core.abs_user_sync as abs_module

    assert abs_module._user_by_name_url("http://abs", "dave") == (
        "http://abs/api/users/username/dave"
    )
    assert abs_module._user_by_name_url("http://abs", "eve/../admin") == (
        "http://abs/api/users/username/eve%2F..%2Fadmin"
    )
    assert abs_module._user_by_name_url("http://abs", "eve?x=1") == (
        "http://abs/api/users/username/eve%3Fx%3D1"
    )


def _password_sync_spy(monkeypatch):
    """Patch both password updaters and return the list they append to."""
    import shelfmark.core.abs_user_sync as abs_module
    import shelfmark.core.cwa_user_sync as cwa_module

    synced = []
    monkeypatch.setattr(
        abs_module,
        "update_abs_password",
        lambda username, password: synced.append("abs") or {"status": "updated", "message": "ok"},
    )
    monkeypatch.setattr(
        cwa_module,
        "update_cwa_password",
        lambda username, password: synced.append("cwa") or {"status": "updated", "message": "ok"},
    )
    return synced


class _FakeUserDB:
    def __init__(self, user):
        self.user = dict(user)

    def get_user(self, user_id=None, username=None):
        return dict(self.user)

    def update_user(self, user_id, **fields):
        self.user.update(fields)


def test_set_password_leaves_unprovisioned_users_alone(monkeypatch):
    """A user who predates provisioning must never have external accounts touched."""
    synced = _password_sync_spy(monkeypatch)
    db = _FakeUserDB({"id": 3, "username": "legacy", "provisioned_services": None})

    results = signup_provisioning.set_password(db, db.user, "newpw1234")

    assert synced == []          # nothing reached Audiobookshelf or Calibre-Web
    assert results == {}
    assert db.user["password_hash"]  # the local password still changed


def test_set_password_only_touches_recorded_services(monkeypatch):
    """Provisioned for ABS only -> Calibre-Web is left alone."""
    synced = _password_sync_spy(monkeypatch)
    db = _FakeUserDB({"id": 4, "username": "abs-only", "provisioned_services": "audiobookshelf"})

    signup_provisioning.set_password(db, db.user, "newpw1234")

    assert synced == ["abs"]


def test_record_provisioned_services_ignores_pre_existing_accounts():
    """'exists' means we did not create it, so we must not claim ownership."""
    db = _FakeUserDB({"id": 5, "username": "carol", "provisioned_services": None})

    signup_provisioning.record_provisioned_services(db, 5, {
        "audiobookshelf": {"status": "created", "message": "ok"},
        "calibre_web": {"status": "exists", "message": "already there"},
    })
    assert db.user["provisioned_services"] == "audiobookshelf"

    # A later run that creates the other account merges, never replaces.
    signup_provisioning.record_provisioned_services(db, 5, {
        "calibre_web": {"status": "created", "message": "ok"},
    })
    assert db.user["provisioned_services"] == "audiobookshelf,calibre_web"


def test_record_provisioned_services_noop_when_nothing_created():
    db = _FakeUserDB({"id": 6, "username": "dan", "provisioned_services": None})
    signup_provisioning.record_provisioned_services(db, 6, {
        "audiobookshelf": {"status": "error", "message": "unreachable"},
        "calibre_web": {"status": "skipped", "message": "disabled"},
    })
    assert db.user["provisioned_services"] is None
