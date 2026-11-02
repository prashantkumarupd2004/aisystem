"""Phase 3 tests: Meta OAuth URL/state, Page->IG sync, health checks.

Meta Graph HTTP calls are monkeypatched -- no Meta network access.
Shares the file DB with test_phase1/2; uses unique IG ids.
Run: cd backend && python -m pytest tests -q
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/aisystem_phase1_test.db")
os.environ.setdefault(
    "TOKEN_ENCRYPTION_KEY", "ZVw3o6SL9CvNVvLspSFoEb0VdbMBt7eFUHnxkHBw3XE="
)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import InstagramAccount, User  # noqa: E402
from app.security import decrypt_token, hash_password  # noqa: E402
from app.services import instagram as ig  # noqa: E402

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
    settings.meta_app_id = "123456789"
    h = {"Authorization": f"Bearer {_token()}"}
    r = client.get("/api/instagram/oauth/start", headers=h)
    assert r.status_code == 200, r.text
    url = r.json()["auth_url"]
    assert "facebook.com" in url and "dialog/oauth" in url
    assert "instagram_content_publish" in url
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(url).query)["state"][0]
    assert ig.verify_state(state) is True
    assert ig.verify_state("bogus") is False


def test_sync_creates_only_eligible_and_upserts(monkeypatch):
    pages = [
        {"id": "page-1", "name": "Page One", "access_token": "page-token-1",
         "instagram_business_account": {"id": "17890001", "username": "biz_one"}},
        {"id": "page-2", "name": "Page Two", "access_token": "page-token-2",
         "instagram_business_account": None},  # personal / unlinked: skipped
    ]
    monkeypatch.setattr(ig, "list_pages_with_instagram", lambda token: pages)
    monkeypatch.setattr(
        ig, "get_ig_profile",
        lambda ig_id, token: {"id": ig_id, "username": "biz_one",
                              "account_type": "BUSINESS",
                              "profile_picture_url": "https://example.invalid/pic.jpg"},
    )
    db = SessionLocal()
    result = ig.sync_accounts(db, "user-token")
    assert result["connected"] == ["biz_one"]
    assert len(result["skipped"]) == 1
    acc = db.query(InstagramAccount).filter_by(instagram_user_id="17890001").first()
    assert acc is not None
    # Stored token is encrypted, and decrypts back to the Page token.
    assert acc.access_token_encrypted != "page-token-1"
    assert decrypt_token(acc.access_token_encrypted) == "page-token-1"
    # Second sync must not duplicate.
    ig.sync_accounts(db, "user-token")
    assert db.query(InstagramAccount).filter_by(instagram_user_id="17890001").count() == 1
    db.close()


def test_check_maps_graph_190_to_token_expired(monkeypatch):
    db = SessionLocal()
    acc = db.query(InstagramAccount).filter_by(instagram_user_id="17890001").first()
    assert acc is not None

    def fake_get(*args, **kwargs):
        request = httpx.Request("GET", "https://graph.facebook.com/test")
        response = httpx.Response(
            400, json={"error": {"code": 190, "message": "Session expired"}},
            request=request,
        )
        raise httpx.HTTPStatusError("bad", request=request, response=response)

    monkeypatch.setattr(ig, "get_ig_profile", fake_get)
    status = ig.check_account(db, acc)
    assert status == "TOKEN_EXPIRED"
    db.refresh(acc)
    assert acc.connection_status == "TOKEN_EXPIRED"
    db.close()


def test_check_success_is_api_accessible_only(monkeypatch):
    db = SessionLocal()
    acc = db.query(InstagramAccount).filter_by(instagram_user_id="17890001").first()
    monkeypatch.setattr(
        ig, "get_ig_profile",
        lambda ig_id, token: {"username": "biz_one", "account_type": "BUSINESS"},
    )
    status = ig.check_account(db, acc)
    assert status == "ACTIVE"
    from app.models import AccountHealth

    health = db.query(AccountHealth).filter_by(instagram_account_id=acc.id).first()
    assert "does not confirm" in (health.detail or "")
    db.close()


def test_instagram_endpoints_require_auth():
    assert client.get("/api/instagram/oauth/start").status_code == 401
