"""Phase 1 tests: auth, token encryption, mapping isolation, dashboard.

Run:  cd backend && python -m pytest tests -q
Uses an in-memory SQLite DB; no network, no Meta/Google calls.
"""
import os
from pathlib import Path

_TEST_DB = Path("/tmp/aisystem_phase1_test.db")
if _TEST_DB.exists():
    _TEST_DB.unlink()
# File-based SQLite (not :memory:) so the pooled connections used by
# TestClient all see the same tables.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["TOKEN_ENCRYPTION_KEY"] = "ZVw3o6SL9CvNVvLspSFoEb0VdbMBt7eFUHnxkHBw3XE="  # test-only key
# NOTE: the key above is a random test fixture, not a real credential.

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    DriveFolder,
    DriveVideo,
    InstagramAccount,
    ScheduledPost,
    User,
)
from app.security import decrypt_token, encrypt_token, hash_password  # noqa: E402
from app.services.mapping import (  # noqa: E402
    MappingMismatch,
    validate_publish_eligibility,
)
from datetime import datetime, timezone  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _admin():
    db = SessionLocal()
    if not db.query(User).filter(User.email == "admin@test.local").first():
        db.add(
            User(
                email="admin@test.local",
                hashed_password=hash_password("test-password-123"),
                role="admin",
            )
        )
        db.commit()
    db.close()


def _token():
    _admin()
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@test.local", "password": "test-password-123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_token_roundtrip_and_never_in_response():
    blob = encrypt_token("secret-token-xyz")
    assert blob != "secret-token-xyz"
    assert decrypt_token(blob) == "secret-token-xyz"
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.post(
        "/api/accounts",
        json={"instagram_user_id": "17841", "username": "XYZ",
              "access_token": "secret-token-xyz"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert "secret-token-xyz" not in r.text
    assert "access_token" not in r.text


def test_mapping_mismatch_blocks_publish():
    db = SessionLocal()
    xyz = db.query(InstagramAccount).filter_by(username="XYZ").first()
    folder_xyz = DriveFolder(drive_folder_id="drive-xyz", name="XYZ")
    folder_abc = DriveFolder(drive_folder_id="drive-abc", name="ABC")
    db.add_all([folder_xyz, folder_abc])
    db.commit()
    # Map XYZ -> XYZ folder, then schedule a video from the ABC folder.
    from app.models import AccountFolderMapping

    db.add(
        AccountFolderMapping(
            instagram_account_id=xyz.id,
            drive_folder_id=folder_xyz.id,
            confirmed_by_admin=True,
        )
    )
    wrong_video = DriveVideo(
        drive_file_id="file-wrong", drive_folder_id=folder_abc.id,
        instagram_account_id=xyz.id, filename="reel001.mp4", status="READY",
    )
    db.add(wrong_video)
    db.commit()
    post = ScheduledPost(
        instagram_account_id=xyz.id, drive_video_id=wrong_video.id,
        scheduled_at_utc=datetime.now(timezone.utc), status="SCHEDULED",
    )
    db.add(post)
    db.commit()
    try:
        validate_publish_eligibility(db, post)
    except MappingMismatch:
        pass
    else:
        raise AssertionError("cross-folder publish was not blocked")
    finally:
        db.close()


def test_dashboard_stats_are_real_counts():
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.get("/api/dashboard/stats", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["connected_accounts"] >= 1
    assert data["total_videos"] >= 1


def test_unauthenticated_dashboard_rejected():
    assert client.get("/api/dashboard/stats").status_code == 401
