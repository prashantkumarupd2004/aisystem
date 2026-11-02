# Security (Phase 10, final)

## Threat model

The system holds OAuth tokens for up to ~50 Instagram accounts and
one Google Drive account. A leak of those tokens would let an
attacker publish as those accounts. The controls below are the
whole defence; there is no "security through obscurity" claim.

## Controls (all implemented and tested)

- Admin passwords: bcrypt (72-byte cap enforced, not silently
  truncated). First admin only from ADMIN_EMAIL/ADMIN_PASSWORD.
- Instagram/Google tokens: Fernet-encrypted at rest
  (`access_token_encrypted`); plain tokens are accepted once over
  the API, encrypted immediately, and never returned in any
  response, log or dashboard (test_phase10 checks this with a
  known token value, and test_phase1 checks the encrypted value
  is not the plain value).
- No Instagram passwords are ever requested or stored (OAuth only).
- JWT (HS256, 8h default) for API auth; admin-only routes check
  role (test_phase10: viewer role gets 401/403 on admin routes,
  and every protected route returns 401 without a token).
- Signed media URLs: short-lived JWT, path-traversal rejected,
  tampered token -> 404, Drive tokens never exposed in the URL.
  Test_phase10 checks traversal and tampering return 404, never
  a file.
- SQL injection: all queries are SQLAlchemy ORM (parameterised);
  test_phase10 checks a classic `' OR '1'='1` login fails with 401.
- CORS restricted to CORS_ORIGINS (default localhost:3000).
- Audit log: login, account create/disconnect, mapping
  create/change.
- Static check: `python scripts/security_check.py` fails if a
  response schema exposes an encrypted token, if a router returns
  one, if a Fernet-looking key is hard-coded in source, or if a
  filled .env is committed. Run it in CI / before release.
- Production gate: `python scripts/deploy_check.py --mode
  production` blocks a default SECRET_KEY, a missing/invalid
  encryption key, a non-Postgres DB, or a non-HTTPS media URL.

## Backups and key loss

- SQLite file in `backend/data/` (copy it); PostgreSQL in cloud
  mode -- schedule `pg_dump` externally.
- If TOKEN_ENCRYPTION_KEY is lost, every stored OAuth token is
  unrecoverable and every account must be reconnected. Keep the
  key offline, separate from the DB backup.
- Never commit `.env`, tokens, or `backend/data/` (all in
  `.gitignore`).

## Known limits (honest)

- No rate limiting on the login endpoint yet (add a reverse-proxy
  limit in front of a public deployment).
- No 2FA for the admin account yet (rely on a strong admin
  password + HTTPS in production).
- Alembic migrations cover the schema; data migrations for
  existing production rows still need a manual review per release.
