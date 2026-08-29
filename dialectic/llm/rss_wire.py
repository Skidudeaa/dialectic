# llm/rss_wire.py — the RSS wire: watchlist feeds join the interruption budget

"""
ARCHITECTURE: One 15-minute scheduler job — rss_wire. It is the FIRST reader
of rooms.watchlist (migration 015: JSONB, NULL = default watch). For every
room wired to a trading book whose watchlist carries {type:"rss", value:
<feed url>} entries, it fetches each feed (stdlib urllib in a worker thread,
15s budget), hand-parses RSS 2.0/Atom with xml.etree.ElementTree (the
treasury.py house precedent — defensive, never a feedparser dependency),
drops URLs the room has already filed, and runs the survivors through the
SAME pipeline the GDELT wire runs: defuddle extract → thin gate → one
relevance score against the room's live thesis (wire._score, threshold 0.7)
→ save_reading(source='wire') → a capped facilitator interjection.

WATCHLIST CONTRACT (015's spec'd shape is {type, value}): this reader
consumes ONLY {type:"rss", value, tag?} entries. The spec'd "gdelt_book" and
"url" types are deliberately IGNORED here — gdelt_book is the default watch
the GDELT wire already covers, and "url" (single-page polling) has no
consumer yet; skipping unknown types is what lets those land later without
touching this job. An optional tag ("social") selects a per-source thin
floor (reading.SOURCE_THIN_FLOORS) so a Truth Social mirror's 30-word post
is not discarded as a bot wall — the global 80-word floor never moves.

WHY the interjection budget is SHARED, not new: the 2026-08-15 volume
lesson — every separately-budgeted speaker compounds into noise. This job
posts through wire._interject, which stamps reason='wire_interjection' on
the llm_decisions ledger, and counts the day's spend through
wire._interjections_today against wire.WIRE_DAILY_CAP. The per-room daily
cap therefore stays ONE number across both wires: an RSS interjection
spends a GDELT slot and vice versa. There is no new budget anywhere in
this module — that is load-bearing and pinned by tests.

GUARDRAILS (the GDELT wire's, reused not mirrored):
  - RSS_WIRE_ENABLED kill switch (unset means on, the Job.enabled default)
  - quiet hours + rooms.auto_interjection_enabled, via the same checks
  - failed feed fetches/parses and failed/thin article extracts cool that
    exact URL for six hours (own cooldown map — a dead feed must not
    consume every run, and wire's map stays wire's)
  - at most wire.WIRE_FEED_SCAN_CAP fresh items scored per room per run,
    wire.WIRE_PER_ROOM_CAP readable articles, feed order = freshness order
  - wire.cap_by_domain on the fresh list (domain from each link's netloc —
    RSS items carry no domain field), so one prolific feed cannot fill the
    scan window when a room watches several; drops are logged with counts
  - per-room/per-item failures skip and record; the job never raises

TRADEOFF: urllib.urlopen is blocking, so the fetch runs in
asyncio.to_thread — the scheduler shares the API server's event loop, and
a 15-second synchronous read would stall every request in flight.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.request import Request, urlopen

from scheduler import Job, SchedulerContext
from llm import defuddle_client as dc
from llm.reading import is_thin, save_reading, seen_urls
from llm.silence_sweep import in_quiet_hours
from llm.wire import (
    THESIS_CONTEXT_CAP,
    WIRE_DAILY_CAP,
    WIRE_FEED_SCAN_CAP,
    WIRE_PER_ROOM_CAP,
    WIRE_THRESHOLD,
    _domain_cap,
    _interject,
    _interjections_today,
    _score,
    _stance_summary,
    cap_by_domain,
)

logger = logging.getLogger(__name__)

FEED_TIMEOUT_S = 15
# A feed is a listing, not an archive — cap the read so a misconfigured
# entry pointing at a huge file cannot balloon the worker thread.
FEED_MAX_BYTES = 2 * 1024 * 1024
FEED_FETCH_COOLDOWN_SECONDS = 6 * 60 * 60

_ATOM = "{http://www.w3.org/2005/Atom}"

# Own map, wire's discipline: failed feeds AND failed article URLs cool here.
_fetch_cooldowns: dict[str, float] = {}


def _in_fetch_cooldown(url: str) -> bool:
    """Whether an exact URL still has time left on its failed-fetch cooldown."""
    expires_at = _fetch_cooldowns.get(url)
    if expires_at is None:
        return False
    if expires_at <= time.monotonic():
        del _fetch_cooldowns[url]
        return False
    return True


def _cool_fetch(url: str) -> None:
    """Suppress an exact failed URL for the bounded retry interval."""
    _fetch_cooldowns[url] = time.monotonic() + FEED_FETCH_COOLDOWN_SECONDS


def _prune_fetch_cooldowns() -> None:
    """Drop expired URLs even when rotating feeds never present them again."""
    now = time.monotonic()
    expired = [url for url, deadline in _fetch_cooldowns.items()
               if deadline <= now]
    for url in expired:
        del _fetch_cooldowns[url]


# =========================================================================
# Feed fetch + parse (stdlib only — treasury.py precedent)
# =========================================================================

def _fetch_feed_bytes(url: str) -> bytes:
    """Blocking fetch — callers run this via asyncio.to_thread."""
    req = Request(url, headers={"User-Agent": "dialectic-rss-wire/1.0"})
    with urlopen(req, timeout=FEED_TIMEOUT_S) as resp:
        return resp.read(FEED_MAX_BYTES)


def _text(element) -> Optional[str]:
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _parse_feed(body: bytes) -> list[dict]:
    """RSS 2.0 + Atom entries as {title, url, published, guid}, feed order.

    Defensive by construction: unparseable XML is an empty list (the caller
    treats empty as a failed feed and cools it); an item without a usable
    link is dropped, never guessed at. A guid/id that IS a URL stands in
    for a missing link — some minimal feeds ship only the guid.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    items: list[dict] = []

    # RSS 2.0: <rss><channel><item> — iter() tolerates nonstandard nesting.
    for item in root.iter("item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        guid = _text(item.find("guid"))
        url = link or (guid if guid and guid.startswith("http") else None)
        if not url:
            continue
        items.append({
            "title": title or "untitled",
            "url": url,
            "published": _text(item.find("pubDate")),
            "guid": guid,
        })

    # Atom: <feed><entry> with the namespace on every element. The alternate
    # link is the article; a bare <link> with no rel means alternate per spec.
    for entry in root.iter(f"{_ATOM}entry"):
        href = None
        for link_el in entry.findall(f"{_ATOM}link"):
            if link_el.get("rel", "alternate") == "alternate":
                href = (link_el.get("href") or "").strip() or None
                break
        guid = _text(entry.find(f"{_ATOM}id"))
        url = href or (guid if guid and guid.startswith("http") else None)
        if not url:
            continue
        items.append({
            "title": _text(entry.find(f"{_ATOM}title")) or "untitled",
            "url": url,
            "published": (_text(entry.find(f"{_ATOM}published"))
                          or _text(entry.find(f"{_ATOM}updated"))),
            "guid": guid,
        })

    return items


def _rss_entries(watchlist) -> list[dict]:
    """The {type:"rss"} entries of a room's watchlist, shape-checked.

    Returns [{url, tag}] in watchlist order. Everything else — NULL, a
    non-list, non-dict entries, other types, non-http values — is skipped
    silently: the column is human-edited JSONB and this job must never be
    the thing a typo breaks.
    """
    if not isinstance(watchlist, list):
        return []
    entries = []
    for entry in watchlist:
        if not isinstance(entry, dict) or entry.get("type") != "rss":
            continue
        value = str(entry.get("value") or "").strip()
        if not value.startswith(("http://", "https://")):
            continue
        tag = entry.get("tag")
        entries.append({"url": value, "tag": tag if isinstance(tag, str) else None})
    return entries


async def _watchlist_rooms(pool):
    """Linked rooms that HAVE a watchlist — the wire._linked_rooms query
    plus the column this job exists to read. Rooms with a NULL watchlist
    are the GDELT wire's default watch and cost this job nothing."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, name, linked_book_id, auto_interjection_enabled,
                      trading_config::text AS trading_config, watchlist
               FROM rooms
               WHERE linked_book_id IS NOT NULL AND watchlist IS NOT NULL"""
        )


# =========================================================================
# The job
# =========================================================================

async def rss_wire_watch(ctx: SchedulerContext) -> dict:
    """One pass over every watchlisted room's RSS feeds."""
    _prune_fetch_cooldowns()
    if in_quiet_hours():
        return {"skipped": "quiet_hours"}

    detail: dict = {}
    rooms = await _watchlist_rooms(ctx.pool)

    async with ctx.pool.acquire() as conn:
        for room in rooms:
            room_key = str(room["id"])
            try:
                entries = _rss_entries(room["watchlist"])
                if not entries:
                    detail[room_key] = "no_rss_entries"
                    continue

                if not room["auto_interjection_enabled"]:
                    detail[room_key] = "toggle_off"
                    continue

                # wire's counter, wire's reason, wire's cap — ONE budget.
                if await _interjections_today(conn, room["id"]) >= WIRE_DAILY_CAP:
                    detail[room_key] = "cap_reached"
                    continue

                # Fetch + parse each feed; tag rides beside every item so the
                # thin gate downstream knows which floor the source earned.
                candidates: list[dict] = []
                failed_feeds: list[dict] = []
                for entry in entries:
                    feed_url = entry["url"]
                    if _in_fetch_cooldown(feed_url):
                        failed_feeds.append(
                            {"feed": feed_url, "reason": "fetch_cooldown"})
                        continue
                    try:
                        body = await asyncio.to_thread(
                            _fetch_feed_bytes, feed_url)
                        parsed = _parse_feed(body)
                    except Exception as e:
                        logger.info("rss feed fetch failed for %s: %s",
                                    feed_url, e)
                        parsed = []
                    if not parsed:
                        _cool_fetch(feed_url)
                        failed_feeds.append(
                            {"feed": feed_url, "reason": "fetch_or_parse_failed"})
                        continue
                    for item in parsed:
                        candidates.append({**item, "tag": entry["tag"]})

                if not candidates:
                    detail[room_key] = {"filed": [], "interjected": [],
                                        "skipped": failed_feeds}
                    continue

                seen = await seen_urls(conn, room["id"])
                seen_this_run: set[str] = set()
                fresh = []
                for item in candidates:
                    if item["url"] in seen or item["url"] in seen_this_run:
                        continue
                    seen_this_run.add(item["url"])
                    fresh.append(item)
                if not fresh:
                    detail[room_key] = "all_seen"
                    continue

                # wire's cap, wire's helper — imported, never copied. Domain
                # falls back to each link's netloc since RSS items carry no
                # domain field of their own.
                fresh, domain_drops = cap_by_domain(fresh, _domain_cap())
                if domain_drops:
                    logger.info(
                        "rss wire domain cap dropped items for room %s: %s",
                        room_key, domain_drops,
                    )

                thesis_context = str(room["trading_config"] or "")[:THESIS_CONTEXT_CAP]
                filed, interjected = [], []
                skipped = list(failed_feeds)
                readable_count = 0
                # Feed order is the freshness ranking (wire's rule). Fetch
                # failures do not consume the readable-article scoring slots.
                for item in fresh[:WIRE_FEED_SCAN_CAP]:
                    if readable_count >= WIRE_PER_ROOM_CAP:
                        break
                    url = item["url"]
                    if _in_fetch_cooldown(url):
                        skipped.append({"url": url, "reason": "fetch_cooldown"})
                        continue
                    try:
                        article = await dc.extract_article(url)
                    except dc.DefuddleError as e:
                        logger.info("defuddle failed for %s: %s", url, e)
                        _cool_fetch(url)
                        skipped.append({"url": url, "reason": "extract_failed"})
                        continue

                    # Before the scoring call, not after (wire's rule) — and
                    # with the SOURCE's floor: a social feed's short post is
                    # signal, everyone else answers to the global 80.
                    if is_thin(article, source_tag=item["tag"]):
                        _cool_fetch(url)
                        skipped.append({"url": url, "reason": "thin_content"})
                        continue

                    readable_count += 1
                    verdict = await _score(article, thesis_context)
                    if verdict is None or verdict["score"] < WIRE_THRESHOLD:
                        skipped.append({"url": url, "reason": "below_threshold"})
                        continue

                    row = await save_reading(
                        conn, room_id=room["id"], article=article,
                        summary=_stance_summary(
                            verdict["why"] or article.get("title")
                            or "wire hit",
                            verdict.get("stance"),
                        ),
                        key_claims=[],
                        source="wire",
                    )
                    filed.append({"url": url, "title": row.get("title"),
                                  "score": verdict["score"],
                                  "stance": verdict.get("stance", "neutral")})

                    # wire._interject: force_response writes the ledger row
                    # (reason='wire_interjection') the shared cap counts.
                    try:
                        response = await _interject(
                            ctx, conn, room["id"], article, verdict,
                        )
                        if response is not None:
                            interjected.append(str(response.id))
                        else:
                            skipped.append({"url": url,
                                            "reason": "interjection_failed"})
                    except Exception:
                        logger.exception(
                            "rss wire interjection failed for room %s", room_key)
                        skipped.append({"url": url,
                                        "reason": "interjection_failed"})
                detail[room_key] = {
                    "filed": filed,
                    "interjected": interjected,
                    "skipped": skipped,
                }
            except Exception as e:
                # A broken room must not sink the wire for the others.
                logger.exception("rss wire failed for room %s", room_key)
                detail[room_key] = f"error: {type(e).__name__}"
    return detail


def register_rss_wire_jobs(scheduler) -> None:
    scheduler.register(Job(
        "rss_wire", 900, rss_wire_watch,
        enabled_env="RSS_WIRE_ENABLED",
        # Dark until set: no room in production lists a feed to watch, and
        # 671 empty passes a week is not a feature (audit 2026-08-29).
        enabled_default=False,
    ))
