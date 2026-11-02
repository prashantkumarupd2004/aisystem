"""FastAPI entrypoint. Mode is explicit: there is NO mock/live switch
that fakes publishing. Phase 1 serves real auth, real DB counts and
real mapping validation; Drive/Instagram publishing arrive in later
phases and are simply not present yet, not simulated.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import cors_origin_list, settings
from .database import Base, SessionLocal, engine, ensure_extra_columns
from .models import User  # noqa: F401  (register all models)
from .routers import accounts, auth, dashboard, drive, instagram, mappings, media, schedules, videos
from .security import hash_password

log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_extra_columns()
    # Bootstrap the first admin ONLY from env, never a hard-coded password.
    if settings.admin_email and settings.admin_password:
        db = SessionLocal()
        try:
            if not db.query(User).filter(User.email == settings.admin_email).first():
                db.add(
                    User(
                        email=settings.admin_email,
                        hashed_password=hash_password(settings.admin_password),
                        role="admin",
                    )
                )
                db.commit()
                log.info("Bootstrap admin created from ADMIN_EMAIL")
        finally:
            db.close()
    yield


app = FastAPI(title=settings.app_name, version="1.0.0-phase1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(mappings.router)
app.include_router(drive.router)
app.include_router(instagram.router)
app.include_router(videos.router)
app.include_router(schedules.router)
app.include_router(media.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "phase": 1, "environment": settings.environment}
