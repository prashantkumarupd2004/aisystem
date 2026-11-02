# Architecture

```
Google Drive (one central account)
  Instagram-Automation/
    XYZ/  ── mapping (permanent) ──► Instagram account XYZ
    ABC/  ── mapping (permanent) ──► Instagram account ABC
        (a video is eligible ONLY for its mapped account, enforced
         by services/mapping.py's 8 pre-publish checks)

Dashboard (Next.js, :3000) ── JWT ──► API (FastAPI, :8000)
                                          │
  Worker (APScheduler, separate process) ─┤
  reads due ScheduledPost rows, claims one (conditional UPDATE),
  publishes via Meta Graph API, logs every attempt.

Publishing path (Phase 6):
  Drive download (server-side, token never exposed)
    -> ffprobe codec check (when available)
    -> signed short-lived media URL /media/{jwt}/{file} (Range/HEAD)
    -> POST /{ig-id}/media (media_type=REELS)
    -> poll container until FINISHED
    -> POST /{ig-id}/media_publish -> Instagram Media ID stored
    -> temp file deleted in finally

Failure path (Phase 7):
  classified -> retry with backoff / quota postponement /
  dead-letter + notification / health flip / UNCERTAIN never
  auto-retried (manual reconcile first).

Database: 15 tables (see alembic initial migration).
  users, instagram_accounts, oauth_tokens, google_drive_connections,
  drive_folders, account_folder_mappings, drive_videos,
  scheduled_posts, publishing_attempts, publishing_logs,
  account_health, notifications, daily_reports, audit_logs,
  system_settings.
```

## Non-negotiable invariants (tested)

1. Cross-account publishing is impossible through the mapping
   validator, not just discouraged in the UI.
2. Duplicate publishes are prevented by claim locking, the
   SUCCESS-attempt check, and a unique idempotency key.
3. Tokens are encrypted at rest and never returned by any API.
4. API accessibility is never reported as "not suspended".
5. Production mode never fakes a publish, a health status, a
   report count, or an alert send.
