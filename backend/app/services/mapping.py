"""Account <-> folder isolation -- the non-negotiable rule.

A video in folder XYZ is eligible ONLY for the Instagram account mapped
to XYZ. Every check below is run before a publish (Phase 5/6 reuses
exactly this function); a mismatch stops the job, it is never "fixed"
by falling back to another account or folder.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AccountFolderMapping,
    DriveVideo,
    InstagramAccount,
    ScheduledPost,
)


class MappingMismatch(Exception):
    pass


class NotPublishable(Exception):
    pass


def validate_folder_mapping(
    db: Session,
    instagram_account_id: int,
    drive_folder_id: int,
    shared_folder_mode: bool = False,
) -> None:
    """Reject a mapping that would silently share a folder, unless the
    admin explicitly enabled shared-folder mode for this mapping."""
    if shared_folder_mode:
        return
    clash = (
        db.query(AccountFolderMapping)
        .filter(
            AccountFolderMapping.drive_folder_id == drive_folder_id,
            AccountFolderMapping.is_active.is_(True),
            AccountFolderMapping.instagram_account_id != instagram_account_id,
        )
        .first()
    )
    if clash:
        raise MappingMismatch(
            "Drive folder is already mapped to another Instagram account. "
            "Enable shared-folder mode explicitly if this is intentional."
        )


def get_mapping(db: Session, instagram_account_id: int) -> AccountFolderMapping | None:
    return (
        db.query(AccountFolderMapping)
        .filter(
            AccountFolderMapping.instagram_account_id == instagram_account_id,
            AccountFolderMapping.is_active.is_(True),
        )
        .first()
    )


def validate_publish_eligibility(db: Session, post: ScheduledPost) -> None:
    """The 8 pre-publish checks from the master prompt, section 6.

    Raises MappingMismatch / NotPublishable on the first failed check.
    Quota is a configurable daily cap (settings), not a Meta claim: the
    real Meta quota/rate-limit response is handled again at publish time
    in Phase 6 and is never guessed here.
    """
    account = db.get(InstagramAccount, post.instagram_account_id)
    if account is None:
        raise NotPublishable("Scheduled job references a missing Instagram account")
    if post.is_paused:
        raise NotPublishable("Scheduled job is paused")
    if post.status == "PUBLISHED":
        raise NotPublishable("Job is already published (idempotency guard)")
    mapping = get_mapping(db, account.id)
    if mapping is None:
        raise MappingMismatch("Instagram account has no active folder mapping")
    video = db.get(DriveVideo, post.drive_video_id)
    if video is None:
        raise NotPublishable("Scheduled job references a missing video")
    if video.drive_folder_id != mapping.drive_folder_id:
        raise MappingMismatch(
            f"Video folder ({video.drive_folder_id}) does not match the "
            f"account mapping ({mapping.drive_folder_id}). Publishing stopped."
        )
    if video.instagram_account_id != account.id:
        raise MappingMismatch("Video is not owned by the mapped Instagram account")
    if account.connection_status not in ("ACTIVE",):
        raise NotPublishable(
            f"Instagram account is not ACTIVE (status={account.connection_status})"
        )
    if not account.access_token_encrypted:
        raise NotPublishable("Instagram account has no stored access token")
    # Daily quota guard (configurable; Meta's own limit is checked live).
    from datetime import datetime, timezone

    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    published_today = (
        db.query(ScheduledPost)
        .filter(
            ScheduledPost.instagram_account_id == account.id,
            ScheduledPost.status == "PUBLISHED",
            ScheduledPost.updated_at >= day_start,
        )
        .count()
    )
    if published_today >= settings.max_reels_per_account_per_day:
        raise NotPublishable("Daily publishing quota for this account reached")
