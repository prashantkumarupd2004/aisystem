"""Phase 2 tests: Drive OAuth state/URL, folder sync, changes token.

Uses the same file DB as test_phase1 (shared session, unique names).
Drive HTTP calls are monkeypatched -- no Google network access.
Run: cd backend && python -m pytest tests -q
"""
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/aisystem_phase1_test.db")
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY", "ZVw3o6SL9CvNVvLspSFoEb0VdbMBt7eFUHnxkHBw3XE="
)
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DriveFolder, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import drive as drive_service  # noqa: E402

Base.metadata.create_all(bind=engine)
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


def test_oauth_start_url_and_state():
    # Settings were already instantiated when test_phase1 imported the
    # app, so set the client id directly instead of relying on env.
    settings.google_client_id = "test-client-id.apps.googleusercontent.com"
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.get("/api/drive/oauth/start", headers=h)
    assert r.status_code == 200, r.text
    url = r.json()["auth_url"]
    assert "accounts.google.com" in url
    assert "drive.readonly" in url
    assert "test-client-id" in url
    # State must be a signed JWT that verifies, and a tampered one must not.
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(url).query)["state"][0]
    assert drive_service.verify_state(state) is True
    assert drive_service.verify_state(state + "tampered") is False


def test_oauth_start_requires_admin_auth():
    assert client.get("/api/drive/oauth/start").status_code == 401


def test_folder_sync_upserts_by_drive_id(monkeypatch):
    pages = [
        {"files": [{"id": "drive-root-1", "name": "Instagram-Automation", "parents": []},
                   {"id": "drive-xyz-1", "name": "XYZ", "parents": ["drive-root-1"]}],
         "nextPageToken": "page2"},
        {"files": [{"id": "drive-xyz-1", "name": "XYZ-renamed", "parents": ["drive-root-1"]}]},
    ]
    calls = {"n": 0}

    def fake_get(token, path, params=None):
        assert token == "fake-access"
        out = pages[calls["n"]]
        calls["n"] += 1
        return out

    monkeypatch.setattr(drive_service, "drive_api_get", fake_get)
    folders = drive_service.list_all_folders("fake-access")
    assert len(folders) == 3  # paginated, including the renamed duplicate row
    db = SessionLocal()
    created, updated = drive_service.sync_folders(db, folders)
    # Second sync of the same IDs must update, not duplicate.
    created2, updated2 = drive_service.sync_folders(db, folders)
    assert db.query(DriveFolder).filter_by(drive_folder_id="drive-xyz-1").count() == 1
    assert db.query(DriveFolder).filter_by(drive_folder_id="drive-xyz-1").first().name == "XYZ-renamed"
    db.close()


def test_account_folders_prefers_root_children():
    db = SessionLocal()
    children = drive_service.account_folders(db)
    names = [f.name for f in children]
    # If the root from the previous test exists, only its children count.
    if "Instagram-Automation" in [f.name for f in db.query(DriveFolder).all()]:
        assert "Instagram-Automation" not in names
    db.close()


def test_drive_endpoints_never_leak_tokens():
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.get("/api/drive/connection", headers=h)
    assert r.status_code == 200
    assert "token" not in r.text.lower()
    assert "refresh" not in r.text.lower()


def test_changes_polling_advances_token(monkeypatch):
    db = SessionLocal()
    # Seed a start token so no startPageToken call is needed.
    from app.models import SystemSetting

    row = db.query(SystemSetting).filter_by(key="drive_changes_page_token").first()
    if row is None:
        db.add(SystemSetting(key="drive_changes_page_token", value="start-1"))
        db.commit()
    else:
        row.value = "start-1"
        db.commit()

    def fake_get(token, path, params=None):
        assert path == "/changes"
        return {"changes": [{"fileId": "file-1", "removed": False}],
                "newStartPageToken": "start-2"}

    monkeypatch.setattr(drive_service, "drive_api_get", fake_get)
    result = drive_service.list_changes(db, "fake-access")
    assert result["changes"][0]["fileId"] == "file-1"
    row = db.query(SystemSetting).filter_by(key="drive_changes_page_token").first()
    assert row.value == "start-2"
    db.close()
