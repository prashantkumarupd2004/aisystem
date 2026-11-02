# Error handling, retry and duplicate protection (Phase 7)

## Classification (backend/app/services/errors.py)

| Kind | What it means | Worker action |
|---|---|---|
| TEMPORARY | Network, 5xx, container processing failure | Retry, backoff 15 min, 30 min, … |
| RATE_LIMIT | Meta rate limit (code 4/17/613/800, 429) | Retry after Retry-After header, else 60 min |
| QUOTA | Daily account cap reached | Postpone to same time next day, not a failure |
| PERMANENT | Bad format/caption, missing file, other non-retryable | Fail immediately, notify |
| TOKEN_EXPIRED | Meta code 190 / expired session | Fail immediately, notify, account health → TOKEN_EXPIRED |
| PERMISSION_REVOKED | Meta code 200/10, revoked scope | Fail immediately, notify, account health → PERMISSION_REVOKED |
| UNCERTAIN | Network failure during media_publish, or publish response with no media id | Fail immediately, **never auto-retry**, notify; reconcile manually |

Max attempts: `MAX_PUBLISH_ATTEMPTS` (default 3). After that, the
job is dead-lettered: status FAILED, a notification is created, and
it appears in `/failed` (API: `/api/failed-jobs`). Nothing is
silently dropped.

## Duplicate protection (all layers)

1. Claim locking: conditional UPDATE on status=SCHEDULED, one winner.
2. SUCCESS-attempt check before publishing: if a SUCCESS attempt
   already exists for the post, it is marked PUBLISHED without
   calling Meta again.
3. PublishingAttempt.idempotency_key is unique per post+attempt.
4. UNCERTAIN jobs are never auto-retried (see below).

## Reconciliation (UNCERTAIN jobs only, manual)

`POST /api/schedules/{id}/reconcile` lists the account's recent
Graph media and looks for a Reel with the same caption, published
at/after the scheduled time (1h grace). A match marks the job
PUBLISHED with that Media ID. A non-match leaves the job FAILED
for a human to check Instagram directly. Reconciliation never
publishes anything.

Only after reconciliation (or a direct Instagram check) should an
admin use `POST /api/schedules/{id}/retry`, which puts a FAILED job
back to SCHEDULED for immediate processing.

## Notifications

Worker-created notifications live at `/api/notifications`
(unread filter, mark read / mark-all-read). They are created only
for dead-letter, permanent and uncertain failures -- not for
routine successes or ordinary retries.
