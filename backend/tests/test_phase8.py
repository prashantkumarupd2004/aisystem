"""Phase 8 tests: reports, health summary, alerts honesty, check-all.

Run: cd backend && python -m pytest tests -q
"""
import os
from datetime import date, datetime, timedelta, timezone

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
    PublishingAttempt,
    ScheduledPost,
    User,
)
from app.security import encrypt_token, hash_password  # noqa: E402
from app.services import alerts, health as health_service  # noqa: E402
from app.services import instagram as ig_service  # noqa: E402
from app.services import reports as report_service  # noqa: E402
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
    acc = db.query(InstagramAccount).filter_by(username="rep_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890444", username="rep_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-rep"))
        db.add(acc)
        db.flush()
    else:
        acc.connection_status = "ACTIVE"
        acc.access_token_encrypted = encrypt_token("page-token-rep")
        db.commit()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-p8").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-p8", name="rep_folder")
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


def test_daily_report_counts_for_one_account():
    db = SessionLocal()
    acc, folder = _setup(db)
    today = datetime.now(timezone.utc).date()
    # One video detected today for this account.
    v = DriveVideo(drive_file_id="p8-file-1", drive_folder_id=folder.id,
                   instagram_account_id=acc.id, filename="r.mp4",
                   mime_type="video/mp4", duration_seconds=30, status="READY")
    db.add(v)
    db.commit()
    row = report_service.generate_daily_report(db, today, acc.id)
    assert row.total_detected >= 1
    # The report row is upserted, not duplicated, on re-generation.
    row2 = report_service.generate_daily_report(db, today, acc.id)
    assert row2.id == row.id
    db.close()


def test_range_report_and_csv():
    h = {"Authorization": f"Bearer {_token()}"}
    today = datetime.now(timezone.utc).date().isoformat()
    r = client.get(f"/api/reports?start={today}&end={today}", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "totals" in data and "per_account" in data and "published_history" in data
    r = client.get(f"/api/reports/export.csv?start={today}&end={today}", headers=h)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "account,detected" in r.text or "start_date" in r.text
    assert client.get("/api/reports").status_code == 401


def test_health_summary_and_last_published():
    db = SessionLocal()
    acc, folder = _setup(db)
    # Publish one job via the scheduler fake publisher, then health
    # must show a last_published_at for this account.
    v = db.query(DriveVideo).filter_by(drive_file_id="p8-file-2").first()
    if v is None:
        v = DriveVideo(drive_file_id="p8-file-2", drive_folder_id=folder.id,
                       instagram_account_id=acc.id, filename="r2.mp4",
                       mime_type="video/mp4", duration_seconds=30, status="READY")
        db.add(v)
        db.commit()
    else:
        v.status = "READY"
        db.commit()
    post = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                         scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
                         timezone="UTC", status="SCHEDULED")
    db.add(post)
    db.commit()
    sched.process_due_posts(db, publish_fn=lambda p: (True, "ig-media-p8", None))
    summary = health_service.health_summary(db)
    row = [a for a in summary["accounts"] if a["username"] == "rep_acct"]
    assert row and row[0]["last_published_at"] is not None
    assert summary["total_connected"] >= 1
    db.close()


def test_check_all_uses_live_check_function(monkeypatch):
    h = {"Authorization": f"Bearer {_token()}"}
    monkeypatch.setattr(ig_service, "check_account", lambda db, acc: "ACTIVE")
    r = client.post("/api/health/check-all", headers=h)
    assert r.status_code == 200, r.text
    assert "checked" in r.json() and "summary" in r.json()


def test_alerts_do_not_claim_success_when_unconfigured():
    # With no SMTP/Telegram env, both channels must report not configured.
    from app.config import settings

    settings.smtp_host = None
    settings.telegram_bot_token = None
    results = alerts.send_alerts("test", "body")
    assert all(r["sent"] is False for r in results)
    assert any("not configured" in (r.get("reason") or "") for r in results)
