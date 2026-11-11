# Pre-release view-only permission audit

Regular users can view all pre-release items. Editing status/release dates, activation, denial, retry and removal remain unavailable to them; admin controls are retained. The original requester has the same pre-release restrictions as other regular users.

The existing UI already guarded row controls with isAdmin, and the existing API rejected mutations. Hid the unrelated Clear Completed footer action on the regular-user Pre-release tab to make the entire tab view-only.

Validation:
- Confirmed the new UI regression test failed on Clear Completed before applying the rendering condition.
- 53 request route tests passed, including 16 new owner/other-user permission cases across eight mutation endpoints with unchanged-row assertions.
- 23 frontend tests passed; TypeScript/Vite production build passed.
- Independent focused review passed.
- Isolated production-database-copy smoke check passed for all 30 regular-user sessions: read access succeeds, eight mutation endpoints reject changes, request remains unchanged, and no messages/downloads are sent.
- Rollback image: shelfmark-dev:before-prerelease-view-only-20261111.

Deployment:
- Deployed implementation commit cdc0a4c; production serves the tested index-Bu-f8NuN.js bundle.
- Confirmed configured authentication is builtin, with authenticated admin-role checks active.
- Re-ran the 30-session/eight-endpoint permission audit against an isolated database copy inside the new image; passed.
- Container healthy and /api/health reports ok.
