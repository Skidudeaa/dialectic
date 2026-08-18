#!/usr/bin/env python3
"""One-shot backfill: dialectic's commitments → the desk's claims ledger.

ARCHITECTURE: read-only against dialectic's Postgres (commitments +
commitment_confidence + users, one pass), write-only against the RUNNING
tradingDesk HTTP API. Re-runnable by construction: every write carries a
source_key (`stake:{uuid}:created` / `:confidence:{seq}` / `:resolved`) and
the desk's save_prediction_once / resolve_prediction_once dedup on it, so a
second run imports 0.

WHY HTTP rather than importing repository functions: the route validates
with the same PredictionCreate the live door uses, needs no td app
context/config, and exercises exactly the interface the stakes relay
(dialectic/api/stakes_relay.py) uses forward-looking — one contract, not
two. The honest interface is the running service.

WHY asyncpg and not stdlib: the desk's stdlib-only convention stops at the
desk's borders — there is no stdlib Postgres client, and asyncpg already
serves dialectic on this host. Everything else here is stdlib.

Mapping mirrors the live relay (see stakes_relay.py's docstring): a
commitment with no deadline or no recorded confidence is NOT importable —
tradingDesk's door requires both, and inventing either is the
confidence-75.0 poison. Those are counted and printed, never guessed at.

Run ONCE against production after the Phase 3 deploy (operator step):

    python3 tools/outcomes/import_dialectic_stakes.py \
        --dialectic-dsn "postgresql://root@localhost/dialectic"

Credentials come from TRADINGDESK_USER / TRADINGDESK_PASSWORD (the same
service principal dialectic's relays use). --dry-run prints the plan
without writing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Optional

DEFAULT_TD_URL = "http://127.0.0.1:8006"
DEFAULT_DSN = "postgresql://root@localhost/dialectic"


# ── mapping (pure — unit-testable without a DB or a desk) ────────────


def deadline_str(deadline: Any) -> Optional[str]:
    if deadline is None:
        return None
    if isinstance(deadline, datetime):
        return deadline.date().isoformat()
    value = str(deadline).strip()
    return value or None


def statement(commitment: dict) -> str:
    claim = str(commitment.get("claim") or "").strip()
    criteria = str(commitment.get("resolution_criteria") or "").strip()
    if criteria:
        return f"{claim} — resolves when: {criteria}"
    return claim


def source_label(commitment: dict) -> str:
    if commitment.get("created_by_user_id") is None:
        return "LLM"
    return commitment.get("display_name") or "human"


def create_body(commitment: dict, first_confidence: float) -> dict:
    cid = str(commitment["id"])
    return {
        "statement": statement(commitment),
        "confidence": float(first_confidence),
        "deadline": deadline_str(commitment.get("deadline")),
        "tags": ["dialectic", str(commitment.get("category") or "prediction")],
        "source_type": "dialectic_commitment",
        "source_label": source_label(commitment),
        "source_ref": cid,
        "source_key": f"stake:{cid}:created",
    }


def plan_commitment(commitment: dict, confidences: list[dict]) -> Optional[dict]:
    """The full write plan for one commitment, or None when unimportable.

    Shape: {create, confidence: [(seq, body), ...], resolve: body|None}.
    Confidence row 1 rides the create (the desk seeds history from it);
    rows 2..n are appended; a resolved/voided commitment resolves LAST so
    the history append never hits the desk's rejects-on-resolved guard.
    """
    if deadline_str(commitment.get("deadline")) is None or not confidences:
        return None
    cid = str(commitment["id"])
    create = create_body(commitment, confidences[0]["confidence"])
    later = [
        (
            seq,
            {
                "confidence": float(row["confidence"]),
                "reasoning": row.get("reasoning"),
                "source_key": f"stake:{cid}:confidence:{seq}",
            },
        )
        for seq, row in enumerate(confidences, start=1)
        if seq > 1
    ]
    resolve = None
    resolution = commitment.get("resolution")
    if resolution in ("correct", "incorrect", "partial", "voided"):
        resolve = {
            "resolution": resolution,
            "resolution_notes": commitment.get("resolution_notes"),
            "source_key": f"stake:{cid}:resolved",
        }
    return {"id": cid, "create": create, "confidence": later, "resolve": resolve}


# ── the desk over HTTP (stdlib) ──────────────────────────────────────


class Desk:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.token = self._login(username, password)

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 token: Optional[str] = None) -> Any:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _login(self, username: str, password: str) -> str:
        data = self._request(
            "POST", "/api/auth/login",
            {"username": username, "password": password},
        )
        token = (data or {}).get("access_token")
        if not token:
            raise SystemExit("tradingDesk login returned no access_token")
        return token

    def get(self, path: str) -> Any:
        return self._request("GET", path, token=self.token)

    def post(self, path: str, body: dict) -> Any:
        return self._request("POST", path, body, token=self.token)


# ── the run ──────────────────────────────────────────────────────────


async def load_dialectic(dsn: str) -> list[tuple[dict, list[dict]]]:
    import asyncpg  # local import: only the read side needs it

    conn = await asyncpg.connect(dsn)
    try:
        commitments = await conn.fetch(
            """SELECT c.*, u.display_name
               FROM commitments c
               LEFT JOIN users u ON u.id = c.created_by_user_id
               ORDER BY c.created_at""",
        )
        history = await conn.fetch(
            """SELECT commitment_id, confidence, reasoning, recorded_at
               FROM commitment_confidence
               ORDER BY recorded_at""",
        )
    finally:
        await conn.close()
    by_commitment: dict[str, list[dict]] = {}
    for row in history:
        by_commitment.setdefault(str(row["commitment_id"]), []).append(dict(row))
    return [
        (dict(c), by_commitment.get(str(c["id"]), [])) for c in commitments
    ]


def existing_source_refs(desk: Desk) -> set[str]:
    """dialectic_commitment rows already in the ledger, by source_ref.

    Used only for the imported/skipped report — correctness never depends
    on it (the desk's source_key dedup replays rather than duplicates), so
    a pre-provenance desk that omits these fields degrades the COUNTS, not
    the data.
    """
    refs: set[str] = set()
    try:
        for row in desk.get("/api/predictions"):
            if (
                isinstance(row, dict)
                and row.get("source_type") == "dialectic_commitment"
                and row.get("source_ref")
            ):
                refs.add(str(row["source_ref"]))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
        pass
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dialectic-dsn",
        default=os.environ.get("DIALECTIC_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DSN,
    )
    parser.add_argument(
        "--td-url", default=os.environ.get("TRADINGDESK_URL", DEFAULT_TD_URL),
    )
    parser.add_argument("--td-user", default=os.environ.get("TRADINGDESK_USER"))
    parser.add_argument(
        "--td-password", default=os.environ.get("TRADINGDESK_PASSWORD"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.td_user or not args.td_password:
        raise SystemExit(
            "TRADINGDESK_USER/TRADINGDESK_PASSWORD are required "
            "(flags or environment)."
        )

    rows = asyncio.run(load_dialectic(args.dialectic_dsn))
    plans, unimportable = [], 0
    for commitment, confidences in rows:
        plan = plan_commitment(commitment, confidences)
        if plan is None:
            unimportable += 1
            print(
                f"  unimportable {commitment['id']}: "
                f"{'no deadline' if deadline_str(commitment.get('deadline')) is None else 'no recorded confidence'}"
            )
        else:
            plans.append(plan)

    if args.dry_run:
        print(
            f"[dry-run] would import {len(plans)} commitment(s); "
            f"{unimportable} unimportable."
        )
        return 0

    desk = Desk(args.td_url, args.td_user, args.td_password)
    already = existing_source_refs(desk)

    imported = skipped = conflicts = 0
    for plan in plans:
        if plan["id"] in already:
            skipped += 1
        try:
            created = desk.post("/api/predictions", plan["create"])
            if plan["id"] not in already:
                imported += 1
            td_id = created.get("id") if isinstance(created, dict) else None
            if not td_id:
                conflicts += 1
                print(f"  conflict {plan['id']}: create returned no id")
                continue
            for _seq, body in plan["confidence"]:
                try:
                    desk.post(f"/api/predictions/{td_id}/confidence", body)
                except urllib.error.HTTPError as e:
                    conflicts += 1
                    print(f"  conflict {plan['id']} confidence: HTTP {e.code}")
            if plan["resolve"] is not None:
                try:
                    desk.post(f"/api/predictions/{td_id}/resolve", plan["resolve"])
                except urllib.error.HTTPError as e:
                    if e.code == 409:
                        # A human already resolved it on the desk — theirs wins.
                        print(f"  conflict {plan['id']} resolve: desk resolution stands")
                    conflicts += 1
        except urllib.error.HTTPError as e:
            conflicts += 1
            print(f"  conflict {plan['id']}: HTTP {e.code} {e.read().decode()[:200]}")

    print(
        f"imported {imported}, skipped (already present) {skipped}, "
        f"unimportable {unimportable}, conflicts {conflicts}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
