"""Self-service "forgot password" by email.

The requests site is the one place passwords change; a reset here is pushed to
the user's linked Calibre-Web / Audiobookshelf accounts (see
signup_provisioning.set_password).

Emailed links carry a random token. Only its sha256 is stored, in
password_reset_codes with a "self:" prefix that keeps it apart from the codes
admins hand out.
"""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Dict, List
from urllib.parse import urlparse

from shelfmark.core.logger import setup_logger

logger = setup_logger(__name__)

CODE_PREFIX = "self:"
LINK_LIFETIME_MINUTES = 60
RESEND_COOLDOWN_MINUTES = 5

_APP_LABELS = {"calibre_web": "Ebooks", "audiobookshelf": "Audiobooks"}
_APP_URL_KEYS = {"calibre_web": "CALIBRE_WEB_URL", "audiobookshelf": "AUDIOBOOK_LIBRARY_URL"}


class PasswordResetError(Exception):
    pass


def _hash_token(token: str) -> str:
    return CODE_PREFIX + hashlib.sha256(token.encode()).hexdigest()


def _public_url() -> str:
    import shelfmark.core.config as core_config

    return str(core_config.config.get("PUBLIC_URL", "") or "").strip().rstrip("/")


def _host(url: str) -> str:
    return urlparse(url).netloc or url


def _app_host(service: str) -> str:
    import shelfmark.core.config as core_config

    url = str(core_config.config.get(_APP_URL_KEYS[service], "") or "").strip()
    return _host(url) if url else _APP_LABELS[service]


def is_available() -> bool:
    """Emailed resets need the site's public URL (for the link) and SMTP."""
    from shelfmark.core.request_notifications import _get_smtp_config

    return bool(_public_url()) and _get_smtp_config() is not None


def _matching_users(user_db: Any, identifier: str) -> List[Dict[str, Any]]:
    wanted = identifier.strip().lower()
    return [
        u for u in user_db.list_users()
        if u.get("auth_source") == "builtin"
        and wanted in (str(u.get("username") or "").lower(), str(u.get("email") or "").strip().lower())
    ]


def request_password_reset(user_db: Any, identifier: str) -> None:
    """Email a reset link to each local account matching a username or email.

    Never raises and never reports whether anything matched, so the caller's
    response can't be used to find out who has an account.
    """
    try:
        for user in _matching_users(user_db, identifier):
            if not user.get("email"):
                logger.info("Password reset requested for '%s', who has no email address", user["username"])
                continue
            if user_db.has_recent_password_reset(int(user["id"]), CODE_PREFIX, RESEND_COOLDOWN_MINUTES):
                logger.info("Password reset for '%s' skipped: one was sent in the last %d minutes",
                            user["username"], RESEND_COOLDOWN_MINUTES)
                continue
            token = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(minutes=LINK_LIFETIME_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            user_db.create_password_reset_code(int(user["id"]), _hash_token(token), None, expires)
            _send_reset_email(user, f"{_public_url()}/reset-password?token={token}")
    except Exception as e:
        logger.error_trace(f"Password reset request failed: {e}")


def complete_password_reset(user_db: Any, token: str, password: str) -> Dict[str, Any]:
    """Use an emailed link: set the new password everywhere the user is linked."""
    from shelfmark.core.signup_provisioning import get_warnings, link_accounts_by_email, set_password

    user = user_db.consume_password_reset_code(None, _hash_token(token or ""))
    if not user:
        raise PasswordResetError("This reset link is invalid, already used, or has expired. Request a new one.")
    # Following the emailed link proves they own that address, so same-named
    # library accounts registered to it are theirs too.
    link_accounts_by_email(user_db, user, user.get("email") or "")
    user = user_db.get_user(user_id=int(user["id"]))
    results = set_password(user_db, user, password)
    logger.info("Self-service password reset completed for '%s'", user["username"])
    return {
        "username": user["username"],
        "updated": [_APP_LABELS[s] for s, r in results.items() if r.get("status") == "updated"],
        "warnings": get_warnings(results),
    }


def _app_rows(user: Dict[str, Any]) -> List[Dict[str, str]]:
    """Per library app: what this reset will do to it, for the email."""
    from shelfmark.core.signup_provisioning import _find_library_account, library_account_status

    status = library_account_status(user)
    email = str(user.get("email") or "").strip().lower()
    rows = []
    for service in ("calibre_web", "audiobookshelf"):
        s = status[service]
        if not s["offered"]:
            continue
        if s["linked"]:
            state, ok = "Linked — will be updated", True
        elif s["has_account"]:
            account = _find_library_account(service, user["username"]) or {}
            if email and str(account.get("email") or "").strip().lower() == email:
                state, ok = "Registered to this email — will be linked and updated", True
            else:
                state, ok = "Not linked — its password won't change", False
        else:
            state, ok = "No account yet — you can add one from Library Access", False
        rows.append({"label": _APP_LABELS[service], "host": _app_host(service), "state": state, "ok": "1" if ok else ""})
    return rows


def compose_reset_email(user: Dict[str, Any], link: str, from_addr: str, rows: List[Dict[str, str]]) -> EmailMessage:
    site = _host(_public_url()) or "the requests site"
    hosts = " and ".join(r["host"] for r in rows) or "your library apps"
    name = user.get("display_name") or user["username"]
    needs_linking = any(not r["ok"] for r in rows)

    text = [
        f"Hi {name},",
        "",
        f"We received a request to reset the password for your {site} account ({user['username']}).",
        "",
        f"Reset your password: {link}",
        "",
        f"This link works once and expires in {LINK_LIFETIME_MINUTES} minutes. If you didn't ask for this, "
        "ignore this email; your password won't change.",
        "",
        "ONE PASSWORD FOR ALL YOUR LIBRARIES",
        f"Resetting this password will also set it for your linked accounts on {hosts}.",
        "",
    ]
    text += [f"  {r['label']} ({r['host']}): {r['state']}" for r in rows]
    text += [
        "",
        "HOW TO LINK AN ACCOUNT",
        f"1. Sign in at {_public_url()}",
        "2. Open the menu (\u2630, top right), choose Account, and find Library Access.",
        "3. Click Link next to Ebooks or Audiobooks and enter that app's current password.",
        "   No account there yet? Click Add to create one with your requests-site password.",
        "",
        "Tip: if your Ebooks or Audiobooks password is the same as your requests-site password, "
        "signing in links it automatically.",
        "",
        f"— {site}",
    ]

    e = html.escape
    row_html = "".join(
        f'<tr><td style="padding:10px 0;border-top:1px solid #e5e7eb;">'
        f'<div style="font-weight:600;color:#111827;">{e(r["label"])} '
        f'<span style="font-weight:400;color:#6b7280;">· {e(r["host"])}</span></div>'
        f'<div style="font-size:14px;color:{"#047857" if r["ok"] else "#b45309"};">'
        f'{"&#10003;" if r["ok"] else "&#9888;"} {e(r["state"])}</div></td></tr>'
        for r in rows
    )
    link_steps = (
        f'<ol style="margin:8px 0 0;padding-left:20px;color:#374151;font-size:14px;line-height:1.6;">'
        f'<li>Sign in at <a href="{e(_public_url())}" style="color:#0e7490;">{e(site)}</a></li>'
        f'<li>Open the menu (&#9776;, top right), choose <b>Account</b>, and find <b>Library Access</b>.</li>'
        f'<li>Click <b>Link</b> next to Ebooks or Audiobooks and enter that app\'s current password. '
        f'No account there yet? Click <b>Add</b> to create one with your requests-site password.</li></ol>'
        f'<p style="margin:10px 0 0;font-size:13px;color:#6b7280;">If your Ebooks or Audiobooks password is the '
        f'same as your requests-site password, signing in links it automatically.</p>'
    )
    body = f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;">
<tr><td style="background:#0f766e;padding:20px 28px;color:#ffffff;font-size:20px;font-weight:700;">{e(site)}</td></tr>
<tr><td style="padding:28px;">
<h1 style="margin:0 0 12px;font-size:22px;color:#111827;">Reset your password</h1>
<p style="margin:0 0 20px;color:#374151;font-size:15px;line-height:1.5;">Hi {e(name)}, we received a request to reset
the password for your account <b>{e(user['username'])}</b>.</p>
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:8px;background:#0d9488;">
<a href="{e(link)}" style="display:inline-block;padding:12px 24px;color:#ffffff;font-weight:600;font-size:16px;text-decoration:none;">Reset my password</a>
</td></tr></table>
<p style="margin:16px 0 0;color:#6b7280;font-size:13px;line-height:1.5;">This link works once and expires in
{LINK_LIFETIME_MINUTES} minutes. If you didn't ask for this, ignore this email; your password won't change.</p>
<div style="margin:24px 0 0;padding:16px 18px;background:#f0fdfa;border:1px solid #99f6e4;border-radius:10px;">
<div style="font-weight:700;color:#134e4a;font-size:15px;">One password for all your libraries</div>
<p style="margin:6px 0 4px;color:#374151;font-size:14px;line-height:1.5;">Resetting this password will also set it for your linked accounts on <b>{e(hosts)}</b>.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{row_html}</table>
</div>
<div style="margin:20px 0 0;">
<div style="font-weight:700;color:#111827;font-size:15px;">{"Link your other accounts" if needs_linking else "How linking works"}</div>
{link_steps}
</div>
<p style="margin:24px 0 0;color:#9ca3af;font-size:12px;line-height:1.5;">Button not working? Paste this into your browser:<br>
<a href="{e(link)}" style="color:#0e7490;word-break:break-all;">{e(link)}</a></p>
</td></tr></table>
</td></tr></table>
</body></html>"""

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = user["email"]
    msg["Subject"] = f"Reset your password for {site}"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(from_addr.rpartition("@")[2].strip(" >") or "shelfmark.local"))
    msg.set_content("\n".join(text))
    msg.add_alternative(body, subtype="html")
    return msg


def _send_reset_email(user: Dict[str, Any], link: str) -> None:
    from shelfmark.core.request_notifications import _get_smtp_config
    from shelfmark.download.outputs.email import send_email_message

    smtp_config = _get_smtp_config()
    if smtp_config is None:
        logger.warning("Cannot email a password reset link: SMTP is not configured")
        return
    send_email_message(smtp_config, compose_reset_email(user, link, smtp_config.from_addr, _app_rows(user)))
    logger.info("Password reset link emailed to '%s'", user["username"])

