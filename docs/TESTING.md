# Testing

## Phase 1 (done, 4 passed)

```bash
cd backend && python -m pytest tests -q
```

Covers: login + JWT, token encryption round-trip and that tokens never
appear in API responses, cross-folder publish blocked by mapping
validation, dashboard stats reflecting real DB rows, unauthenticated
dashboard rejected (401).

## Before production (master prompt, section 18 — not yet done)

1. One authorised Instagram account end-to-end.
2. Drive folder mapping. 3. Video detection. 4. Manual scheduling.
5. Automatic publishing. 6. Duplicate prevention. 7. Token expiration.
8. Invalid permissions. 9. Drive file deletion. 10. Network failure/retry.
11. Incorrect folder mapping. 12. Simultaneous jobs. 13. Daily reports.
14. Recovery after worker restart.

Then scale testing to 5, 10, 20 and finally 50 authorised accounts.
Each later phase adds its tests here and must pass before moving on.
