# Multi-Account Instagram Reels Automation Agent — All 10 Phases Complete

Centralised web platform to manage ~50 Instagram Professional accounts
from one dashboard, with one central Google Drive library, strict
account→folder isolation, scheduling and official Meta API publishing.

> **Phase 10 status: COMPLETE (all phases built, tested, documented).**
> 54 backend tests pass, frontend builds, Alembic migrations work
> (upgrade head creates all 15 tables, downgrade base drops them),
> security check passes. What is still external, not code, and not
> faked: GitHub push (no GitHub auth on this machine), Google/Meta
> OAuth credentials, and a stable public HTTPS media URL. Docker
> images were validated by config checks only (Docker is not
> installed on this dev VM) -- build them once on the target host.

## Non-negotiable rule

A video in Drive folder `XYZ` is eligible **only** for the Instagram
account mapped to `XYZ`. Every publish path re-checks
`video.drive_folder_id == mapping.drive_folder_id` and
`video.instagram_account_id == account.id` before publishing
(`backend/app/services/mapping.py`). A mismatch stops the job.

API connectivity is **not** treated as proof an account is unsuspended:
health status defaults to `UNKNOWN` / `NEEDS_MANUAL_REVIEW` unless an
authorised API check says otherwise.

## Quick start (local)

```bash
# Backend (Python 3.12)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # then edit SECRET_KEY, TOKEN_ENCRYPTION_KEY, ADMIN_*
uvicorn app.main:app --reload --port 8000
python -m app.worker      # separate terminal: the publishing worker

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

Or with Docker (Postgres + API + worker + frontend):

```bash
cp .env.production.example .env   # fill in real secrets
docker compose up --build
```

## What was built (phases)

| Phase | What | Key guarantee |
|---|---|---|
| 1 | Project, schema (15 tables), auth, dashboard | Tokens encrypted, never returned |
| 2 | Google Drive OAuth + folder sync | Sync keyed by permanent Drive ID |
| 3 | Instagram OAuth + multi-account | Only Business/Creator on a Page; upsert by IG id |
| 4 | Video detection + library | Missing duration -> NEW, never READY; vanished -> NEEDS_REVIEW, never deleted |
| 5 | Scheduling + persistent worker | UTC + IANA timezones, quota postpones (never fails), claim locking |
| 6 | Meta Reels publishing + signed media | Container -> poll FINISHED -> publish; temp cleanup; PERMANENT/UNCERTAIN never auto-retried |
| 7 | Retry + duplicate protection | Classification, Retry-After, dead-letter, reconcile-before-retry |
| 8 | Monitoring + reports + alerts | Health honesty, daily/range reports, CSV, alerts never faked |
| 9 | Local + cloud deployment | Docker Compose, Procfile/render.yaml, systemd, deploy_check gate |
| 10 | Integration tests + security + docs | Alembic migrations, end-to-end chain, security_check script |

## Project structure

```
backend/
  app/            # config, security, database, models, schemas, deps
  app/routers/    # auth, dashboard, accounts, drive, instagram, mappings,
                  # videos, schedules, media, notifications, failed_jobs,
                  # health, reports, alerts
  app/services/   # mapping, drive, instagram, video_detection, scheduler,
                  # publishing, media_delivery, errors, reconcile,
                  # health, reports, alerts
  alembic/        # migrations (initial: all 15 tables)
  tests/          # test_phase1.py ... test_phase10.py (54 tests)
frontend/
  app/            # dashboard, login, accounts, drive, mappings, videos,
                  # scheduler, history, failed, health, reports, notifications
  lib/api.ts      # typed client (NEXT_PUBLIC_API_URL)
scripts/          # deploy_check.py, security_check.py
deploy/           # systemd units
docs/             # SECURITY, DEPLOYMENT, TESTING, API, ARCHITECTURE,
                  # GOOGLE_DRIVE_SETUP, META_SETUP, PUBLISHING,
                  # ERROR_HANDLING, MONITORING_REPORTS
```

## Docs

- `docs/API.md` -- endpoint list (no token ever in a response)
- `docs/ARCHITECTURE.md` -- data flow + the 5 non-negotiable invariants
- `docs/GOOGLE_DRIVE_SETUP.md` / `docs/META_SETUP.md` -- OAuth setup
- `docs/PUBLISHING.md` / `docs/ERROR_HANDLING.md` /
  `docs/MONITORING_REPORTS.md` -- publishing, retry, reports
- `docs/DEPLOYMENT.md` -- bare metal, Docker, hybrid cloud, backups
- `docs/SECURITY.md` / `docs/TESTING.md` -- controls, limits, checklist

## Tests

```bash
cd backend && python -m pytest tests -q   # 54 passed
cd frontend && npm run build
python scripts/security_check.py           # PASSED
python scripts/deploy_check.py --mode production --env-file .env
```

## Still required before any real publishing (external config, not code)

1. GitHub auth (PAT) to push this repo -- all commits are local so far.
2. Meta app + Instagram Graph API permissions, Business/Creator accounts
   connected to a Facebook Page, and OAuth redirect URIs.
3. Google Cloud project + Drive API OAuth consent.
4. A stable public HTTPS `PUBLIC_MEDIA_BASE_URL` for Meta to fetch
   videos (Cloudflare Tunnel is for local testing only).
5. `TOKEN_ENCRYPTION_KEY` + `SECRET_KEY` set in production; without the
   former, tokens are encrypted with an ephemeral key and do not
   survive a restart (logged on startup).
6. The manual production checklist in `docs/TESTING.md` (one real
   account end-to-end, then scale 5 -> 10 -> 20 -> 50).

## Zero-budget note

Everything is free/open-source (Next.js, FastAPI, SQLite/Postgres,
APScheduler). No paid AI API is used. Free hosting tiers are **not**
assumed to be always-on -- see `docs/DEPLOYMENT.md`.
