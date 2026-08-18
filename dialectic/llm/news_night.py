# llm/news_night.py — the night shift reads the news against each room's thesis

"""
ARCHITECTURE: One daily scheduler job — thesis_news_digest at 05:30
America/Chicago, ninety minutes before the morning brief so the brief's
"Read overnight" section (night_shift._render_brief) has something to show.
It iterates rooms with a linked trading book (trading_watch._linked_rooms
pattern), pulls the book's GDELT headlines from tradingDesk, defuddles the
newest few the room hasn't filed yet, distills each against the room's live
thesis snapshot with one background-model call, and files the result in the reading
library (llm/reading.py, source='night_shift').

WHY: a thesis that never meets the news is a diary, not a position. The room
should wake up to find the reading already done — and because it lands in
reading_items, recall and the 07:00 brief pick it up with zero new plumbing.

GUARDRAILS:
  - enabled_env NEWS_DIGEST_ENABLED — default ON (unset means on). The kill
    switch exists because this job spends LLM money on a wall-clock timer;
    set it to 0 to stop it.
  - NEWS_DIGEST_PER_ROOM_CAP articles per room per run
  - NEWS_DIGEST_DAILY_LLM_CAP distill calls per UTC-day, counted by
    reading_items rows saved with source='night_shift' (mirrors
    night_shift._briefs_posted_today: each saved reading is exactly one
    background-model call, so the row count IS the LLM budget)
  - per-room/per-article failures (tradingDesk down, defuddle down, a bad
    parse) skip that room/article and are recorded in the job's
    detail dict — the job itself never raises

BIAS CONTROLS (Phase 7): each distill also takes a STANCE toward the thesis
(supports/contradicts/neutral, invalid degrades to neutral). A contradicting
item is filed with its summary prefixed COUNTER so the brief and recall
cannot render dissent as just another headline; when the night carried no
dissent, assemble_digest says so explicitly (NO_DISSENT_LINE) instead of
promoting a weak counter-pick — absence of opposition is reported, never
manufactured. And one EXPLORATION pull per run (NEWS_EXPLORATION_ENABLED,
default on) reads a broad, thesis-independent query — a deterministic
day-of-year rotation over EXPLORATION_QUERIES — so the room's diet is not
purely the thing it already believes.

CONNECTIONS: the job body acquires its own connections from ctx.pool and
never touches the scheduler's ledger connection (the scheduler caution —
a long job holding the ledger conn stalls every other tick).
"""

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from scheduler import Job, SchedulerContext
from llm import defuddle_client as dc
from llm import tradingdesk_client as td
from llm.reading import is_thin, save_reading, seen_urls
from llm.wire import WIRE_STANCES

logger = logging.getLogger(__name__)

NEWS_DIGEST_PER_ROOM_CAP = 3
NEWS_DIGEST_DAILY_LLM_CAP = 20
COUNTER_LABEL = "COUNTER — "
NO_DISSENT_LINE = ("no credible contradicting coverage cleared the "
                   "threshold this run")
EXPLORATION_LABEL = "EXPLORATION — "
# Broad beats deliberately OUTSIDE any one book's frame — macro,
# cross-asset, geopolitics beyond the current theses. Rotation is
# day-of-year modulo len (exploration_query), so the pick is deterministic
# and every beat comes around.
EXPLORATION_QUERIES = (
    "global macro economy",
    "central bank policy shift",
    "commodity markets shock",
    "emerging markets crisis",
    "sovereign debt stress",
    "global supply chain disruption",
)
# The thesis snapshot goes into the prompt truncated: a trading_config JSON
# can carry whole orderbooks; the model needs the posture, not the ticks.
THESIS_CONTEXT_CAP = 4000
ARTICLE_CONTEXT_CAP = 6000  # mirrors tools.ARTICLE_CONTENT_CAP
SUMMARY_CAP = 500
KEY_CLAIMS_CAP = 5
BACKGROUND_MODEL = "claude-sonnet-5"


async def _linked_rooms(pool):
    """Rooms wired to a trading book (mirrors trading_watch._linked_rooms).

    trading_config is cast to text so the thesis context is a string
    regardless of the pool's JSONB codec.
    """
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, name, linked_book_id, trading_config::text AS trading_config
               FROM rooms WHERE linked_book_id IS NOT NULL"""
        )


async def _readings_saved_today(conn) -> int:
    """Night-shift readings filed so far today (UTC) — the LLM budget gauge.

    WHY reading_items rather than the messages-metadata count night_shift
    uses: this job posts no messages; its artifact (and its LLM spend) is
    the reading row, so that is what the cap must count.
    """
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM reading_items
           WHERE source = 'night_shift' AND created_at >= $1""",
        start_of_day,
    )
    return count or 0


def _parse_distill(text: str) -> Optional[dict]:
    """Tolerant JSON parse of the distillation (thesis_drafter pattern)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    import json

    try:
        parsed = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except ValueError:
            return None
    if not isinstance(parsed, dict) or not parsed.get("summary"):
        return None
    claims = parsed.get("key_claims") or []
    # Stance is advisory, never disqualifying: a missing or invented value
    # degrades to neutral rather than failing an otherwise-good distill.
    stance = parsed.get("stance")
    stance = stance.strip().lower() if isinstance(stance, str) else ""
    if stance not in WIRE_STANCES:
        stance = "neutral"
    return {
        "summary": str(parsed["summary"]),
        "key_claims": [str(c) for c in claims if c][:KEY_CLAIMS_CAP],
        "relevance": str(parsed.get("relevance") or ""),
        "stance": stance,
    }


async def _distill(article: dict, thesis_context: str) -> Optional[dict]:
    """One background-model call: what does this article say, and why does the thesis care?

    Provider import stays lazy (briefing.py pattern) so importing this module
    never touches provider config; a missing API key or any provider failure
    degrades to None — the caller skips the article.
    """
    from llm.providers import get_provider, ProviderName, LLMRequest

    provider = get_provider(ProviderName.ANTHROPIC)
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                "Summarize this article for a room holding the thesis below.\n\n"
                f"THESIS STATE (truncated):\n{thesis_context or '(no thesis snapshot)'}\n\n"
                f"ARTICLE — {article.get('title') or 'untitled'}"
                f" ({article.get('site') or 'unknown site'}):\n"
                f"{str(article.get('content') or '')[:ARTICLE_CONTEXT_CAP]}\n\n"
                "Respond with ONLY JSON: {\"summary\": \"...\", "
                "\"key_claims\": [\"...\"], \"relevance\": \"...\", "
                "\"stance\": \"supports|contradicts|neutral\"}. "
                f"Summary under {SUMMARY_CAP} characters; at most "
                f"{KEY_CLAIMS_CAP} key claims; relevance is one line on how "
                "the article bears on the thesis; stance is whether the "
                "article's facts support, contradict, or sit neutral to the "
                "thesis's central claim."
            ),
        }],
        system="You distill news articles against a trading thesis. Be terse, factual, and output only the JSON object asked for.",
        model=BACKGROUND_MODEL,
        max_tokens=512,
        temperature=0.2,
    )
    try:
        response = await provider.complete(request)
    except Exception as e:
        logger.info("news distill LLM call failed: %s", e)
        return None
    return _parse_distill(response.content or "")


def assemble_digest(items: list[dict]) -> list[str]:
    """The digest's dissent contract (Phase 7 bias controls).

    One line per filed item, filing order kept. Any item whose stance is
    'contradicts' is labeled COUNTER — when the night's coverage carried
    dissent, the digest MUST show it, not average it away. When none did,
    the digest states NO_DISSENT_LINE rather than promoting a low-quality
    counter-pick: balance is reported, never manufactured.
    """
    lines: list[str] = []
    dissent = False
    for item in items:
        title = str(item.get("title") or item.get("url") or "untitled")
        if item.get("stance") == "contradicts":
            dissent = True
            lines.append(f"{COUNTER_LABEL}{title}")
        else:
            lines.append(title)
    if not dissent:
        lines.append(NO_DISSENT_LINE)
    return lines


def exploration_enabled() -> bool:
    """NEWS_EXPLORATION_ENABLED, default ON — read at run time, not import
    time, so operators and tests flip it without a reload dance."""
    raw = os.environ.get("NEWS_EXPLORATION_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes")


def exploration_query(now: Optional[datetime] = None) -> str:
    """Deterministic rotation: day-of-year modulo the query list. No
    random — a rerun on the same day explores the same beat, and every
    beat comes around on the calendar."""
    now = now or datetime.now(timezone.utc)
    return EXPLORATION_QUERIES[now.timetuple().tm_yday % len(EXPLORATION_QUERIES)]


async def _explore(conn, room, filed_this_run: set) -> tuple:
    """The exploration budget: ONE broad, thesis-independent article per
    digest run — the fix for thematic self-selection ("look up nothing but
    oil and gold and you get oil and gold reflected back").

    The pull rides the host room's bridge route with a query override, so
    no new endpoint; the distill sees an EMPTY thesis context by
    construction, so the summary cannot be bent toward the book; the same
    defuddle + thin gates apply. Returns (detail entry, llm_calls) —
    llm_calls separately so the caller charges the daily budget even when
    the distill parse fails (the money is spent either way).
    """
    query = exploration_query()
    try:
        news = await td.service_get(
            f"/api/bridge/news/{room['linked_book_id']}",
            params={"query": query},
            timeout=td.NEWS_TIMEOUT_S,
        )
    except td.TradingDeskError as e:
        logger.warning("exploration news fetch failed: %s", e)
        return f"news_unavailable: {e}", 0
    articles = news.get("articles") if isinstance(news, dict) else None
    if not articles:
        return "no_articles", 0

    seen = await seen_urls(conn, room["id"])
    fresh = [a for a in articles
             if a.get("url") and a["url"] not in seen
             and a["url"] not in filed_this_run]
    # Exactly one article; the scan bound reuses the per-room cap so an
    # unreadable broad feed cannot balloon the run.
    for headline in fresh[:NEWS_DIGEST_PER_ROOM_CAP]:
        url = headline["url"]
        try:
            article = await dc.extract_article(url)
        except dc.DefuddleError as e:
            logger.info("defuddle failed for %s: %s", url, e)
            continue
        if is_thin(article):
            continue
        distill = await _distill(article, "")
        if distill is None:
            return {"query": query, "url": url,
                    "reason": "distill_failed"}, 1
        summary = f"{EXPLORATION_LABEL}{distill['summary']}"
        row = await save_reading(
            conn, room_id=room["id"], article=article,
            summary=summary[:SUMMARY_CAP],
            key_claims=distill["key_claims"],
            source="night_shift",
        )
        title = str(row.get("title") or url)
        return {"query": query, "url": url, "title": title,
                "line": f"{EXPLORATION_LABEL}{title}"}, 1
    return {"query": query, "reason": "no_readable_article"}, 0


async def thesis_news_digest(ctx: SchedulerContext) -> dict:
    """File the overnight news into each linked room's reading library."""
    detail: dict = {}
    rooms = await _linked_rooms(ctx.pool)

    async with ctx.pool.acquire() as conn:
        spent = await _readings_saved_today(conn)
        for room in rooms:
            room_key = str(room["id"])
            try:
                if spent >= NEWS_DIGEST_DAILY_LLM_CAP:
                    detail[room_key] = "cap_reached"
                    continue

                try:
                    news = await td.service_get(
                        f"/api/bridge/news/{room['linked_book_id']}",
                        # GDELT queries routinely take longer than the 10s
                        # client default; a slow feed must not read as down.
                        # The number lives on td.NEWS_TIMEOUT_S so all five
                        # callers of this route share one budget.
                        timeout=td.NEWS_TIMEOUT_S,
                    )
                except td.TradingDeskError as e:
                    logger.warning("news fetch failed for room %s: %s",
                                   room_key, e)
                    detail[room_key] = f"news_unavailable: {e}"
                    continue

                articles = news.get("articles") if isinstance(news, dict) else None
                if not articles:
                    # Note-only payloads ("no feed configured") land here.
                    detail[room_key] = "no_articles"
                    continue

                seen = await seen_urls(conn, room["id"])
                fresh = [a for a in articles
                         if a.get("url") and a["url"] not in seen]
                if not fresh:
                    detail[room_key] = "all_seen"
                    continue

                thesis_context = str(room["trading_config"] or "")[:THESIS_CONTEXT_CAP]
                saved, skipped = [], []
                # Feed order is the freshness ranking; the cap takes the top.
                for headline in fresh[:NEWS_DIGEST_PER_ROOM_CAP]:
                    url = headline["url"]
                    if spent >= NEWS_DIGEST_DAILY_LLM_CAP:
                        skipped.append({"url": url, "reason": "cap_reached"})
                        continue
                    try:
                        article = await dc.extract_article(url)
                    except dc.DefuddleError as e:
                        logger.info("defuddle failed for %s: %s", url, e)
                        skipped.append({"url": url, "reason": "extract_failed"})
                        continue

                    if is_thin(article):
                        skipped.append({"url": url, "reason": "thin_content"})
                        continue

                    distill = await _distill(article, thesis_context)
                    # The money is spent even when the parse fails — count it.
                    spent += 1
                    if distill is None:
                        skipped.append({"url": url, "reason": "distill_failed"})
                        continue

                    summary = distill["summary"]
                    if distill["relevance"]:
                        # The relevance note rides inside the summary (capped)
                        # so the brief and recall see it without a schema change.
                        summary = f"{summary} Relevance: {distill['relevance']}"
                    stance = distill.get("stance") or "neutral"
                    if stance == "contradicts":
                        # The label is a PREFIX so neither the cap below nor
                        # the brief's first-sentence render can eat it —
                        # dissent must survive every downstream truncation.
                        summary = f"{COUNTER_LABEL}{summary}"
                    row = await save_reading(
                        conn, room_id=room["id"], article=article,
                        summary=summary[:SUMMARY_CAP],
                        key_claims=distill["key_claims"],
                        source="night_shift",
                    )
                    saved.append({"url": url, "title": row.get("title"),
                                  "stance": stance})
                detail[room_key] = {"saved": saved, "skipped": skipped,
                                    "digest": assemble_digest(saved)}
            except Exception as e:
                # A broken room must not sink the digest for the others.
                logger.exception("news digest failed for room %s", room_key)
                detail[room_key] = f"error: {type(e).__name__}"

        # The exploration pull runs LAST so a broad-beat failure can never
        # starve the thesis lane, and only when the budget has room left.
        if not exploration_enabled():
            detail["exploration"] = "disabled"
        elif not rooms:
            detail["exploration"] = "no_rooms"
        elif spent >= NEWS_DIGEST_DAILY_LLM_CAP:
            detail["exploration"] = "cap_reached"
        else:
            host = rooms[0]
            host_entry = detail.get(str(host["id"]))
            host_filed = ({s["url"] for s in host_entry["saved"]}
                          if isinstance(host_entry, dict) else set())
            try:
                entry, llm_calls = await _explore(conn, host, host_filed)
            except Exception as e:
                logger.exception("exploration pull failed")
                entry, llm_calls = f"error: {type(e).__name__}", 0
            spent += llm_calls
            detail["exploration"] = entry
            if (isinstance(entry, dict) and entry.get("line")
                    and isinstance(host_entry, dict)):
                host_entry["digest"].append(entry["line"])
    return detail


def register_news_jobs(scheduler) -> None:
    scheduler.register(Job(
        "thesis_news_digest", 86400, thesis_news_digest,
        enabled_env="NEWS_DIGEST_ENABLED",
        daily_at="05:30", daily_tz="America/Chicago",
    ))
