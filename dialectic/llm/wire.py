# llm/wire.py — the wire: breaking news that interrupts the room

"""
ARCHITECTURE: One 15-minute scheduler job — wire_watch. It walks every room
wired to a trading book, pulls the book's GDELT headlines from tradingDesk,
drops URLs the room has already filed (reading_items), defuddles the freshest
few, and scores each against the room's live thesis snapshot with one Haiku
call. Articles at or above WIRE_THRESHOLD are filed in the reading library
(llm/reading.py, source='wire') AND posted into the room as a real
facilitator turn — force_response with the article in context (Path B, the
silence_sweep pattern: persist via the orchestrator, broadcast via
_broadcast_follow_up).

WHY: the night shift (llm/news_night.py) reads the news so the room wakes up
briefed; the wire exists for the story that cannot wait until morning — a
node-trigger event at 14:00 is stale by 05:30. Same pipeline, opposite
cadence, plus the interjection the digest deliberately never makes.

GUARDRAILS:
  - enabled_env WIRE_ENABLED — default ON (unset means on: Job.enabled reads
    the var with "1" as its default, and .env.example ships it as 1). The
    kill switch exists because this job spends LLM money on a wall-clock timer
    AND speaks uninvited; set it to 0 to stop both.
  - quiet hours 23:00–07:00 America/Chicago (silence_sweep.in_quiet_hours —
    zero interjections at night; the news keeps, the digest will file it)
  - rooms.auto_interjection_enabled = false: the room is not interrupted
    (the same toggle that gates the silence sweep)
  - WIRE_DAILY_CAP interjections per room per UTC day, counted on the
    llm_decisions ledger (reason='wire_interjection') — force_response
    already writes that row, so the cap needs no new plumbing
  - WIRE_PER_ROOM_CAP readable articles per room per run, found within the
    first WIRE_FEED_SCAN_CAP unseen headlines in feed freshness order
  - fetch failures and thin bodies cool that exact URL for six hours so a
    blocked lead story cannot consume every scheduled run
  - a failed relevance parse scores below threshold (silence, never a bad
    interruption); per-room/per-article failures (tradingDesk down, defuddle
    down, a dead interjection) skip that room/article and are recorded in
    the job's detail dict — the job itself never raises

CONNECTIONS: the job body acquires its own connections from ctx.pool and
never touches the scheduler's ledger connection (the scheduler caution —
a long job holding the ledger conn stalls every other tick).
"""

import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from scheduler import Job, SchedulerContext
from models import Message, MessageType, SpeakerType
from llm import defuddle_client as dc
from llm import tradingdesk_client as td
from llm.orchestrator import LLMOrchestrator
from llm.reading import is_thin, save_reading, seen_urls
from llm.silence_sweep import (
    _broadcast_follow_up,
    _load_room_context,
    in_quiet_hours,
)

logger = logging.getLogger(__name__)

INTERJECTION_REASON = "wire_interjection"
WIRE_DAILY_CAP = 4
WIRE_PER_ROOM_CAP = 2
WIRE_FEED_SCAN_CAP = 6
WIRE_FETCH_COOLDOWN_SECONDS = 6 * 60 * 60
WIRE_THRESHOLD = 0.7
# The thesis snapshot goes into the prompt truncated: a trading_config JSON
# can carry whole orderbooks; the model needs the posture, not the ticks.
THESIS_CONTEXT_CAP = 4000
ARTICLE_CONTEXT_CAP = 6000  # mirrors news_night / tools.ARTICLE_CONTENT_CAP
SUMMARY_CAP = 500
BACKGROUND_MODEL = "claude-sonnet-5"

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
    _fetch_cooldowns[url] = time.monotonic() + WIRE_FETCH_COOLDOWN_SECONDS


async def _linked_rooms(pool):
    """Rooms wired to a trading book (news_night._linked_rooms pattern),
    carrying the interjection toggle so the job never speaks where the room
    has asked it not to.
    """
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT id, name, linked_book_id, auto_interjection_enabled,
                      trading_config::text AS trading_config
               FROM rooms WHERE linked_book_id IS NOT NULL"""
        )


async def _interjections_today(conn, room_id) -> int:
    """Wire interjections already posted in this room today (UTC day —
    silence_sweep._followups_today pattern: a day boundary is something a
    human can reason about)."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    count = await conn.fetchval(
        """SELECT COUNT(*) FROM llm_decisions
           WHERE room_id = $1
           AND should_interject
           AND reason = $2
           AND decided_at >= $3""",
        room_id, INTERJECTION_REASON, start_of_day,
    )
    return count or 0


def _parse_score(text: str) -> Optional[dict]:
    """Tolerant JSON parse of the relevance verdict (thesis_drafter
    pattern). Anything unparseable — or a score that is not a number — is
    None, and the caller treats None as below threshold."""
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
    if not isinstance(parsed, dict):
        return None
    try:
        score = float(parsed["score"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"score": max(0.0, min(1.0, score)),
            "why": str(parsed.get("why") or "")}


async def _score(article: dict, thesis_context: str) -> Optional[dict]:
    """One background-model call: does this article bear on the room's live thesis?

    Provider import stays lazy (briefing.py pattern) so importing this module
    never touches provider config; a missing API key or any provider failure
    degrades to None — the caller treats the article as below threshold.
    """
    from llm.providers import get_provider, ProviderName, LLMRequest

    provider = get_provider(ProviderName.ANTHROPIC)
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                "Score how relevant this breaking article is to the trading "
                "thesis below — would a room holding this thesis want to be "
                "interrupted for it?\n\n"
                f"THESIS STATE (truncated):\n{thesis_context or '(no thesis snapshot)'}\n\n"
                f"ARTICLE — {article.get('title') or 'untitled'}"
                f" ({article.get('site') or 'unknown site'}):\n"
                f"{str(article.get('content') or '')[:ARTICLE_CONTEXT_CAP]}\n\n"
                "Respond with ONLY JSON: {\"score\": 0.0, \"why\": \"...\"}. "
                "score is 0..1 (1 = directly moves a thesis trigger); why is "
                "one sentence."
            ),
        }],
        system="You score breaking news against a trading thesis. Be terse, factual, and output only the JSON object asked for.",
        model=BACKGROUND_MODEL,
        max_tokens=256,
        temperature=0.1,
    )
    try:
        response = await provider.complete(request)
    except Exception as e:
        logger.info("wire relevance LLM call failed: %s", e)
        return None
    return _parse_score(response.content or "")


def _wire_context_message(thread_id, sequence, article, verdict) -> Message:
    """The article as the last turn of the conversation window.

    force_response takes no side-channel context — the prompt is built from
    the message list, so the wire frames its material as a trailing SYSTEM
    message (renders as a '[SYSTEM]' user-role turn, never persisted): the
    facilitator sees the article, the score, and why it was woken, then
    speaks to it.
    """
    content = (
        f"WIRE — this just broke (relevance {verdict['score']:.2f} to the "
        f"room's thesis): {article.get('title') or 'untitled'}"
        f" — {article.get('site') or 'unknown site'}"
        f"{', ' + str(article.get('published')) if article.get('published') else ''}\n"
        f"{article.get('url')}\n"
        f"Why it bears on the thesis: {verdict['why'] or 'scored above threshold'}\n\n"
        f"Article excerpt:\n"
        f"{str(article.get('content') or '')[:ARTICLE_CONTEXT_CAP]}\n\n"
        "Speak to it in one short turn — what it means for the thesis — "
        "and cite the source."
    )
    return Message(
        id=uuid4(),
        thread_id=thread_id,
        sequence=sequence,
        created_at=datetime.now(timezone.utc),
        speaker_type=SpeakerType.SYSTEM,
        user_id=None,
        message_type=MessageType.TEXT,
        content=content,
    )


async def _interject(ctx: SchedulerContext, conn, room_id, article, verdict):
    """Post the facilitator turn (Path B): persist via force_response —
    which writes the llm_decisions ledger row the daily cap counts — then
    broadcast, which force_response deliberately does not do."""
    loaded = await _load_room_context(conn, room_id)
    if loaded is None:
        return None
    room, thread, users, messages, memories = loaded

    wire_message = _wire_context_message(
        thread.id,
        (messages[-1].sequence + 1) if messages else 1,
        article, verdict,
    )
    orchestrator = LLMOrchestrator(conn, db_pool=ctx.pool)
    result = await orchestrator.force_response(
        room=room,
        thread=thread,
        users=users,
        messages=[*messages, wire_message],
        memories=memories,
        reason=INTERJECTION_REASON,
    )
    if not (result.triggered and result.response):
        return None
    await _broadcast_follow_up(ctx, room_id, result.response)
    return result.response


async def wire_watch(ctx: SchedulerContext) -> dict:
    """One pass over every linked room's news feed."""
    if in_quiet_hours():
        return {"skipped": "quiet_hours"}

    detail: dict = {}
    rooms = await _linked_rooms(ctx.pool)

    async with ctx.pool.acquire() as conn:
        for room in rooms:
            room_key = str(room["id"])
            try:
                if not room["auto_interjection_enabled"]:
                    detail[room_key] = "toggle_off"
                    continue

                if await _interjections_today(conn, room["id"]) >= WIRE_DAILY_CAP:
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
                    logger.warning("wire news fetch failed for room %s: %s",
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
                filed, interjected, skipped = [], [], []
                readable_count = 0
                # Feed order is the freshness ranking. Fetch failures do not
                # consume either of the two readable-article scoring slots.
                for headline in fresh[:WIRE_FEED_SCAN_CAP]:
                    if readable_count >= WIRE_PER_ROOM_CAP:
                        break
                    url = headline["url"]
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

                    # Before the scoring call, not after: a bot-blocked shell
                    # must not cost a background-model call, and must never reach the room
                    # as an interjection.
                    if is_thin(article):
                        _cool_fetch(url)
                        skipped.append({"url": url, "reason": "thin_content"})
                        continue

                    readable_count += 1
                    verdict = await _score(article, thesis_context)
                    if verdict is None or verdict["score"] < WIRE_THRESHOLD:
                        skipped.append({"url": url, "reason": "below_threshold"})
                        continue

                    # The one-sentence why IS the filed summary — the wire's
                    # artifact is the interruption, not a full distillation.
                    row = await save_reading(
                        conn, room_id=room["id"], article=article,
                        summary=(verdict["why"] or article.get("title")
                                 or "wire hit")[:SUMMARY_CAP],
                        key_claims=[],
                        source="wire",
                    )
                    filed.append({"url": url, "title": row.get("title"),
                                  "score": verdict["score"]})

                    # A dead interjection must not cost the room its second
                    # article — the reading is already filed either way.
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
                            "wire interjection failed for room %s", room_key)
                        skipped.append({"url": url,
                                        "reason": "interjection_failed"})
                detail[room_key] = {
                    "filed": filed,
                    "interjected": interjected,
                    "skipped": skipped,
                }
            except Exception as e:
                # A broken room must not sink the wire for the others.
                logger.exception("wire watch failed for room %s", room_key)
                detail[room_key] = f"error: {type(e).__name__}"
    return detail


def register_wire_jobs(scheduler) -> None:
    scheduler.register(Job(
        "wire_watch", 900, wire_watch,
        enabled_env="WIRE_ENABLED",
    ))
