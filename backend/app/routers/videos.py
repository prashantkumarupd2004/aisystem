"""Video library endpoints (Phase 4).

Scanning never deletes Drive originals. Editing here only changes
caption/hashtags in our DB -- it never edits the Drive file.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import AccountFolderMapping, DriveVideo, User
from ..services import video_detection as vd
from ..services import drive as drive_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


class VideoOut(BaseModel):
    id: int
    drive_file_id: str
    drive_folder_id: int
    instagram_account_id: int
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    content_hash: str | None = None
    caption: str | None = None
    hashtags: str | None = None
    thumbnail_url: str | None = None
    validation_notes: str | None = None
    status: str

    model_config = {"from_attributes": True}


class VideoEdit(BaseModel):
    caption: str | None = None
    hashtags: str | None = None


@router.get("", response_model=list[VideoOut])
def list_videos(
    account_id: int | None = None,
    status: str | None = None,
    search: str = "",
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(DriveVideo)
    if account_id:
        q = q.filter(DriveVideo.instagram_account_id == account_id)
    if status:
        q = q.filter(DriveVideo.status == status)
    if search:
        q = q.filter(DriveVideo.filename.ilike(f"%{search}%"))
    return q.order_by(DriveVideo.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{video_id}", response_model=VideoOut)
def get_video(
    video_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    video = db.get(DriveVideo, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


@router.patch("/{video_id}", response_model=VideoOut)
def edit_video(
    video_id: int,
    payload: VideoEdit,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    video = db.get(DriveVideo, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if payload.caption is not None:
        video.caption = payload.caption
    if payload.hashtags is not None:
        video.hashtags = payload.hashtags
    db.commit()
    db.refresh(video)
    return video


@router.post("/scan")
def scan_all(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        results = vd.scan_all_mapped_folders(db)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Video scan failed: {exc}")
    return {"results": results}


@router.post("/scan/{account_id}")
def scan_one(
    account_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    mapping = db.query(AccountFolderMapping).filter(
        AccountFolderMapping.instagram_account_id == account_id,
        AccountFolderMapping.is_active.is_(True),
    ).first()
    if not mapping:
        raise HTTPException(404, "No active folder mapping for this account")
    try:
        access_token, _conn = drive_service.get_valid_access_token(db)
        result = vd.scan_folder(db, mapping, access_token)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Video scan failed: {exc}")
    return result


@router.get("/{video_id}/thumbnail")
def thumbnail(
    video_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    """Return the Drive-generated thumbnail URL for this video, or 404
    when Drive did not provide one. The frontend displays it as an
    <img>; full authenticated video playback arrives with the Phase 6
    media endpoint and is not faked here."""
    video = db.get(DriveVideo, video_id)
    if not video or not video.thumbnail_url:
        raise HTTPException(404, "No thumbnail available for this video")
    return {"thumbnail_url": video.thumbnail_url}
