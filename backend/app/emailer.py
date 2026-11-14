"""Outbound email: Resend first, then SMTP, then the console in development."""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import (
    APP_NAME,
    CONTACT_EMAIL,
    FROM_EMAIL,
    RESEND_API_KEY,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


def provider_name() -> str:
    if RESEND_API_KEY:
        return "resend"
    if SMTP_HOST:
        return "smtp"
    return "console"


def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    """Send one email. Returns True when it was handed to a provider."""
    if RESEND_API_KEY:
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={"from": FROM_EMAIL, "to": [to], "subject": subject, "html": html},
                timeout=15.0,
            )
            response.raise_for_status()
            return True
        except Exception as exc:  # pragma: no cover - network
            logger.warning("Resend failed (%s); falling back", exc)

    if SMTP_HOST:
        try:
            message = EmailMessage()
            message["From"] = FROM_EMAIL
            message["To"] = to
            message["Subject"] = subject
            message.set_content(text or subject)
            message.add_alternative(html, subtype="html")
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls()
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASS)
                server.send_message(message)
            return True
        except Exception as exc:  # pragma: no cover - network
            logger.warning("SMTP failed (%s); falling back to console", exc)

    logger.info("Email (dev mode) to=%s subject=%s\n%s", to, subject, text or html)
    return False


def _otp_html(code: str) -> str:
    return f"""\
<div style="background:#0a0a0a;padding:32px;font-family:Inter,Helvetica,Arial,sans-serif">
  <div style="max-width:480px;margin:0 auto;background:#0f0f10;border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:32px;color:#e5e5e5">
    <p style="margin:0 0 8px;font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:#8a8a8a">{APP_NAME}</p>
    <h1 style="margin:0 0 16px;font-size:22px;color:#ffffff">Your sign-in code</h1>
    <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#b3b3b3">
      Enter this code to finish signing in. It expires in 10 minutes.
    </p>
    <p style="margin:0 0 20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:32px;letter-spacing:.32em;color:#ffffff">{code}</p>
    <p style="margin:0;font-size:12px;color:#8a8a8a">
      If you didn't request this code you can ignore this email.
    </p>
  </div>
</div>"""


def send_otp_code(email: str, code: str) -> bool:
    return send_email(
        email,
        f"Your {APP_NAME} sign-in code: {code}",
        _otp_html(code),
        text=f"Your {APP_NAME} sign-in code is {code}. It expires in 10 minutes.",
    )


def send_contact_message(name: str, email: str, subject: str, message: str) -> bool:
    if not CONTACT_EMAIL:
        logger.info("Contact form (no CONTACT_EMAIL set): %s <%s> — %s\n%s", name, email, subject, message)
        return False
    html = f"""\
<div style="font-family:Inter,Helvetica,Arial,sans-serif;color:#111">
  <h2>New contact message</h2>
  <p><strong>From:</strong> {name} &lt;{email}&gt;</p>
  <p><strong>Subject:</strong> {subject}</p>
  <p style="white-space:pre-wrap">{message}</p>
</div>"""
    return send_email(CONTACT_EMAIL, f"[{APP_NAME}] {subject}", html, text=message)
