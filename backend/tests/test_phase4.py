"""Phase 4 tests: validation rules, scan dedup/rename/missing, API edit.

Drive listing is monkeypatched -- no Google network access.
Run: cd backend && python -m pytest tests -q
"""
import os

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
    User,
)
from app.security import hash_password  # noqa: E402
from app.services import video_detection as vd  # noqa: E402

Base.metadata.create_all(bind=engine)
ensure_extra_columns()
client = TestClient(app)


def _token():
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
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@test.local", "password": "test-password-123"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _meta(duration_ms=30000, width=1080, height=1920):
    return {"durationMillis": str(duration_ms), "width": width, "height": height}


def test_validation_rules():
    assert vd.validate_video({"mimeType": "video/mp4", "size": "1000000", "videoMediaMetadata": _meta()})[0] == "READY"
    assert vd.validate_video({"mimeType": "video/quicktime", "size": "1000000", "videoMediaMetadata": _meta()})[0] == "READY"
    assert vd.validate_video({"mimeType": "video/webm", "size": "1000", "videoMediaMetadata": _meta()})[0] == "NEEDS_REVIEW"
    assert vd.validate_video({"mimeType": "video/mp4", "size": str(300 * 1024 * 1024), "videoMediaMetadata": _meta()})[0] == "NEEDS_REVIEW"
    assert vd.validate_video({"mimeType": "video/mp4", "size": "1000", "videoMediaMetadata": _meta(2000)})[0] == "NEEDS_REVIEW"
    assert vd.validate_video({"mimeType": "video/mp4", "size": "1000", "videoMediaMetadata": _meta(1000000)})[0] == "NEEDS_REVIEW"
    # Missing duration metadata must NOT be marked READY.
    assert vd.validate_video({"mimeType": "video/mp4", "size": "1000"})[0] == "NEW"


def _setup_mapping(db):
    acc = db.query(InstagramAccount).filter_by(username="biz_one").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890001", username="biz_one")
        db.add(acc)
        db.flush()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-p4").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-p4", name="biz_one_folder")
        db.add(folder)
        db.flush()
    mapping = db.query(AccountFolderMapping).filter_by(instagram_account_id=acc.id).first()
    if mapping is None:
        mapping = AccountFolderMapping(
            instagram_account_id=acc.id, drive_folder_id=folder.id,
            confirmed_by_admin=True,
        )
        db.add(mapping)
        db.commit()
    else:
        mapping.drive_folder_id = folder.id
        mapping.is_active = True
        db.commit()
    return acc, folder, mapping


def test_scan_dedup_rename_and_missing(monkeypatch):
    db = SessionLocal()
    acc, folder, mapping = _setup_mapping(db)
    # Clean any previous Phase 4 test rows for this folder.
    db.query(DriveVideo).filter_by(drive_folder_id=folder.id).delete()
    db.commit()

    files_v1 = [
        {"id": "file-a", "name": "reel001.mp4", "mimeType": "video/mp4",
         "size": "5000000", "md5Checksum": "hash-a",
         "thumbnailLink": "https://example.invalid/thumb-a",
         "videoMediaMetadata": _meta()},
        {"id": "file-b", "name": "clip.mov", "mimeType": "video/quicktime",
         "size": "4000000", "md5Checksum": "hash-b",
         "videoMediaMetadata": _meta()},
    ]
    monkeypatch.setattr(vd, "list_folder_videos", lambda token, fid: files_v1)
    result = vd.scan_folder(db, mapping, "fake-token")
    assert result["created"] == 2 and result["found"] == 2
    # Second identical scan: no new rows, no duplicates.
    result2 = vd.scan_folder(db, mapping, "fake-token")
    assert result2["created"] == 0
    assert db.query(DriveVideo).filter_by(drive_folder_id=folder.id).count() == 2
    # Rename + one file gone: rename updates, missing file -> NEEDS_REVIEW.
    files_v2 = [
        {"id": "file-a", "name": "reel001-renamed.mp4", "mimeType": "video/mp4",
         "size": "5000000", "md5Checksum": "hash-a",
         "videoMediaMetadata": _meta()},
    ]
    monkeypatch.setattr(vd, "list_folder_videos", lambda token, fid: files_v2)
    result3 = vd.scan_folder(db, mapping, "fake-token")
    assert result3["missing_marked"] == 1
    row_a = db.query(DriveVideo).filter_by(drive_file_id="file-a").first()
    assert row_a.filename == "reel001-renamed.mp4"
    row_b = db.query(DriveVideo).filter_by(drive_file_id="file-b").first()
    assert row_b.status == "NEEDS_REVIEW"
    db.close()


def test_video_api_edit_and_filters():
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.get("/api/videos?status=NEEDS_REVIEW", headers=h)
    assert r.status_code == 200
    videos = r.json()
    assert len(videos) >= 1
    vid = videos[0]["id"]
    r = client.patch(
        f"/api/videos/{vid}",
        json={"caption": "Test caption", "hashtags": "#test"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["caption"] == "Test caption"
    assert client.get("/api/videos").status_code == 401
