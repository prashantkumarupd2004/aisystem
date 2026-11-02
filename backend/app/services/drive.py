"""Google Drive integration (Phase 2).

Real Drive API v3 over HTTPS with httpx -- no fake folder list, no
scraping. Only the official OAuth 2.0 flow is used, with least-privilege
scope (drive.readonly) and tokens encrypted at rest via security.py.

Flow:
  1. Admin calls GET /api/drive/oauth/start -> Google consent URL.
  2. Google redirects to /api/drive/oauth/callback?code=...&state=...
     State is a short-lived signed JWT (no DB row needed, no CSRF hole
     from an unsigned state value).
  3. Callback exchanges the code for access + refresh tokens, stores
     them encrypted, and marks the single central connection CONNECTED.
  4. Folder sync lists folders via Drive files.list (paginated) and
     upserts DriveFolder rows keyed by the permanent Drive folder ID --
     never by name alone.

Changes detection (Phase 4 will use it for video detection):
  get_changes_page_token() / list_changes() wrap Drive changes.list.
  The page token is stored in system_settings, so polling resumes
  where the last poll stopped instead of re-scanning everything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    DriveFolder,
    GoogleDriveConnection,
    OAuthToken,
    SystemSetting,
)
from ..security import create_access_token, decode_access_token, decrypt_token, encrypt_token

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
ROOT_FOLDER_NAME = "Instagram-Automation"


def build_auth_url() -> tuple[str, str]:
    """Return (google_consent_url, signed_state)."""
    if not settings.google_client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is not set. See docs/GOOGLE_DRIVE_SETUP.md"
        )
    # Reuse the JWT helper with a dedicated subject; expiry is handled
    # by the token itself (10 minutes) at callback time.
    state = create_access_token("drive_oauth", "oauth_state")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": settings.google_drive_scopes,
        "access_type": "offline",  # needed for a refresh token
        "prompt": "consent",  # consent every time so a refresh token is issued
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}", state


def verify_state(state: str) -> bool:
    try:
        payload = decode_access_token(state)
    except Exception:
        return False
    return payload.get("sub") == "drive_oauth"


def exchange_code(code: str) -> dict:
    """Exchange an auth code for tokens. Raises on any Google error."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth client credentials are not set")
    resp = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def save_connection(db: Session, token_data: dict) -> GoogleDriveConnection:
    """Upsert the ONE central Drive connection + its OAuth token row."""
    connection = db.query(GoogleDriveConnection).order_by(
        GoogleDriveConnection.id
    ).first()
    if connection is None:
        connection = GoogleDriveConnection()
        db.add(connection)
        db.flush()
    expires_in = token_data.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )
    connection.status = "CONNECTED"
    if token_data.get("refresh_token"):
        connection.refresh_token_encrypted = encrypt_token(
            token_data["refresh_token"]
        )
    token_row = (
        db.query(OAuthToken)
        .filter(
            OAuthToken.provider == "google",
            OAuthToken.drive_connection_id == connection.id,
        )
        .first()
    )
    if token_row is None:
        token_row = OAuthToken(
            provider="google", drive_connection_id=connection.id
        )
        db.add(token_row)
    token_row.access_token_encrypted = encrypt_token(token_data["access_token"])
    if token_data.get("refresh_token"):
        token_row.refresh_token_encrypted = encrypt_token(
            token_data["refresh_token"]
        )
    token_row.expires_at = expires_at
    token_row.scope = settings.google_drive_scopes
    db.commit()
    db.refresh(connection)
    return connection


def get_valid_access_token(db: Session) -> tuple[str, GoogleDriveConnection]:
    """Return a working access token, refreshing it first if expired."""
    connection = db.query(GoogleDriveConnection).order_by(
        GoogleDriveConnection.id
    ).first()
    if connection is None or connection.status != "CONNECTED":
        raise RuntimeError("Google Drive is not connected")
    token_row = (
        db.query(OAuthToken)
        .filter(
            OAuthToken.provider == "google",
            OAuthToken.drive_connection_id == connection.id,
        )
        .first()
    )
    if token_row is None:
        raise RuntimeError("Google Drive token not found; reconnect Drive")
    now = datetime.now(timezone.utc)
    if token_row.expires_at and token_row.expires_at > now + timedelta(seconds=60):
        return decrypt_token(token_row.access_token_encrypted), connection
    if not token_row.refresh_token_encrypted:
        raise RuntimeError("Google Drive token expired and no refresh token stored")
    data = refresh_access_token(decrypt_token(token_row.refresh_token_encrypted))
    token_row.access_token_encrypted = encrypt_token(data["access_token"])
    if data.get("expires_in"):
        token_row.expires_at = now + timedelta(seconds=int(data["expires_in"]))
    db.commit()
    return data["access_token"], connection


def drive_api_get(access_token: str, path: str, params: dict | None = None) -> dict:
    resp = httpx.get(
        f"{DRIVE_API}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params or {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_all_folders(access_token: str) -> list[dict]:
    """All non-trashed folders, paginated. Returns raw Drive file dicts."""
    folders: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict = {
            "q": "mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            "fields": "nextPageToken, files(id, name, parents)",
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token
        data = drive_api_get(access_token, "/files", params)
        folders.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return folders


def sync_folders(db: Session, folders: list[dict]) -> tuple[int, int]:
    """Upsert folders by permanent Drive ID. Returns (created, updated).

    The session is created with autoflush=False, so a folder added
    earlier in the same batch is NOT visible to a later query until it
    is flushed -- track seen IDs in memory to avoid a UNIQUE violation
    when Drive returns the same folder twice (e.g. across pages).
    """
    connection = db.query(GoogleDriveConnection).order_by(
        GoogleDriveConnection.id
    ).first()
    seen: dict[str, DriveFolder] = {
        r.drive_folder_id: r for r in db.query(DriveFolder).all()
    }
    created = updated = 0
    for f in folders:
        row = seen.get(f["id"])
        parents = f.get("parents") or []
        parent = parents[0] if parents else None
        if row is None:
            row = DriveFolder(
                drive_folder_id=f["id"],
                name=f["name"],
                parent_drive_id=parent,
                drive_connection_id=connection.id if connection else None,
            )
            db.add(row)
            db.flush()
            seen[f["id"]] = row
            created += 1
        elif row.name != f["name"] or row.parent_drive_id != parent:
            row.name = f["name"]
            row.parent_drive_id = parent
            updated += 1
    db.commit()
    return created, updated


def account_folders(db: Session) -> list[DriveFolder]:
    """Folders under the Instagram-Automation root, if that root exists;
    otherwise every synced folder (mapping can still use any folder)."""
    root = db.query(DriveFolder).filter(
        DriveFolder.name == ROOT_FOLDER_NAME
    ).first()
    if root is None:
        return db.query(DriveFolder).order_by(DriveFolder.name).all()
    return (
        db.query(DriveFolder)
        .filter(DriveFolder.parent_drive_id == root.drive_folder_id)
        .order_by(DriveFolder.name)
        .all()
    )


def _setting(db: Session, key: str) -> SystemSetting | None:
    return db.query(SystemSetting).filter(SystemSetting.key == key).first()


def get_changes_page_token(db: Session, access_token: str) -> str:
    row = _setting(db, "drive_changes_page_token")
    if row and row.value:
        return row.value
    data = drive_api_get(access_token, "/changes/startPageToken", {})
    token = data["startPageToken"]
    db.add(SystemSetting(key="drive_changes_page_token", value=token))
    db.commit()
    return token


def list_changes(db: Session, access_token: str) -> dict:
    """Poll Drive changes since the stored page token, then advance it."""
    page_token = get_changes_page_token(db, access_token)
    changes: list[dict] = []
    new_token = page_token
    while True:
        params: dict = {"pageToken": page_token, "pageSize": 100}
        data = drive_api_get(access_token, "/changes", params)
        changes.extend(data.get("changes", []))
        new_token = data.get("newStartPageToken", new_token)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    row = _setting(db, "drive_changes_page_token")
    if row is None:
        db.add(SystemSetting(key="drive_changes_page_token", value=new_token))
    else:
        row.value = new_token
    db.commit()
    return {"changes": changes, "new_start_page_token": new_token}
