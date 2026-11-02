"""Scheduling API (Phase 5).

Validation on create (all-or-nothing for bulk):
  - account exists, video exists and is READY
  - video belongs to the account's mapped folder (account isolation)
  - no existing SCHEDULED post for the same account+video+UTC time
  - recurrence_rule, if given, must be daily / weekly / monthly

Timestamps: the API accepts either an aware ISO datetime in
`scheduled_at` (converted to UTC) or a naive local datetime in
`scheduled_at_local` plus a `timezone` (IANA name, e.g. Asia/Kolkata).
Storage is always UTC; responses include both UTC and the requested
local display time when ?timezone= is given.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import (
    AccountFolderMapping,
    DriveVideo,
    InstagramAccount,
    PublishingAttempt,
    PublishingLog,
    ScheduledPost,
    User,
)
from ..services.scheduler import (
    local_to_utc,
    next_eligible_time,
    utc_to_local,
)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class ScheduleCreate(BaseModel):
    instagram_account_id: int
    drive_video_id: int
    scheduled_at: Optional[datetime] = None
    scheduled_at_local: Optional[datetime] = None
    timezone: str = "UTC"
    recurrence_rule: Optional[str] = None


class ScheduleOut(BaseModel):
    id: int
    instagram_account_id: int
    drive_video_id: int
    scheduled_at_utc: datetime
    scheduled_at_local: Optional[datetime] = None
    timezone: str
    recurrence_rule: Optional[str] = None
    status: str
    is_paused: bool

    model_config = {"from_attributes": True}


def _resolve_utc(payload: ScheduleCreate) -> datetime:
    if payload.scheduled_at is not None:
        dt = payload.scheduled_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if payload.scheduled_at_local is not None:
        return local_to_utc(payload.scheduled_at_local, payload.timezone)
    raise HTTPException(400, "scheduled_at or scheduled_at_local is required")


def _validate_create(
    db: Session, payload: ScheduleCreate, utc_dt: datetime
) -> None:
    account = db.get(InstagramAccount, payload.instagram_account_id)
    if not account:
        raise HTTPException(404, "Instagram account not found")
    video = db.get(DriveVideo, payload.drive_video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if video.status != "READY":
        raise HTTPException(400, f"Video is not READY (status={video.status})")
    mapping = db.query(AccountFolderMapping).filter(
        AccountFolderMapping.instagram_account_id == account.id,
        AccountFolderMapping.is_active.is_(True),
    ).first()
    if not mapping or video.drive_folder_id != mapping.drive_folder_id:
        raise HTTPException(
            409, "Video does not belong to this account's mapped folder"
        )
    if video.instagram_account_id != account.id:
        raise HTTPException(409, "Video is not owned by this account")
    if payload.recurrence_rule and payload.recurrence_rule.lower() not in (
        "daily", "weekly", "monthly",
    ):
        raise HTTPException(400, "recurrence_rule must be daily, weekly or monthly")
    clash = db.query(ScheduledPost).filter(
        ScheduledPost.instagram_account_id == account.id,
        ScheduledPost.drive_video_id == video.id,
        ScheduledPost.scheduled_at_utc == utc_dt,
        ScheduledPost.status == "SCHEDULED",
    ).first()
    if clash:
        raise HTTPException(409, "This video is already scheduled at that time")


def _out(post: ScheduledPost, display_tz: str | None) -> ScheduleOut:
    out = ScheduleOut.model_validate(post)
    tz = display_tz or post.timezone
    out.timezone = tz
    utc_dt = post.scheduled_at_utc
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    out.scheduled_at_local = utc_to_local(utc_dt, tz)
    return out


@router.post("", response_model=ScheduleOut, status_code=201)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    utc_dt = _resolve_utc(payload)
    _validate_create(db, payload, utc_dt)
    post = ScheduledPost(
        instagram_account_id=payload.instagram_account_id,
        drive_video_id=payload.drive_video_id,
        scheduled_at_utc=utc_dt,
        timezone=payload.timezone,
        recurrence_rule=payload.recurrence_rule.lower() if payload.recurrence_rule else None,
        status="SCHEDULED",
    )
    db.add(post)
    # Video moves to SCHEDULED so it cannot be double-scheduled
    # elsewhere; the worker moves it to PROCESSING/PUBLISHED later.
    video = db.get(DriveVideo, payload.drive_video_id)
    if video:
        video.status = "SCHEDULED"
    db.commit()
    db.refresh(post)
    return _out(post, None)


@router.post("/bulk", response_model=list[ScheduleOut], status_code=201)
def bulk_create(
    payloads: list[ScheduleCreate],
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Validate ALL first: bulk is all-or-nothing.
    utc_list = [_resolve_utc(p) for p in payloads]
    for payload, utc_dt in zip(payloads, utc_list):
        _validate_create(db, payload, utc_dt)
    created = []
    for payload, utc_dt in zip(payloads, utc_list):
        post = ScheduledPost(
            instagram_account_id=payload.instagram_account_id,
            drive_video_id=payload.drive_video_id,
            scheduled_at_utc=utc_dt,
            timezone=payload.timezone,
            recurrence_rule=payload.recurrence_rule.lower() if payload.recurrence_rule else None,
            status="SCHEDULED",
        )
        db.add(post)
        db.flush()
        video = db.get(DriveVideo, payload.drive_video_id)
        if video:
            video.status = "SCHEDULED"
        created.append(post)
    db.commit()
    for post in created:
        db.refresh(post)
    return [_out(p, None) for p in created]


@router.get("", response_model=list[ScheduleOut])
def list_schedules(
    account_id: int | None = None,
    status: str | None = None,
    timezone: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(ScheduledPost)
    if account_id:
        q = q.filter(ScheduledPost.instagram_account_id == account_id)
    if status:
        q = q.filter(ScheduledPost.status == status)
    posts = q.order_by(ScheduledPost.scheduled_at_utc).offset(skip).limit(limit).all()
    return [_out(p, timezone) for p in posts]


@router.get("/calendar")
def calendar_view(
    year: int,
    month: int,
    timezone: str = "UTC",
    account_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Group scheduled posts by local calendar date for the month."""
    q = db.query(ScheduledPost).filter(ScheduledPost.status == "SCHEDULED")
    if account_id:
        q = q.filter(ScheduledPost.instagram_account_id == account_id)
    grouped: dict[str, list] = {}
    for post in q.order_by(ScheduledPost.scheduled_at_utc).all():
        local = utc_to_local(post.scheduled_at_utc, timezone)
        if local.year == year and local.month == month:
            grouped.setdefault(local.date().isoformat(), []).append(
                _out(post, timezone).model_dump(mode="json")
            )
    return grouped


@router.get("/next-eligible")
def next_eligible(
    account_id: int,
    desired: datetime,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    dt = desired
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {"next_eligible_utc": next_eligible_time(db, account_id, dt.astimezone(timezone.utc))}


@router.get("/{schedule_id}/attempts")
def schedule_attempts(
    schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    return [
        {
            "id": a.id, "attempt_number": a.attempt_number, "status": a.status,
            "error_code": a.error_code, "error_detail": a.error_detail,
            "instagram_media_id": a.instagram_media_id,
            "created_at": a.created_at,
        }
        for a in db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == schedule_id
        ).order_by(PublishingAttempt.attempt_number).all()
    ]


@router.get("/{schedule_id}/logs")
def schedule_logs(
    schedule_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    return [
        {"id": l.id, "level": l.level, "message": l.message,
         "details": l.details, "created_at": l.created_at}
        for l in db.query(PublishingLog).filter(
            PublishingLog.scheduled_post_id == schedule_id
        ).order_by(PublishingLog.created_at).all()
    ]


@router.post("/{schedule_id}/reconcile")
def reconcile_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Manual reconciliation for an UNCERTAIN / FAILED job. Only for
    FAILED jobs; never publishes anything itself."""
    from ..services import reconcile as reconcile_service

    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    if post.status != "FAILED":
        raise HTTPException(400, "Only FAILED schedules can be reconciled")
    return reconcile_service.reconcile_uncertain(db, post)


@router.post("/{schedule_id}/retry", response_model=ScheduleOut)
def retry_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Manual retry of a FAILED job, by an admin, after fixing the
    cause (token, permission, caption, etc.). This is deliberate, not
    automatic -- in particular, retry an UNCERTAIN job only after
    reconciliation has confirmed it is not already live."""
    from datetime import datetime, timezone

    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    if post.status != "FAILED":
        raise HTTPException(400, "Only FAILED schedules can be retried")
    post.status = "SCHEDULED"
    post.scheduled_at_utc = datetime.now(timezone.utc)
    video = db.get(DriveVideo, post.drive_video_id)
    if video and video.status == "READY":
        video.status = "SCHEDULED"
    db.commit()
    db.refresh(post)
    return _out(post, None)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
def edit_schedule(
    schedule_id: int,
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    if post.status == "PUBLISHED":
        raise HTTPException(400, "Published schedules cannot be edited")
    utc_dt = _resolve_utc(payload)
    post.scheduled_at_utc = utc_dt
    post.timezone = payload.timezone
    if payload.recurrence_rule is not None:
        post.recurrence_rule = payload.recurrence_rule.lower()
    db.commit()
    db.refresh(post)
    return _out(post, None)


@router.post("/{schedule_id}/pause", response_model=ScheduleOut)
def pause_schedule(
    schedule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    post.is_paused = True
    db.commit()
    db.refresh(post)
    return _out(post, None)


@router.post("/{schedule_id}/resume", response_model=ScheduleOut)
def resume_schedule(
    schedule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    post.is_paused = False
    db.commit()
    db.refresh(post)
    return _out(post, None)


@router.post("/{schedule_id}/cancel", response_model=ScheduleOut)
def cancel_schedule(
    schedule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    post = db.get(ScheduledPost, schedule_id)
    if not post:
        raise HTTPException(404, "Schedule not found")
    if post.status == "PUBLISHED":
        raise HTTPException(400, "Published schedules cannot be cancelled")
    post.status = "CANCELLED"
    video = db.get(DriveVideo, post.drive_video_id)
    if video and video.status == "SCHEDULED":
        video.status = "READY"
    db.commit()
    db.refresh(post)
    return _out(post, None)
