# When a task is done

Run what the change touched; there is no monorepo-wide single gate.

- dialectic backend: `cd dialectic && python3 -m pytest tests/ -q` (~790 tests, should be green).
- trading backend: `cd trading && python3 -m pytest -q` (collect-only baseline ~1359).
- dialectic frontend: `cd dialectic/frontend/app && npm run lint && npm run build` (build runs `tsc -b`, which is the type check).
- trading frontend: `cd trading/frontend && npm run lint && npm run test && npm run build`.
- Schema changes: update numbered migration in `dialectic/migrations/` AND `dialectic/schema.sql` baseline together.
- "Ready to commit/push/ship" from the user means run the full pre-flight (lint/build/tests) and fix failures first — verified-clean, not just staged.
- If the change is backend code for a running service, completion includes the deploy step — see `mem:deploy` (services run their working trees; tests passing ≠ deployed).
