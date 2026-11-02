"""Relational schema -- all 15 tables from the master prompt, section 14.

Account-isolation invariants enforced here AND in services/mapping.py:
* One Instagram account has at most one active folder mapping
  (instagram_account_id is unique on account_folder_mappings).
* A Drive video belongs to exactly one folder and one account; the
  publishing path re-checks video.drive_folder_id against the mapping
  before every publish, it never trusts a name or a client-supplied id.
* A scheduled post references exactly one account and one video.
* Sharing one folder across accounts is only possible when
  shared_folder_mode=True on the mapping, and is rejected by the service
  layer otherwise (a partial unique index is not portable SQLite/PG,
  so the service check is the enforced rule, with an audit-log entry).

Statuses are plain strings (not native enums) so SQLite and PostgreSQL
behave identically.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(32), default="admin", nullable=False)  # admin | viewer
    is_active = Column(Boolean, default=True, nullable=False)


class InstagramAccount(Base, TimestampMixin):
    __tablename__ = "instagram_accounts"
    id = Column(Integer, primary_key=True)
    instagram_user_id = Column(String(128), unique=True, nullable=False, index=True)
    username = Column(String(128), unique=True, nullable=False, index=True)
    account_type = Column(String(32), default="BUSINESS", nullable=False)
    # Encrypted with Fernet; plain tokens are never persisted or returned.
    access_token_encrypted = Column(Text, nullable=True)
    token_expiry = Column(DateTime(timezone=True), nullable=True)
    connection_status = Column(String(32), default="UNKNOWN", nullable=False)
    profile_image_url = Column(String(1024), nullable=True)
    drive_folder_id = Column(
        Integer, ForeignKey("drive_folders.id"), nullable=True
    )
    mapping = relationship(
        "AccountFolderMapping", back_populates="account", uselist=False
    )
    health = relationship(
        "AccountHealth", back_populates="account", uselist=False
    )


class OAuthToken(Base, TimestampMixin):
    __tablename__ = "oauth_tokens"
    id = Column(Integer, primary_key=True)
    provider = Column(String(32), nullable=False)  # instagram | google
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=True
    )
    drive_connection_id = Column(
        Integer, ForeignKey("google_drive_connections.id"), nullable=True
    )
    scope = Column(Text, nullable=True)
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class GoogleDriveConnection(Base, TimestampMixin):
    __tablename__ = "google_drive_connections"
    id = Column(Integer, primary_key=True)
    google_account_email = Column(String(255), nullable=True)
    status = Column(String(32), default="DISCONNECTED", nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)


class DriveFolder(Base, TimestampMixin):
    __tablename__ = "drive_folders"
    id = Column(Integer, primary_key=True)
    drive_folder_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    parent_drive_id = Column(String(255), nullable=True)
    drive_connection_id = Column(
        Integer, ForeignKey("google_drive_connections.id"), nullable=True
    )


class AccountFolderMapping(Base, TimestampMixin):
    __tablename__ = "account_folder_mappings"
    id = Column(Integer, primary_key=True)
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), unique=True, nullable=False
    )
    drive_folder_id = Column(
        Integer, ForeignKey("drive_folders.id"), nullable=False
    )
    shared_folder_mode = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    confirmed_by_admin = Column(Boolean, default=False, nullable=False)
    account = relationship("InstagramAccount", back_populates="mapping")
    folder = relationship("DriveFolder")


class DriveVideo(Base, TimestampMixin):
    __tablename__ = "drive_videos"
    id = Column(Integer, primary_key=True)
    drive_file_id = Column(String(255), unique=True, nullable=False, index=True)
    drive_folder_id = Column(
        Integer, ForeignKey("drive_folders.id"), nullable=False
    )
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=False
    )
    filename = Column(String(512), nullable=False)
    mime_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    content_hash = Column(String(128), nullable=True)
    caption = Column(Text, nullable=True)
    hashtags = Column(Text, nullable=True)
    # Drive-generated thumbnail link (Phase 4). Full video preview
    # playback needs the authenticated media endpoint in Phase 6/9;
    # the thumbnail is the preview shown in the library until then.
    thumbnail_url = Column(Text, nullable=True)
    validation_notes = Column(Text, nullable=True)
    status = Column(String(32), default="NEW", nullable=False)
    # NEW | READY | SCHEDULED | PROCESSING | PUBLISHED | FAILED | NEEDS_REVIEW
    __table_args__ = (
        CheckConstraint(
            "status IN ('NEW','READY','SCHEDULED','PROCESSING','PUBLISHED','FAILED','NEEDS_REVIEW')",
            name="ck_drive_video_status",
        ),
    )


class ScheduledPost(Base, TimestampMixin):
    __tablename__ = "scheduled_posts"
    id = Column(Integer, primary_key=True)
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=False
    )
    drive_video_id = Column(
        Integer, ForeignKey("drive_videos.id"), nullable=False
    )
    scheduled_at_utc = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String(64), default="UTC", nullable=False)
    recurrence_rule = Column(String(255), nullable=True)
    status = Column(String(32), default="SCHEDULED", nullable=False)
    is_paused = Column(Boolean, default=False, nullable=False)
    account = relationship("InstagramAccount")
    video = relationship("DriveVideo")


class PublishingAttempt(Base, TimestampMixin):
    __tablename__ = "publishing_attempts"
    id = Column(Integer, primary_key=True)
    scheduled_post_id = Column(
        Integer, ForeignKey("scheduled_posts.id"), nullable=False
    )
    attempt_number = Column(Integer, nullable=False, default=1)
    status = Column(String(32), default="PENDING", nullable=False)
    error_code = Column(String(128), nullable=True)
    error_detail = Column(Text, nullable=True)
    instagram_media_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=False)


class PublishingLog(Base, TimestampMixin):
    __tablename__ = "publishing_logs"
    id = Column(Integer, primary_key=True)
    scheduled_post_id = Column(
        Integer, ForeignKey("scheduled_posts.id"), nullable=True
    )
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=True
    )
    level = Column(String(16), default="INFO", nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)


class AccountHealth(Base, TimestampMixin):
    __tablename__ = "account_health"
    id = Column(Integer, primary_key=True)
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), unique=True, nullable=False
    )
    status = Column(String(32), default="UNKNOWN", nullable=False)
    # ACTIVE | TOKEN_EXPIRED | PERMISSION_REVOKED | CONNECTION_ERROR |
    # PUBLISHING_RESTRICTED | NEEDS_MANUAL_REVIEW | UNKNOWN
    last_api_check_at = Column(DateTime(timezone=True), nullable=True)
    last_published_at = Column(DateTime(timezone=True), nullable=True)
    detail = Column(Text, nullable=True)
    account = relationship("InstagramAccount", back_populates="health")


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=True
    )
    kind = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)


class DailyReport(Base, TimestampMixin):
    __tablename__ = "daily_reports"
    id = Column(Integer, primary_key=True)
    report_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    instagram_account_id = Column(
        Integer, ForeignKey("instagram_accounts.id"), nullable=True
    )
    total_detected = Column(Integer, default=0, nullable=False)
    total_scheduled = Column(Integer, default=0, nullable=False)
    total_published = Column(Integer, default=0, nullable=False)
    total_failed = Column(Integer, default=0, nullable=False)
    total_pending = Column(Integer, default=0, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "report_date", "instagram_account_id", name="uq_daily_report_day_account"
        ),
    )


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(Integer, nullable=True)
    detail = Column(Text, nullable=True)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text, nullable=True)
