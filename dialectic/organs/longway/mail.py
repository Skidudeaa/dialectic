"""Mail out of The Long Way: one SMTP door, STARTTLS, stdlib only.

Credentials live in /etc/longway/longway.env as LONGWAY_SMTP_USER and LONGWAY_SMTP_PASSWORD (for Gmail: the address
and an app password). Unset credentials mean no mail, said loudly through MailDisabled; nothing is queued in silence.
"""
import os
import smtplib
from email.message import EmailMessage


class MailDisabled(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("LONGWAY_SMTP_USER") and os.environ.get("LONGWAY_SMTP_PASSWORD"))


def notify_address() -> str:
    """Where the planner hears about the house: LONGWAY_INVITE_NOTIFY_TO, or the sending account itself."""
    return os.environ.get("LONGWAY_INVITE_NOTIFY_TO") or os.environ.get("LONGWAY_SMTP_USER", "")


def send(to: str, subject: str, body: str) -> None:
    """Deliver one plain-text message synchronously (call it through asyncio.to_thread).

    Raises MailDisabled without credentials, smtplib.SMTPException or OSError when the server refuses.
    """
    user, password = os.environ.get("LONGWAY_SMTP_USER"), os.environ.get("LONGWAY_SMTP_PASSWORD")
    if not user or not password:
        raise MailDisabled("LONGWAY_SMTP_USER and LONGWAY_SMTP_PASSWORD are not set")
    message = EmailMessage()
    message["From"] = f"The Long Way <{user}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(os.environ.get("LONGWAY_SMTP_HOST", "smtp.gmail.com"),
                      int(os.environ.get("LONGWAY_SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)
