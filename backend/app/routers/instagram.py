"""Instagram OAuth + health-check endpoints (Phase 3).

Callback is public by necessity (Meta redirects the browser here) but
is protected by the signed state token. Starting the flow and checking
accounts require an admin / logged-in user respectively. No token is
ever returned by these endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import InstagramAccount, User
from ..services import instagram as ig_service

router = APIRouter(prefix="/api/instagram", tags=["instagram"])


@router.get("/oauth/start")
def oauth_start(admin: User = Depends(require_admin)):
    try:
        url, _state = ig_service.build_auth_url()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"auth_url": url}


@router.get("/oauth/callback")
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    format: str = "redirect",
    db: Session = Depends(get_db),
):
    if error:
        raise HTTPException(400, f"Meta OAuth error: {error}")
    if not code or not state or not ig_service.verify_state(state):
        raise HTTPException(400, "Invalid or expired OAuth state")
    try:
        short = ig_service.exchange_code(code)
        long_lived = ig_service.exchange_long_lived(short["access_token"])
        ig_service.save_user_token(db, long_lived)
        result = ig_service.sync_accounts(db, long_lived["access_token"])
    except Exception as exc:
        raise HTTPException(502, f"Instagram account sync failed: {exc}")
    if format == "json":
        return result
    count = len(result["connected"])
    return RedirectResponse(
        f"{settings.frontend_url}/accounts?instagram_connected={count}"
    )


@router.post("/accounts/{account_id}/check")
def check_account(
    account_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    account = db.get(InstagramAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    status = ig_service.check_account(db, account)
    return {"id": account.id, "username": account.username, "status": status}


@router.post("/accounts/{account_id}/reconnect")
def reconnect_note(
    account_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Reconnecting is just re-running OAuth: this returns the start
    URL so the admin can complete it. There is no password-based
    reconnect, and an expired token is never refreshed silently."""
    account = db.get(InstagramAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    try:
        url, _state = ig_service.build_auth_url()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"auth_url": url, "account_id": account.id}
