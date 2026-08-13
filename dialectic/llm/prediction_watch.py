# llm/prediction_watch.py — the deadline watcher that proposes resolutions

"""
ARCHITECTURE: One hourly scheduler job — prediction_deadline_watch. It lists
the predictions logged on tradingDesk (the dialectic service principal's own
tracker), finds the unresolved ones whose deadline is today or tomorrow,
gathers evidence for the book-linked ones (thesis news → defuddled
articles), asks the background model for a verdict, and posts a quiet annotator-lane
message carrying a resolution_proposal card. Nothing is resolved here — a
human tapping Mark correct/incorrect on the card hits
api/prediction_relay.resolve_accept, and THAT tap is the write.

WHY: a prediction nobody revisits is astrology. The desk already tracks
statements, confidences, and deadlines; what was missing is the moment the
deadline arrives and someone is asked "were we right?". The machine does the
homework (evidence + a proposed verdict), the human makes the call.

ROOM MAPPING: tradingDesk's Prediction record carries no room id — only
tags and linked_book_id (trading/web/models.py). Rooms, however, carry
linked_book_id, so a linked prediction's originating room is the room bound
to that book. Unlinked predictions have no room to come home to; v1 skips
them and reports them in the job detail.

GUARDRAILS:
  - enabled_env PREDICTION_WATCH_ENABLED (kill switch, default off — this
    job spends LLM money on a wall-clock timer)
  - PREDICTION_WATCH_RUN_CAP proposals per run; dedup on
    metadata->>'source' = 'prediction_watch' carrying the same prediction id
    means a re-run never re-proposes
  - per-prediction failures (desk down, defuddle down, a bad parse)
    skip that prediction and are recorded in the detail dict — the job
    itself never raises

CONNECTIONS: the job body acquires its own connections from ctx.pool and
never touches the scheduler's ledger connection (the scheduler caution —
a long job holding the ledger conn stalls every other tick).
"""

import json
import logging
import re
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from uuid import uuid4

from scheduler import Job, SchedulerContext
from models import SpeakerType, MessageType, EventType
from transport.websocket import OutboundMessage, MessageTypes
from llm import defuddle_client as dc
from llm import tradingdesk_client as td

logger = logging.getLogger(__name__)

PREDICTION_WATCH_RUN_CAP = 3
EVIDENCE_ARTICLE_CAP = 2
# The article body goes into the verdict prompt truncated — the model needs
# the gist, not the full text.
EVIDENCE_CONTENT_CAP = 4000
# A prediction is due when its deadline is today or tomorrow — a one-day
# runway so the proposal lands before the moment, not after.
DEADLINE_GRACE_DAYS = 1
BACKGROUND_MODEL = "claude-sonnet-5"
VERDICTS = ("correct", "incorrect", "unclear")


def _due_predictions(predictions, today: date) -> tuple[list, list]:
    """Split the desk's list into (due, skipped) — unresolved and inside the
    deadline runway. Malformed records are skipped, never fatal."""
    due, skipped = [], []
    horizon = today + timedelta(days=DEADLINE_GRACE_DAYS)
    for p in predictions:
        if not isinstance(p, dict) or not p.get("id") or not p.get("statement"):
            skipped.append({"id": None, "reason": "malformed"})
            continue
        pid = str(p["id"])
        if p.get("resolution") is not None:
            skipped.append({"id": pid, "reason": "already_resolved"})
            continue
        try:
            # Deadline may arrive as a date or a datetime — the date part
            # is what the runway compares.
            deadline = date.fromisoformat(str(p.get("deadline") or "")[:10])
        except ValueError:
            skipped.append({"id": pid, "reason": "bad_deadline"})
            continue
        if deadline > horizon:
            skipped.append({"id": pid, "reason": "not_due"})
            continue
        due.append(p)
    return due, skipped


async def _already_proposed(conn) -> set:
    """Prediction ids that already carry a proposal card — the dedup gauge
    (mirrors night_shift's metadata-source counting)."""
    rows = await conn.fetch(
        """SELECT m.metadata->'resolution_proposal'->>'prediction_id' AS prediction_id
           FROM messages m
           WHERE m.metadata->>'source' = 'prediction_watch'"""
    )
    return {r["prediction_id"] for r in rows if r["prediction_id"]}


async def _room_for_book(conn, book_id: str):
    """The originating room for a linked prediction: the room bound to the
    same trading book."""
    return await conn.fetchrow(
        "SELECT id, name FROM rooms WHERE linked_book_id = $1 LIMIT 1",
        book_id,
    )


async def _gather_evidence(book_id: str) -> list:
    """Thesis news → defuddled article bodies, top EVIDENCE_ARTICLE_CAP.

    Every failure degrades to less evidence, never to a skipped prediction:
    a deadline verdict with no evidence is still worth asking about.
    """
    try:
        news = await td.service_get(f"/api/bridge/news/{book_id}")
    except td.TradingDeskError as e:
        logger.info("evidence news fetch failed for book %s: %s", book_id, e)
        return []
    articles = news.get("articles") if isinstance(news, dict) else None
    if not articles:
        return []
    evidence = []
    # Feed order is the freshness ranking; the cap takes the top.
    for headline in articles:
        if len(evidence) >= EVIDENCE_ARTICLE_CAP:
            break
        url = headline.get("url")
        if not url:
            continue
        try:
            article = await dc.extract_article(url)
        except dc.DefuddleError as e:
            logger.info("defuddle failed for %s: %s", url, e)
            continue
        evidence.append({
            "url": url,
            "title": article.get("title") or headline.get("title") or url,
            "content": str(article.get("content") or "")[:EVIDENCE_CONTENT_CAP],
        })
    return evidence


def _parse_verdict(text: str) -> Optional[dict]:
    """Tolerant JSON parse of the Haiku verdict (news_night._parse_distill
    pattern)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
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
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        return None
    return {"verdict": verdict, "rationale": str(parsed.get("rationale") or "")}


async def _verdict(prediction: dict, evidence: list) -> Optional[dict]:
    """One background-model call: given the statement and the evidence, did it land?

    Provider import stays lazy (news_night._distill pattern) so importing
    this module never touches provider config; a missing API key, a provider
    failure, or an unparseable answer degrades to None — the caller skips
    the prediction.
    """
    from llm.providers import get_provider, ProviderName, LLMRequest

    if evidence:
        ev_block = "\n\n".join(
            f"EVIDENCE — {ev['title']} ({ev['url']}):\n{ev['content']}"
            for ev in evidence
        )
    else:
        ev_block = "(no evidence could be gathered — judge from the deadline note alone)"
    provider = get_provider(ProviderName.ANTHROPIC)
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                "A logged prediction has reached its deadline. Judge it.\n\n"
                f"STATEMENT: {prediction['statement']}\n"
                f"CONFIDENCE: {prediction.get('confidence')}\n"
                f"DEADLINE: {prediction.get('deadline')}\n\n"
                f"{ev_block}\n\n"
                "Respond with ONLY JSON: {\"verdict\": \"correct\" | "
                "\"incorrect\" | \"unclear\", \"rationale\": \"one sentence\"}. "
                "Use \"unclear\" when the evidence does not settle it."
            ),
        }],
        system="You judge logged predictions against evidence. Be terse, factual, and output only the JSON object asked for.",
        model=BACKGROUND_MODEL,
        max_tokens=256,
        temperature=0.2,
    )
    try:
        response = await provider.complete(request)
    except Exception as e:
        logger.info("prediction verdict LLM call failed: %s", e)
        return None
    return _parse_verdict(response.content or "")


def _render_proposal(prediction: dict, verdict: dict, evidence: list) -> str:
    """Deterministic message text: statement first, then verdict and sources."""
    lines = [f"⏳ Prediction deadline — {prediction['statement']}"]
    lines.append(f"Verdict: {verdict['verdict']} — {verdict['rationale']}")
    for ev in evidence:
        lines.append(f"📰 {ev['title']}: {ev['url']}")
    return "\n".join(lines)


async def _post_proposal(conn, ctx, room, prediction: dict,
                         verdict: dict, evidence: list) -> str:
    """Annotator-lane proposal, mirroring night_shift._post_brief_message."""
    msg_id = uuid4()
    now = datetime.now(timezone.utc)
    thread_row = await conn.fetchrow(
        "SELECT id FROM threads WHERE room_id = $1 ORDER BY created_at ASC LIMIT 1",
        room["id"],
    )
    if thread_row is None:
        return "no_thread"
    content = _render_proposal(prediction, verdict, evidence)
    metadata = {
        "source": "prediction_watch",
        "resolution_proposal": {
            "prediction_id": str(prediction["id"]),
            "statement": prediction["statement"],
            "verdict": verdict["verdict"],
            "rationale": verdict["rationale"],
            "evidence": [{"url": ev["url"], "title": ev["title"]}
                         for ev in evidence],
            "accepted": False,
        },
    }
    await conn.execute(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, user_id,
            message_type, content, metadata)
           VALUES (
               $1, $2,
               (SELECT COALESCE(MAX(sequence), 0) + 1
                FROM messages WHERE thread_id = $2),
               $3, $4, NULL, $5, $6, $7
           )""",
        msg_id, thread_row["id"], now,
        SpeakerType.LLM_ANNOTATOR.value, MessageType.TEXT.value,
        content, metadata,
    )
    await conn.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.ANNOTATION_CREATED.value,
        room["id"], thread_row["id"],
        {"message_id": str(msg_id), "source": "prediction_watch"},
    )
    if ctx.broadcast is not None:
        await ctx.broadcast(room["id"], OutboundMessage(
            type=MessageTypes.MESSAGE_CREATED,
            payload={
                "id": str(msg_id),
                "thread_id": str(thread_row["id"]),
                "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                "message_type": MessageType.TEXT.value,
                "content": content,
                "created_at": now.isoformat(),
                "metadata": metadata,
            },
        ))
    return str(msg_id)


async def prediction_deadline_watch(ctx: SchedulerContext) -> dict:
    """Propose resolutions for predictions whose deadline has arrived."""
    detail: dict = {"proposed": [], "skipped": []}
    try:
        predictions = await td.get("/api/predictions")
    except td.TradingDeskError as e:
        # A down desk is a quiet run, not a failed one.
        logger.warning("prediction watch could not list predictions: %s", e)
        detail["error"] = f"predictions_unavailable: {e}"
        return detail
    if not isinstance(predictions, list):
        detail["error"] = "unexpected_predictions_payload"
        return detail

    due, skipped = _due_predictions(predictions, datetime.now(timezone.utc).date())
    detail["skipped"].extend(skipped)

    async with ctx.pool.acquire() as conn:
        proposed_ids = await _already_proposed(conn)
        for prediction in due:
            pid = str(prediction["id"])
            if len(detail["proposed"]) >= PREDICTION_WATCH_RUN_CAP:
                detail["skipped"].append({"id": pid, "reason": "cap_reached"})
                continue
            if pid in proposed_ids:
                detail["skipped"].append({"id": pid, "reason": "already_proposed"})
                continue
            try:
                book_id = str(prediction.get("linked_book_id") or "").strip()
                if not book_id:
                    # No room mapping exists for unlinked predictions
                    # (see the module header) — v1 notes and skips them.
                    detail["skipped"].append({"id": pid, "reason": "unlinked_no_room"})
                    continue
                room = await _room_for_book(conn, book_id)
                if room is None:
                    detail["skipped"].append({"id": pid, "reason": "no_room_for_book"})
                    continue

                evidence = await _gather_evidence(book_id)
                verdict = await _verdict(prediction, evidence)
                if verdict is None:
                    detail["skipped"].append({"id": pid, "reason": "verdict_failed"})
                    continue

                msg_id = await _post_proposal(
                    conn, ctx, room, prediction, verdict, evidence,
                )
                if msg_id == "no_thread":
                    detail["skipped"].append({"id": pid, "reason": "no_thread"})
                    continue
                detail["proposed"].append({
                    "id": pid, "room_id": str(room["id"]),
                    "verdict": verdict["verdict"], "message_id": msg_id,
                })
                proposed_ids.add(pid)
            except Exception:
                # A broken prediction must not sink the watch for the others.
                logger.exception("prediction watch failed for %s", pid)
                detail["skipped"].append({"id": pid, "reason": "error"})
    return detail


def register_prediction_watch_jobs(scheduler) -> None:
    scheduler.register(Job(
        "prediction_deadline_watch", 3600, prediction_deadline_watch,
        enabled_env="PREDICTION_WATCH_ENABLED",
    ))
