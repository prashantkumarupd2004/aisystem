"""Optional email / Telegram alerts (Phase 8).

Both channels are opt-in via environment variables. If a channel is
not configured, its send function returns sent=False with a reason
and performs NO network call -- it never claims an alert was sent.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def send_email_alert(subject: str, body: str) -> dict:
    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_password,
                settings.smtp_from, settings.alert_email_to]):
        return {"channel": "email", "sent": False, "reason": "SMTP not configured"}
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = settings.alert_email_to
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return {"channel": "email", "sent": True}
    except Exception as exc:
        log.warning("Email alert failed: %s", exc)
        return {"channel": "email", "sent": False, "reason": str(exc)}


def send_telegram_alert(text: str) -> dict:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return {"channel": "telegram", "sent": False, "reason": "Telegram not configured"}
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=30,
        )
        resp.raise_for_status()
        return {"channel": "telegram", "sent": True}
    except Exception as exc:
        log.warning("Telegram alert failed: %s", exc)
        return {"channel": "telegram", "sent": False, "reason": str(exc)}


def send_alerts(subject: str, body: str) -> list[dict]:
    """Try both configured channels; returns one result per channel
    that was attempted or explicitly skipped as not configured."""
    results = []
    # Only report a channel if at least one of its settings exists,
    # so a completely unconfigured install reports both as skipped
    # rather than silently doing nothing.
    results.append(send_email_alert(subject, body))
    results.append(send_telegram_alert(body))
    return results
