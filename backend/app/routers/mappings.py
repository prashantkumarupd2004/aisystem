"""Account -> Drive folder mapping (Phase 1: validated CRUD).

Folder discovery (Drive API) lands in Phase 2; this router already
enforces the isolation rule against folders/accounts created in the DB.
Changing a mapping requires confirmed_by_admin=True, and is audit-logged.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import (
    AccountFolderMapping,
    AuditLog,
    DriveFolder,
    InstagramAccount,
    User,
)
from ..schemas import MappingCreate, MappingOut
from ..services.mapping import MappingMismatch, validate_folder_mapping

router = APIRouter(prefix="/api/mappings", tags=["mappings"])


@router.get("", response_model=list[MappingOut])
def list_mappings(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(AccountFolderMapping).all()


@router.post("", response_model=MappingOut, status_code=201)
def create_or_update_mapping(
    payload: MappingCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    account = db.get(InstagramAccount, payload.instagram_account_id)
    folder = db.get(DriveFolder, payload.drive_folder_id)
    if not account or not folder:
        raise HTTPException(404, "Account or folder not found")
    if not payload.confirmed_by_admin:
        raise HTTPException(
            400, "Mapping changes require administrator confirmation"
        )
    try:
        validate_folder_mapping(
            db,
            payload.instagram_account_id,
            payload.drive_folder_id,
            payload.shared_folder_mode,
        )
    except MappingMismatch as exc:
        raise HTTPException(409, str(exc))
    existing = (
        db.query(AccountFolderMapping)
        .filter(
            AccountFolderMapping.instagram_account_id == payload.instagram_account_id
        )
        .first()
    )
    if existing:
        existing.drive_folder_id = payload.drive_folder_id
        existing.shared_folder_mode = payload.shared_folder_mode
        existing.is_active = True
        existing.confirmed_by_admin = True
        mapping = existing
        action = "mapping_changed"
    else:
        mapping = AccountFolderMapping(
            instagram_account_id=payload.instagram_account_id,
            drive_folder_id=payload.drive_folder_id,
            shared_folder_mode=payload.shared_folder_mode,
            confirmed_by_admin=True,
        )
        db.add(mapping)
        action = "mapping_created"
    account.drive_folder_id = payload.drive_folder_id
    db.add(
        AuditLog(
            user_id=admin.id,
            action=action,
            entity_type="account_folder_mapping",
            entity_id=account.id,
            detail=f"{account.username} -> folder {folder.name}",
        )
    )
    db.commit()
    db.refresh(mapping)
    return mapping
