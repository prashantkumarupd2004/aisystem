"""Video detection + validation (Phase 4).

Sources of truth, in order:
  1. Drive file ID -- a file already in drive_videos is never created
     twice, even if it is renamed. Renames update the stored filename.
  2. Drive md5Checksum (content_hash) -- a second Drive file with the
     same hash in the same folder is flagged NEEDS_REVIEW as a likely
     duplicate, but is still tracked as its own row (it is a different
     Drive file, so deleting one must not delete the other).
  3. Folder ownership -- a file discovered in folder X is only ever
     attached to the account mapped to X. If its Drive ID already
     belongs to a different account, it is skipped and logged; it is
     NEVER reassigned to the scanning account.

Validation (documented, configurable via settings in Phase 5):
  - Allowed containers: video/mp4 and video/quicktime (MOV). Anything
    else -> NEEDS_REVIEW, never silently published.
  - Size: <= 250 MB (Instagram Reels container limit used by Meta docs
    for API uploads; if Meta raises it, raise MAX_VIDEO_SIZE_MB).
  - Duration: 3 s to 900 s (15 min). Missing duration metadata ->
    status stays NEW (cannot be validated yet), not READY.
  - Aspect ratio: if width/height are known, ratio must be 0.2..5.
    Reels are normally 9:16 (0.5625); this range only rejects clearly
    broken metadata, it does not enforce 9:16.
  - Codec: Drive does not expose codec in files.list, so codec is
    NOT claimed as validated here. Phase 6 validates codec after
    download (ffprobe, when available) before creating a container.

Original Drive videos are never deleted, renamed or moved by scanning.
A file that disappears from its folder is marked NEEDS_REVIEW (moved /
deleted in Drive) and logged, but its row is kept for history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AccountFolderMapping,
    DriveFolder,
    DriveVideo,
    InstagramAccount,
    PublishingLog,
)
from . import drive as drive_service

log = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {"video/mp4", "video/quicktime"}
MAX_VIDEO_SIZE_MB = 250
MIN_DURATION_SECONDS = 3
MAX_DURATION_SECONDS = 900


def validate_video(meta: dict) -> tuple[str, list[str]]:
    """Return (status, notes) for Drive file metadata."""
    notes: list[str] = []
    mime = meta.get("mimeType")
    if mime not in ALLOWED_MIME_TYPES:
        notes.append(f"Unsupported mime type: {mime} (only MP4 and MOV)")
    size = meta.get("size")
    if size is not None:
        try:
            size_int = int(size)
        except (TypeError, ValueError):
            size_int = None
        if size_int is not None and size_int > MAX_VIDEO_SIZE_MB * 1024 * 1024:
            notes.append(f"File size exceeds {MAX_VIDEO_SIZE_MB} MB")
    video_meta = meta.get("videoMediaMetadata") or {}
    duration_ms = video_meta.get("durationMillis")
    width = video_meta.get("width")
    height = video_meta.get("height")
    if duration_ms is None:
        # Cannot validate duration yet -- keep as NEW, not READY.
        return "NEW", ["Duration metadata missing from Drive; validation pending"]
    try:
        duration = int(duration_ms) // 1000
    except (TypeError, ValueError):
        return "NEW", ["Duration metadata unreadable; validation pending"]
    if duration < MIN_DURATION_SECONDS:
        notes.append(f"Duration {duration}s is below {MIN_DURATION_SECONDS}s minimum")
    if duration > MAX_DURATION_SECONDS:
        notes.append(f"Duration {duration}s exceeds {MAX_DURATION_SECONDS}s maximum")
    if width and height:
        ratio = float(width) / float(height)
        if ratio < 0.2 or ratio > 5:
            notes.append(f"Aspect ratio {ratio:.2f} looks invalid (width={width}, height={height})")
    if notes:
        return "NEEDS_REVIEW", notes
    return "READY", []


def list_folder_videos(access_token: str, drive_folder_id: str) -> list[dict]:
    """All video files directly in one Drive folder, paginated."""
    videos: list[dict] = []
    page_token: str | None = None
    # Drive query: folder membership + video mime. Quoting the folder id
    # with single quotes is the Drive API syntax for `in parents`.
    q = (
        f"'{drive_folder_id}' in parents and trashed = false "
        "and mimeType contains 'video/'"
    )
    while True:
        params: dict = {
            "q": q,
            "fields": (
                "nextPageToken, files(id, name, mimeType, size, createdTime, "
                "modifiedTime, md5Checksum, thumbnailLink, "
                "videoMediaMetadata(durationMillis, width, height))"
            ),
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token
        data = drive_service.drive_api_get(access_token, "/files", params)
        videos.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return videos


def _log(db: Session, account_id: int, message: str, details: str | None = None):
    db.add(
        PublishingLog(
            instagram_account_id=account_id,
            level="INFO",
            message=message,
            details=details,
        )
    )


def scan_folder(
    db: Session, mapping: AccountFolderMapping, access_token: str
) -> dict:
    """Scan one mapped folder. Returns counts for the report."""
    folder = db.get(DriveFolder, mapping.drive_folder_id)
    if folder is None:
        raise ValueError("Mapping references a missing Drive folder row")
    account = db.get(InstagramAccount, mapping.instagram_account_id)
    files = list_folder_videos(access_token, folder.drive_folder_id)
    seen_ids: set[str] = set()
    created = updated = needs_review = 0
    # Existing rows in this folder, keyed by Drive ID (session has
    # autoflush=False, so track in memory like sync_folders does).
    existing: dict[str, DriveVideo] = {
        v.drive_file_id: v
        for v in db.query(DriveVideo)
        .filter(DriveVideo.drive_folder_id == folder.id)
        .all()
    }
    for f in files:
        drive_id = f["id"]
        seen_ids.add(drive_id)
        # Cross-account guard: same Drive ID owned by another account.
        other = db.query(DriveVideo).filter(
            DriveVideo.drive_file_id == drive_id,
            DriveVideo.instagram_account_id != mapping.instagram_account_id,
        ).first()
        if other is not None:
            _log(db, mapping.instagram_account_id,
                 "Skipped file already owned by another account",
                 f"Drive file {drive_id} belongs to account {other.instagram_account_id}; not reassigned.")
            continue
        status, notes = validate_video(f)
        video_meta = f.get("videoMediaMetadata") or {}
        duration = None
        if video_meta.get("durationMillis") is not None:
            try:
                duration = int(video_meta["durationMillis"]) // 1000
            except (TypeError, ValueError):
                duration = None
        size = None
        if f.get("size") is not None:
            try:
                size = int(f["size"])
            except (TypeError, ValueError):
                size = None
        row = existing.get(drive_id)
        if row is None:
            # Same-content duplicate in the same folder?
            dup = None
            if f.get("md5Checksum"):
                dup = db.query(DriveVideo).filter(
                    DriveVideo.drive_folder_id == folder.id,
                    DriveVideo.content_hash == f["md5Checksum"],
                ).first()
            if dup is not None:
                status = "NEEDS_REVIEW"
                notes = notes + [f"Possible duplicate content of Drive file {dup.drive_file_id}"]
            row = DriveVideo(
                drive_file_id=drive_id,
                drive_folder_id=folder.id,
                instagram_account_id=mapping.instagram_account_id,
                filename=f["name"],
                mime_type=f.get("mimeType"),
                size_bytes=size,
                duration_seconds=duration,
                width=video_meta.get("width"),
                height=video_meta.get("height"),
                content_hash=f.get("md5Checksum"),
                thumbnail_url=f.get("thumbnailLink"),
                validation_notes="; ".join(notes) if notes else None,
                status=status,
            )
            db.add(row)
            db.flush()
            existing[drive_id] = row
            created += 1
        else:
            # Never reset a published/scheduled job by re-scanning.
            if row.status in ("PUBLISHED", "SCHEDULED", "PROCESSING"):
                row.filename = f["name"]
                row.thumbnail_url = f.get("thumbnailLink") or row.thumbnail_url
            else:
                row.filename = f["name"]
                row.mime_type = f.get("mimeType")
                row.size_bytes = size
                row.duration_seconds = duration
                row.width = video_meta.get("width")
                row.height = video_meta.get("height")
                row.thumbnail_url = f.get("thumbnailLink") or row.thumbnail_url
                row.validation_notes = "; ".join(notes) if notes else None
                row.status = status
            updated += 1
        if status == "NEEDS_REVIEW":
            needs_review += 1
    # Files that vanished from the folder listing.
    missing = 0
    for drive_id, row in existing.items():
        if drive_id not in seen_ids and row.status in ("NEW", "READY"):
            row.status = "NEEDS_REVIEW"
            row.validation_notes = "File no longer listed in its Drive folder (moved or deleted in Drive)"
            _log(db, mapping.instagram_account_id,
                 "Video no longer in Drive folder", f"Drive file {drive_id} ({row.filename})")
            missing += 1
    db.commit()
    return {
        "account_id": mapping.instagram_account_id,
        "username": account.username if account else None,
        "folder": folder.name,
        "found": len(files),
        "created": created,
        "updated": updated,
        "needs_review": needs_review,
        "missing_marked": missing,
    }


def scan_all_mapped_folders(db: Session) -> list[dict]:
    """Scan every active mapping. Requires a connected Drive."""
    access_token, _conn = drive_service.get_valid_access_token(db)
    mappings = db.query(AccountFolderMapping).filter(
        AccountFolderMapping.is_active.is_(True)
    ).all()
    results = []
    for mapping in mappings:
        try:
            results.append(scan_folder(db, mapping, access_token))
        except Exception as exc:
            _log(db, mapping.instagram_account_id,
                 "Folder scan failed", str(exc))
            db.commit()
            results.append({
                "account_id": mapping.instagram_account_id,
                "error": str(exc),
            })
    return results
