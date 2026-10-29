"""Asking for a seat: a stranger's request, the planner's decision, the invite that follows, and the mail carrying both.

WHY a request table and not open signups: AGENTS.md in the Long Way repo makes membership the planner's act. The door
on the sign-in screen records who is asking; Amo invites or declines from the house. The request row is the system of
record; the email to the planner and the push to house managers are its announcements, and both may lag the row.
"""
import asyncio
import logging
import os
import smtplib
from uuid import uuid4

from api.notifications.webpush import send_web_notifications
from . import mail
from .membership import CODE_DAYS, invite as issue_invite

logger = logging.getLogger(__name__)
SITE = os.environ.get("LONGWAY_SITE_URL", "https://thelongway.world")


async def ask(db, email: str, name: str, note: str, ip: str | None) -> dict:
    """Record one open request per address; asking again refreshes the name, note and time and re-arms the email."""
    row = await db.fetchrow("""INSERT INTO longway_invite_requests (id, email, name, note, ip) VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (email) WHERE decision IS NULL DO UPDATE SET name = EXCLUDED.name,
          note = CASE WHEN EXCLUDED.note = '' THEN longway_invite_requests.note ELSE EXCLUDED.note END,
          ip = EXCLUDED.ip, created_at = clock_timestamp(), notified_at = NULL
        RETURNING *""", uuid4(), email, name, note, ip)
    return dict(row)


async def announce(db, row: dict) -> dict:
    """Push to the house managers now and email the planner; failures are logged and left to the notifier job."""
    result = {"pushed": 0, "emailed": False}
    managers = await db.fetch("""SELECT m.user_id FROM room_memberships m JOIN rooms r ON r.id = m.room_id
        WHERE r.is_home AND m.can_manage_home""")
    if managers:
        try:
            pushed = await send_web_notifications(db=db, recipient_user_ids=[str(m["user_id"]) for m in managers],
                title=f"{row['name']} asks for a seat", body=(row["note"] or row["email"])[:240],
                data={"type": "longway_invite_request", "request_id": str(row["id"])}, tag=f"longway_invite_{row['id']}")
            result["pushed"] = pushed.get("sent", 0)
        except Exception:
            logger.exception("Push for invite request %s failed", row["id"])
    try:
        result["emailed"] = await email_planner(db, row)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Email for invite request %s failed: %s", row["id"], exc)
    return result


async def email_planner(db, row: dict) -> bool:
    """The email Amo asked for; stamps notified_at when it goes. False, and no stamp, while mail is off."""
    body = (f"{row['name']} <{row['email']}> asks for a seat at The Long Way.\n\n"
            f"{row['note'] or '(no note)'}\n\n"
            f"Invite or decline from the house: {SITE}/\n"
            f"Asked {row['created_at']:%d %b %Y %H:%M} UTC" + (f" from {row['ip']}" if row.get("ip") else "") + ".\n")
    try:
        await asyncio.to_thread(mail.send, mail.notify_address(), f"{row['name']} asks for a seat at The Long Way", body)
    except mail.MailDisabled:
        return False
    await db.execute("UPDATE longway_invite_requests SET notified_at = clock_timestamp() WHERE id = $1", row["id"])
    return True


async def pending_emails(db) -> list:
    return [dict(r) for r in await db.fetch("""SELECT * FROM longway_invite_requests
        WHERE notified_at IS NULL AND decision IS NULL ORDER BY created_at LIMIT 20""")]


async def decide_invite(db, request_id, actor_id) -> dict:
    """Seat the requester: account, house membership and a fresh code; email the code when mail is on.

    The code is always returned to the manager, so a house without mail can still pass it on by hand.
    """
    row = await db.fetchrow("SELECT * FROM longway_invite_requests WHERE id = $1", request_id)
    if not row:
        raise KeyError(request_id)
    issued = await issue_invite(db, row["email"], row["name"])
    await db.execute("""UPDATE longway_invite_requests
        SET decision = 'invited', decided_at = clock_timestamp(), decided_by = $2, user_id = $3 WHERE id = $1""",
        request_id, actor_id, issued["user_id"])
    body = ("Amo invited you to The Long Way.\n\n"
            f"Open {SITE}/ and tap \"I have a code\" under Sign In, then enter\n"
            f"  email: {row['email']}\n  code: {issued['code']}\n"
            f"and choose a password of your own. The code works for {CODE_DAYS} days.\n")
    emailed, mail_error = False, None
    try:
        await asyncio.to_thread(mail.send, row["email"], "Your seat at The Long Way", body)
        emailed = True
        await db.execute("UPDATE longway_invite_requests SET invited_email_at = clock_timestamp() WHERE id = $1", request_id)
    except mail.MailDisabled:
        pass
    except (smtplib.SMTPException, OSError) as exc:
        mail_error = str(exc)
        logger.warning("Invite email for request %s failed: %s", request_id, exc)
    return {"id": request_id, "email": row["email"], "name": row["name"], "code": issued["code"],
            "emailed": emailed, "mail_error": mail_error, "expires_at": issued["expires_at"]}


async def decline(db, request_id, actor_id) -> dict:
    row = await db.fetchrow("""UPDATE longway_invite_requests
        SET decision = 'declined', decided_at = clock_timestamp(), decided_by = $2 WHERE id = $1 RETURNING id""",
        request_id, actor_id)
    if not row:
        raise KeyError(request_id)
    return {"id": request_id, "decision": "declined"}


async def listing(db) -> dict:
    rows = await db.fetch("""SELECT id, email, name, note, created_at, decision, decided_at, notified_at, invited_email_at
        FROM longway_invite_requests ORDER BY (decision IS NULL) DESC, created_at DESC LIMIT 50""")
    return {"mail_configured": mail.configured(), "requests": [dict(r) for r in rows]}
