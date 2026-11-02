"""Scheduling engine + persistent worker (Phase 5).

Design notes (important, read before changing):
- All timestamps are stored in UTC (scheduled_at_utc). The timezone
  column is only the display/input timezone the admin chose.
- The worker is persistent because jobs live in scheduled_posts, not
  in APScheduler's memory: a restart re-reads due jobs from the DB.
  APScheduler only provides the periodic tick.
- Claim locking: a job is claimed with a conditional UPDATE
  (WHERE status='SCHEDULED'). Only one worker can win that update,
  so two workers cannot publish the same job twice. SQLite/Postgres
  both support this via rowcount.
- Idempotency: before publishing, the worker checks for an existing
  SUCCESS attempt for the post. If one exists, the post is marked
  PUBLISHED without calling the publisher again.
- Publisher is injectable. In production Phase 5, no publisher is
  wired yet (Phase 6) -- the worker then SKIPS due jobs (leaving them
  SCHEDULED, counted as `skipped_no_publisher`) instead of faking a
  publish. Tests inject a fake publisher; that fake never ships as
  the production publisher.
- Quota: if an account already published max_reels_per_account_per_day
  today, a due job is POSTPONED to the same time tomorrow, not failed.
- Recurrence: "daily" / "weekly" / "monthly" on a post means the admin
  opted to re-publish that same video on that cadence (evergreen
  reel). On success the worker creates the next occurrence. Cancel
  the series by cancelling the latest occurrence.
- Retry (basic, Phase 7 expands it): a failed publish is rescheduled
  with exponential backoff (15 min, 30 min) up to max_publish_attempts,
  then marked FAILED (dead-letter) for manual review.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    DriveVideo,
    PublishingAttempt,
    PublishingLog,
    ScheduledPost,
)
from .mapping import MappingMismatch, NotPublishable, validate_publish_eligibility

log = logging.getLogger(__name__)
MAX_ATTEMPTS = settings.max_publish_attempts


def local_to_utc(local_dt: datetime, tz_name: str) -> datetime:
    """Naive local datetime + IANA timezone -> aware UTC datetime."""
    tz = ZoneInfo(tz_name)
    if local_dt.tzinfo is not None:
        return local_dt.astimezone(timezone.utc)
    return local_dt.replace(tzinfo=tz).astimezone(timezone.utc)


def utc_to_local(utc_dt: datetime, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    dt = utc_dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def published_today_count(db: Session, account_id: int, now: datetime) -> int:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(ScheduledPost)
        .filter(
            ScheduledPost.instagram_account_id == account_id,
            ScheduledPost.status == "PUBLISHED",
            ScheduledPost.updated_at >= day_start,
        )
        .count()
    )


def next_eligible_time(
    db: Session, account_id: int, desired_utc: datetime
) -> datetime:
    """Advance desired_utc day by day while that day's quota is full."""
    candidate = desired_utc
    # Guard against an infinite loop if the cap is 0 (misconfiguration).
    for _ in range(366):
        day_start = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = (
            db.query(ScheduledPost)
            .filter(
                ScheduledPost.instagram_account_id == account_id,
                ScheduledPost.status == "PUBLISHED",
                ScheduledPost.updated_at >= day_start,
                ScheduledPost.updated_at < day_end,
            )
            .count()
        )
        if count < settings.max_reels_per_account_per_day:
            return candidate
        candidate = candidate + timedelta(days=1)
    return candidate


def next_recurrence(scheduled_utc: datetime, rule: str | None) -> datetime | None:
    if not rule:
        return None
    rule = rule.strip().lower()
    if rule == "daily":
        return scheduled_utc + timedelta(days=1)
    if rule == "weekly":
        return scheduled_utc + timedelta(weeks=1)
    if rule == "monthly":
        # Same day next month, clamped to month end via a simple loop.
        year, month = scheduled_utc.year, scheduled_utc.month + 1
        if month > 12:
            month, year = 1, year + 1
        import calendar

        day = min(scheduled_utc.day, calendar.monthrange(year, month)[1])
        return scheduled_utc.replace(year=year, month=month, day=day)
    return None


def _log(db: Session, post: ScheduledPost, message: str, details: str | None = None):
    db.add(
        PublishingLog(
            scheduled_post_id=post.id,
            instagram_account_id=post.instagram_account_id,
            level="INFO",
            message=message,
            details=details,
        )
    )


def process_due_posts(
    db: Session,
    publish_fn=None,
    now: datetime | None = None,
) -> dict:
    """Process due jobs, one account at a time (independent per account).

    publish_fn(post) -> (success: bool, media_id: str | None, error: str | None)
    If publish_fn is None, due jobs are skipped, not faked.
    Returns a summary dict for the worker run report.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due = (
        db.query(ScheduledPost)
        .filter(
            ScheduledPost.status == "SCHEDULED",
            ScheduledPost.is_paused.is_(False),
            ScheduledPost.scheduled_at_utc <= now,
        )
        .order_by(ScheduledPost.instagram_account_id, ScheduledPost.scheduled_at_utc)
        .all()
    )
    summary = {
        "due": len(due), "published": 0, "failed": 0,
        "postponed_quota": 0, "skipped_no_publisher": 0,
        "skipped_already_published": 0,
    }
    for post in due:
        # Quota postponement happens before claiming, so a postponed
        # job is not lost and not counted as a failure.
        if published_today_count(db, post.instagram_account_id, now) >= settings.max_reels_per_account_per_day:
            post.scheduled_at_utc = post.scheduled_at_utc + timedelta(days=1)
            _log(db, post, "Postponed: daily publishing quota reached",
                 f"Moved to {post.scheduled_at_utc.isoformat()}")
            db.commit()
            summary["postponed_quota"] += 1
            continue
        if publish_fn is None:
            summary["skipped_no_publisher"] += 1
            continue
        # Already published via a previous successful attempt?
        success_attempt = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id,
            PublishingAttempt.status == "SUCCESS",
        ).first()
        if success_attempt is not None:
            post.status = "PUBLISHED"
            db.commit()
            summary["skipped_already_published"] += 1
            continue
        # Claim with conditional update (distributed lock).
        result = db.execute(
            update(ScheduledPost)
            .where(
                ScheduledPost.id == post.id,
                ScheduledPost.status == "SCHEDULED",
            )
            .values(status="PROCESSING")
        )
        db.commit()
        if result.rowcount != 1:
            continue  # another worker claimed it
        db.refresh(post)
        video = db.get(DriveVideo, post.drive_video_id)
        if video is not None:
            video.status = "PROCESSING"
            db.commit()
        # Mapping / eligibility validation (the 8 checks).
        try:
            validate_publish_eligibility(db, post)
        except (MappingMismatch, NotPublishable) as exc:
            # Quota can be hit between the pre-check and validation;
            # that is a postponement, not a permanent failure.
            if "quota" in str(exc).lower():
                post.scheduled_at_utc = post.scheduled_at_utc + timedelta(days=1)
                post.status = "SCHEDULED"
                if video is not None:
                    video.status = "READY"
                _log(db, post, "Postponed: daily publishing quota reached",
                     f"Moved to {post.scheduled_at_utc.isoformat()}")
                db.commit()
                summary["postponed_quota"] += 1
                continue
            post.status = "FAILED"
            if video is not None:
                video.status = "READY"
            _log(db, post, "Publish blocked by eligibility check", str(exc))
            db.commit()
            summary["failed"] += 1
            continue
        attempt_number = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id
        ).count() + 1
        try:
            success, media_id, error = publish_fn(post)
        except Exception as exc:  # publisher raised: treat as temporary
            success, media_id, error = False, None, str(exc)
        attempt = PublishingAttempt(
            scheduled_post_id=post.id,
            attempt_number=attempt_number,
            status="SUCCESS" if success else "FAILED",
            error_detail=None if success else error,
            instagram_media_id=media_id,
            idempotency_key=f"publish-{post.id}-{attempt_number}",
        )
        db.add(attempt)
        if success:
            post.status = "PUBLISHED"
            if video is not None:
                video.status = "PUBLISHED"
            _log(db, post, "Published", f"Instagram Media ID: {media_id}")
            summary["published"] += 1
            # Recurrence: create the next occurrence of this same video.
            nxt = next_recurrence(post.scheduled_at_utc, post.recurrence_rule)
            if nxt is not None:
                db.add(
                    ScheduledPost(
                        instagram_account_id=post.instagram_account_id,
                        drive_video_id=post.drive_video_id,
                        scheduled_at_utc=nxt,
                        timezone=post.timezone,
                        recurrence_rule=post.recurrence_rule,
                        status="SCHEDULED",
                    )
                )
                _log(db, post, "Recurring next occurrence created",
                     f"Next: {nxt.isoformat()}")
        else:
            if attempt_number < MAX_ATTEMPTS:
                backoff_minutes = 15 * (2 ** (attempt_number - 1))
                post.scheduled_at_utc = now + timedelta(minutes=backoff_minutes)
                post.status = "SCHEDULED"
                if video is not None:
                    video.status = "READY"
                _log(db, post, "Publish failed, will retry",
                     f"Attempt {attempt_number}: {error}; retry in {backoff_minutes} min")
            else:
                post.status = "FAILED"
                if video is not None:
                    video.status = "READY"
                _log(db, post, "Publish failed permanently (dead-letter)",
                     f"Attempt {attempt_number}: {error}")
                summary["failed"] += 1
        db.commit()
    return summary


def start_scheduler(publish_fn=None):
    """APScheduler tick every scheduler_interval_seconds. Returns the
    scheduler (caller must call .start() / keep the process alive)."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from ..database import SessionLocal  # local import to avoid cycles

    scheduler = BackgroundScheduler(timezone="UTC")

    def _tick():
        db = SessionLocal()
        try:
            result = process_due_posts(db, publish_fn=publish_fn)
            if result["due"]:
                log.info("Scheduler tick: %s", result)
        except Exception:
            log.exception("Scheduler tick failed")
        finally:
            db.close()

    scheduler.add_job(_tick, "interval",
                      seconds=settings.scheduler_interval_seconds,
                      id="process_due_posts", replace_existing=True)
    return scheduler
