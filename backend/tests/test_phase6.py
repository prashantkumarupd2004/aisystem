"""Phase 6 tests: Meta publish flow, media endpoint, error classes.

Graph + Drive HTTP calls are monkeypatched -- no Meta/Google network.
Run: cd backend && python -m pytest tests -q
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    ScheduledPost,
    User,
)
from app.security import encrypt_token, hash_password  # noqa: E402
from app.services import media_delivery, publishing, scheduler as sched  # noqa: E402
from app.services import drive as drive_service  # noqa: E402

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
    acc = db.query(InstagramAccount).filter_by(username="pub_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890111", username="pub_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-pub"))
        db.add(acc)
        db.flush()
    else:
        # Shared test DB persists across runs; reset status/token.
        acc.connection_status = "ACTIVE"
        acc.access_token_encrypted = encrypt_token("page-token-pub")
        db.commit()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-p6").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-p6", name="pub_folder")
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
                       instagram_account_id=acc.id, filename="reel.mp4",
                       mime_type="video/mp4", duration_seconds=30,
                       caption="Hello", hashtags="#test", status="READY")
        db.add(v)
        db.commit()
    else:
        v.status = "READY"
        v.caption = "Hello"
        v.hashtags = "#test"
        db.commit()
    post = ScheduledPost(instagram_account_id=acc.id, drive_video_id=v.id,
                         scheduled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=5),
                         timezone="UTC", status="SCHEDULED")
    db.add(post)
    db.commit()
    return post, v


def test_full_publish_flow_mocked(monkeypatch):
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p6-file-1")
    post_id = post.id

    def fake_download(token, drive_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-video-bytes-0123456789")
        return dest

    monkeypatch.setattr(media_delivery, "download_from_drive", fake_download)
    monkeypatch.setattr(drive_service, "get_valid_access_token", lambda db_: ("drive-token", None))
    monkeypatch.setattr(publishing, "_check_codec", lambda path: None)
    calls = {"media_url": None}

    def fake_post(path, params):
        if path.endswith("/media"):
            calls["media_url"] = params["video_url"]
            assert params["media_type"] == "REELS"
            assert params["caption"] == "Hello #test"
            return {"id": "container-1"}
        if path.endswith("/media_publish"):
            assert params["creation_id"] == "container-1"
            return {"id": "ig-media-999"}
        raise AssertionError(f"unexpected POST {path}")

    def fake_get(path, params):
        assert path == "/container-1"
        return {"status_code": "FINISHED", "status": {}}

    monkeypatch.setattr(publishing, "_graph_post", fake_post)
    monkeypatch.setattr(publishing, "_graph_get", fake_get)
    success, media_id, error = publishing.publish_reel(db, post, poll_interval=0)
    assert success is True and media_id == "ig-media-999" and error is None, error
    assert calls["media_url"] is not None
    # Temp file must be cleaned up after publishing.
    assert not list(Path(settings.media_temp_dir).glob(f"post-{post_id}-*"))
    db.close()


def test_container_error_is_failure_not_success(monkeypatch):
    db = SessionLocal()
    acc, folder = _setup(db)
    post, video = _post(db, acc, folder, "p6-file-2")
    monkeypatch.setattr(media_delivery, "download_from_drive",
                        lambda token, drive_id, dest: (dest.parent.mkdir(parents=True, exist_ok=True), dest.write_bytes(b"x"))[1] or dest)
    monkeypatch.setattr(drive_service, "get_valid_access_token", lambda db_: ("drive-token", None))
    monkeypatch.setattr(publishing, "_check_codec", lambda path: None)
    monkeypatch.setattr(publishing, "_graph_post", lambda path, params: {"id": "container-2"})
    monkeypatch.setattr(publishing, "_graph_get", lambda path, params: {"status_code": "ERROR", "status": {"error": "bad video"}})
    success, media_id, error = publishing.publish_reel(db, post, poll_interval=0)
    assert success is False and media_id is None
    assert "ERROR" in error
    db.close()


def test_media_endpoint_range_and_head():
    # Create a temp file + signed URL directly, without a publish run.
    post_id = 424242
    path = media_delivery.temp_path_for(post_id, "clip.mp4")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0123456789ABCDEFGHIJ")
    try:
        url = media_delivery.create_signed_media_url(post_id, "clip.mp4")
        # URL is {base}/{token}/{filename}; strip the base to get the path.
        rel = "/" + "/".join(url.split("/")[3:])
        r = client.get(rel, headers={"Range": "bytes=0-9"})
        assert r.status_code == 206, r.status_code
        assert r.content == b"0123456789"
        assert r.headers["Content-Range"] == "bytes 0-9/20"
        r = client.head(rel)
        assert r.status_code == 200
        assert r.headers["Content-Length"] == "20"
        # Tampered token must not serve the file.
        bad = rel.rsplit("/", 2)[0] + "/tampered/clip.mp4"
        assert client.get(bad).status_code == 404
    finally:
        path.unlink(missing_ok=True)


def test_scheduler_never_retries_permanent_or_uncertain():
    db = SessionLocal()
    # Use a dedicated account for this test: the shared DB contains
    # leftover due posts for pub_acct from earlier tests, and a
    # permanent failure for one of them would flip pub_acct to
    # TOKEN_EXPIRED before this post is reached (correct behaviour,
    # wrong test setup). A fresh account avoids that interference.
    acc = db.query(InstagramAccount).filter_by(username="perm_acct").first()
    if acc is None:
        acc = InstagramAccount(instagram_user_id="17890333", username="perm_acct",
                               account_type="BUSINESS", connection_status="ACTIVE",
                               access_token_encrypted=encrypt_token("page-token-perm"))
        db.add(acc)
        db.flush()
    else:
        acc.connection_status = "ACTIVE"
        acc.access_token_encrypted = encrypt_token("page-token-perm")
        db.commit()
    folder = db.query(DriveFolder).filter_by(drive_folder_id="drive-folder-perm").first()
    if folder is None:
        folder = DriveFolder(drive_folder_id="drive-folder-perm", name="perm_folder")
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
    post, video = _post(db, acc, folder, "p6-file-perm")
    called_ids = []
    post_id = post.id

    def permanent_publisher(p):
        called_ids.append(p.id)
        return False, None, "PERMANENT: token expired"

    sched.process_due_posts(db, publish_fn=permanent_publisher)
    db.refresh(post)
    assert post.status == "FAILED"
    # Second run: FAILED jobs are not reprocessed, publisher not called again.
    sched.process_due_posts(db, publish_fn=permanent_publisher)
    assert called_ids.count(post_id) == 1
    db.close()


def test_media_endpoint_requires_valid_token():
    assert client.get("/media/badtoken/clip.mp4").status_code == 404
