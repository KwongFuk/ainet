from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from .config import Settings

logger = logging.getLogger(__name__)


async def send_verification_code(settings: Settings, email: str, code: str) -> None:
    if not settings.smtp_host:
        if settings.log_email_codes:
            logger.warning("email verification code for %s: %s", email, code)
        else:
            logger.warning("SMTP not configured; verification email for %s was not sent", email)
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = email
    message["Subject"] = "Ainet verification code"
    message.set_content(f"Your Ainet verification code is: {code}\nIt expires soon.")

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_starttls,
    )

