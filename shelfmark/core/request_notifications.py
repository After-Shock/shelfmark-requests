"""SMTP notifications for book request status changes.

Sends email to the requesting user when their request is approved, denied,
fulfilled, or failed. Reuses the existing SMTP configuration from
the email output settings.
"""

from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Optional

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)


STATUS_MESSAGES = {
    "approved": "Your book request has been approved and is being processed.",
    "denied": "Your book request has been denied.",
    "fulfilled": "Your book request has been fulfilled! The book should now be available in your library.",
    "failed": "Your book request could not be fulfilled. An admin may retry or find an alternative.",
}


def _is_notification_enabled() -> bool:
    """Check if request email notifications are enabled."""
    try:
        import shelfmark.core.config as core_config
        core_config.config.refresh()
        return bool(core_config.config.get("NOTIFY_REQUESTS_VIA_EMAIL", False))
    except Exception:
        return False


def _get_smtp_config():
    """Build SMTP config from existing email settings, or None if not configured."""
    try:
        import shelfmark.core.config as core_config
        from shelfmark.download.outputs.email import build_email_smtp_config

        core_config.config.refresh()
        settings = {
            "EMAIL_SMTP_HOST": core_config.config.get("EMAIL_SMTP_HOST", ""),
            "EMAIL_SMTP_PORT": core_config.config.get("EMAIL_SMTP_PORT", 587),
            "EMAIL_SMTP_SECURITY": core_config.config.get("EMAIL_SMTP_SECURITY", "starttls"),
            "EMAIL_SMTP_USERNAME": core_config.config.get("EMAIL_SMTP_USERNAME", ""),
            "EMAIL_SMTP_PASSWORD": core_config.config.get("EMAIL_SMTP_PASSWORD", ""),
            "EMAIL_FROM": core_config.config.get("EMAIL_FROM", ""),
            "EMAIL_SMTP_TIMEOUT_SECONDS": core_config.config.get("EMAIL_SMTP_TIMEOUT_SECONDS", 60),
            "EMAIL_ALLOW_UNVERIFIED_TLS": core_config.config.get("EMAIL_ALLOW_UNVERIFIED_TLS", False),
        }
        return build_email_smtp_config(settings)
    except Exception as e:
        logger.debug(f"SMTP config not available for notifications: {e}")
        return None


def send_request_notification(
    user_email: str,
    request_title: str,
    new_status: str,
    admin_note: Optional[str] = None,
) -> bool:
    """Send an email notification about a request status change.

    Args:
        user_email: Recipient email address.
        request_title: Title of the requested book.
        new_status: New status (approved, denied, fulfilled, failed).
        admin_note: Optional admin note to include.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not _is_notification_enabled():
        return False

    if not user_email:
        return False

    smtp_config = _get_smtp_config()
    if not smtp_config:
        logger.warning("Cannot send request notification: SMTP not configured")
        return False

    status_label = new_status.capitalize()
    status_message = STATUS_MESSAGES.get(new_status, f"Your request status has changed to: {status_label}.")

    subject = f"Request {status_label}: {request_title}"
    body_lines = [
        f"Book: {request_title}",
        f"Status: {status_label}",
        "",
        status_message,
    ]

    if admin_note:
        body_lines.extend(["", f"Note from admin: {admin_note}"])

    body_lines.extend(["", "— Shelfmark"])

    try:
        from shelfmark.download.outputs.email import send_email_message

        msg = EmailMessage()
        msg["From"] = smtp_config.from_addr
        msg["To"] = user_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)

        domain = "shelfmark.local"
        try:
            from_email = parseaddr(smtp_config.from_addr)[1]
            domain = (from_email.partition("@")[2] or "").strip().rstrip(">") or domain
        except Exception:
            pass
        msg["Message-ID"] = make_msgid(domain=domain)

        msg.set_content("\n".join(body_lines))

        send_email_message(smtp_config, msg)
        logger.info(f"Request notification sent to {user_email}: {subject}")
        return True

    except Exception as e:
        logger.warning(f"Failed to send request notification to {user_email}: {e}")
        return False
