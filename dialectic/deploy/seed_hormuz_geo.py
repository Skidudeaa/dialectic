"""
Seed the Iran/Hormuz Trading Room's geography (World Lens).

Thin wrapper: the six Hormuz scopes (Strait of Hormuz, TSS inbound lane,
Persian Gulf, Gulf of Oman, Bab el Mandeb, Strait of Malacca) now live in
`deploy/geo/iran-hormuz.json`, resolved and inserted by the generalised
`deploy/seed_room_geo.py` — same writer, same idempotency-by-live-label
rule, same GEO_SCOPE_CREATED event. This file exists only so a founder can
still run the original one-room command by name.

Reviewed operator script — run manually, never automatically, as the
founder who is confirming the geometry (their user id is stamped as
confirmed_by, per the CHECK `confirmed_iff_human`):
    /usr/bin/python3 deploy/seed_hormuz_geo.py --confirmed-by <user uuid> [--dry-run]
"""
import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_room_geo import main  # noqa: E402

MANIFEST = Path(__file__).resolve().parent / "geo" / "iran-hormuz.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmed-by", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--geometry-inspected-by-named-human", action="store_true")
    return parser


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    args = build_parser().parse_args()
    asyncio.run(main(
        MANIFEST, args.confirmed_by, args.dry_run,
        geometry_inspected=args.geometry_inspected_by_named_human,
    ))
