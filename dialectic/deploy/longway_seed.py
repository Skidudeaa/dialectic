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
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import asyncpg  # noqa: E402

from organs.longway.membership import CODE_DAYS, ensure_house, invite  # noqa: E402


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


async def invite_cmd(conn: asyncpg.Connection, email: str, name: str, manager: bool) -> None:
    # The rows come from organs/longway/membership.py, the same door the house's Invite button uses.
    try:
        issued = await invite(conn, email, name, manager)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"{'created' if issued['created'] else 'updated'} {issued['name']} <{issued['email']}>{' as house manager' if manager else ''}")
    print(f"one-time reset code (valid {CODE_DAYS} days): {issued['code']}")
    print("They open the app, choose reset password, and enter this email, the code and a password of their own.")


async def members(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch(
        """SELECT u.display_name, c.email, m.can_manage_home, m.joined_at
           FROM room_memberships m JOIN rooms r ON r.id = m.room_id AND r.is_home
           JOIN users u ON u.id = m.user_id LEFT JOIN user_credentials c ON c.user_id = u.id
           ORDER BY m.joined_at""")
    if not rows:
        print("the house has no members yet" if await conn.fetchval("SELECT 1 FROM rooms WHERE is_home") else "no house yet")
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
            await invite_cmd(conn, args.email, args.name, args.manager)
        else:
            await members(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
