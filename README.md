# Multi-Account Instagram Reels Automation Agent — Phase 1

Centralised web platform to manage ~50 Instagram Professional accounts
from one dashboard, with one central Google Drive library, strict
account→folder isolation, scheduling and official Meta API publishing.

> **Phase 7 status: Retry engine + duplicate protection, working.**
> Phases 1-6 are done, plus formal error classification (TEMPORARY /
> RATE_LIMIT / QUOTA / PERMANENT / TOKEN_EXPIRED / PERMISSION_REVOKED
> / UNCERTAIN), Retry-After-aware backoff, dead-letter queue with
> admin notifications, account health flips on token/permission
> failures, and manual reconciliation for UNCERTAIN jobs (check
> Instagram before any retry) plus manual retry. A job that flips
> an account to TOKEN_EXPIRED no longer fails that account's other
> jobs in the same tick -- they stay SCHEDULED for after a
> reconnect. See docs/ERROR_HANDLING.md. Live publishing still
> needs the external Meta/Drive/HTTPS setup from Phase 6.

## Non-negotiable rule

A video in Drive folder `XYZ` is eligible **only** for the Instagram
account mapped to `XYZ`. Every publish path re-checks
`video.drive_folder_id == mapping.drive_folder_id` and
`video.instagram_account_id == account.id` before publishing
(`backend/app/services/mapping.py`). A mismatch stops the job.

API connectivity is **not** treated as proof an account is unsuspended:
health status defaults to `UNKNOWN` / `NEEDS_MANUAL_REVIEW` unless an
authorised API check says otherwise (Phase 8).

## Quick start (local)

```bash
# Backend (Python 3.11+)
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env   # then edit SECRET_KEY, TOKEN_ENCRYPTION_KEY, ADMIN_*
uvicorn app.main:app --reload --port 8000

# Frontend (Node 20+), in another terminal
cd frontend
npm install
npm run dev   # http://localhost:3000, API at http://localhost:8000
```

Generate a Fernet key for `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The first admin is created on backend startup **only** from
`ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`. There is no hard-coded
password. Log in at `/login`.

Or with Docker (SQLite by default; see `docker-compose.yml` for the
optional PostgreSQL profile):

```bash
docker compose up --build
```

## Project structure

```
backend/
  app/
    config.py            # env-based settings, no production defaults for secrets
    security.py          # bcrypt passwords, JWT, Fernet token encryption at rest
    database.py          # SQLAlchemy engine (SQLite default, PostgreSQL via URL)
    models.py            # all 15 tables (section 14 of the master prompt)
    schemas.py           # Pydantic schemas — responses never include tokens
    deps.py              # JWT auth + admin role guard
    routers/             # auth, dashboard, accounts, mappings
    services/mapping.py  # account→folder isolation + 8 pre-publish checks
  tests/test_phase1.py   # auth, encryption, mapping-mismatch, dashboard, 401
frontend/
  app/                   # Next.js 14 App Router: dashboard, login, accounts
  lib/api.ts             # typed backend client (NEXT_PUBLIC_API_URL)
docs/
  SECURITY.md  DEPLOYMENT.md  TESTING.md
```

## API (Phase 1)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | public liveness |
| POST | `/api/auth/login` | OAuth2 password form → JWT |
| GET | `/api/auth/me` | requires JWT |
| GET | `/api/dashboard/stats` | real counts |
| GET | `/api/dashboard/accounts-summary` | per-account counts, no tokens |
| GET/POST | `/api/accounts` | POST is admin-only; token encrypted, never returned |
| GET | `/api/accounts/{id}` | |
| POST | `/api/accounts/{id}/disconnect` | admin-only; clears stored token |
| GET/POST | `/api/mappings` | POST requires `confirmed_by_admin=true`; rejects a folder already mapped to another account unless `shared_folder_mode=true` |

## Tests

```bash
cd backend && python -m pytest tests -q   # 4 passed (Phase 1)
```

## Still required before any real publishing (external config, not code)

1. Meta app + Instagram Graph API permissions, Business/Creator accounts
   connected to a Facebook Page, and OAuth redirect URIs — Phase 3.
2. Google Cloud project + Drive API OAuth consent — Phase 2.
3. A stable public HTTPS `PUBLIC_MEDIA_BASE_URL` for Meta to fetch
   videos (Cloudflare Tunnel is for local testing only) — Phase 6/9.
4. `TOKEN_ENCRYPTION_KEY` + `SECRET_KEY` set in production; without the
   former, tokens are encrypted with an ephemeral key and do not
   survive a restart (logged on startup).

## Zero-budget note

Everything in Phase 1 is free/open-source (Next.js, FastAPI, SQLite,
APScheduler in later phases). No paid AI API is used. Free hosting
tiers are **not** assumed to be always-on — see `docs/DEPLOYMENT.md`.
