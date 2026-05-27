from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HTTP_MODULE = ROOT / "shelfmark" / "download" / "http.py"
BYPASSER_MODULE = ROOT / "shelfmark" / "bypass" / "internal_bypasser.py"


def test_hotfix_modules_compile_cleanly():
    py_compile.compile(str(HTTP_MODULE), doraise=True)
    py_compile.compile(str(BYPASSER_MODULE), doraise=True)


def test_http_module_keeps_runtime_annotation_imports():
    source = HTTP_MODULE.read_text(encoding="utf-8")

    assert "from collections.abc import Callable" in source
    assert "from types import ModuleType" in source
    assert "except (ValueError, IndexError)" in source
    assert "from typing import TYPE_CHECKING" not in source


def test_internal_bypasser_uses_timezone_utc_for_py310_compatibility():
    source = BYPASSER_MODULE.read_text(encoding="utf-8")

    assert "from datetime import datetime, timezone" in source
    assert "datetime.now(timezone.utc)" in source
    assert "from datetime import UTC, datetime" not in source
