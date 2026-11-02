"""Dead-letter queue API (Phase 7): FAILED schedules with their last
attempt, so an admin can see exactly why a job stopped -- and retry
or reconcile it deliberately, never automatically."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import PublishingAttempt, ScheduledPost

router = APIRouter(prefix="/api/failed-jobs", tags=["failed-jobs"])


@router.get("")
def failed_jobs(
    account_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(ScheduledPost).filter(ScheduledPost.status == "FAILED")
    if account_id:
        q = q.filter(ScheduledPost.instagram_account_id == account_id)
    out = []
    for post in q.order_by(ScheduledPost.updated_at.desc()).limit(200).all():
        last = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id
        ).order_by(PublishingAttempt.attempt_number.desc()).first()
        out.append({
            "id": post.id,
            "instagram_account_id": post.instagram_account_id,
            "drive_video_id": post.drive_video_id,
            "scheduled_at_utc": post.scheduled_at_utc,
            "last_error": last.error_detail if last else None,
            "last_attempt_number": last.attempt_number if last else 0,
            "instagram_media_id": last.instagram_media_id if last else None,
        })
    return out
