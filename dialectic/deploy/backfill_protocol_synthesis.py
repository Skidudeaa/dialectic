"""One-off: replace "synthesis pending" protocol memories with the real synthesis.

F-003: _conclude_protocol used to link a placeholder memory and never fill it.
The synthesis is each protocol's latest final-phase facilitator message; this
appends a new memory version (edit_memory) and links source_message_id.

    cd dialectic && python3 deploy/backfill_protocol_synthesis.py [--dry-run]
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from memory.manager import MemoryManager  # noqa: E402

SQL = """
SELECT p.id AS protocol_id, m.id AS memory_id, fm.id AS message_id, fm.content
FROM thread_protocols p
JOIN memories m ON m.id = p.synthesis_memory_id
JOIN LATERAL (
    SELECT x.id, x.content FROM messages x WHERE x.protocol_id = p.id
    ORDER BY x.protocol_phase DESC NULLS LAST, x.sequence DESC LIMIT 1
) fm ON true
WHERE p.status = 'concluded' AND m.content LIKE '[Protocol %synthesis pending]'
"""


async def main(dry_run: bool) -> None:
    cfg = dotenv_values(os.path.join(os.path.dirname(__file__), "..", ".env"))
    conn = await asyncpg.connect(os.environ.get("DATABASE_URL") or cfg["DATABASE_URL"])
    try:
        rows = await conn.fetch(SQL)
        print(f"{len(rows)} placeholder synthesis memories")
        if dry_run:
            return
        mm = MemoryManager(conn)
        for r in rows:
            await mm.edit_memory(r["memory_id"], r["content"], edit_reason="F-003 backfill")
            await conn.execute(
                "UPDATE memories SET source_message_id = $1 WHERE id = $2",
                r["message_id"], r["memory_id"],
            )
            print(f"backfilled protocol {r['protocol_id']} -> memory {r['memory_id']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
