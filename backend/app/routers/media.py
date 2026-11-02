"""Public (signed-token) media endpoint for Meta's video fetch.

This route is intentionally NOT behind the admin JWT: Meta's servers
fetch it, and they cannot present our admin token. Protection is the
short-lived signed JWT in the URL plus filename validation. No Drive
tokens, account ids or internal paths are exposed here.
"""
import re

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from ..services import media_delivery

router = APIRouter(tags=["media"])


def _resolve_file(token: str, filename: str):
    try:
        post_id = media_delivery.verify_media_token(token)
    except Exception:
        return None, None
    if "/" in filename or "\\" in filename or ".." in filename:
        return None, None
    # Temp files are named post-{id}-{sanitised filename}; find the one
    # for this post whose suffix matches the requested filename.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    path = media_delivery.temp_dir() / f"post-{post_id}-{safe}"
    if not path.exists():
        return None, None
    return post_id, path


@router.get("/media/{token}/{filename}")
def serve_media(token: str, filename: str, request: Request):
    post_id, path = _resolve_file(token, filename)
    if path is None:
        return Response(status_code=404, content="Media not found or link expired")
    size = path.stat().st_size
    range_header = request.headers.get("range")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "video/mp4",
        "Content-Disposition": f'inline; filename="{filename}"',
    }
    if range_header:
        m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if m:
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start > end:
                return Response(status_code=416, headers=headers)
            length = end - start + 1

            def _iter():
                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            headers["Content-Length"] = str(length)
            return StreamingResponse(_iter(), status_code=206, headers=headers)

    def _full():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    headers["Content-Length"] = str(size)
    return StreamingResponse(_full(), headers=headers)


@router.head("/media/{token}/{filename}")
def serve_media_head(token: str, filename: str):
    post_id, path = _resolve_file(token, filename)
    if path is None:
        return Response(status_code=404)
    return Response(
        headers={
            "Accept-Ranges": "bytes",
            "Content-Type": "video/mp4",
            "Content-Length": str(path.stat().st_size),
        }
    )
