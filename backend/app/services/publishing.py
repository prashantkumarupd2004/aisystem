"""Official Meta Reels publishing (Phase 6, prompt section 8).

Steps, in order, with no browser automation and no unofficial API:
  1. Validate the job (mapping service -- same 8 checks as Phase 5).
  2. Download the video from Drive (server-side, token never exposed).
  3. Validate codec with ffprobe when available; if ffprobe is absent,
     codec is NOT claimed as validated (logged, not faked).
  4. Create a short-lived signed media URL for Meta to fetch.
  5. POST /{ig-user-id}/media with media_type=REELS -> container id.
  6. Poll GET /{container-id}?fields=status_code until FINISHED or a
     terminal ERROR/EXPIRED, with a bounded number of polls.
  7. POST /{ig-user-id}/media_publish with creation_id -> media id.
  8. Delete the temp file (success or terminal failure).

Error classification (Phase 7 retry engine relies on these prefixes):
  - "PERMANENT: ..."  -- retrying the same job cannot help (bad token,
    revoked permission, bad caption, missing Drive file). Scheduler
    fails the job immediately, no backoff.
  - "UNCERTAIN: ..."  -- the publish request may or may not have
    taken effect (network failure during media_publish). Scheduler
    must NOT auto-retry; the job goes to FAILED for manual
    reconciliation (check Instagram before re-posting).
  - anything else     -- temporary; scheduler retries with backoff.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DriveVideo, InstagramAccount, ScheduledPost
from ..services import drive as drive_service
from ..services import media_delivery
from ..services.mapping import MappingMismatch, NotPublishable, validate_publish_eligibility

log = logging.getLogger(__name__)

TEMPORARY_GRAPH_CODES = {4, 17, 32, 613, 800, 2}  # rate limit / transient


def graph_base() -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}"


def _graph_post(path: str, params: dict) -> dict:
    resp = httpx.post(f"{graph_base()}{path}", data=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _graph_get(path: str, params: dict) -> dict:
    resp = httpx.get(f"{graph_base()}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _classify_graph_error(exc: httpx.HTTPStatusError) -> tuple[bool, str]:
    """Return (is_permanent, message) for a Graph HTTP error."""
    try:
        err = exc.response.json().get("error", {})
        code = err.get("code")
        message = err.get("message", str(exc))
    except Exception:
        code, message = None, str(exc)
    retry_after = None
    try:
        retry_after = exc.response.headers.get("retry-after")
    except Exception:
        retry_after = None
    if code == 190:
        return True, f"PERMANENT: Meta token expired/invalid: {message}"
    if code in (200, 10):
        return True, f"PERMANENT: Meta permission revoked/missing: {message}"
    if code in TEMPORARY_GRAPH_CODES:
        suffix = f" retry_after={retry_after}" if retry_after else ""
        return False, f"Meta rate limit/transient error (code {code}): {message}{suffix}"
    if exc.response.status_code and exc.response.status_code >= 500:
        return False, f"Meta server error: {message}"
    return False, f"Meta API error (code {code}): {message}"


def _check_codec(path) -> str | None:
    """Return a problem string, or None if codec looks OK / unchecked.

    Returns None with a log note when ffprobe is unavailable -- the
    caller must not claim codec validation in that case.
    """
    if shutil.which("ffprobe") is None:
        log.info("ffprobe not available; codec not validated for %s", path)
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout or "{}")
        streams = data.get("streams", [])
        if not streams:
            return "PERMANENT: Could not read video codec (no video stream)"
        codec = streams[0].get("codec_name", "")
        if codec not in ("h264", "hevc", "h265", "mpeg4"):
            return f"PERMANENT: Unsupported video codec: {codec} (use H.264/HEVC)"
    except Exception as exc:
        log.warning("ffprobe check failed: %s", exc)
        return None
    return None


def build_caption(video: DriveVideo) -> str:
    parts = []
    if video.caption:
        parts.append(video.caption.strip())
    if video.hashtags:
        parts.append(video.hashtags.strip())
    caption = " ".join(parts).strip()
    return caption


def publish_reel(
    db: Session,
    post: ScheduledPost,
    poll_interval: int | None = None,
    max_polls: int | None = None,
) -> tuple[bool, str | None, str | None]:
    """Publish one scheduled post. Returns (success, media_id, error)."""
    poll_interval = settings.media_poll_interval_seconds if poll_interval is None else poll_interval
    max_polls = settings.media_poll_max_attempts if max_polls is None else max_polls
    # 1-2. Validate mapping/account before touching Drive or Meta.
    try:
        validate_publish_eligibility(db, post)
    except (MappingMismatch, NotPublishable) as exc:
        msg = str(exc)
        if "quota" in msg.lower():
            return False, None, msg
        return False, None, f"PERMANENT: {msg}"
    account = db.get(InstagramAccount, post.instagram_account_id)
    video = db.get(DriveVideo, post.drive_video_id)
    if account is None or video is None or not account.access_token_encrypted:
        return False, None, "PERMANENT: Account or video missing, or no stored token"
    from ..security import decrypt_token

    page_token = decrypt_token(account.access_token_encrypted)
    caption = build_caption(video)
    if len(caption) > 2200:
        return False, None, "PERMANENT: Caption exceeds Instagram 2200 character limit"
    temp_path = None
    try:
        # 3. Download from Drive.
        try:
            drive_token, _conn = drive_service.get_valid_access_token(db)
            temp_path = media_delivery.temp_path_for(post.id, video.filename)
            media_delivery.download_from_drive(drive_token, video.drive_file_id, temp_path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False, None, "PERMANENT: Video file not found in Google Drive"
            return False, None, f"Drive download failed: {exc}"
        except Exception as exc:
            return False, None, f"Drive download failed: {exc}"
        # Codec check (ffprobe when available).
        codec_problem = _check_codec(temp_path)
        if codec_problem:
            return False, None, codec_problem
        # 4. Signed media URL for Meta.
        media_url = media_delivery.create_signed_media_url(post.id, video.filename)
        # 5. Create container.
        try:
            container = _graph_post(
                f"/{account.instagram_user_id}/media",
                {
                    "media_type": "REELS",
                    "video_url": media_url,
                    "caption": caption,
                    "access_token": page_token,
                },
            )
        except httpx.HTTPStatusError as exc:
            permanent, msg = _classify_graph_error(exc)
            return False, None, (f"PERMANENT: {msg}" if permanent else msg)
        container_id = container.get("id")
        if not container_id:
            return False, None, "Meta did not return a media container id"
        # 6. Poll container status.
        for _ in range(max_polls):
            try:
                status_data = _graph_get(
                    f"/{container_id}",
                    {"fields": "status_code,status", "access_token": page_token},
                )
            except httpx.HTTPStatusError as exc:
                permanent, msg = _classify_graph_error(exc)
                return False, None, (f"PERMANENT: {msg}" if permanent else msg)
            status_code = status_data.get("status_code")
            if status_code == "FINISHED":
                break
            if status_code in ("ERROR", "EXPIRED"):
                detail = status_data.get("status", {})
                return False, None, f"Meta container failed ({status_code}): {detail}"
            if poll_interval:
                time.sleep(poll_interval)
        else:
            return False, None, "Meta container did not finish within the polling limit"
        # 8. Publish.
        try:
            published = _graph_post(
                f"/{account.instagram_user_id}/media_publish",
                {"creation_id": container_id, "access_token": page_token},
            )
        except httpx.HTTPStatusError as exc:
            permanent, msg = _classify_graph_error(exc)
            return False, None, (f"PERMANENT: {msg}" if permanent else msg)
        except httpx.HTTPError as exc:
            # Network failure during the publish call itself: the Reel
            # may or may not exist on Instagram. Never blindly retry.
            return False, None, f"UNCERTAIN: Network failure during media_publish: {exc}. Check Instagram before retrying."
        media_id = published.get("id")
        if not media_id:
            return False, None, "UNCERTAIN: Meta publish response had no media id. Check Instagram before retrying."
        return True, media_id, None
    finally:
        if temp_path is not None:
            media_delivery.cleanup_temp_file(temp_path)
