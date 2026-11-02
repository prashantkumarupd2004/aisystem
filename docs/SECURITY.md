# Security

- Admin passwords: bcrypt (72-byte cap enforced, not silently truncated).
- Instagram/Google tokens: Fernet-encrypted at rest (`access_token_encrypted`);
  plain tokens are accepted once over the API, encrypted immediately, and
  never returned in any response, log or dashboard.
- No Instagram passwords are ever requested or stored (OAuth only, Phase 3).
- JWT (HS256, 8h default) for API auth; admin-only routes check role.
- CORS is restricted to `CORS_ORIGINS` (default localhost:3000).
- Audit log: login, account create/disconnect, mapping create/change.
- Temporary media URLs (Phase 6) will be short-lived and signed, will
  never expose Drive OAuth tokens, and local files are cleaned up after
  processing.
- Backups: SQLite file in `backend/data/` (copy it); PostgreSQL in cloud
  mode — schedule `pg_dump` externally. This repo contains no backup
  automation yet (Phase 9).
- Never commit `.env`, tokens, or `backend/data/` (all in `.gitignore`).
