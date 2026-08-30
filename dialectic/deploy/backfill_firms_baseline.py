#!/usr/bin/env python3
"""Seed the fire baseline from FIRMS history so day one is not all-novel.

WHY: `llm/world_watch._score_fire` calls a cell NEW when this room's
`world_observations` hold no prior acquisition day for it. On the day FIRMS
is switched on that is every cell — 106 of them over the Persian Gulf, 87 of
which are flares that burn every night. Without history the participant
would spend a week learning what a flare looks like. FIRMS serves five days
per call with a start date, so two calls per dataset per fence give the ten
days before today.

WHAT IT WRITES: rows shaped exactly like world_watch's, through the same
`WorldSignal` validation and the same point-in-polygon test, but with
`first_seen_at`/`last_seen_at` set to the ACQUISITION time (not now), label
suffix `backfilled baseline`, `details.backfill = true`, and never a
`novel` verdict. So they are prior days for the scorer, invisible to every
"last 24h" reader, and age out of the 30-day retention on their own clock.
Today's rows are never touched (`ON CONFLICT DO NOTHING`; the windows end
yesterday). Read-only against NASA; no interjection can fire from here.

Usage:
    python3 deploy/backfill_firms_baseline.py [--days 10] [--dry-run]
"""

import argparse
import asyncio
import csv
import io
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=10, help="days before today to fetch (multiple of 5, max 30)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.days % 5 or not 5 <= args.days <= 30:
        parser.error("--days must be 5, 10, ..., 30 (FIRMS serves five days per call)")

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import asyncpg
    import httpx
    import world_adapters as wa
    from geo_scopes import GeoScopeService, point_in_geometry

    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        print("FIRMS_MAP_KEY is not set", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    for t in ("jsonb", "json"):
        await conn.set_type_codec(t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    try:
        fences = await wa.room_fences(conn)
        starts = [date.today() - timedelta(days=d) for d in range(args.days, 0, -5)]
        rows: list[dict] = []
        calls = 0
        async with httpx.AsyncClient(timeout=60.0) as client:
            for fence in fences:
                for source in wa.FIRMS_SOURCES:
                    for start in starts:
                        # The live adapter's URL ends in day range 1; history
                        # asks for the full five days from `start`.
                        url = wa.FIRMS_URL.format(
                            key=key, source=source,
                            west=round(fence.west, 3), south=round(fence.south, 3),
                            east=round(fence.east, 3), north=round(fence.north, 3),
                        ).rsplit("/", 1)[0] + f"/5/{start.isoformat()}"
                        calls += 1
                        body = (await wa._get(client, url)).text
                        rows.extend(csv.DictReader(io.StringIO(body)))
        today = date.today().isoformat()
        merged = [o for o in wa._merge_fire_cells(rows) if o["details"]["acq_date"] < today]
        adapter = next(a for a in wa.ADAPTERS if a.provider == "firms")
        # The live cap protects the in-process store; history goes to Postgres.
        wa.MAX_SIGNALS_PER_PROVIDER = max(wa.MAX_SIGNALS_PER_PROVIDER, len(merged))
        snapshot = wa.build_snapshot(adapter, wa.AdapterResult("ok", "current", "backfill", merged), fences)
        print(f"{calls} FIRMS calls, {len(rows)} pixels, {len(merged)} cell-days before today, "
              f"{len(snapshot.signals) if snapshot else 0} inside a fence")
        if snapshot is None:
            return 0

        inserted = 0
        by_room: dict[UUID, list] = {}
        for signal in snapshot.signals:
            by_room.setdefault(signal.room_id, []).append(signal)
        for room_id, signals in by_room.items():
            projection = await GeoScopeService(conn).build(room_id)
            scopes = [(UUID(s.id.split(":", 1)[1]), s) for s in projection.scopes
                      if s.authority != "machine_proposed"]
            for scope_id, scope in scopes:
                for signal in signals:
                    lon, lat = signal.geometry["coordinates"][:2]
                    if not point_in_geometry(scope.geometry, float(lon), float(lat)):
                        continue
                    if args.dry_run:
                        inserted += 1
                        continue
                    status = await conn.execute(
                        """INSERT INTO world_observations
                               (room_id, scope_id, provider, signal_id, layer, kind, label,
                                geometry, provenance, details, observed_at, retrieved_at,
                                first_seen_at, last_seen_at)
                           VALUES ($1,$2,'firms',$3,'fires','point',$4,$5,$6,$7,$8,$9,$8,$8)
                           ON CONFLICT (scope_id, signal_id) DO NOTHING""",
                        room_id, scope_id, signal.id, f"{signal.label} · backfilled baseline",
                        signal.geometry, signal.provenance.model_dump(),
                        {**signal.details, "backfill": True},
                        signal.observed_at, signal.retrieved_at,
                    )
                    inserted += int(status.endswith(" 1"))
        print(f"{'would insert' if args.dry_run else 'inserted'} {inserted} baseline rows")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
