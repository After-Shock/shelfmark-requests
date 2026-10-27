"""Ebook requests check the Calibre library (metadata.db) for the book."""

import sqlite3

import shelfmark.core.calibre_library as calibre_library


def _library(tmp_path, books):
    db = tmp_path / "metadata.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT);"
        "CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE books_authors_link (book INTEGER, author INTEGER);"
    )
    for i, (title, authors) in enumerate(books, 1):
        conn.execute("INSERT INTO books VALUES (?, ?)", (i, title))
        for name in authors:
            cur = conn.execute("INSERT INTO authors (name) VALUES (?)", (name,))
            conn.execute("INSERT INTO books_authors_link VALUES (?, ?)", (i, cur.lastrowid))
    conn.commit()
    conn.close()
    return str(db)


def test_find_match(tmp_path, monkeypatch):
    path = _library(tmp_path, [
        ("Daggermouth: A Dark Dystopian Romance", ["H. M. Wolfe"]),
        ("Dune", ["Frank Herbert"]),
    ])
    monkeypatch.setenv("CALIBRE_LIBRARY_DB_PATH", path)

    assert calibre_library.find_match("Daggermouth", "H.M. Wolfe")["title"].startswith("Daggermouth")
    assert calibre_library.find_match("dune", "")["title"] == "Dune"
    assert calibre_library.find_match("Dune", "Someone Else") is None
    assert calibre_library.find_match("Dune Messiah", "Frank Herbert") is None


def test_no_library_mounted_means_no_match(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRE_LIBRARY_DB_PATH", str(tmp_path / "missing.db"))
    assert calibre_library.find_match("Dune", "Frank Herbert") is None
