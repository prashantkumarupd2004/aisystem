"""Meta Instagram Graph API integration (Phase 3).

Official Facebook Login OAuth only. No Instagram passwords, no browser
automation, no scraping, no unofficial API.

Flow:
  1. Admin calls GET /api/instagram/oauth/start -> Facebook consent URL.
  2. Facebook redirects to /api/instagram/oauth/callback?code=&state=
     (state is a short-lived signed JWT, same pattern as Drive).
  3. Callback exchanges the code for a short-lived user token, then
     for a long-lived (~60 day) user token.
  4. /me/accounts lists the user's Facebook Pages; each Page that has
     an instagram_business_account is an eligible Instagram account.
     Pages without one (personal Instagram, or no linked IG) are
     skipped with a reason -- they are NOT created as accounts.
  5. For each eligible IG account, the Page access token is stored
     encrypted (that token is what the Graph API uses for publishing
     in Phase 6) and the account is upserted by instagram_user_id.

Token expiry / revocation:
  - A long-lived token can be refreshed before it expires via the
    fb_exchange_token grant. An already-expired or revoked token
    CANNOT be refreshed silently -- the account goes to TOKEN_EXPIRED
    / PERMISSION_REVOKED and the admin must reconnect (re-run OAuth).
  - check_account() maps Graph errors to health statuses: 190 ->
    TOKEN_EXPIRED, 200/10 (permission) -> PERMISSION_REVOKED, other
    Graph errors -> UNKNOWN. A successful API check means "API
    accessible" only; it is NEVER reported as proof the account is
    not suspended -- see AccountHealth.detail for that wording.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AccountHealth, InstagramAccount, OAuthToken
from ..security import (
    create_access_token,
    decode_access_token,
    decrypt_token,
    encrypt_token,
)

log = logging.getLogger(__name__)


def _graph_base() -> str:
    return f"https://graph.facebook.com/{settings.meta_graph_version}"


def build_auth_url() -> tuple[str, str]:
    if not settings.meta_app_id:
        raise RuntimeError("META_APP_ID is not set. See docs/META_SETUP.md")
    state = create_access_token("instagram_oauth", "oauth_state")
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "scope": settings.meta_scopes,
        "response_type": "code",
        "state": state,
    }
    url = f"https://www.facebook.com/{settings.meta_graph_version}/dialog/oauth?{urlencode(params)}"
    return url, state


def verify_state(state: str) -> bool:
    try:
        payload = decode_access_token(state)
    except Exception:
        return False
    return payload.get("sub") == "instagram_oauth"


def _graph_get(path: str, params: dict) -> dict:
    resp = httpx.get(f"{_graph_base()}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def exchange_code(code: str) -> dict:
    if not settings.meta_app_id or not settings.meta_app_secret:
        raise RuntimeError("Meta app credentials are not set")
    return _graph_get(
        "/oauth/access_token",
        {
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "redirect_uri": settings.meta_redirect_uri,
            "code": code,
        },
    )


def exchange_long_lived(short_token: str) -> dict:
    """Short-lived user token -> long-lived user token (~60 days)."""
    return _graph_get(
        "/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": short_token,
        },
    )


def refresh_long_lived_token(existing_token: str) -> dict:
    """Refresh a still-valid long-lived token before it expires."""
    return exchange_long_lived(existing_token)


def list_pages_with_instagram(user_token: str) -> list[dict]:
    """Pages for /me/accounts, each with its instagram_business_account
    (when linked). Paginates through Graph paging cursors."""
    pages: list[dict] = []
    url: str | None = "/me/accounts"
    params: dict = {
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "access_token": user_token,
        "limit": 100,
    }
    while url:
        if url.startswith("http"):
            resp = httpx.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        else:
            data = _graph_get(url, params)
            params = {}
        pages.extend(data.get("data", []))
        paging = data.get("paging", {})
        url = paging.get("next")
    return pages


def get_ig_profile(ig_user_id: str, page_token: str) -> dict:
    return _graph_get(
        f"/{ig_user_id}",
        {
            "fields": "id,username,account_type,profile_picture_url",
            "access_token": page_token,
        },
    )


def sync_accounts(db: Session, user_token: str) -> dict:
    """Create/update eligible IG accounts from the user's Pages.

    Returns {connected: [...usernames...], skipped: [{page, reason}]}.
    Tokens are stored encrypted; nothing secret is in the return value.
    """
    pages = list_pages_with_instagram(user_token)
    connected: list[str] = []
    skipped: list[dict] = []
    seen: dict[str, InstagramAccount] = {
        a.instagram_user_id: a
        for a in db.query(InstagramAccount).all()
    }
    for page in pages:
        ig = page.get("instagram_business_account")
        if not ig:
            skipped.append(
                {"page": page.get("name"), "reason": "no linked Instagram Business/Creator account"}
            )
            continue
        ig_id = str(ig["id"])
        try:
            profile = get_ig_profile(ig_id, page["access_token"])
        except Exception as exc:
            skipped.append({"page": page.get("name"), "reason": f"profile fetch failed: {exc}"})
            continue
        account_type = (profile.get("account_type") or "BUSINESS").upper()
        if account_type not in ("BUSINESS", "CREATOR"):
            skipped.append(
                {"page": page.get("name"), "reason": f"ineligible account type: {account_type}"}
            )
            continue
        expires_in = None
        # Long-lived user token expiry is tracked on the OAuthToken row
        # by the caller (callback); the Page token itself is stored here.
        account = seen.get(ig_id)
        if account is None:
            account = InstagramAccount(
                instagram_user_id=ig_id,
                username=profile.get("username") or ig.get("username") or ig_id,
                account_type=account_type,
            )
            db.add(account)
            db.flush()
            seen[ig_id] = account
        else:
            account.username = profile.get("username") or account.username
            account.account_type = account_type
        account.access_token_encrypted = encrypt_token(page["access_token"])
        account.profile_image_url = profile.get("profile_picture_url")
        account.connection_status = "ACTIVE"
        health = db.query(AccountHealth).filter(
            AccountHealth.instagram_account_id == account.id
        ).first()
        if health is None:
            health = AccountHealth(instagram_account_id=account.id)
            db.add(health)
        health.status = "ACTIVE"
        health.detail = "API accessible. This does not confirm the account has no suspension or policy restriction."
        health.last_api_check_at = datetime.now(timezone.utc)
        connected.append(account.username)
    db.commit()
    return {"connected": connected, "skipped": skipped}


def save_user_token(db: Session, token_data: dict) -> OAuthToken:
    """Store the long-lived user token (for future refresh attempts)."""
    row = db.query(OAuthToken).filter(
        OAuthToken.provider == "instagram",
        OAuthToken.instagram_account_id.is_(None),
    ).first()
    if row is None:
        row = OAuthToken(provider="instagram")
        db.add(row)
    row.access_token_encrypted = encrypt_token(token_data["access_token"])
    if token_data.get("expires_in"):
        row.expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(token_data["expires_in"])
        )
    db.commit()
    return row


def check_account(db: Session, account: InstagramAccount) -> str:
    """Live Graph check for one account. Returns the new health status
    and persists it. Never invents a suspension status."""
    if not account.access_token_encrypted:
        status = "TOKEN_EXPIRED"
        detail = "No stored access token; reconnect required."
    else:
        try:
            token = decrypt_token(account.access_token_encrypted)
            profile = get_ig_profile(account.instagram_user_id, token)
            account.username = profile.get("username") or account.username
            status = "ACTIVE"
            detail = "API accessible. This does not confirm the account has no suspension or policy restriction."
        except httpx.HTTPStatusError as exc:
            try:
                err = exc.response.json().get("error", {})
                code = err.get("code")
                subcode = err.get("error_subcode")
            except Exception:
                code, subcode = None, None
            if code == 190:
                status = "TOKEN_EXPIRED"
                detail = "Meta reports the token is expired/invalid; reconnect required."
            elif code in (200, 10) or subcode == 458:
                status = "PERMISSION_REVOKED"
                detail = "Meta reports missing/revoked permission; reconnect with required scopes."
            else:
                status = "UNKNOWN"
                detail = f"Graph API check failed (code={code}); manual verification needed."
        except Exception as exc:
            status = "CONNECTION_ERROR"
            detail = f"Network/API check failed: {exc}"
    account.connection_status = status if status != "ACTIVE" else "ACTIVE"
    health = db.query(AccountHealth).filter(
        AccountHealth.instagram_account_id == account.id
    ).first()
    if health is None:
        health = AccountHealth(instagram_account_id=account.id)
        db.add(health)
    health.status = status
    health.detail = detail
    health.last_api_check_at = datetime.now(timezone.utc)
    db.commit()
    return status
