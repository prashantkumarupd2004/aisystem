#!/usr/bin/env bash
# Run API + publishing worker in ONE service (Render/Railway fix).
#
# Why one service, not two: the worker downloads a video to
# media_temp_dir and the API serves it to Meta from /media.
# Two separate services have separate filesystems, so Meta would
# get a 404 for a file that only exists on the worker's disk.
# In one service both processes share the same disk, so the
# signed media URL always resolves.
#
# Usage (from the repo root, as in render.yaml):
#   bash backend/start_all.sh
# Render sets PORT; locally it defaults to 8000.
set -e
cd "$(dirname "$0")"

cleanup() {
  # Kill both children on exit/signal so neither is orphaned.
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT TERM INT

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
python -m app.worker &
wait
