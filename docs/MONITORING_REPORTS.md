# Monitoring, reports and alerts (Phase 8)

## Health (`/health`, API `/api/health/accounts`)

Counts: total connected, API accessible, disconnected, expired
tokens, revoked permissions, needing reconnection, needing manual
review, accounts with publishing errors. Per account: health status,
last API check, last successful publishing time (recorded by the
scheduler on every successful publish), and whether it has FAILED
jobs.

"API accessible" means only that the last Graph check succeeded.
It is never presented as proof of no suspension or policy
restriction -- those cases stay UNKNOWN / NEEDS_MANUAL_REVIEW.
`POST /api/health/check-all` (admin) runs a live Graph check for
every account and returns the refreshed summary.

## Reports (`/reports`, API `/api/reports`)

- `GET /api/reports/daily?report_date=YYYY-MM-DD[&account_id=]`
  generates (upserts) and returns that day's report.
- `POST /api/reports/generate?report_date=YYYY-MM-DD` (admin)
  generates the overall + one per-account report for that day.
- `GET /api/reports?start=&end=[&account_id=]` returns the range
  report: totals, per-account breakdown, published history (exact
  publishing time + Instagram Media ID + attempt history) and
  failed history (errors + retry history). Weekly/monthly reports
  are the same endpoint with a 7-day / 30-day range.
- `GET /api/reports/export.csv?start=&end=` downloads the
  per-account summary as CSV.

Definitions: detected = videos created in the period; scheduled =
posts whose scheduled time falls in the period; published = posts
that became PUBLISHED in the period; failed = failed attempts in
the period; pending = posts currently SCHEDULED (a live snapshot,
not a historical count).

## Alerts (optional, never faked)

Configure SMTP_* / ALERT_EMAIL_TO for email, or
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID for Telegram, in
backend/.env. `POST /api/alerts/test` (admin) tries both and
reports each channel's real result. With nothing configured it
honestly reports "not configured" and makes no network call.
