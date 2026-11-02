"""Account health aggregation (Phase 8, prompt section 11).

Status meanings, honestly:
  ACTIVE               -- last API check succeeded (API accessible).
  TOKEN_EXPIRED        -- Meta reported an expired/invalid token.
  PERMISSION_REVOKED   -- Meta reported a missing/revoked permission.
  CONNECTION_ERROR     -- API check failed for network/other reasons.
  PUBLISHING_RESTRICTED-- publishing was refused for this account
                          (set by a publishing-restriction error).
  NEEDS_MANUAL_REVIEW  -- a human must verify (e.g. policy/suspension
                          cannot be confirmed via API).
  UNKNOWN              -- never checked, or check result inconclusive.

A successful API check is recorded as "API accessible" in the detail
field. It is NEVER recorded as proof the account is not suspended,
because the authorised APIs do not expose that.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (
    AccountHealth,
    InstagramAccount,
    PublishingAttempt,
    ScheduledPost,
)


def health_summary(db: Session) -> dict:
    accounts = db.query(InstagramAccount).all()
    health_rows = {h.instagram_account_id: h for h in db.query(AccountHealth).all()}
    total = len(accounts)
    api_accessible = sum(
        1 for a in accounts
        if (health_rows.get(a.id).status if health_rows.get(a.id) else a.connection_status) == "ACTIVE"
    )
    disconnected = sum(1 for a in accounts if a.connection_status == "DISCONNECTED")
    expired = sum(1 for a in accounts if a.connection_status == "TOKEN_EXPIRED")
    revoked = sum(1 for a in accounts if a.connection_status == "PERMISSION_REVOKED")
    needing_reconnect = expired + revoked
    needing_review = sum(
        1 for a in accounts
        if (health_rows.get(a.id).status if health_rows.get(a.id) else a.connection_status)
        in ("UNKNOWN", "NEEDS_MANUAL_REVIEW", "CONNECTION_ERROR")
    )
    # Publishing errors: accounts with at least one FAILED post.
    failed_account_ids = {
        p.instagram_account_id
        for p in db.query(ScheduledPost).filter(ScheduledPost.status == "FAILED").all()
    }
    per_account = []
    for acc in sorted(accounts, key=lambda a: a.username):
        health = health_rows.get(acc.id)
        last_published = None
        if health and health.last_published_at:
            last_published = health.last_published_at
        else:
            latest = db.query(ScheduledPost).filter(
                ScheduledPost.instagram_account_id == acc.id,
                ScheduledPost.status == "PUBLISHED",
            ).order_by(ScheduledPost.updated_at.desc()).first()
            last_published = latest.updated_at if latest else None
        per_account.append({
            "id": acc.id,
            "username": acc.username,
            "account_type": acc.account_type,
            "connection_status": acc.connection_status,
            "health_status": health.status if health else "UNKNOWN",
            "detail": health.detail if health else None,
            "last_api_check_at": health.last_api_check_at if health else None,
            "last_published_at": last_published,
            "has_publishing_errors": acc.id in failed_account_ids,
        })
    return {
        "total_connected": total,
        "api_accessible": api_accessible,
        "disconnected": disconnected,
        "expired_tokens": expired,
        "revoked_permissions": revoked,
        "needing_reconnection": needing_reconnect,
        "needing_manual_review": needing_review,
        "accounts_with_publishing_errors": len(failed_account_ids),
        "accounts": per_account,
    }
