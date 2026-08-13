# llm/claim_check.py — background "does this message fairly represent the
# linked article?" check for human messages carrying an http(s) URL.
#
# Fire-and-forget from the message-send path (transport/handlers.py, beside
# _detect_commitment_proposals): the defuddle sidecar fetches the article,
# one Haiku call compares the message text against the body, and only a
# `mixed` or `misrepresented` verdict lands — a metadata.claim_check patch
# on the SOURCE message plus a MESSAGE_METADATA broadcast, the exact
# write/broadcast shape commitment proposals use.
#
# `supported` and `unrelated` stay silent on purpose: the card is a nudge
# to be careful, not a fact-check scoreboard, and a badge on every
# well-sourced link would train the room to ignore it. Every failure path
# (sidecar down, no ANTHROPIC_API_KEY, junk verdict JSON, db hiccup) logs
# and returns — the send path must never feel this task.

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Optional
from uuid import UUID

from . import defuddle_client as dc
from .defuddle_client import DefuddleError

logger = logging.getLogger(__name__)

# First http(s) URL only — a message linking three articles gets one check,
# against the link its author led with.
URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")

# Same off-value set as orchestrator.tools_enabled: unset means ON — the env
# var is a kill switch, not an opt-in.
_OFF_VALUES = frozenset({"0", "false", "no", "off"})

# Verdicts that produce a card. Everything else keeps the room quiet.
CARD_VERDICTS = frozenset({"mixed", "misrepresented"})

# Haiku never sees more than this — mirrors tools.ARTICLE_CONTENT_CAP.
ARTICLE_BODY_CAP = 6000

CLAIM_CHECK_IDENTITY = '''You compare a chat message against the article it links \
to and judge whether the message fairly represents the article.

Reply with ONLY a JSON object — no prose, no code fence:
{"verdict": "...", "note": "..."}

verdict is exactly one of:
- "supported" — the message's claims about the article match what the article says
- "mixed" — partly right, but overstates the article or omits an important caveat
- "misrepresented" — the article does not say what the message claims, or says the opposite
- "unrelated" — the message is not really about the article's content

note is ONE sentence naming the specific gap (what the article actually says \
vs. what the message claims). Use an empty string for supported/unrelated.'''


def claim_check_enabled() -> bool:
    """Whether human messages with links get a claim check (default on)."""
    return os.getenv("CLAIM_CHECK_ENABLED", "").strip().lower() not in _OFF_VALUES


def first_url(text: str) -> Optional[str]:
    """The first http(s) URL in the message text, if any."""
    match = URL_RE.search(text or "")
    return match.group(0) if match else None


def _check_url(message) -> Optional[str]:
    """The URL to check, or None when this message should be left alone.

    WHY all gates in one pure helper: the spawn site stays a one-liner and
    the gating (env kill switch, human-only, has-a-URL) is unit-testable
    without an event loop.
    """
    if not claim_check_enabled():
        return None
    speaker = getattr(message.speaker_type, "value", message.speaker_type)
    if speaker != "human":
        return None
    return first_url(message.content or "")


def schedule_claim_check(
    *,
    room_id: UUID,
    message,
    db,
    db_pool=None,
    broadcast: Callable,
) -> None:
    """Fire-and-forget entry called from the message-send path.

    Spawns the check as a detached task; every gate and every failure is
    contained inside, so the send path never awaits and never hears about a
    failure. `db`/`db_pool`/`broadcast` are the same handles the
    commitment-proposal spawn uses — the task prefers a FRESH pool
    acquisition for its write because the per-message connection is already
    back in the pool by the time the check finishes.
    """
    url = _check_url(message)
    if url is None:
        return
    asyncio.create_task(
        run_claim_check(
            room_id=room_id,
            message_id=message.id,
            text=message.content,
            url=url,
            db=db,
            db_pool=db_pool,
            broadcast=broadcast,
        )
    )


async def run_claim_check(
    *,
    room_id: UUID,
    message_id: UUID,
    text: str,
    url: str,
    db,
    db_pool,
    broadcast: Callable,
) -> None:
    """Fetch the article, judge the message against it, patch the metadata.

    Any verdict outside CARD_VERDICTS writes nothing. Silence is the default
    posture; the card exists for the two cases where a reader deserves a
    nudge before relying on the message.
    """
    try:
        try:
            article = await dc.extract_article(url)
        except DefuddleError as e:
            # Sidecar down or the page won't extract — normal, not alarming.
            logger.info("claim check skipped — article fetch failed: %s", e)
            return
        verdict = await _judge_claim(text, article)
        if verdict is None or verdict["verdict"] not in CARD_VERDICTS:
            return
        patch = {
            "claim_check": {
                "url": url,
                "title": article.get("title"),
                "verdict": verdict["verdict"],
                "note": verdict["note"],
            }
        }
        if db_pool is not None:
            async with db_pool.acquire() as conn:
                await _write_claim_check(conn, message_id, patch)
        else:
            await _write_claim_check(db, message_id, patch)
        # Lazy import: transport.websocket's package __init__ pulls in
        # handlers, which imports THIS module — a top-level import here
        # would deadlock the import graph.
        from transport.websocket import MessageTypes, OutboundMessage
        await broadcast(room_id, OutboundMessage(
            type=MessageTypes.MESSAGE_METADATA,
            payload={
                "message_id": str(message_id),
                "metadata_patch": patch,
            },
        ))
    except Exception:
        # Fire-and-forget means a fault must die here, quietly.
        logger.exception("claim check failed for message %s", message_id)


async def _write_claim_check(db, message_id: UUID, patch: dict) -> None:
    """Same write shape as commitment proposals: merge, never overwrite."""
    await db.execute(
        """UPDATE messages
           SET metadata = COALESCE(metadata, '{}'::jsonb) || $2
           WHERE id = $1""",
        message_id, patch,
    )


async def _judge_claim(message_text: str, article: dict) -> Optional[dict]:
    """One Haiku call: message vs. article body → {verdict, note} or None.

    None on ANY failure — no API key, provider error, unparseable JSON, an
    out-of-vocabulary verdict, or an empty article body. The caller treats
    None as "say nothing".
    """
    # Lazy import, mirroring annotator.py: a missing ANTHROPIC_API_KEY raises
    # in get_provider, and that must degrade to silence, not an import error.
    from .providers import get_provider, ProviderName, LLMRequest

    body = str(article.get("content") or "")[:ARTICLE_BODY_CAP]
    if not body.strip():
        return None
    request = LLMRequest(
        messages=[{
            "role": "user",
            "content": (
                f"Chat message:\n\"{message_text}\"\n\n"
                f"Article title: {article.get('title') or '(untitled)'}\n\n"
                f"Article body:\n{body}\n\n"
                "Judge the message against the article."
            ),
        }],
        system=CLAIM_CHECK_IDENTITY,
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        temperature=0.0,
    )
    try:
        response = await get_provider(ProviderName.ANTHROPIC).complete(request)
    except Exception as e:
        logger.info("claim check judge unavailable: %s", e)
        return None
    return _parse_verdict(response.content)


def _parse_verdict(text: str) -> Optional[dict]:
    """Strict-JSON verdict extraction; None on anything unexpected.

    Tolerates a code fence around the object (Haiku sometimes adds one
    despite instructions) but never a verdict outside the fixed vocabulary.
    """
    try:
        data: Any = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    verdict = data.get("verdict")
    if verdict not in ("supported", "mixed", "misrepresented", "unrelated"):
        return None
    note = data.get("note")
    return {"verdict": verdict, "note": str(note).strip() if note else ""}
