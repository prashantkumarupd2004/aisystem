"""Phase 7 tests: classification, backoff, dead-letter, reconcile, retry.

Run: cd backend && python -m pytest tests -q
"""
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/aisystem_phase1_test.db")
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY", "ZVw3o6SL9CvNVvLspSFoEb0VdbMBt7eFUHnxkHBw3XE="
)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine, ensure_extra_columns  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AccountFolderMapping,
    DriveFolder,
    DriveVideo,
    InstagramAccount,
    Notification,
    PublishingAttempt,
    ScheduledPost,
    User,
)
from app.security import encrypt_token, hash_password  # noqa: E402
from app.services import errors, publishing  # noqa: E402
from app.services import reconcile as reconcile_service  # noqa: E402
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


def test_classification():
    assert errors.classify_error("PERMANENT: Meta token expired/invalid")[0] == "TOKEN_EXPIRED"
    assert errors.classify_error("PERMANENT: Meta permission revoked/missing")[0] == "PERMISSION_REVOKED"
    assert errors.classify_error("PERMANENT: bad caption")[0] == "PERMANENT"
    assert errors.classify_error("UNCERTAIN: network during publish")[0] == "UNCERTAIN"
    assert errors.classify_error("Daily publishing quota reached")[0] == "QUOTA"
    kind, retry_after = errors.classify_error("Meta rate limit/transient error (code 4): x retry_after=3600")
    assert kind == "RATE_LIMIT" and retry_after == 3600
    assert errors.classify_error("Meta server error 500")[0] == "TEMPORARY"
    # Retry delays.
    assert errors.next_retry_delay(1, "TEMPORARY", None) == timedelta(minutes=15)
    assert errors.next_retry_delay(2, "TEMPORARY", None) == timedelta(minutes=30)
    assert errors.next_retry_delay(1, "RATE_LIMIT", 3600) == timedelta(seconds=3600)
    assert errors.next_retry_delay(1, "RATE_LIMIT", None) == timedelta(minutes=60)


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _setup(db):
    acc = db.query(InstagramAccount).filter_by(username="err_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890222", username="err_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-err"))
        db.add(acc)
        db.flush()
    else:
        # Shared test DB persists across runs; earlier tests may have
        # flipped this account to TOKEN_EXPIRED -- reset for each test.
        acc.connection_status = "ACTIVE"
        acc.access_token_encrypted = encrypt_token("page-token-err")
        db.commit()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-p7").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-p7", name="err_folder")
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


def _post(db, acc, folder, drive_id):
    v = db.query(DriveVideo).filter_by(drive_file_id=drive_id).first()
    if v is None:
        v = DriveVideo(drive_file_id=drive_id, drive_folder_id=folder.id,
                       instagram_account_id=acc.id, filename="e.mp4",
                       mime_type="video/mp4", duration_seconds=30,
                       caption="ErrCap", hashtags="#err", status="READY")
        db.add(v)
        db.commit()
    else:
        v.status = "READY"
        v.caption = "ErrCap"
        v.hashtags = "#err"
        db.commit()
    post = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                         scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
                         timezone="UTC", status="SCHEDULED")
    db.add(post)
    db.commit()
    return post, v


def test_temporary_failure_reschedules_with_backoff():
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-1")
    now = datetime.now(timezone.utc)
    sched.process_due_posts(db, publish_fn=lambda p: (False, None, "Meta server error 500"), now=now)
    db.refresh(post)
    assert post.status == "SCHEDULED"
    # Rescheduled ~15 min after `now` (first attempt backoff).
    # SQLite stores naive datetimes, so normalise before subtracting.
    delta = _aware(post.scheduled_at_utc) - now
    assert 10 <= delta.total_seconds() / 60 <= 20
    db.close()


def test_rate_limit_respects_retry_after():
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-2")
    now = datetime.now(timezone.utc)
    sched.process_due_posts(
        db,
        publish_fn=lambda p: (False, None, "Meta rate limit (code 4) retry_after=3600"),
        now=now,
    )
    db.refresh(post)
    assert post.status == "SCHEDULED"
    delta = _aware(post.scheduled_at_utc) - now
    assert 55 <= delta.total_seconds() / 60 <= 65
    db.close()


def test_dead_letter_after_max_attempts_creates_notification():
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-3")
    # Pre-seed 2 failed attempts, so the next failure is attempt 3 = max.
    for n in (1, 2):
        db.add(PublishingAttempt(scheduled_post_id=post.id, attempt_number=n,
                                 status="FAILED", error_detail="old",
                                 idempotency_key=f"p7-seed-{post.id}-{n}"))
    db.commit()
    before = db.query(Notification).filter_by(instagram_account_id=acc.id).count()
    sched.process_due_posts(db, publish_fn=lambda p: (False, None, "Meta server error 500"))
    db.refresh(post)
    assert post.status == "FAILED"
    after = db.query(Notification).filter_by(instagram_account_id=acc.id).count()
    assert after > before
    db.close()


def test_token_expired_flips_account_health():
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-4")
    sched.process_due_posts(db, publish_fn=lambda p: (False, None, "PERMANENT: Meta token expired/invalid"))
    db.refresh(acc)
    assert acc.connection_status == "TOKEN_EXPIRED"
    db.close()


def test_second_job_for_bad_account_is_left_scheduled():
    """After one job flips an account to TOKEN_EXPIRED, the account's
    other due jobs in the same tick must stay SCHEDULED (so they can
    run after a reconnect), not be marked FAILED one by one."""
    db = SessionLocal()
    acc, folder = _setup(db)
    post1, _ = _post(db, acc, folder, "p7-file-8a")
    post2, _ = _post(db, acc, folder, "p7-file-8b")
    sched.process_due_posts(db, publish_fn=lambda p: (False, None, "PERMANENT: Meta token expired/invalid"))
    db.refresh(post1)
    db.refresh(post2)
    statuses = sorted([post1.status, post2.status])
    assert statuses == ["FAILED", "SCHEDULED"]
    db.close()


def test_reconcile_finds_matching_media(monkeypatch):
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-5")
    post.status = "FAILED"
    db.commit()

    def fake_get(path, params):
        return {"data": [
            {"id": "ig-media-reconciled", "caption": "ErrCap #err",
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "media_type": "VIDEO"},
        ]}

    monkeypatch.setattr(publishing, "_graph_get", fake_get)
    result = reconcile_service.reconcile_uncertain(db, post)
    assert result["found"] is True
    assert result["instagram_media_id"] == "ig-media-reconciled"
    db.refresh(post)
    assert post.status == "PUBLISHED"
    db.close()


def test_reconcile_no_match_stays_failed(monkeypatch):
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-6")
    post.status = "FAILED"
    db.commit()
    monkeypatch.setattr(publishing, "_graph_get", lambda path, params: {"data": []})
    result = reconcile_service.reconcile_uncertain(db, post)
    assert result["found"] is False
    db.refresh(post)
    assert post.status == "FAILED"
    db.close()


def test_retry_and_failed_jobs_endpoints():
    h = {"Authorization": f"Bearer {_token()}"}
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p7-file-7")
    post.status = "FAILED"
    db.commit()
    post_id = post.id
    db.close()
    r = client.get("/api/failed-jobs", headers=h)
    assert r.status_code == 200
    assert any(j["id"] == post_id for j in r.json())
    r = client.post(f"/api/schedules/{post_id}/retry", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SCHEDULED"
    # Retrying a non-FAILED job must be rejected.
    r = client.post(f"/api/schedules/{post_id}/retry", headers=h)
    assert r.status_code == 400
    assert client.get("/api/failed-jobs").status_code == 401
