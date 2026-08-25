"""
Backfill: Trump Tariffs Trading Room (8adcabb7-817a-4802-87c6-3bfd42e6a9eb) is
a live, bound thesis book per dialectic/CLAUDE.md's own live-trading-rooms
table, but has zero room_memberships -- the same root-cause bug
fix-room-membership-root-cause fixed for future rooms (POST /rooms never
joined its own creator). This backfills the one existing real room affected,
adding the same two members every one of its four sibling live trading rooms
already has (verified by direct query: Amo + Dan are members of Iran/Hormuz,
AI Capex, China Property, and Japan Rate Shock -- all four). Mirrors the
exact event emitted by the real join flow (api/main.py's join_room:
EventType.USER_JOINED_ROOM).

Reviewed operator script -- run manually, never automatically:
  /usr/bin/python3 deploy/backfill_trump_tariffs_membership.py
(blocked from running inline this session by the permission classifier;
prepared here, unrun, for the owner to execute directly.)
"""
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg

ROOM = UUID("8adcabb7-817a-4802-87c6-3bfd42e6a9eb")
AMO = UUID("de883378-a6ef-4af0-a8bc-462265ca7a54")
DAN = UUID("c9c8f30e-23ad-4730-bb9b-5555e29ae245")


async def main():
    conn = await asyncpg.connect("postgresql://root@localhost/dialectic")
    try:
        async with conn.transaction():
            existing = await conn.fetch(
                "SELECT user_id FROM room_memberships WHERE room_id = $1", ROOM
            )
            if existing:
                print(f"already has members, aborting: {existing}")
                return
            now = datetime.now(timezone.utc)
            for user_id in (AMO, DAN):
                await conn.execute(
                    "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
                    ROOM, user_id, now,
                )
                await conn.execute(
                    """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
                       VALUES ($1, $2, 'user_joined_room', $3, $4, $5)""",
                    uuid4(), now, ROOM, user_id,
                    '{"backfill": "orphaned-room-membership-fix-2026-08-25"}',
                )
        rows = await conn.fetch(
            """SELECT u.display_name FROM room_memberships rm
               JOIN users u ON u.id = rm.user_id WHERE rm.room_id = $1""",
            ROOM,
        )
        print("COMMITTED. members now:", [r["display_name"] for r in rows])
    finally:
        await conn.close()


asyncio.run(main())
