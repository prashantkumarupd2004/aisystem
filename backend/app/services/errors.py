"""Error classification + retry policy (Phase 7, prompt section 10).

Every publishing failure is classified exactly once, and the
classification -- not the raw message -- decides what happens next:

  PERMANENT           -- retrying cannot help (bad token, revoked
                         permission, missing file, bad caption/format).
                         Fail immediately, notify, no backoff.
  TOKEN_EXPIRED       -- a PERMANENT sub-type; also flips the account
                         health to TOKEN_EXPIRED so the dashboard shows
                         it needs reconnection.
  PERMISSION_REVOKED  -- a PERMANENT sub-type; flips health likewise.
  UNCERTAIN           -- the publish may already be live (network
                         failure during media_publish, or a response
                         with no media id). NEVER auto-retry; the job
                         goes to FAILED for manual reconciliation
                         (see reconcile.py) before any manual retry.
  QUOTA               -- daily cap reached; postpone to next day.
  RATE_LIMIT          -- Meta rate limit; retry after the Retry-After
                         header when present, otherwise after 60 min.
  TEMPORARY           -- network / 5xx / container processing failure;
                         retry with exponential backoff.

Retry delays (temporary): 15 min, then 30 min (attempts 1, 2).
Max attempts is settings.max_publish_attempts (default 3); after the
last attempt the job is dead-lettered (FAILED + notification), never
silently dropped.
"""
from __future__ import annotations

import re
from datetime import timedelta

PERMANENT = "PERMANENT"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
PERMISSION_REVOKED = "PERMISSION_REVOKED"
UNCERTAIN = "UNCERTAIN"
QUOTA = "QUOTA"
RATE_LIMIT = "RATE_LIMIT"
TEMPORARY = "TEMPORARY"

NO_RETRY_KINDS = {PERMANENT, TOKEN_EXPIRED, PERMISSION_REVOKED, UNCERTAIN}


def parse_retry_after(error_text: str | None) -> int | None:
    """Seconds from 'Retry-After: N' / 'retry_after=N' in an error string."""
    if not error_text:
        return None
    m = re.search(r"[Rr]etry-[Aa]fter[:=]\s*(\d+)", error_text)
    if m:
        return int(m.group(1))
    m = re.search(r"retry_after=(\d+)", error_text)
    if m:
        return int(m.group(1))
    return None


def classify_error(error_text: str | None) -> tuple[str, int | None]:
    """Return (kind, retry_after_seconds_or_None)."""
    text = (error_text or "").lower()
    retry_after = parse_retry_after(error_text)
    if text.startswith("uncertain:") or "uncertain" in text:
        return UNCERTAIN, None
    if "quota" in text:
        return QUOTA, None
    if "token expired" in text or "token is expired" in text or "session expired" in text or "code 190" in text or "190" in text and "token" in text:
        return TOKEN_EXPIRED, None
    if "permission revoked" in text or "permission" in text and "revoked" in text or "missing permission" in text or "(#200)" in text or "code 200" in text:
        return PERMISSION_REVOKED, None
    if text.startswith("permanent:"):
        return PERMANENT, None
    if "rate limit" in text or "rate_limit" in text or "too many requests" in text or "code 4" in text or "code 17" in text or "code 613" in text or " 429" in text:
        return RATE_LIMIT, retry_after
    if "not found in google drive" in text or "file not found" in text:
        return PERMANENT, None
    return TEMPORARY, retry_after


def next_retry_delay(
    attempt_number: int, kind: str, retry_after: int | None
) -> timedelta:
    """Delay before the next attempt for a retryable failure."""
    if kind == RATE_LIMIT:
        if retry_after is not None:
            # Cap at 24h so a bogus header cannot stall a job forever.
            return timedelta(seconds=min(retry_after, 24 * 3600))
        return timedelta(minutes=60)
    if retry_after is not None:
        return timedelta(seconds=min(retry_after, 24 * 3600))
    # Exponential backoff: 15 min, 30 min, 60 min, ...
    return timedelta(minutes=15 * (2 ** (attempt_number - 1)))
