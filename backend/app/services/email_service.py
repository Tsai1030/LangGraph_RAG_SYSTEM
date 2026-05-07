"""
email_service.py — Gmail SMTP 寄信服務

目前僅用於密碼重設信。SMTP 設定走 settings；若 SMTP_HOST 為空則不寄信並印 warning（dev 友善）。
"""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import settings

logger = logging.getLogger("app.email")


def _is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def _from_addr() -> str:
    name = settings.smtp_from_name or "System"
    return f"{name} <{settings.smtp_user}>"


async def _send(to: str, subject: str, html: str, text: str) -> None:
    if not _is_configured():
        logger.warning(
            "SMTP not configured — would send to %s, subject=%r. Body:\n%s",
            to, subject, text,
        )
        return

    msg = EmailMessage()
    msg["From"] = _from_addr()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_password,
        start_tls=True,
        timeout=15,
    )
    logger.info("Sent email to %s, subject=%r", to, subject)


async def send_password_reset_email(to_email: str, reset_link: str, display_name: str | None = None) -> None:
    name = display_name or to_email.split("@")[0]
    subject = "BES 密碼重設連結"

    text = (
        f"您好 {name}，\n\n"
        f"我們收到一個重設您 BES 帳號密碼的請求。\n"
        f"請點擊以下連結重設密碼（一小時內有效）：\n\n"
        f"{reset_link}\n\n"
        f"若非您本人操作，請忽略此信件，您的密碼不會變更。\n\n"
        f"— BES 系統"
    )

    html = f"""\
<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,sans-serif;max-width:560px;margin:24px auto;color:#222;line-height:1.6">
  <h2 style="margin-bottom:8px">密碼重設</h2>
  <p>您好 {name}，</p>
  <p>我們收到一個重設您 BES 帳號密碼的請求。請在 <strong>一小時內</strong> 點擊下方按鈕完成重設：</p>
  <p style="margin:24px 0">
    <a href="{reset_link}" style="display:inline-block;padding:12px 20px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px">重設密碼</a>
  </p>
  <p style="font-size:13px;color:#666">或複製此連結到瀏覽器：<br><span style="word-break:break-all">{reset_link}</span></p>
  <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
  <p style="font-size:12px;color:#888">若非您本人操作，請忽略此信件，您的密碼不會變更。</p>
</body></html>"""

    await _send(to_email, subject, html, text)
