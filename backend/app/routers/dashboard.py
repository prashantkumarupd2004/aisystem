"""Dashboard stats are real DB counts, never hard-coded demo numbers."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import (
    DriveVideo,
    InstagramAccount,
    PublishingAttempt,
    ScheduledPost,
)
from ..schemas import DashboardStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def stats(db: Session = Depends(get_db), _=Depends(get_current_user)):
    connected = db.query(InstagramAccount).count()
    active = (
        db.query(InstagramAccount)
        .filter(InstagramAccount.connection_status == "ACTIVE")
        .count()
    )
    return DashboardStats(
        connected_accounts=connected,
        active_accounts=active,
        accounts_needing_attention=connected - active,
        total_videos=db.query(DriveVideo).count(),
        scheduled_reels=db.query(ScheduledPost)
        .filter(ScheduledPost.status == "SCHEDULED")
        .count(),
        published_reels=db.query(ScheduledPost)
        .filter(ScheduledPost.status == "PUBLISHED")
        .count(),
        failed_jobs=db.query(PublishingAttempt)
        .filter(PublishingAttempt.status == "FAILED")
        .count(),
    )


@router.get("/accounts-summary")
def accounts_summary(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Per-account summary used by the dashboard table (no tokens)."""
    out = []
    for acc in db.query(InstagramAccount).order_by(InstagramAccount.username).all():
        out.append(
            {
                "id": acc.id,
                "username": acc.username,
                "connection_status": acc.connection_status,
                "videos": db.query(DriveVideo)
                .filter(DriveVideo.instagram_account_id == acc.id)
                .count(),
                "scheduled": db.query(ScheduledPost)
                .filter(
                    ScheduledPost.instagram_account_id == acc.id,
                    ScheduledPost.status == "SCHEDULED",
                )
                .count(),
                "published": db.query(ScheduledPost)
                .filter(
                    ScheduledPost.instagram_account_id == acc.id,
                    ScheduledPost.status == "PUBLISHED",
                )
                .count(),
            }
        )
    return out
