"""Alert test endpoint (Phase 8). Never claims a send that did not
happen: if email/Telegram are not configured, the result says so."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import require_admin
from ..models import User
from ..services import alerts as alert_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class AlertTest(BaseModel):
    subject: str = "Test alert from Reels Automation"
    body: str = "This is a test alert. If you received this, alerts are configured."


@router.post("/test")
def test_alerts(payload: AlertTest, admin: User = Depends(require_admin)):
    return {"results": alert_service.send_alerts(payload.subject, payload.body)}
