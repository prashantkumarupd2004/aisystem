"""Daily / weekly / monthly reports (Phase 8, prompt section 12).

Counts are computed from real DB rows, never from a dashboard guess:
  - detected: DriveVideo rows created in the period
  - scheduled: ScheduledPost rows whose scheduled_at_utc falls in the period
  - published: ScheduledPost rows that became PUBLISHED (updated_at in
    the period) -- exact publishing time is the post's updated_at, and
    the Instagram Media ID comes from its SUCCESS attempt
  - failed attempts: PublishingAttempt rows with status FAILED created
    in the period
  - pending: ScheduledPost rows currently SCHEDULED (a current
    snapshot, not a historical count -- documented as such, because a
    historical pending count cannot be reconstructed from current rows)

Daily reports are persisted in daily_reports (upsert by date+account)
so a generated report is reproducible. Range reports are computed
live from the same primitives and are not persisted as a single row.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import (
    DailyReport,
    DriveVideo,
    InstagramAccount,
    PublishingAttempt,
    ScheduledPost,
)


def _day_range(report_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(report_date, time.min).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _counts_for_period(
    db: Session, start: datetime, end: datetime, account_id: int | None
) -> dict:
    def _filter(q, model, column):
        q = q.filter(column >= start, column < end)
        if account_id:
            # DriveVideo / ScheduledPost / Attempt have different
            # account columns; handled by the caller via explicit filters.
            pass
        return q

    detected_q = db.query(DriveVideo).filter(
        DriveVideo.created_at >= start, DriveVideo.created_at < end
    )
    scheduled_q = db.query(ScheduledPost).filter(
        ScheduledPost.scheduled_at_utc >= start, ScheduledPost.scheduled_at_utc < end
    )
    published_q = db.query(ScheduledPost).filter(
        ScheduledPost.status == "PUBLISHED",
        ScheduledPost.updated_at >= start, ScheduledPost.updated_at < end,
    )
    failed_q = db.query(PublishingAttempt).filter(
        PublishingAttempt.status == "FAILED",
        PublishingAttempt.created_at >= start, PublishingAttempt.created_at < end,
    )
    if account_id:
        detected_q = detected_q.filter(DriveVideo.instagram_account_id == account_id)
        scheduled_q = scheduled_q.filter(ScheduledPost.instagram_account_id == account_id)
        published_q = published_q.filter(ScheduledPost.instagram_account_id == account_id)
        # Failed attempts join through their scheduled post.
        failed_q = failed_q.join(
            ScheduledPost,
            PublishingAttempt.scheduled_post_id == ScheduledPost.id,
        ).filter(ScheduledPost.instagram_account_id == account_id)
    pending_q = db.query(ScheduledPost).filter(ScheduledPost.status == "SCHEDULED")
    if account_id:
        pending_q = pending_q.filter(ScheduledPost.instagram_account_id == account_id)
    return {
        "total_detected": detected_q.count(),
        "total_scheduled": scheduled_q.count(),
        "total_published": published_q.count(),
        "total_failed": failed_q.count(),
        "total_pending": pending_q.count(),
    }


def generate_daily_report(
    db: Session, report_date: date, account_id: int | None = None
) -> DailyReport:
    start, end = _day_range(report_date)
    counts = _counts_for_period(db, start, end, account_id)
    row = db.query(DailyReport).filter(
        DailyReport.report_date == report_date.isoformat(),
        DailyReport.instagram_account_id == account_id,
    ).first()
    if row is None:
        row = DailyReport(
            report_date=report_date.isoformat(),
            instagram_account_id=account_id,
        )
        db.add(row)
    row.total_detected = counts["total_detected"]
    row.total_scheduled = counts["total_scheduled"]
    row.total_published = counts["total_published"]
    row.total_failed = counts["total_failed"]
    row.total_pending = counts["total_pending"]
    db.commit()
    db.refresh(row)
    return row


def build_range_report(
    db: Session, start_date: date, end_date: date, account_id: int | None = None
) -> dict:
    """Inclusive date range report with per-account breakdown + history."""
    start = datetime.combine(start_date, time.min).replace(tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.min).replace(tzinfo=timezone.utc) + timedelta(days=1)
    totals = _counts_for_period(db, start, end, account_id)
    accounts = db.query(InstagramAccount)
    if account_id:
        accounts = accounts.filter(InstagramAccount.id == account_id)
    per_account = []
    for acc in accounts.order_by(InstagramAccount.username).all():
        c = _counts_for_period(db, start, end, acc.id)
        per_account.append({"id": acc.id, "username": acc.username, **c})
    # History: published posts in the period, with media id + attempts.
    published = db.query(ScheduledPost).filter(
        ScheduledPost.status == "PUBLISHED",
        ScheduledPost.updated_at >= start, ScheduledPost.updated_at < end,
    )
    if account_id:
        published = published.filter(ScheduledPost.instagram_account_id == account_id)
    history = []
    for post in published.order_by(ScheduledPost.updated_at).all():
        success = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id,
            PublishingAttempt.status == "SUCCESS",
        ).first()
        attempts = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id
        ).order_by(PublishingAttempt.attempt_number).all()
        acc = db.get(InstagramAccount, post.instagram_account_id)
        history.append({
            "schedule_id": post.id,
            "account": acc.username if acc else None,
            "scheduled_at_utc": post.scheduled_at_utc,
            "published_at_utc": post.updated_at,
            "instagram_media_id": success.instagram_media_id if success else None,
            "attempts": [
                {"n": a.attempt_number, "status": a.status, "error": a.error_detail}
                for a in attempts
            ],
        })
    # Failed history too (errors + retry history), for completeness.
    failed_posts = db.query(ScheduledPost).filter(ScheduledPost.status == "FAILED")
    if account_id:
        failed_posts = failed_posts.filter(ScheduledPost.instagram_account_id == account_id)
    failed_history = []
    for post in failed_posts.order_by(ScheduledPost.updated_at.desc()).limit(200).all():
        attempts = db.query(PublishingAttempt).filter(
            PublishingAttempt.scheduled_post_id == post.id
        ).order_by(PublishingAttempt.attempt_number).all()
        acc = db.get(InstagramAccount, post.instagram_account_id)
        failed_history.append({
            "schedule_id": post.id,
            "account": acc.username if acc else None,
            "scheduled_at_utc": post.scheduled_at_utc,
            "attempts": [
                {"n": a.attempt_number, "status": a.status, "error": a.error_detail}
                for a in attempts
            ],
        })
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "account_id": account_id,
        "totals": totals,
        "per_account": per_account,
        "published_history": history,
        "failed_history": failed_history,
    }


def report_to_csv(report: dict) -> str:
    """Per-account summary CSV for download."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "start_date", "end_date", "account", "detected",
        "scheduled", "published", "failed_attempts", "pending",
    ])
    for row in report["per_account"]:
        writer.writerow([
            report["start_date"], report["end_date"], row["username"],
            row["total_detected"], row["total_scheduled"],
            row["total_published"], row["total_failed"], row["total_pending"],
        ])
    totals = report["totals"]
    writer.writerow([
        report["start_date"], report["end_date"], "TOTAL",
        totals["total_detected"], totals["total_scheduled"],
        totals["total_published"], totals["total_failed"], totals["total_pending"],
    ])
    return out.getvalue()
