"""Membership is the planner's act. An invitation is an account plus a one-time reset code, never a password.

Moved here from deploy/longway_seed.py so the house (a manager tapping Invite) and the shell command write the same
rows: users + user_credentials + a house membership + a 7-day password_reset code, mirroring api/auth/routes.py
signup and migration 013's Home creation. The invitee opens the app, chooses "I have a code", and enters their email,
the code and a password of their own; nothing secret passes through whoever invited them.
"""
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from api.auth.utils import get_password_hash

HOUSE_NAME = "The Long Way"
CODE_DAYS = 7


async def ensure_house(conn) -> str:
    """The one is_home room, created with its Main thread and receipts when absent; returns its id."""
    home = await conn.fetchrow("SELECT id, name FROM rooms WHERE is_home")
    if home:
        return str(home["id"])
    now = datetime.now(timezone.utc)
    home_id, main_id = uuid4(), uuid4()
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO rooms (id, created_at, token, name, is_home) VALUES ($1, $2, $3, $4, TRUE)",
            home_id, now, uuid4().hex, HOUSE_NAME)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, $3, 'Main')", main_id, home_id, now)
        await conn.execute(
            "INSERT INTO events (id, timestamp, event_type, room_id, payload) VALUES ($1, $2, 'room_created', $3, $4)",
            uuid4(), now, home_id, {"name": HOUSE_NAME})
        await conn.execute(
            "INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload) VALUES ($1, $2, 'thread_created', $3, $4, $5)",
            uuid4(), now, home_id, main_id, {"title": "Main"})
    return str(home_id)


async def invite(conn, email: str, name: str, manager: bool = False) -> dict:
    """Create (or reuse) the account for email, seat it in the house and issue a fresh reset code.

    Returns user_id, email, name, code, expires_at and created (False when the account already existed).
    Raises ValueError on an empty address or name. Earlier unused reset codes for the account are spent.
    """
    email = email.strip().lower()
    name = name.strip()
    if not email or "@" not in email or not name:
        raise ValueError("An email address and a display name are required.")
    home_id = await ensure_house(conn)
    now = datetime.now(timezone.utc)
    existing = await conn.fetchval("SELECT user_id FROM user_credentials WHERE email = $1", email)
    async with conn.transaction():
        if existing:
            user_id = existing
        else:
            user_id = uuid4()
            await conn.execute(
                "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)", user_id, now, name)
            # A random 48-byte password nobody knows: the account is usable only after the reset below.
            await conn.execute(
                """INSERT INTO user_credentials (user_id, email, email_verified, password_hash, created_at, updated_at)
                   VALUES ($1, $2, TRUE, $3, $4, $4)""",
                user_id, email, get_password_hash(secrets.token_urlsafe(48)), now)
        joined = await conn.fetchval(
            """INSERT INTO room_memberships (room_id, user_id, joined_at, can_manage_home)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (room_id, user_id) DO UPDATE SET can_manage_home = room_memberships.can_manage_home OR EXCLUDED.can_manage_home
               RETURNING (xmax = 0) AS inserted""",
            home_id, user_id, now, manager)
        if joined:
            await conn.execute(
                "INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload) VALUES ($1, $2, 'user_joined', $3, $4, $5)",
                uuid4(), now, home_id, user_id, {"invited": True})
        code = f"{secrets.randbelow(1_000_000):06d}"
        await conn.execute("UPDATE verification_codes SET used_at = $2 WHERE user_id = $1 AND purpose = 'password_reset' AND used_at IS NULL",
                           user_id, now)
        await conn.execute(
            "INSERT INTO verification_codes (user_id, code, purpose, created_at, expires_at) VALUES ($1, $2, 'password_reset', $3, $4)",
            user_id, code, now, now + timedelta(days=CODE_DAYS))
    return {"user_id": user_id, "email": email, "name": name, "code": code,
            "expires_at": now + timedelta(days=CODE_DAYS), "created": existing is None}
