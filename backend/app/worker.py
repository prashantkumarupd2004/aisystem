"""Persistent publishing worker entrypoint.

Run:  cd backend && python -m app.worker

The worker ticks every SCHEDULER_INTERVAL_SECONDS, reads due jobs
from the database (so it survives restarts), and processes them via
services.scheduler.process_due_posts.

Phase 5 note: no Meta publisher is wired yet (Phase 6), so due jobs
are skipped, not faked as published. The worker still handles quota
postponement and recurring creation for jobs that a publisher (in
tests, or Phase 6) actually publishes.
"""
from __future__ import annotations

import logging
import time

from .database import Base, engine, ensure_extra_columns
from .services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main():
    Base.metadata.create_all(bind=engine)
    ensure_extra_columns()
    scheduler = start_scheduler(publish_fn=None)
    scheduler.start()
    log.info("Worker started (no publisher wired yet -- Phase 6). Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        scheduler.shutdown()
        log.info("Worker stopped.")


if __name__ == "__main__":
    main()
