"""Account health endpoints (Phase 8)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import InstagramAccount, User
from ..services import health as health_service
from ..services import instagram as ig_service

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/accounts")
def accounts_health(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return health_service.health_summary(db)


@router.get("/accounts/{account_id}")
def account_health(
    account_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)
):
    summary = health_service.health_summary(db)
    for acc in summary["accounts"]:
        if acc["id"] == account_id:
            return acc
    raise HTTPException(404, "Account not found")


@router.post("/check-all")
def check_all(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Live Graph check for every account (mockable in tests via
    ig_service.check_account). Returns the refreshed summary."""
    results = {}
    for acc in db.query(InstagramAccount).all():
        try:
            results[acc.username] = ig_service.check_account(db, acc)
        except Exception as exc:
            results[acc.username] = f"check failed: {exc}"
    return {"checked": results, "summary": health_service.health_summary(db)}
