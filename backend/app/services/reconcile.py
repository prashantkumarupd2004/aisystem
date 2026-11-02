"""Reconciliation for UNCERTAIN publishes (Phase 7).

When media_publish fails at the network layer, the Reel may already
exist on Instagram. Blindly retrying would create a duplicate, so
reconciliation is a manual, explicit step:

  POST /api/schedules/{id}/reconcile

It lists the account's recent media via the Graph API and looks for
a Reel whose caption matches this video's caption+hashtags and whose
timestamp is at/after the scheduled time (with a 1-hour grace for
clock skew). This is a heuristic, not a guarantee -- Meta does not
offer a "find by container id after a failed response" endpoint -- so
a match is recorded as "reconciled" with the media id, and a
non-match is reported as not_found and the job stays FAILED for a
human to check Instagram directly. Reconciliation never publishes
anything itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import (
    DriveVideo,
    InstagramAccount,
    PublishingAttempt,
    PublishingLog,
    ScheduledPost,
)
from ..security import decrypt_token
from . import publishing


def reconcile_uncertain(db: Session, post: ScheduledPost) -> dict:
    account = db.get(InstagramAccount, post.instagram_account_id)
    video = db.get(DriveVideo, post.drive_video_id)
    if account is None or video is None or not account.access_token_encrypted:
        return {"found": False, "reason": "Account, video or token missing"}
    token = decrypt_token(account.access_token_encrypted)
    try:
        data = publishing._graph_get(
            f"/{account.instagram_user_id}/media",
            {
                "fields": "id,caption,timestamp,media_type",
                "limit": 25,
                "access_token": token,
            },
        )
    except Exception as exc:
        return {"found": False, "reason": f"Graph media listing failed: {exc}"}
    expected_caption = publishing.build_caption(video).strip()
    scheduled = post.scheduled_at_utc
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    earliest = scheduled - timedelta(hours=1)
    for item in data.get("data", []):
        if item.get("media_type") not in ("VIDEO", None):
            # Reels appear as VIDEO in /media; skip obvious non-video.
            if item.get("media_type") not in (None, "VIDEO"):
                continue
        caption = (item.get("caption") or "").strip()
        ts_raw = item.get("timestamp")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = None
            if ts is not None and ts < earliest:
                continue
        if expected_caption and caption == expected_caption:
            media_id = item["id"]
            post.status = "PUBLISHED"
            video.status = "PUBLISHED"
            db.add(
                PublishingAttempt(
                    scheduled_post_id=post.id,
                    attempt_number=db.query(PublishingAttempt).filter(
                        PublishingAttempt.scheduled_post_id == post.id
                    ).count() + 1,
                    status="SUCCESS",
                    error_detail="Reconciled: found on Instagram after uncertain publish",
                    instagram_media_id=media_id,
                    idempotency_key=f"reconcile-{post.id}",
                )
            )
            db.add(
                PublishingLog(
                    scheduled_post_id=post.id,
                    instagram_account_id=post.instagram_account_id,
                    level="INFO",
                    message="Reconciled uncertain publish",
                    details=f"Found Instagram Media ID: {media_id}",
                )
            )
            db.commit()
            return {"found": True, "instagram_media_id": media_id}
    return {"found": False, "reason": "No matching recent Reel found on Instagram"}
