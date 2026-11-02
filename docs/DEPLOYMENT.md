# Deployment

## Mode A — local Windows/Linux (Phase 1 verified path)

Backend on :8000 (SQLite), frontend on :3000, worker later (Phase 5).
Start the worker/backend after reboot with a systemd unit (Linux) or a
scheduled task / startup script (Windows) — that unit is a Phase 9 item,
not yet shipped.

## Mode B — hybrid cloud

Frontend on a free static/hosting tier, backend + worker on an
always-on host, PostgreSQL via `DATABASE_URL`. Do **not** assume a free
tier gives always-on workers, persistent disk or unlimited bandwidth:
if the worker sleeps, scheduled publishes will be missed, not queued
forever. Keep Google Drive as the single video library and use a stable
public HTTPS `PUBLIC_MEDIA_BASE_URL` — Cloudflare Quick Tunnel URLs are
temporary and must not be used for guaranteed production scheduling.

## Cost / resource transparency (Phase 1)

- Software: $0 (open-source stack).
- Meta Graph API: free tier, subject to Meta's rate limits/quotas.
- Google Drive: your existing storage quota.
- Hosting/bandwidth: whatever your host charges; video delivery is the
  dominant cost driver and scales with account count × video size.
