from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.config import Settings


class EmailNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_to)

    async def send(self, subject: str, html: str, text: str) -> tuple[bool, str]:
        if not self.configured:
            return False, "未配置 SMTP"
        return await asyncio.to_thread(self._send_sync, subject, html, text)

    def _send_sync(self, subject: str, html: str, text: str) -> tuple[bool, str]:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.settings.smtp_from or self.settings.smtp_username
        message["To"] = self.settings.smtp_to
        message.set_content(text)
        message.add_alternative(html, subtype="html")

        recipients = [
            address.strip() for address in self.settings.smtp_to.split(",") if address.strip()
        ]
        try:
            if self.settings.smtp_ssl:
                server = smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=30,
                )
            else:
                server = smtplib.SMTP(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=30,
                )
            with server:
                if self.settings.smtp_starttls and not self.settings.smtp_ssl:
                    server.starttls()
                if self.settings.smtp_username:
                    server.login(self.settings.smtp_username, self.settings.smtp_password)
                server.send_message(message, to_addrs=recipients)
            return True, ""
        except Exception as exc:
            return False, str(exc)

