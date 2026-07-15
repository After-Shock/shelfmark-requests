"""Tests for canonical Shelfmark release version resolution."""

import json
import re
from pathlib import Path

import pytest

from shelfmark.version import (
    is_semantic_version,
    read_version_file,
    resolve_release_version,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.6.0", True),
        ("0.1.2", True),
        ("1.06", False),
        ("v1.6.0", False),
        ("1.6", False),
        ("N/A", False),
        (None, False),
    ],
)
def test_is_semantic_version(value, expected):
    assert is_semantic_version(value) is expected


def test_resolve_release_version_prefers_valid_environment(tmp_path: Path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.6.0\n", encoding="utf-8")
    assert resolve_release_version("1.7.0", version_file) == "1.7.0"


def test_resolve_release_version_falls_back_from_invalid_environment(tmp_path: Path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.6.0\n", encoding="utf-8")
    assert resolve_release_version("N/A", version_file) == "1.6.0"


def test_read_version_file_returns_none_for_missing_file(tmp_path: Path):
    assert read_version_file(tmp_path / "missing") is None


def test_resolve_release_version_returns_na_for_malformed_file(tmp_path: Path, caplog):
    version_file = tmp_path / "VERSION"
    version_file.write_text("release-one", encoding="utf-8")
    assert resolve_release_version(None, version_file) == "N/A"
    assert "Invalid release version" in caplog.text


def test_invalid_utf8_version_file_does_not_raise(tmp_path: Path, caplog):
    version_file = tmp_path / "VERSION"
    version_file.write_bytes(b"\xff\xfe")

    assert resolve_release_version(None, version_file) == "N/A"
    assert "Unable to read release version" in caplog.text


def test_unreadable_version_file_does_not_raise(tmp_path: Path, monkeypatch, caplog):
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.6.0", encoding="utf-8")

    def fail_read_text(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    assert resolve_release_version(None, version_file) == "N/A"
    assert "Unable to read release version" in caplog.text


def test_package_metadata_matches_version_file():
    root = Path(__file__).resolve().parent.parent
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    pyproject_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    pyproject_version = re.search(
        r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE
    )
    package = json.loads((root / "src/frontend/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((root / "src/frontend/package-lock.json").read_text(encoding="utf-8"))

    assert version == "1.6.0"
    assert pyproject_version is not None
    assert pyproject_version.group(1) == version
    assert package["version"] == version
    assert package_lock["version"] == version
    assert package_lock["packages"][""]["version"] == version
