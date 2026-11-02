"""Notifications API (Phase 7). Notifications are created by the
worker for dead-letter, permanent and uncertain failures; they are
never created for a routine success."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import Notification, User

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    return [
        {"id": n.id, "instagram_account_id": n.instagram_account_id,
         "kind": n.kind, "title": n.title, "body": n.body,
         "is_read": n.is_read, "created_at": n.created_at}
        for n in q.order_by(Notification.created_at.desc()).limit(200).all()
    ]


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    db.commit()
    return {"id": n.id, "is_read": True}


@router.post("/mark-all-read")
def mark_all_read(db: Session = Depends(get_db), _=Depends(get_current_user)):
    db.query(Notification).filter(Notification.is_read.is_(False)).update(
        {"is_read": True}
    )
    db.commit()
    return {"ok": True}
