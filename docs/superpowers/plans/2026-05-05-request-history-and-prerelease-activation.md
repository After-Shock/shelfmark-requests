# Request History And Prerelease Activation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a request history section, allow admins to schedule prerelease returns for both ebooks and audiobooks, and reactivate due prerelease requests at 9:00 AM America/New_York using the existing notification path.

**Architecture:** Extend the existing `requests` table with a completion timestamp and keep prerelease scheduling on the request row via `expected_release_date`. Reuse the current Flask request routes and the prerelease background loop, and update the React request sidebar to separate active queues from historical items.

**Tech Stack:** Flask, SQLite, React, TypeScript, pytest, Vite

---

## Chunk 1: Backend Lifecycle

### Task 1: Add failing database and scheduler tests

**Files:**
- Modify: `tests/core/test_request_db.py`
- Modify: `tests/core/test_prerelease_requests.py`

- [ ] **Step 1: Write failing tests for completion timestamps and 9:00 AM activation**
- [ ] **Step 2: Run targeted pytest commands and confirm the failures are for missing behavior**
- [ ] **Step 3: Implement minimal database and scheduler changes**
- [ ] **Step 4: Re-run targeted pytest commands and confirm they pass**

### Task 2: Add failing route tests for history and admin prerelease scheduling

**Files:**
- Modify: `tests/core/test_request_routes.py`
- Modify: `tests/core/test_request_routes_prerelease.py`

- [ ] **Step 1: Write failing route tests for history filtering and prerelease scheduling metadata**
- [ ] **Step 2: Run targeted pytest commands and confirm the failures are for missing behavior**
- [ ] **Step 3: Implement minimal route changes**
- [ ] **Step 4: Re-run targeted pytest commands and confirm they pass**

## Chunk 2: Frontend Request Views

### Task 3: Add failing request sidebar and hook tests

**Files:**
- Modify: `src/frontend/src/components/RequestsSidebar.tsx`
- Modify: `src/frontend/src/hooks/useRequests.ts`
- Modify: `src/frontend/src/services/api.ts`
- Modify: `src/frontend/src/types/index.ts`
- Test: `src/frontend/src/components/__tests__/RequestsSidebar.test.tsx` or existing request UI test file if present

- [ ] **Step 1: Add failing tests for a separate History section and prerelease scheduling visibility**
- [ ] **Step 2: Run the frontend test/build command that exercises the affected code and confirm the failures**
- [ ] **Step 3: Implement the minimal UI and API updates**
- [ ] **Step 4: Re-run the frontend verification command and confirm it passes**

## Chunk 3: Integration And Deployment

### Task 4: Verify end-to-end request lifecycle behavior

**Files:**
- Modify only if verification exposes issues in the files above

- [ ] **Step 1: Run the combined backend and frontend verification commands**
- [ ] **Step 2: Review the git diff and confirm only intended files changed**
- [ ] **Step 3: Commit with a focused message**
- [ ] **Step 4: Push to the remote branch**
- [ ] **Step 5: Deploy the updated repo to `sullyflix-com` and restart the local production container**
- [ ] **Step 6: Run a production smoke check on the remote instance**
