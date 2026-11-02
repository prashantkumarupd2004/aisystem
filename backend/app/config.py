"""Environment-based configuration.

No secret has a production default. Local development uses SQLite and a
developer-supplied SECRET_KEY / TOKEN_ENCRYPTION_KEY (see .env.example).
If TOKEN_ENCRYPTION_KEY is missing, an ephemeral key is generated so the
app can start in dev, but encrypted tokens will NOT survive a restart --
this is logged loudly and must never be used in production.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Instagram Reels Automation"
    environment: str = "development"  # development | production
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'app.db'}"
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    token_encryption_key: str | None = None  # Fernet key (base64, 44 chars)
    public_media_base_url: str = "http://localhost:8000/media"
    max_reels_per_account_per_day: int = 25
    admin_email: str | None = None
    admin_password: str | None = None
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"
    # Google Drive OAuth (Phase 2). Values come from a Google Cloud
    # project; see docs/GOOGLE_DRIVE_SETUP.md. drive.readonly is enough
    # to list folders and download videos for Meta publishing.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/drive/oauth/callback"
    google_drive_scopes: str = "https://www.googleapis.com/auth/drive.readonly"
    # Meta / Instagram Graph API (Phase 3). See docs/META_SETUP.md.
    # Only Business/Creator accounts linked to a Facebook Page are
    # eligible; personal Instagram accounts are skipped, not created.
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    meta_redirect_uri: str = "http://localhost:8000/api/instagram/oauth/callback"
    meta_graph_version: str = "v21.0"
    meta_scopes: str = (
        "instagram_basic,instagram_content_publish,"
        "pages_show_list,pages_read_engagement"
    )
    # Scheduling worker (Phase 5). Run the worker as a separate process
    # (`python -m app.worker`) in production; set ENABLE_SCHEDULER=true
    # only for single-process local dev, otherwise two workers can race
    # (claim locking still prevents duplicate publishes, see scheduler.py).
    enable_scheduler: bool = False
    scheduler_interval_seconds: int = 60
    max_publish_attempts: int = 3


settings = Settings()


def cors_origin_list() -> list[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
