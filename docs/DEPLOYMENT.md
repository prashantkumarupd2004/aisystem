# Deployment (Phase 9)

## Before any deploy: readiness check

```bash
cp .env.production.example .env   # fill in real secrets, never commit it
python scripts/deploy_check.py --mode production --env-file .env
```

The check fails on blocking errors (missing/invalid
TOKEN_ENCRYPTION_KEY, default SECRET_KEY, non-Postgres
DATABASE_URL in production, non-HTTPS or localhost
PUBLIC_MEDIA_BASE_URL) and warns on missing OAuth credentials
(those connections simply cannot be completed until set) and on
ENABLE_SCHEDULER=true alongside a separate worker.

## Mode A — local bare metal (SQLite)

Backend on :8000, frontend on :3000, worker as a separate process:

```bash
cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
cd backend && .venv/bin/python -m app.worker &
cd frontend && npm install && npm run build && npm start
```

On a Linux VPS, use the systemd units in `deploy/` instead of
`&`: `aisystem-backend.service` and `aisystem-worker.service`
(edit the paths, `systemctl enable --now` both). On Windows, use a
scheduled task / startup script for the same two commands.

## Mode B — Docker Compose (recommended local / VPS)

Postgres + API + worker + frontend, one command:

```bash
cp .env.production.example .env   # fill in secrets
docker compose up --build
```

Backend http://localhost:8000, frontend http://localhost:3000.
Backend and worker share the `media_temp` volume (the worker
downloads a video, the API serves it to Meta from the same
directory). Do NOT set ENABLE_SCHEDULER=true in this stack --
the worker service already ticks. Docker is not installed on the
dev VM used to build this, so images were validated by syntax
and config checks, not by a local `docker build` -- run the
build once on your target host and fix any host-specific error
there; the Dockerfiles are standard python:3.12-slim /
node:20-alpine images.

## Mode C — hybrid cloud

- **Frontend on Vercel:** import the `frontend/` directory, set
  `NEXT_PUBLIC_API_URL` to your public backend URL, deploy.
  (This variable is baked in at build time, so changing the
  backend URL requires a rebuild.)
- **Backend + worker + Postgres on Railway or Render:** use
  `Procfile` (web + worker processes) or `render.yaml` (web +
  worker + database blueprint). Set DATABASE_URL from the
  managed Postgres, TOKEN_ENCRYPTION_KEY, SECRET_KEY, admin
  credentials, and PUBLIC_MEDIA_BASE_URL (stable HTTPS, ending
  in /media).
- **Database:** switching SQLite -> Postgres is a config change
  only (DATABASE_URL); models use no SQLite-specific features.
  Fresh cloud DBs are created by `create_all` on first start.
  Alembic migrations for existing production DBs are a Phase 10
  item -- do not run `create_all` against a DB that already has
  data from an older schema without a backup.
- **Always-on warning:** do NOT assume a free tier gives an
  always-on worker, persistent disk, or unlimited bandwidth. If
  the worker sleeps, scheduled publishes are missed, not queued
  forever. Keep Google Drive as the single video library.

## Cloudflare Tunnel (local testing only)

For local testing, a tunnel can expose localhost:8000 as a public
HTTPS media URL (see docs/PUBLISHING.md). Quick Tunnel URLs are
temporary and must NOT be used for production scheduling -- use a
named tunnel or a real domain with a stable URL instead.

## Backups

Back up Postgres (managed snapshots or `pg_dump`) and keep a copy
of TOKEN_ENCRYPTION_KEY offline: without it, encrypted OAuth
tokens in the DB cannot be decrypted after a move, and every
account must be reconnected.

## Cost / resource transparency

- Software: $0 (open-source stack).
- Meta Graph API: free tier, subject to Meta's rate limits/quotas.
- Google Drive: your existing storage quota.
- Hosting/bandwidth: whatever your host charges; video delivery
  is the dominant cost driver and scales with account count x
  video size.
