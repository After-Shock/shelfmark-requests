"""Send-to-Kindle sender address read from Calibre-Web's app.db."""

import sqlite3

import shelfmark.core.cwa_user_sync as cwa


def test_get_cwa_mail_from(tmp_path, monkeypatch):
    db = tmp_path / "app.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE settings (mail_from TEXT)")
    conn.execute("INSERT INTO settings VALUES (' admin@example.com ')")
    conn.commit()
    monkeypatch.setattr(cwa, "_get_cwa_db_path", lambda: str(db))
    assert cwa.get_cwa_mail_from() == "admin@example.com"

    conn.execute("UPDATE settings SET mail_from = NULL")
    conn.commit()
    conn.close()
    assert cwa.get_cwa_mail_from() is None

    monkeypatch.setattr(cwa, "_get_cwa_db_path", lambda: None)
    assert cwa.get_cwa_mail_from() is None
