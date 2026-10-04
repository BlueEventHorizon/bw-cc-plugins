"""Bar タスク管理の共通メール送信部品。"""

import smtplib
from email.message import EmailMessage

from bar.config import load_smtp_settings


class MailError(Exception):
    """メールの送信に失敗した。"""


def send_mail(to: list[str], subject: str, body: str) -> None:
    """宛先の一覧へプレーンテキストのメールを送る。失敗したら MailError を送出する。"""
    if not to:
        raise MailError("宛先がありません")
    settings = load_smtp_settings()
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.host, settings.port) as smtp:
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise MailError(str(error)) from error
