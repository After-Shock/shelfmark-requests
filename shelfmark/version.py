"""Resolve Shelfmark's semantic release version without app dependencies."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_DEFAULT_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"


def is_semantic_version(value: object) -> bool:
    return isinstance(value, str) and _SEMANTIC_VERSION.fullmatch(value.strip()) is not None


def read_version_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Unable to read release version from %s: %s", path, exc)
        return None

    if not is_semantic_version(value):
        logger.warning("Invalid release version in %s: %r", path, value)
        return None
    return value


def resolve_release_version(
    env_value: str | None,
    version_path: Path | None = None,
) -> str:
    if is_semantic_version(env_value):
        return env_value.strip()

    if env_value and env_value.strip() not in {"", "N/A"}:
        logger.warning("Invalid RELEASE_VERSION value: %r", env_value)

    file_version = read_version_file(version_path or _DEFAULT_VERSION_PATH)
    return file_version or "N/A"
