# Project Versioning and Footer Display Design

**Date:** 2026-07-15

## Goal

Establish explicit semantic versioning for Shelfmark Requests and display the running release version at the bottom of the authenticated home screen.

The first explicit version is `1.6.0`.

## Current State

The project currently has several partially connected version mechanisms:

- `pyproject.toml` declares `version = "1.06"`;
- `shelfmark/config/env.py` exposes `BUILD_VERSION` and `RELEASE_VERSION`, both defaulting to `N/A`;
- `/api/config` already returns `build_version` and `release_version`;
- the frontend `AppConfig` type already contains both fields;
- the existing footer displays `Sullyflix Inc` and an optional admin debug badge, but no version.

There is no documented source of truth or release-tag workflow.

## Version Source of Truth

Add a root `VERSION` text file containing exactly:

```text
1.6.0
```

`VERSION` is the human-maintained release source of truth. It uses semantic versioning in `major.minor.patch` form.

Normalize `pyproject.toml` to `version = "1.6.0"`. The release checklist requires `VERSION` and `pyproject.toml` to be updated together. Automated release tooling is deliberately out of scope for this first versioning change.

## Backend Resolution

Backend startup resolves the displayed release version in this order:

1. A valid non-placeholder `RELEASE_VERSION` environment variable.
2. A valid semantic version read from the root `VERSION` file.
3. The string `N/A` when neither source is available or valid.

An explicit deployment environment value remains authoritative so packaged or CI-produced releases can identify themselves without rewriting source files.

`BUILD_VERSION` remains unchanged and continues representing build-specific metadata when supplied.

The version loader validates `major.minor.patch` numeric syntax. Reading or validation errors are logged at an appropriate level and do not prevent application startup.

## API Data Flow

No new endpoint is added.

The existing authenticated `GET /api/config` response continues returning:

```json
{
  "build_version": "...",
  "release_version": "1.6.0"
}
```

The existing frontend `AppConfig.release_version` field remains the typed consumer. Authentication behavior for `/api/config` is unchanged.

## Footer Display

Extend the existing `Footer` component with an optional `version` prop.

When `version` is a valid display value, render one compact centered line:

```text
Sullyflix Inc · v1.6.0
```

The version uses the footer's existing subtle typography and does not become a link or interactive control.

When the version is empty, malformed, or `N/A`, render only:

```text
Sullyflix Inc
```

The existing admin-only Debug badge remains unchanged and appears after the company/version text.

`App.tsx` passes `config?.release_version` to `Footer`. The version therefore appears on the authenticated home screen wherever the current footer is rendered, without adding another network request.

## Release Workflow

For each release:

1. Select the next semantic version according to the change scope.
2. Update the root `VERSION` file.
3. Update `pyproject.toml` to the same value.
4. Run backend tests, frontend typecheck/tests, and the production build.
5. Commit the release changes.
6. Create a matching annotated Git tag such as `v1.6.0`.
7. Build and deploy from that tagged commit.

Patch releases increment the third number, compatible feature releases increment the second, and breaking releases increment the first.

This design documents the tag workflow but does not create tags automatically. Tag creation remains an explicit outward-facing release action requiring user approval.

## Error Handling

- Missing `VERSION`: use a valid `RELEASE_VERSION`, otherwise return `N/A`.
- Malformed `VERSION`: log the invalid value and return `N/A` unless a valid environment override exists.
- Malformed `RELEASE_VERSION`: ignore it and try `VERSION`.
- Frontend receives `N/A`: omit the version from the footer.
- Config fetch failure: preserve the existing application behavior; the footer renders without a version until configuration is available.

## Testing

### Backend

- reads `1.6.0` from `VERSION` when no environment override exists;
- prefers a valid `RELEASE_VERSION` environment value;
- rejects malformed environment values and falls back to `VERSION`;
- returns `N/A` for missing or malformed sources;
- confirms `/api/config` exposes the resolved release version;
- confirms application startup is not blocked by a read error.

### Frontend

- renders `Sullyflix Inc · v1.6.0` for a valid version;
- renders only `Sullyflix Inc` for `undefined`, empty, malformed, or `N/A` values;
- preserves the admin Debug badge;
- passes strict TypeScript checking and the production Vite build.

### Deployment Verification

After rebuilding the container, confirm `/api/config` reports `1.6.0` and the authenticated home-screen footer displays `Sullyflix Inc · v1.6.0`.

## Out of Scope

- automatic version bumping;
- automatic Git tag creation or pushing;
- changelog generation;
- update-available checks;
- displaying commit hashes or dirty-worktree state;
- changing login, setup, or registration page footers;
- changing `BUILD_VERSION` semantics.
