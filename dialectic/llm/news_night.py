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
  - enabled_env NEWS_DIGEST_ENABLED (kill switch, default off — this job
    spends LLM money on a wall-clock timer)
  - NEWS_DIGEST_PER_ROOM_CAP articles per room per run
  - NEWS_DIGEST_DAILY_LLM_CAP distill calls per UTC-day, counted by
    reading_items rows saved with source='night_shift' (mirrors
    night_shift._briefs_posted_today: each saved reading is exactly one
    background-model call, so the row count IS the LLM budget)
  - per-room/per-article failures (tradingDesk down, defuddle down, a bad
    parse) skip that room/article and are recorded in the job's
    detail dict — the job itself never raises

CONNECTIONS: the job body acquires its own connections from ctx.pool and
never touches the scheduler's ledger connection (the scheduler caution —
a long job holding the ledger conn stalls every other tick).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from scheduler import Job, SchedulerContext
from llm import defuddle_client as dc
from llm import tradingdesk_client as td
from llm.reading import is_thin, save_reading, seen_urls

logger = logging.getLogger(__name__)

NEWS_DIGEST_PER_ROOM_CAP = 3
NEWS_DIGEST_DAILY_LLM_CAP = 20
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
    return {
        "summary": str(parsed["summary"]),
        "key_claims": [str(c) for c in claims if c][:KEY_CLAIMS_CAP],
        "relevance": str(parsed.get("relevance") or ""),
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
                "\"key_claims\": [\"...\"], \"relevance\": \"...\"}. "
                f"Summary under {SUMMARY_CAP} characters; at most "
                f"{KEY_CLAIMS_CAP} key claims; relevance is one line on how "
                "the article bears on the thesis."
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
                        timeout=30.0,
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
                    row = await save_reading(
                        conn, room_id=room["id"], article=article,
                        summary=summary[:SUMMARY_CAP],
                        key_claims=distill["key_claims"],
                        source="night_shift",
                    )
                    saved.append({"url": url, "title": row.get("title")})
                detail[room_key] = {"saved": saved, "skipped": skipped}
            except Exception as e:
                # A broken room must not sink the digest for the others.
                logger.exception("news digest failed for room %s", room_key)
                detail[room_key] = f"error: {type(e).__name__}"
    return detail


def register_news_jobs(scheduler) -> None:
    scheduler.register(Job(
        "thesis_news_digest", 86400, thesis_news_digest,
        enabled_env="NEWS_DIGEST_ENABLED",
        daily_at="05:30", daily_tz="America/Chicago",
    ))
