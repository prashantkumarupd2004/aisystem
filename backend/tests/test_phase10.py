"""Phase 10 tests: end-to-end integration + security checks.

Run: cd backend && python -m pytest tests -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    ScheduledPost,
    User,
)
from app.security import encrypt_token, hash_password  # noqa: E402
from app.services import reports as report_service  # noqa: E402
from app.services import scheduler as sched  # noqa: E402

Base.metadata.create_all(bind=engine)
ensure_extra_columns()
client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import security_check  # noqa: E402


def _login(email, password):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _admin_token():
    db = SessionLocal()
    if not db.query(User).filter(User.email == "admin@test.local").first():
        db.add(User(email="admin@test.local", hashed_password=hash_password("test-password-123"), role="admin"))
        db.commit()
    # A non-admin viewer for role tests.
    if not db.query(User).filter(User.email == "viewer@test.local").first():
        db.add(User(email="viewer@test.local", hashed_password=hash_password("viewer-pass-123"), role="user"))
        db.commit()
    db.close()
    return _login("admin@test.local", "test-password-123")


def test_end_to_end_video_to_published_to_report():
    """Integration: video READY -> scheduled -> published (fake
    publisher, as in earlier phases) -> report counts it -> health
    shows a last-published time. One chain, no mocked DB rows."""
    h = {"Authorization": f"Bearer {_admin_token()}"}
    db = SessionLocal()
    acc = db.query(InstagramAccount).filter_by(username="e2e_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890555", username="e2e_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-e2e"))
        db.add(acc)
        db.flush()
    else:
        acc.connection_status = "ACTIVE"
        acc.access_token_encrypted = encrypt_token("page-token-e2e")
        db.commit()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-e2e").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-e2e", name="e2e_folder")
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
    v = db.query(DriveVideo).filter_by(drive_file_id="e2e-file-1").first()
    if v is None:
        v = DriveVideo(drive_file_id="e2e-file-1", drive_folder_id=folder.id,
                       instagram_account_id=acc.id, filename="e2e.mp4",
                       mime_type="video/mp4", duration_seconds=30, status="READY")
        db.add(v)
        db.commit()
    else:
        v.status = "READY"
        db.commit()
    # Schedule via the API, not by inserting a row directly.
    r = client.post("/api/schedules", json={
        "instagram_account_id": acc.id, "drive_video_id": v.id,
        "scheduled_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "timezone": "UTC",
    }, headers=h)
    assert r.status_code in (200, 201), r.text
    post_id = r.json()["id"]
    # Worker processes it.
    sched.process_due_posts(db, publish_fn=lambda p: (True, "ig-media-e2e", None))
    post = db.get(ScheduledPost, post_id)
    assert post.status == "PUBLISHED"
    # Report + health reflect the same chain.
    today = datetime.now(timezone.utc).date()
    row = report_service.generate_daily_report(db, today, acc.id)
    assert row.total_published >= 1
    r = client.get("/api/health/accounts", headers=h)
    assert r.status_code == 200
    acc_row = [a for a in r.json()["accounts"] if a["username"] == "e2e_acct"]
    assert acc_row and acc_row[0]["last_published_at"] is not None
    db.close()


def test_tokens_never_appear_in_api_responses():
    h = {"Authorization": f"Bearer {_admin_token()}"}
    secret = "page-token-leak-test-xyz"
    r = client.post("/api/accounts", json={
        "instagram_user_id": "17890666", "username": "leak_acct",
        "account_type": "BUSINESS", "access_token": secret,
    }, headers=h)
    assert r.status_code in (200, 201, 409), r.text
    if r.status_code == 409:
        return  # already created by a previous run; token was never returned then either
    assert secret not in r.text
    assert "access_token_encrypted" not in r.text
    r = client.get("/api/accounts?search=leak_acct", headers=h)
    assert r.status_code == 200
    assert secret not in r.text
    assert "access_token_encrypted" not in r.text


def test_protected_endpoints_require_auth_and_admin():
    viewer = _login("viewer@test.local", "viewer-pass-123")
    vh = {"Authorization": f"Bearer {viewer}"}
    for path in ("/api/accounts", "/api/videos", "/api/schedules", "/api/health/accounts",
                 "/api/reports?start=2026-11-02&end=2026-11-02", "/api/failed-jobs",
                 "/api/notifications"):
        assert client.get(path).status_code == 401, path
    # Viewer (non-admin) cannot use admin-only endpoints.
    assert client.post("/api/reports/generate?report_date=2026-11-02", headers=vh).status_code in (401, 403)
    assert client.post("/api/health/check-all", headers=vh).status_code in (401, 403)


def test_login_injection_does_not_bypass_auth():
    r = client.post("/api/auth/login", data={
        "username": "admin@test.local' OR '1'='1", "password": "anything"})
    assert r.status_code == 401


def test_media_path_traversal_and_tampered_token_rejected():
    # No valid media token exists in this test; traversal / tampering
    # must return 404, never a file.
    for bad in ("/media/..%2F..%2Fetc%2Fpasswd/x.mp4",
                "/media/invalid-token-123/video.mp4"):
        r = client.get(bad)
        assert r.status_code in (401, 404), bad


def test_security_check_script_passes():
    assert security_check.check() == []
