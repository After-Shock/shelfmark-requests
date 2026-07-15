# Project Versioning and Footer Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish `1.6.0` as the explicit Shelfmark Requests release version and display `Sullyflix Inc · v1.6.0` in the authenticated home-screen footer.

**Architecture:** A root `VERSION` file is the human-maintained source of truth, synchronized with Python and private frontend package metadata. A small stdlib-only backend module validates and resolves `RELEASE_VERSION` environment overrides before falling back to `VERSION`; the existing `/api/config` payload carries the resolved value to the existing React footer.

**Tech Stack:** Python 3, Flask, pytest, React, TypeScript, Vite, Vitest, Docker, Git annotated tags.

## Global Constraints

- Execute this plan only after the ongoing duplicate-request plan has completed its frontend Task 6, so this work consumes the installed Vitest setup and does not race on `App.tsx`, `package.json`, or `package-lock.json`.
- Preserve all existing uncommitted changes; never reset, checkout, or overwrite files wholesale.
- The initial release version is exactly `1.6.0`.
- The root `VERSION`, `pyproject.toml`, `src/frontend/package.json`, and `src/frontend/package-lock.json` must contain the same release version.
- `RELEASE_VERSION` is authoritative only when it is a valid numeric `major.minor.patch` value; otherwise fall back to `VERSION`.
- `BUILD_VERSION` behavior remains unchanged.
- Missing `VERSION` files fall back silently; unreadable files and malformed values log a warning and must not prevent startup.
- The authenticated footer text is exactly `Sullyflix Inc · v1.6.0` for a valid version and exactly `Sullyflix Inc` when the value is absent, malformed, or `N/A`.
- Preserve the existing admin-only Debug badge after the company/version text.
- Do not add a new API endpoint or network request; use the existing `/api/config` and `AppConfig.release_version` data flow.
- Creating or pushing a Git tag is an outward-facing release action and requires a separate user confirmation after implementation and deployment verification.
- Run `src/frontend/node_modules/.bin/tsc --noEmit` before every frontend commit.

## File Structure

- Create `VERSION` — canonical human-maintained semantic version text.
- Create `shelfmark/version.py` — stdlib-only validation, file reading, and environment/file resolution.
- Modify `shelfmark/config/env.py` — consume `resolve_release_version` while retaining current build metadata behavior.
- Modify `pyproject.toml` — normalize Python package metadata to `1.6.0`.
- Modify `src/frontend/package.json` and `src/frontend/package-lock.json` — normalize private frontend package metadata to `1.6.0`; retain Vitest added by duplicate-request work.
- Create `tests/test_version.py` — pure version resolution tests.
- Modify `tests/e2e/test_api.py` — assert the existing config endpoint exposes a valid release version.
- Modify `src/frontend/src/components/Footer.tsx` — optional version prop and validated display.
- Create `src/frontend/src/components/Footer.test.tsx` — footer rendering tests using the already-installed Vitest environment.
- Modify `src/frontend/src/App.tsx` — pass `config?.release_version` to `Footer` without altering concurrent duplicate-request outcome changes.
- Modify `readme.md` — document the manual semantic release checklist.

---

### Task 1: Add the Canonical Version Source and Backend Resolver

**Files:**
- Create: `VERSION`
- Create: `shelfmark/version.py`
- Modify: `shelfmark/config/env.py:1-8,154-160`
- Modify: `pyproject.toml:1-4`
- Modify: `src/frontend/package.json:1-6`
- Modify: `src/frontend/package-lock.json:1-20`
- Create: `tests/test_version.py`

**Interfaces:**
- Produces: `is_semantic_version(value: object) -> bool`.
- Produces: `read_version_file(path: Path) -> str | None`.
- Produces: `resolve_release_version(env_value: str | None, version_path: Path | None = None) -> str`.
- Changes: `shelfmark.config.env.RELEASE_VERSION` uses `resolve_release_version(os.getenv("RELEASE_VERSION"))`.
- Preserves: `BUILD_VERSION = os.getenv("BUILD_VERSION", "N/A")`.

- [ ] **Step 1: Write failing pure resolver tests**

```python
# tests/test_version.py
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


def test_unreadable_version_file_does_not_raise(tmp_path: Path, monkeypatch, caplog):
    version_file = tmp_path / "VERSION"
    version_file.write_text("1.6.0", encoding="utf-8")

    def fail_read_text(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    assert resolve_release_version(None, version_file) == "N/A"
    assert "Unable to read release version" in caplog.text
```

- [ ] **Step 2: Run the resolver tests and verify failure**

Run: `python3 -m pytest tests/test_version.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'shelfmark.version'`.

- [ ] **Step 3: Create the version source and stdlib-only resolver**

```text
# VERSION
1.6.0
```

```python
# shelfmark/version.py
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
```

- [ ] **Step 4: Wire the resolver into bootstrap environment metadata**

```python
# shelfmark/config/env.py
from shelfmark.version import resolve_release_version
```

```python
BUILD_VERSION = os.getenv("BUILD_VERSION", "N/A")
RELEASE_VERSION = resolve_release_version(os.getenv("RELEASE_VERSION"))
```

The new module imports only Python standard-library modules, so `env.py` remains safe as an early bootstrap import.

- [ ] **Step 5: Normalize all package metadata**

Set these exact values:

```toml
# pyproject.toml
version = "1.6.0"
```

```json
// src/frontend/package.json
"version": "1.6.0"
```

Update both top-level version fields in `src/frontend/package-lock.json` to `1.6.0` without changing dependency versions or removing Vitest.

- [ ] **Step 6: Add a metadata synchronization test**

```python
# append to tests/test_version.py
import json
import re


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
```

- [ ] **Step 7: Run backend resolver tests and frontend metadata checks**

Run: `python3 -m pytest tests/test_version.py -v`

Run: `src/frontend/node_modules/.bin/tsc --noEmit`

Expected: resolver tests PASS and TypeScript reports no errors.

- [ ] **Step 8: Commit the canonical version source**

```bash
git add VERSION shelfmark/version.py shelfmark/config/env.py tests/test_version.py \
  pyproject.toml src/frontend/package.json src/frontend/package-lock.json
git commit -m "feat: establish project version 1.6.0"
```

---

### Task 2: Expose and Render the Release Version

**Files:**
- Modify: `tests/e2e/test_api.py:57-84`
- Modify: `src/frontend/src/components/Footer.tsx`
- Create: `src/frontend/src/components/Footer.test.tsx`
- Modify: `src/frontend/src/App.tsx:1039-1045`

**Interfaces:**
- Consumes: `AppConfig.release_version: string`, already returned by `/api/config`.
- Produces: `FooterProps.version?: string`.
- Produces: `formatFooterVersion(version?: string) -> string | null` for testable validation and display formatting.
- Preserves: `FooterProps.debug`, `FooterProps.isAdmin`, and admin-only Debug badge behavior.

- [ ] **Step 1: Extend the existing config endpoint E2E assertion**

```python
# tests/e2e/test_api.py, TestConfigEndpoint

def test_config_returns_release_version(self, api_client: APIClient):
    resp = api_client.get("/api/config")
    _skip_if_protected(api_client, resp)

    assert resp.status_code == 200
    data = resp.json()
    assert data["release_version"] == "1.6.0"
```

- [ ] **Step 2: Write failing footer formatter and rendering tests**

```tsx
// src/frontend/src/components/Footer.test.tsx
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Footer, formatFooterVersion } from './Footer';

describe('formatFooterVersion', () => {
  it('formats a semantic version', () => {
    expect(formatFooterVersion('1.6.0')).toBe('v1.6.0');
  });

  it.each([undefined, '', 'N/A', '1.06', 'v1.6.0'])('hides invalid value %s', (value) => {
    expect(formatFooterVersion(value)).toBeNull();
  });
});

describe('Footer', () => {
  it('renders the company and release version', () => {
    const html = renderToStaticMarkup(<Footer version="1.6.0" />);
    expect(html).toContain('Sullyflix Inc');
    expect(html).toContain('·');
    expect(html).toContain('v1.6.0');
  });

  it('omits the separator and version when unavailable', () => {
    const html = renderToStaticMarkup(<Footer version="N/A" />);
    expect(html).toContain('Sullyflix Inc');
    expect(html).not.toContain('·');
    expect(html).not.toContain('vN/A');
  });

  it('preserves the admin debug badge', () => {
    const html = renderToStaticMarkup(<Footer version="1.6.0" debug isAdmin />);
    expect(html).toContain('Debug');
  });
});
```

- [ ] **Step 3: Run the footer tests and verify failure**

Run: `src/frontend/node_modules/.bin/vitest run src/components/Footer.test.tsx`

Expected: FAIL because `Footer` has no `version` prop and `formatFooterVersion` does not exist.

- [ ] **Step 4: Add footer version formatting and rendering**

```tsx
// src/frontend/src/components/Footer.tsx
interface FooterProps {
  debug?: boolean;
  isAdmin?: boolean;
  version?: string;
}

const SEMANTIC_VERSION = /^[0-9]+\.[0-9]+\.[0-9]+$/;

export const formatFooterVersion = (version?: string): string | null => {
  const normalized = version?.trim();
  return normalized && SEMANTIC_VERSION.test(normalized) ? `v${normalized}` : null;
};

export const Footer = ({ debug, isAdmin, version }: FooterProps) => {
  const displayVersion = formatFooterVersion(version);
  return (
    <footer
      className="mt-8 py-4"
      style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-baseline justify-center gap-2">
        <span className="text-sm font-medium opacity-70">
          Sullyflix Inc{displayVersion && <> · {displayVersion}</>}
        </span>
        {debug && isAdmin && (
          <span className="text-xs px-1.5 py-0.5 rounded opacity-60" style={{ background: 'var(--border-muted)' }}>
            Debug
          </span>
        )}
      </div>
    </footer>
  );
};
```

- [ ] **Step 5: Pass the existing config value from App**

Modify only the existing footer invocation and preserve duplicate-request changes elsewhere in `App.tsx`:

```tsx
<Footer
  debug={config?.debug}
  isAdmin={isAdmin}
  version={config?.release_version}
/>
```

- [ ] **Step 6: Run frontend tests, strict typecheck, and build**

Run: `src/frontend/node_modules/.bin/vitest run src/components/Footer.test.tsx`

Run: `src/frontend/node_modules/.bin/tsc --noEmit`

Run: `src/frontend/node_modules/.bin/vite build`

Expected: all PASS.

- [ ] **Step 7: Run the config endpoint E2E test in the application test container**

Run: `docker exec shelfmark python3 -m pytest tests/e2e/test_api.py::TestConfigEndpoint -v`

Expected: PASS when the container image includes `VERSION=1.6.0`. If the running container does not include the new source yet, defer this command until Task 3 rebuilds it and record that deferral in the task report.

- [ ] **Step 8: Commit footer rendering**

```bash
git add tests/e2e/test_api.py src/frontend/src/components/Footer.tsx \
  src/frontend/src/components/Footer.test.tsx src/frontend/src/App.tsx
git commit -m "feat: display project version in footer"
```

---

### Task 3: Document and Verify the Release Workflow

**Files:**
- Modify: `readme.md`
- Modify only implementation files required to fix observed verification failures.

**Interfaces:**
- Documents: manual semantic-version bump and tag checklist.
- Verifies: packaged runtime reads `/app/VERSION`, `/api/config` reports `1.6.0`, and the footer displays the expected text.

- [ ] **Step 1: Add the manual release checklist to the README**

Append this section near the development/deployment documentation:

```markdown
## Release Versioning

Shelfmark Requests uses semantic versions in `major.minor.patch` form. The root
`VERSION` file is the release source of truth. For every release:

1. Update `VERSION`.
2. Set the same value in `pyproject.toml`, `src/frontend/package.json`, and both
   root package version fields in `src/frontend/package-lock.json`.
3. Run backend tests, frontend tests, TypeScript checking, and the production build.
4. Commit the release changes.
5. After explicit approval, create an annotated tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
6. Build and deploy from the tagged commit.

`RELEASE_VERSION` can override the displayed release version in packaged builds,
but only when it contains a valid numeric semantic version.
```

- [ ] **Step 2: Run focused backend and frontend verification**

Run:

```bash
python3 -m pytest tests/test_version.py -v
src/frontend/node_modules/.bin/vitest run
src/frontend/node_modules/.bin/tsc --noEmit
src/frontend/node_modules/.bin/vite build
```

Expected: all PASS.

- [ ] **Step 3: Build and recreate the local container**

Run:

```bash
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d --force-recreate
```

Expected: the image builds successfully and container `shelfmark` starts on port `8084` with the root `VERSION` copied to `/app/VERSION` by the existing `COPY . .` instruction.

- [ ] **Step 4: Verify the runtime resolver inside the container**

Run:

```bash
docker exec shelfmark python3 -c \
  "from shelfmark.config.env import RELEASE_VERSION; print(RELEASE_VERSION)"
```

Expected output: `1.6.0` when no explicit valid `RELEASE_VERSION` override is supplied.

- [ ] **Step 5: Run the config endpoint E2E test after rebuild**

Run: `docker exec shelfmark python3 -m pytest tests/e2e/test_api.py::TestConfigEndpoint -v`

Expected: PASS, including `release_version == "1.6.0"`.

- [ ] **Step 6: Drive the authenticated home-screen footer**

Invoke the project `verify` skill. Sign in, load the home screen, scroll to the footer, and observe the exact visible text `Sullyflix Inc · v1.6.0`. Also verify the admin Debug badge still appears when debug mode is enabled for an admin.

- [ ] **Step 7: Commit documentation or verification fixes**

```bash
git add readme.md VERSION shelfmark/version.py shelfmark/config/env.py \
  tests/test_version.py tests/e2e/test_api.py pyproject.toml \
  src/frontend/package.json src/frontend/package-lock.json \
  src/frontend/src/components/Footer.tsx src/frontend/src/components/Footer.test.tsx \
  src/frontend/src/App.tsx
git commit -m "docs: document release version workflow"
```

Stage only files changed by this task. Skip the commit when `readme.md` was already committed with Task 3 and verification required no fixes.

---

### Task 4: Prepare the `v1.6.0` Release Tag Approval Gate

**Files:**
- No source files are modified by this task.

**Interfaces:**
- Consumes: a clean, tested commit whose four version declarations equal `1.6.0`.
- Produces only after explicit user approval: local annotated Git tag `v1.6.0`.

- [ ] **Step 1: Verify the release commit is clean and synchronized**

Run:

```bash
git status --short
python3 -m pytest tests/test_version.py -v
git tag --list 'v1.6.0'
```

Expected: no feature-related uncommitted changes, version tests PASS, and no existing `v1.6.0` tag.

- [ ] **Step 2: Present the release evidence and request approval**

Report the tested commit hash, successful build/runtime/footer evidence, and whether the working tree contains unrelated pre-existing changes. Ask the user whether to create the local annotated `v1.6.0` tag. Do not create or push a tag in the same turn as the approval request.

- [ ] **Step 3: Create the annotated tag only after approval**

Run only after the user explicitly approves:

```bash
git tag -a v1.6.0 -m "Release v1.6.0"
git show --no-patch --decorate v1.6.0
```

Expected: the tag points to the verified release commit.

- [ ] **Step 4: Request separate approval before pushing the tag**

Pushing publishes the release marker externally. Report the local tag and ask whether to run `git push origin v1.6.0`; do not push without that separate approval.
