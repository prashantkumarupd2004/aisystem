# Testing (Phase 10, final)

```bash
cd backend && python -m pytest tests -q
cd frontend && npm run build
python scripts/security_check.py
python scripts/deploy_check.py --mode production --env-file .env
```

## Coverage by phase

- Phase 1 (4): login + JWT, token encryption round-trip and
  tokens never in API responses, cross-folder publish blocked,
  dashboard stats from real DB rows, unauthenticated 401.
- Phase 2 (10 total): Drive OAuth state/code exchange, folder
  sync dedup across pages, changes polling.
- Phase 3 (15): Meta OAuth, Page->IG discovery, ineligible
  skipped, upsert by IG id, health error mapping.
- Phase 4 (18): video validation, missing duration -> NEW,
  dedup by Drive id + md5, vanished -> NEEDS_REVIEW.
- Phase 5 (23): timezone conversion, bulk all-or-nothing,
  quota postponement, claim locking, retry backoff, recurrence.
- Phase 6 (28): media signing/Range/HEAD/traversal, container
  creation + polling, media_publish, temp cleanup, PERMANENT /
  UNCERTAIN never auto-retried.
- Phase 7 (37): classification, Retry-After, dead-letter,
  reconcile match/no-match, manual retry, bad-account skipping.
- Phase 8 (42): daily/range reports, CSV export, health summary,
  last-published recording, alerts not claiming unconfigured sends.
- Phase 9 (48): deploy_check rules, compose validity (worker
  service, shared media volume), Dockerfile/Procfile presence.
- Phase 10 (54): end-to-end video -> scheduled -> published ->
  report -> health chain, token-leak check, auth/admin role
  checks, login injection, media traversal/tampering,
  security_check script itself.

## Production checklist (master prompt, section 18)

Before connecting a real account, run these manually -- they are
NOT automated, because they need real Meta/Drive accounts:

1. One authorised Instagram account end-to-end.
2. Drive folder mapping. 3. Video detection. 4. Manual scheduling.
5. Automatic publishing. 6. Duplicate prevention. 7. Token expiration.
8. Invalid permissions. 9. Drive file deletion. 10. Network failure/retry.
11. Incorrect folder mapping. 12. Simultaneous jobs. 13. Daily reports.
14. Recovery after worker restart.

Then scale testing to 5, 10, 20 and finally 50 authorised accounts.

## Migrations

```bash
cd backend
alembic upgrade head      # fresh DB: creates all 15 tables
alembic downgrade base    # drops them (tested on SQLite)
alembic revision --autogenerate -m "description"  # after model changes
```

For an existing production DB, back it up first, then run
`alembic upgrade head` -- do not use `create_all` on a DB with
data from an older schema.
