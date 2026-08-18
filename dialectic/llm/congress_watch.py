# llm/congress_watch.py — politician trade disclosures become readings

"""
ARCHITECTURE: One hourly scheduler job — congress_watch. It pulls the two
community-maintained public JSON datasets of congressional stock
disclosures (Senate/House Stock Watcher), keeps the newest filings, and
for every room wired to a trading book whose instrument universe holds the
disclosed ticker, files ONE reading per (room, disclosure): source =
'congress', synthetic URL `congress://<member-slug>/<tx-hash>`, body =
member, ticker, direction, amount band, filing + transaction dates.

READINGS ONLY — deliberately NO interjection. The owner's "trump trades"
ask is a signal lane, not a klaxon: reading_echo already surfaces new
readings to the rooms they bear on, and the morning brief renders them, so
a disclosure reaches the humans through the existing capped channels
without a new speaker anywhere. The reading is also what the LLM cites
when it drafts a disclosure-implied claim (source_type='congress' at the
td door — the ledger then scores congress as a source).

DATASET ASSUMPTION (verify live before enabling): the canonical community
S3 dumps —
  https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json
  https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json
Row shape assumed: senator/representative, ticker, type, amount,
transaction_date, disclosure_date, ptr_link — every read is .get() with a
fallback, any fetch or shape failure logs and SKIPS, the job never raises.
These are volunteer-run mirrors of the official eFD/Clerk filings; the URL
or shape drifting is an expected failure mode, which is exactly why:

SHIPS DARK: CONGRESS_WATCH_ENABLED defaults OFF — read in the job body
with default "0", because scheduler.Job.enabled() treats an UNSET env as
on ("1" default) and this job must not fetch a multi-megabyte dataset on a
timer until someone has verified the URLs against production reality.
Setting the var to "1" arms it; "0" (or unset) keeps it dark at both the
tick gate and the body gate, consistently.

WHY the instrument universe and not keywords: a book's instruments map
(builder format, served by td's /api/bridge/structure/{thesis_id}) is the
authored list of tickers the thesis actually trades. A senator buying XOP
is signal for the Hormuz room BECAUSE the book holds XOP; a senator buying
anything else is somebody else's news.

TRADEOFF: the whole-dataset pull re-downloads history every run. Fine at
one run/hour behind a dark flag; an incremental endpoint can replace
_fetch_dataset without touching the pipeline when volume ever matters.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from urllib.request import Request, urlopen

from scheduler import Job, SchedulerContext
from llm import tradingdesk_client as td
from llm.reading import save_reading, seen_urls

logger = logging.getLogger(__name__)

ENABLED_ENV = "CONGRESS_WATCH_ENABLED"

# ASSUMPTION (documented above, coded defensively): community dataset URLs.
SENATE_DATASET_URL = (
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com"
    "/aggregate/all_transactions.json"
)
HOUSE_DATASET_URL = (
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com"
    "/data/all_transactions.json"
)

FETCH_TIMEOUT_S = 30
# The senate dump runs ~10-20 MB; cap the read so a misbehaving mirror
# cannot balloon the worker thread.
DATASET_MAX_BYTES = 60 * 1024 * 1024

# Newest disclosures considered per run (post-sort); the datasets carry a
# decade of history and only the leading edge is news.
SCAN_CAP = 400
# New readings filed per room per run — a first run against a fresh room
# must not dump the whole leading edge into its library at once.
PER_ROOM_CAP = 5

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Real tickers: 1-6 alphanumerics with optional .-suffix (BRK.B). The house
# dataset carries "--", "N/A" and stray HTML in its ticker column.
_TICKER_RE = re.compile(r"^[A-Z0-9]{1,6}(\.[A-Z0-9]{1,2})?$")


def _enabled() -> bool:
    """Body-level gate with a DARK default — see SHIPS DARK above."""
    return os.environ.get(ENABLED_ENV, "0").strip().lower() in ("1", "true", "yes")


def _fetch_dataset_bytes(url: str) -> bytes:
    """Blocking fetch — callers run this via asyncio.to_thread."""
    req = Request(url, headers={"User-Agent": "dialectic-congress-watch/1.0"})
    with urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read(DATASET_MAX_BYTES)


def _parse_date(raw) -> datetime | None:
    """MM/DD/YYYY (senate) or YYYY-MM-DD (house), else None — a filing with
    an unreadable date sorts as oldest rather than crashing the run."""
    text = str(raw or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _clean_ticker(raw) -> str | None:
    ticker = str(raw or "").strip().upper()
    return ticker if _TICKER_RE.match(ticker) else None


def _direction(tx_type: str) -> str:
    lowered = tx_type.lower()
    if "purchase" in lowered:
        return "buy"
    if "sale" in lowered:
        return "sell"
    return tx_type or "unknown"


def _slugify(raw: str) -> str:
    slug = _SLUG_RE.sub("-", raw.lower()).strip("-")[:50].strip("-")
    return slug or "member"


def normalize_disclosures(raw, chamber: str) -> list[dict]:
    """Dataset rows → uniform disclosure dicts, junk dropped.

    The datasets have no stable row id, so identity is a content hash of
    the fields that make two rows the same filing — the synthetic URL
    built from it is what seen_urls dedups on across runs.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        member = str(row.get("senator") or row.get("representative") or "").strip()
        ticker = _clean_ticker(row.get("ticker"))
        if not member or not ticker:
            continue
        tx_type = str(row.get("type") or "").strip()
        amount = str(row.get("amount") or "").strip()
        tx_date = str(row.get("transaction_date") or "").strip()
        filed_date = str(row.get("disclosure_date") or "").strip()
        tx_hash = hashlib.sha256(
            f"{chamber}|{member}|{ticker}|{tx_date}|{tx_type}|{amount}"
            .encode("utf-8")
        ).hexdigest()[:16]
        out.append({
            "url": f"congress://{_slugify(member)}/{tx_hash}",
            "chamber": chamber,
            "member": member,
            "ticker": ticker,
            "type": tx_type or "unknown",
            "direction": _direction(tx_type),
            "amount": amount or "undisclosed band",
            "transaction_date": tx_date,
            "disclosure_date": filed_date,
            "ptr_link": str(row.get("ptr_link") or "").strip(),
            "_filed_at": _parse_date(filed_date) or datetime.min,
        })
    return out


def _disclosure_article(d: dict) -> dict:
    """The reading body — structured facts, not fetched prose, so the thin
    gate deliberately does NOT apply: this text is synthesized from a
    trusted dataset, and 'too short to be a real page' is a property of
    scraped pages."""
    title = (f"{d['member']} ({d['chamber']}) — "
             f"{d['direction']} {d['ticker']}, {d['amount']}")
    content = (
        f"Congressional stock disclosure.\n"
        f"Member: {d['member']} ({d['chamber']})\n"
        f"Ticker: {d['ticker']}\n"
        f"Transaction: {d['type']} ({d['direction']})\n"
        f"Amount band: {d['amount']}\n"
        f"Transaction date: {d['transaction_date'] or 'unknown'}\n"
        f"Disclosure filed: {d['disclosure_date'] or 'unknown'}\n"
        + (f"Filing: {d['ptr_link']}\n" if d["ptr_link"] else "")
    )
    return {
        "url": d["url"],
        "title": title,
        "author": None,
        "site": "congress",
        "published": d["disclosure_date"] or None,
        "word_count": len(content.split()),
        "content": content,
    }


def _book_symbols(structure) -> set[str]:
    """Ticker universe of a book's builder-format structure — every
    instrument id across every node's instrument list, shape-checked."""
    symbols: set[str] = set()
    if not isinstance(structure, dict):
        return symbols
    instruments = structure.get("instruments")
    if not isinstance(instruments, dict):
        return symbols
    for per_node in instruments.values():
        if not isinstance(per_node, list):
            continue
        for item in per_node:
            if isinstance(item, dict):
                symbol = str(item.get("id") or "").strip().upper()
                if symbol:
                    symbols.add(symbol)
    return symbols


async def _linked_rooms(pool):
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, name, linked_book_id
               FROM rooms WHERE linked_book_id IS NOT NULL"""
        )


async def _fetch_all_disclosures(detail: dict) -> list[dict]:
    """Both chambers, each failing independently — one dead mirror must not
    silence the other."""
    disclosures: list[dict] = []
    for chamber, url in (("Senate", SENATE_DATASET_URL),
                         ("House", HOUSE_DATASET_URL)):
        try:
            body = await asyncio.to_thread(_fetch_dataset_bytes, url)
            rows = json.loads(body)
        except Exception as e:
            logger.warning("congress dataset fetch failed (%s): %s", chamber, e)
            detail[f"fetch_{chamber.lower()}"] = f"failed: {type(e).__name__}"
            continue
        normalized = normalize_disclosures(rows, chamber)
        detail[f"fetch_{chamber.lower()}"] = f"{len(normalized)} rows"
        disclosures.extend(normalized)
    return disclosures


async def congress_watch(ctx: SchedulerContext) -> dict:
    """One pass: pull disclosures, file the fresh ones where they trade."""
    detail: dict = {}
    if not _enabled():
        return {"skipped": "disabled"}

    disclosures = await _fetch_all_disclosures(detail)
    if not disclosures:
        return detail

    # Newest filings first; the tail of history never reaches a room.
    disclosures.sort(key=lambda d: d["_filed_at"], reverse=True)
    recent = disclosures[:SCAN_CAP]

    rooms = await _linked_rooms(ctx.pool)
    async with ctx.pool.acquire() as conn:
        for room in rooms:
            room_key = str(room["id"])
            try:
                try:
                    structure = await td.service_get(
                        f"/api/bridge/structure/{room['linked_book_id']}",
                    )
                except td.TradingDeskError as e:
                    logger.warning(
                        "congress watch structure fetch failed for room %s: %s",
                        room_key, e)
                    detail[room_key] = f"structure_unavailable: {e}"
                    continue
                symbols = _book_symbols(structure)
                if not symbols:
                    detail[room_key] = "no_instruments"
                    continue

                seen = await seen_urls(conn, room["id"])
                filed = []
                for d in recent:
                    if len(filed) >= PER_ROOM_CAP:
                        break
                    if d["ticker"] not in symbols or d["url"] in seen:
                        continue
                    row = await save_reading(
                        conn, room_id=room["id"],
                        article=_disclosure_article(d),
                        summary=(f"{d['member']} disclosed a {d['direction']} "
                                 f"of {d['ticker']} ({d['amount']}), "
                                 f"filed {d['disclosure_date'] or 'undated'}."),
                        key_claims=[],
                        source="congress",
                    )
                    filed.append({"url": d["url"], "ticker": d["ticker"],
                                  "title": row.get("title")})
                detail[room_key] = {"filed": filed}
            except Exception as e:
                # A broken room must not sink the watch for the others.
                logger.exception("congress watch failed for room %s", room_key)
                detail[room_key] = f"error: {type(e).__name__}"
    return detail


def register_congress_watch_jobs(scheduler) -> None:
    # enabled_env would default ON when unset (Job.enabled's contract), so
    # the dark default lives in _enabled(); the env var still hard-stops the
    # tick when explicitly "0". Both gates read the same variable.
    scheduler.register(Job(
        "congress_watch", 3600, congress_watch,
        enabled_env=ENABLED_ENV,
    ))
