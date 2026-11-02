"""Instagram account management (Phase 1: CRUD + health + disconnect).

OAuth connect itself lands in Phase 3. Accounts created here accept a
token once (admin only); it is encrypted immediately and never returned.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import AccountHealth, AuditLog, InstagramAccount, User
from ..schemas import AccountCreate, AccountOut
from ..security import encrypt_token

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(
    search: str = "",
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(InstagramAccount)
    if search:
        q = q.filter(InstagramAccount.username.ilike(f"%{search}%"))
    return q.order_by(InstagramAccount.username).offset(skip).limit(limit).all()


@router.post("", response_model=AccountOut, status_code=201)
def create_account(
    payload: AccountCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if (
        db.query(InstagramAccount)
        .filter(
            (InstagramAccount.instagram_user_id == payload.instagram_user_id)
            | (InstagramAccount.username == payload.username)
        )
        .first()
    ):
        raise HTTPException(409, "Account with this Instagram ID or username exists")
    acc = InstagramAccount(
        instagram_user_id=payload.instagram_user_id,
        username=payload.username,
        account_type=payload.account_type,
        access_token_encrypted=encrypt_token(payload.access_token)
        if payload.access_token
        else None,
        token_expiry=payload.token_expiry,
        connection_status="ACTIVE" if payload.access_token else "UNKNOWN",
    )
    db.add(acc)
    db.flush()
    db.add(AccountHealth(instagram_account_id=acc.id, status=acc.connection_status))
    db.add(
        AuditLog(
            user_id=admin.id,
            action="account_created",
            entity_type="instagram_account",
            entity_id=acc.id,
            detail=payload.username,
        )
    )
    db.commit()
    db.refresh(acc)
    return acc


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    acc = db.get(InstagramAccount, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    return acc


@router.post("/{account_id}/disconnect", response_model=AccountOut)
def disconnect_account(
    account_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    acc = db.get(InstagramAccount, account_id)
    if not acc:
        raise HTTPException(404, "Account not found")
    # Disconnecting clears the stored token -- reconnect requires a new
    # OAuth grant in Phase 3, never a recovered password.
    acc.access_token_encrypted = None
    acc.connection_status = "DISCONNECTED"
    health = db.query(AccountHealth).filter(
        AccountHealth.instagram_account_id == acc.id
    ).first()
    if health:
        health.status = "CONNECTION_ERROR"
        health.detail = "Disconnected by administrator"
    db.add(
        AuditLog(
            user_id=admin.id,
            action="account_disconnected",
            entity_type="instagram_account",
            entity_id=acc.id,
        )
    )
    db.commit()
    db.refresh(acc)
    return acc
