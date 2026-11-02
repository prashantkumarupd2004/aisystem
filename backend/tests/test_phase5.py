"""Phase 5 tests: timezone conversion, bulk atomicity, worker behaviour.

Worker publishing uses a fake publisher injected into process_due_posts
only -- production code ships with no publisher until Phase 6.
Run: cd backend && python -m pytest tests -q
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/aisystem_phase1_test.db")
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY", "ZVw3o6SL9CvNVvLspSFoEb0VdbMBt7eFUHnxkHBw3XE="
)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine, ensure_extra_columns  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccountFolderMapping,
    DriveFolder,
    DriveVideo,
    InstagramAccount,
    PublishingAttempt,
    ScheduledPost,
    User,
)
from app.security import encrypt_token, hash_password  # noqa: E402
from app.services import scheduler as sched  # noqa: E402

Base.metadata.create_all(bind=engine)
ensure_extra_columns()
client = TestClient(app)


def _token():
    db = SessionLocal()
    if not db.query(User).filter(User.email == "admin@test.local").first():
        db.add(User(email="admin@test.local", hashed_password=hash_password("test-password-123"), role="admin"))
        db.commit()
    db.close()
    r = client.post("/api/auth/login", data={"username": "admin@test.local", "password": "test-password-123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _setup(db):
    acc = db.query(InstagramAccount).filter_by(username="sched_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890099", username="sched_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-sched"))
        db.add(acc)
        db.flush()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-p5").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-p5", name="sched_folder")
        db.add(folder)
        db.flush()
    mapping = db.query(AccountFolderMapping).filter_by(instagram_account_id=acc.id).first()
    if mapping is None:
        mapping = AccountFolderMapping(instagram_account_id=acc.id, drive_folder_id=folder.id, confirmed_by_admin=True)
        db.add(mapping)
        db.commit()
    else:
        mapping.drive_folder_id = folder.id
        mapping.is_active = True
        db.commit()
    return acc, folder


def _video(db, acc, folder, drive_id, name):
    v = db.query(DriveVideo).filter_by(drive_file_id=drive_id).first()
    if v is None:
        v = DriveVideo(drive_file_id=drive_id, drive_folder_id=folder.id,
                       instagram_account_id=acc.id, filename=name,
                       mime_type="video/mp4", duration_seconds=30, status="READY")
        db.add(v)
        db.commit()
    else:
        v.status = "READY"
        v.drive_folder_id = folder.id
        v.instagram_account_id = acc.id
        db.commit()
    return v


def test_timezone_conversion_kolkata_to_utc():
    # 10:00 IST = 04:30 UTC (IST is UTC+5:30, no DST).
    utc_dt = sched.local_to_utc(datetime(2026, 11, 10, 10, 0), "Asia/Kolkata")
    assert utc_dt.hour == 4 and utc_dt.minute == 30
    assert utc_dt.tzinfo == timezone.utc


def test_api_schedule_and_bulk_atomicity():
    h = {"Authorization": f"Bearer {_token()}"}
    db = SessionLocal()
    acc, folder = _setup(db)
    v1 = _video(db, acc, folder, "p5-file-1", "one.mp4")
    v2 = _video(db, acc, folder, "p5-file-2", "two.mp4")
    acc_id, v1_id, v2_id = acc.id, v1.id, v2.id
    db.close()
    # Single: local Kolkata time converts to UTC in storage.
    r = client.post("/api/schedules", json={
        "instagram_account_id": acc_id, "drive_video_id": v1_id,
        "scheduled_at_local": "2026-11-10T10:00:00", "timezone": "Asia/Kolkata"},
        headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["scheduled_at_utc"].startswith("2026-11-10T04:30")
    # Bulk with one invalid video (not READY / not found) creates nothing.
    db = SessionLocal()
    v2_row = db.get(DriveVideo, v2_id)
    v2_row.status = "NEEDS_REVIEW"
    db.commit()
    db.close()
    before = client.get("/api/schedules?account_id=" + str(acc_id), headers=h).json()
    r = client.post("/api/schedules/bulk", json=[
        {"instagram_account_id": acc_id, "drive_video_id": v2_id,
         "scheduled_at": "2026-11-11T10:00:00+00:00", "timezone": "UTC"},
    ], headers=h)
    assert r.status_code == 400
    after = client.get("/api/schedules?account_id=" + str(acc_id), headers=h).json()
    assert len(after) == len(before)


def test_worker_publishes_once_and_recurs():
    db = SessionLocal()
    acc, folder = _setup(db)
    v = _video(db, acc, folder, "p5-file-3", "three.mp4")
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    post = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                         scheduled_at_utc=past, timezone="UTC",
                         recurrence_rule="daily", status="SCHEDULED")
    db.add(post)
    db.commit()
    post_id = post.id
    calls = {"n": 0}

    def fake_publish(p):
        calls["n"] += 1
        return True, "ig-media-123", None

    result = sched.process_due_posts(db, publish_fn=fake_publish)
    assert result["published"] == 1
    db.refresh(post)
    assert post.status == "PUBLISHED"
    # Second run must not call the publisher again (idempotency).
    result2 = sched.process_due_posts(db, publish_fn=fake_publish)
    assert calls["n"] == 1
    # Recurring next occurrence exists for tomorrow.
    nxt = db.query(ScheduledPost).filter(
        ScheduledPost.instagram_account_id == acc.id,
        ScheduledPost.drive_video_id == v.id,
        ScheduledPost.status == "SCHEDULED").first()
    assert nxt is not None
    assert nxt.scheduled_at_utc.date() == (past + timedelta(days=1)).date()
    db.close()


def test_worker_paused_and_quota_postpone():
    db = SessionLocal()
    acc, folder = _setup(db)
    v = _video(db, acc, folder, "p5-file-4", "four.mp4")
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    paused = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                           scheduled_at_utc=past, timezone="UTC",
                           status="SCHEDULED", is_paused=True)
    db.add(paused)
    db.commit()
    called = []
    sched.process_due_posts(db, publish_fn=lambda p: called.append(p) or (True, "x", None))
    assert called == []  # paused jobs must never reach the publisher
    db.refresh(paused)
    assert paused.status == "SCHEDULED"  # paused jobs are never published
    # Quota: set cap to 0 temporarily so any due job postpones.
    old_cap = settings.max_reels_per_account_per_day
    settings.max_reels_per_account_per_day = 0
    try:
        v2 = _video(db, acc, folder, "p5-file-5", "five.mp4")
        due = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v2.id,
                            scheduled_at_utc=past, timezone="UTC", status="SCHEDULED")
        db.add(due)
        db.commit()
        due_id = due.id
        old_date = due.scheduled_at_utc.date()
        sched.process_due_posts(db, publish_fn=lambda p: (True, "x", None))
        db.refresh(due)
        assert due.status == "SCHEDULED"
        assert due.scheduled_at_utc.date() != old_date
    finally:
        settings.max_reels_per_account_per_day = old_cap
    db.close()


def test_worker_mapping_mismatch_fails_without_publishing():
    db = SessionLocal()
    acc, folder = _setup(db)
    # Video in a DIFFERENT folder than the account mapping.
    other_folder = DriveFolder(drive_folder_id="drive-folder-other", name="other")
    db.add(other_folder)
    db.flush()
    v = DriveVideo(drive_file_id="p5-file-wrong", drive_folder_id=other_folder.id,
                   instagram_account_id=acc.id, filename="wrong.mp4",
                   mime_type="video/mp4", duration_seconds=30, status="READY")
    db.add(v)
    db.commit()
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    post = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                         scheduled_at_utc=past, timezone="UTC", status="SCHEDULED")
    db.add(post)
    db.commit()
    called = []
    sched.process_due_posts(db, publish_fn=lambda p: called.append(p) or (True, "x", None))
    assert called == []
    db.refresh(post)
    assert post.status == "FAILED"
    db.close()
