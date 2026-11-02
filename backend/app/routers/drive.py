"""Google Drive endpoints (Phase 2).

No token, email or refresh token is ever returned by these endpoints.
The OAuth callback is public by necessity (Google redirects the browser
here) but is protected by the signed state token; starting the flow is
admin-only.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import GoogleDriveConnection, User
from ..services import drive as drive_service

router = APIRouter(prefix="/api/drive", tags=["drive"])


@router.get("/oauth/start")
def oauth_start(admin: User = Depends(require_admin)):
    try:
        url, _state = drive_service.build_auth_url()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"auth_url": url}


@router.get("/oauth/callback")
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    format: str = "redirect",
    db: Session = Depends(get_db),
):
    if error:
        raise HTTPException(400, f"Google OAuth error: {error}")
    if not code or not state or not drive_service.verify_state(state):
        raise HTTPException(400, "Invalid or expired OAuth state")
    try:
        token_data = drive_service.exchange_code(code)
        connection = drive_service.save_connection(db, token_data)
    except Exception as exc:
        raise HTTPException(502, f"Google token exchange failed: {exc}")
    if format == "json":
        return {"status": connection.status, "connection_id": connection.id}
    return RedirectResponse(f"{settings.frontend_url}/drive?connected=1")


@router.get("/connection")
def connection(db: Session = Depends(get_db), _=Depends(get_current_user)):
    row = db.query(GoogleDriveConnection).order_by(
        GoogleDriveConnection.id
    ).first()
    if row is None:
        return {"status": "DISCONNECTED", "google_account_email": None}
    return {"status": row.status, "google_account_email": row.google_account_email}


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    row = db.query(GoogleDriveConnection).order_by(
        GoogleDriveConnection.id
    ).first()
    if row is None:
        return {"status": "DISCONNECTED"}
    row.status = "DISCONNECTED"
    row.refresh_token_encrypted = None
    db.commit()
    return {"status": "DISCONNECTED"}


@router.get("/folders")
def folders(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Folders already synced to the DB (no live Drive call)."""
    from ..models import DriveFolder

    return [
        {
            "id": f.id,
            "drive_folder_id": f.drive_folder_id,
            "name": f.name,
            "parent_drive_id": f.parent_drive_id,
        }
        for f in db.query(DriveFolder).order_by(DriveFolder.name).all()
    ]


@router.post("/sync")
def sync(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Live Drive folder discovery + DB sync. Requires a connected Drive."""
    try:
        access_token, _conn = drive_service.get_valid_access_token(db)
        raw = drive_service.list_all_folders(access_token)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Drive folder listing failed: {exc}")
    created, updated = drive_service.sync_folders(db, raw)
    return {"created": created, "updated": updated, "total": len(raw)}


@router.get("/account-folders")
def account_folders(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Candidate folders for account mapping: children of the
    Instagram-Automation root when it exists, else all synced folders."""
    return [
        {
            "id": f.id,
            "drive_folder_id": f.drive_folder_id,
            "name": f.name,
            "parent_drive_id": f.parent_drive_id,
        }
        for f in drive_service.account_folders(db)
    ]


@router.post("/changes/sync")
def changes_sync(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Poll Drive changes (Phase 4 will turn these into video rows).
    Returns changed Drive file IDs + kinds, not video content."""
    try:
        access_token, _conn = drive_service.get_valid_access_token(db)
        result = drive_service.list_changes(db, access_token)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Drive changes polling failed: {exc}")
    return {
        "changed_files": [
            {"file_id": c.get("fileId"), "removed": c.get("removed", False)}
            for c in result["changes"]
        ],
        "new_start_page_token_present": bool(result["new_start_page_token"]),
    }
