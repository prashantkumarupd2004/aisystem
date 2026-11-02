"""Temporary secure video delivery (Phase 6, prompt section 9).

Google Drive private links are NOT handed to Meta. Instead:
  1. The worker downloads the video from Drive with the server's
     OAuth token (never exposed to Meta or the browser).
  2. The file is stored under media_temp_dir for this post only.
  3. Meta gets a short-lived signed URL:
     {PUBLIC_MEDIA_BASE_URL}/{jwt}/{url-encoded filename}
     The JWT is signed with SECRET_KEY, carries the post id, and
     expires after media_url_expiry_minutes (default 2h). No Drive
     token, account id or internal path is in the URL.
  4. The /media endpoint serves the file with Range + HEAD support
     (Meta may use either), validates the JWT and the filename, and
     rejects path traversal.
  5. After publishing (success or terminal failure) the publisher
     deletes the temp file. A file left behind by a crashed worker is
     safe to delete: the next retry re-downloads it fresh.

Local testing: PUBLIC_MEDIA_BASE_URL=http://localhost:8000/media with
a Cloudflare Tunnel in front of the backend (see docs/PUBLISHING.md).
Production: a stable public HTTPS base URL -- Quick Tunnel URLs are
temporary and must not be used for guaranteed scheduling.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from jose import jwt

from ..config import settings

log = logging.getLogger(__name__)


def temp_dir() -> Path:
    path = Path(settings.media_temp_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def temp_path_for(post_id: int, filename: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
    return temp_dir() / f"post-{post_id}-{safe}"


def download_from_drive(access_token: str, drive_file_id: str, dest: Path) -> Path:
    """Download a Drive file (alt=media) to dest. Raises on HTTP error."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://www.googleapis.com/drive/v3/files/{drive_file_id}?alt=media"
    with httpx.stream(
        "GET", url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=300,
    ) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def create_signed_media_url(post_id: int, filename: str) -> str:
    """Signed URL Meta can fetch without any credential in the URL
    beyond the short-lived JWT itself."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.media_url_expiry_minutes
    )
    token = jwt.encode(
        {"sub": f"media:{post_id}", "post_id": post_id, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    base = settings.public_media_base_url.rstrip("/")
    return f"{base}/{token}/{quote(Path(filename).name)}"


def verify_media_token(token: str) -> int:
    """Return the post id for a valid media token, else raise."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    sub = payload.get("sub", "")
    if not sub.startswith("media:"):
        raise ValueError("Invalid media token subject")
    return int(payload["post_id"])


def cleanup_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        log.warning("Could not delete temp media file %s", path)
