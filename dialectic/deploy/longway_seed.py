#!/usr/bin/env python3
"""
The Long Way house: seed the house room and invite members, against this instance's database.

    python3 deploy/longway_seed.py house                       create the one is_home room ("The Long Way") if absent
    python3 deploy/longway_seed.py invite --email E --name N   create an account with no usable password, add it to the
                                                               house, and print a one-time 6-digit reset code (7 days)
    python3 deploy/longway_seed.py invite ... --manager        the same, with can_manage_home (the planner: Amo)
    python3 deploy/longway_seed.py members                     list house members

ARCHITECTURE: an invitation is an account plus a password-reset code, never a password. The invitee opens the app,
chooses "reset password", enters their email, the code and a password of their own. Nothing secret passes through the
person who ran this script. Mirrors api/auth/routes.py signup (users + user_credentials + verification_codes) and
migration 013's Home creation (rooms.is_home, a Main thread, room_created/thread_created events), so the app sees
rows it would have written itself.

WHY not SIGNUPS_ENABLED: an open sign-up door on a URL that only friends know is still an open door. Signups stay
closed; membership is the planner's act, as AGENTS.md in the Long Way repo requires.

Reads DATABASE_URL from the environment (EnvironmentFile /etc/longway/longway.env when run through systemd-run, or
`set -a; . /etc/longway/longway.env; set +a` in a shell). Refuses to run against a database whose rooms carry
linked_book_id values, which marks the Dialectic trading instance.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import asyncpg  # noqa: E402

from api.auth.utils import get_password_hash  # noqa: E402

HOUSE_NAME = "The Long Way"


async def connect() -> asyncpg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    conn = await asyncpg.connect(url)
    # A bare connection has no jsonb codec; the app's pool sets this one (the deploy-script law in CLAUDE.md).
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    bound = await conn.fetchval("SELECT count(*) FROM rooms WHERE linked_book_id IS NOT NULL")
    if bound:
        await conn.close()
        sys.exit("This database holds trading rooms; refusing to seed The Long Way into the Dialectic instance.")
    return conn


async def ensure_house(conn: asyncpg.Connection) -> str:
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


async def invite(conn: asyncpg.Connection, email: str, name: str, manager: bool) -> None:
    email = email.strip().lower()
    name = name.strip()
    if not email or "@" not in email or not name:
        sys.exit("An email address and a display name are required.")
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
            user_id, code, now, now + timedelta(days=7))
    print(f"{'updated' if existing else 'created'} {name} <{email}>{' as house manager' if manager else ''}")
    print(f"one-time reset code (valid 7 days): {code}")
    print("They open the app, choose reset password, and enter this email, the code and a password of their own.")


async def members(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch(
        """SELECT u.display_name, c.email, m.can_manage_home, m.joined_at
           FROM room_memberships m JOIN rooms r ON r.id = m.room_id AND r.is_home
           JOIN users u ON u.id = m.user_id LEFT JOIN user_credentials c ON c.user_id = u.id
           ORDER BY m.joined_at""")
    if not rows:
        print("no house yet")
    for r in rows:
        print(f"{r['display_name']:24} {r['email'] or '-':32} {'manager' if r['can_manage_home'] else 'member':8} since {r['joined_at']:%Y-%m-%d}")


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("house")
    i = sub.add_parser("invite")
    i.add_argument("--email", required=True)
    i.add_argument("--name", required=True)
    i.add_argument("--manager", action="store_true")
    sub.add_parser("members")
    args = p.parse_args()
    conn = await connect()
    try:
        if args.command == "house":
            print("house room", await ensure_house(conn))
        elif args.command == "invite":
            await invite(conn, args.email, args.name, args.manager)
        else:
            await members(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
