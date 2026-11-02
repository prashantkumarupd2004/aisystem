# Reels publishing (Phase 6)

## How a Reel is published

1. The worker claims a due job (conditional UPDATE, one winner).
2. The 8 eligibility checks run again (account, mapping, folder,
   quota, not already published).
3. The video is downloaded from Drive server-side (OAuth token never
   leaves the server).
4. ffprobe, when installed, checks the video codec (H.264/HEVC).
   Without ffprobe, codec is logged as unchecked, never claimed.
5. A short-lived signed media URL is created:
   `{PUBLIC_MEDIA_BASE_URL}/{jwt}/{filename}` (default 2h expiry).
   The `/media` endpoint serves it with Range + HEAD support for
   Meta's fetch. No Drive token is in the URL.
6. `POST /{ig-user-id}/media` with `media_type=REELS` creates a
   container. The container is polled until FINISHED or ERROR/EXPIRED.
7. `POST /{ig-user-id}/media_publish` with the container id publishes
   it and returns the Instagram Media ID, stored on the attempt.
8. The temp file is deleted.

## Temporary HTTPS for local testing

Meta must fetch the video over public HTTPS. Locally:

```bash
cloudflared tunnel --url http://localhost:8000
# set PUBLIC_MEDIA_BASE_URL to the tunnel URL + /media, e.g.
# https://xxx.trycloudflare.com/media
```

Quick Tunnel URLs change on restart and are NOT for production.
Production needs a stable public HTTPS endpoint (your own domain /
server, or a persistent tunnel) in front of the backend.

## Uncertain publishes -- do not blindly retry

If the network fails during `media_publish` itself, the Reel may or
may not exist on Instagram. The publisher returns an `UNCERTAIN:`
error, the scheduler marks the job FAILED (no auto-retry), and an
admin must check Instagram before manually re-scheduling. The same
applies to a publish response with no media id. `PERMANENT:` errors
(bad token, revoked permission, missing Drive file, caption too long)
also fail immediately without backoff; only other errors retry.

## Running the worker

```bash
cd backend && python -m app.worker
```

The worker now uses the real Meta publisher. A job with no valid
Meta token, no Drive connection, or no public media URL will fail
with a clear error in its attempts/logs -- it will not be marked
published.
