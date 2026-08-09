"""
LLM routes — chat and compare via OpenRouter.

WHY: Both analysts need to query multiple LLMs from the trading room.
OpenRouter provides a single API for Claude, GPT-4o, Llama, Gemini.
Responses stream token-by-token via WebSocket for real-time display.
"""

import asyncio
import collections
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.deps import get_repo
from web.models import User, LLMChatRequest, LLMCompareRequest
from web.persistence.repository import Repository
from web.runtime.coordinator import get_latest_revision
from web.ws import manager, mark_agent_thinking, mark_agent_idle

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"], dependencies=[Depends(get_current_user)])

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# WHY: Model aliases for @mention routing in chat.
MODEL_ALIASES = {
    "claude": "anthropic/claude-sonnet-4.6",
    "gpt": "openai/gpt-5.3-chat",
    "deepseek": "deepseek/deepseek-r1",
    "gemini": "google/gemini-3.1-pro-preview",
}

# WHY: The agent-in-room panel (Unit 11) needs to show the last ~20 LLM calls
# the desk made — model, prompt summary, latency, status, and the snapshot
# revision the agent was reasoning against at call time. We keep a tiny
# module-level ring buffer so the data is in-process (no DB round-trip on
# every poll) and tests can read `_AGENT_CALL_LOG` directly.
#
# Maxlen=50 chosen because the panel renders the last 20 by default but
# allows ?limit=50 for operators inspecting a short burst (e.g. /compare
# fans out 4 models concurrently — burst easily clears 20 in a minute).
# Bigger than 50 wastes memory; smaller than 50 means /compare bursts
# silently truncate the recent history.
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"
AGENT_LOG_MAXLEN = 50
_AGENT_CALL_LOG: "collections.deque[dict]" = collections.deque(maxlen=AGENT_LOG_MAXLEN)


def record_agent_call(
    *,
    model: str,
    prompt: str,
    tool_calls: Optional[list] = None,
    latency_ms: float,
    status: str,
    room_id: Optional[str] = None,
    thesis_id: Optional[str] = None,
    snapshot_revision: Optional[int] = None,
) -> dict:
    """Append a single LLM call summary to the in-process ring buffer.

    WHY structured fields (not free-form text): the frontend sorts/filters
    by room_id and renders status as a colored chip. Truncating prompt to
    80 chars keeps the buffer compact and avoids accidentally surfacing
    long secrets in the agent panel.
    """
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "prompt_first_80": (prompt or "")[:80],
        "tool_calls": list(tool_calls or []),
        "latency_ms": round(float(latency_ms), 1),
        "status": status,
        "room_id": room_id,
        "thesis_id": thesis_id,
        "snapshot_revision": snapshot_revision,
    }
    _AGENT_CALL_LOG.append(row)
    return row


def get_agent_log(
    room_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Return recent agent calls, newest-first, optionally filtered by room.

    WHY newest-first: the panel renders top-to-bottom as a timeline, with
    the most recent call at the top. Passing the filter into this helper
    (instead of letting the route slice) keeps the agent-call shape in one
    place and lets adjacent modules use the same view.
    """
    rows = list(_AGENT_CALL_LOG)
    if room_id is not None:
        rows = [r for r in rows if r.get("room_id") == room_id]
    rows.reverse()
    if limit > 0:
        rows = rows[:limit]
    return rows


def _resolve_thesis_id(room_id: Optional[str], repo: Repository) -> Optional[str]:
    """Look up the linked book id for a room, swallowing repo errors.

    WHY: Used to stamp the agent-call ring buffer. Never raises — a missing
    or unresolvable room must not break the LLM stream.
    """
    if not room_id:
        return None
    try:
        room = repo.get_room(room_id)
    except Exception:
        return None
    if not room:
        return None
    return room.get("linked_book_id")


def _get_room_context(room_id: Optional[str], repo: Repository) -> list[dict]:
    """Build conversation history from room messages for LLM context."""
    if not room_id:
        return []
    messages = repo.list_messages(room_id, limit=20)
    context: list[dict] = []
    for msg in messages:
        role = "assistant" if msg.get("msg_type") == "llm" else "user"
        name = msg.get("user", "unknown")
        content = msg.get("content", "")
        context.append({"role": role, "content": f"[{name}] {content}"})
    return context


def _get_thesis_context(room_id: Optional[str], repo: Repository) -> Optional[str]:
    """If room has a linked book, build thesis state context string."""
    if not room_id:
        return None
    room = repo.get_room(room_id)
    if not room or not room.get("linked_book_id"):
        return None
    try:
        from web.adapters.thesis import get_state
        book_id = room["linked_book_id"]
        thesis_state = get_state(book_id)

        # Build concise context string
        phase = thesis_state.get("cascadePhase", {})
        node_states = thesis_state.get("nodeStates", {})
        confluence = thesis_state.get("confluenceScores", {})
        countdowns = thesis_state.get("countdowns", [])

        hot_nodes = [f"{n}={s}" for n, s in node_states.items() if s in ("fired", "approaching")]
        top_conf = sorted(confluence.items(), key=lambda x: -x[1])[:5]

        lines = [
            f"THESIS CONTEXT: {thesis_state.get('title', book_id)}",
            f"Phase: {phase.get('number', '?')} ({phase.get('key', '?')}) — {phase.get('status', '?')}",
            f"Hot nodes: {', '.join(hot_nodes) if hot_nodes else 'none'}",
            f"Top confluence: {', '.join(f'{n}={v}' for n, v in top_conf)}",
        ]
        for cd in countdowns:
            days = cd.get("daysRemaining", "?")
            label = cd.get("label", cd.get("nodeId", "?"))
            lines.append(f"Deadline: {label} in {days} days")
        return "\n".join(lines)
    except Exception as e:
        log.warning("Failed to build thesis context: %s", e)
        return None


async def _stream_llm(
    model: str, prompt: str, room_id: Optional[str],
    user: str, model_label: str, repo: Repository,
) -> str:
    """Call OpenRouter streaming API, broadcast chunks via WebSocket, return full response."""
    # Unit 9: signal agent-thinking to the global presence pill row for the
    # duration of the stream. mark_agent_idle is called in the callers'
    # success + error branches (chat / compare) via a shared helper.
    mark_agent_thinking(book_id=_resolve_thesis_id(room_id, repo))
    if not OPENROUTER_API_KEY:
        mark_agent_idle()
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not set")

    # Build messages
    system_parts: list[str] = [
        "You are an AI assistant in a macro trading analysis workspace. "
        "Two analysts (Amo and Dan) collaborate on commodities, futures, and geopolitical analysis. "
        "Be concise, data-driven, and opinionated about market structure."
    ]

    thesis_ctx = _get_thesis_context(room_id, repo)
    if thesis_ctx:
        system_parts.append(thesis_ctx)

    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]
    messages.extend(_get_room_context(room_id, repo))
    messages.append({"role": "user", "content": prompt})

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://tradingdesk.local",
    }

    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 4096,
    }

    full_response = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", OPENROUTER_URL, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                error_body = await resp.aread()
                mark_agent_idle()  # Unit 9: clear pill on upstream error
                raise HTTPException(status_code=resp.status_code, detail=f"OpenRouter error: {error_body.decode()}")

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_response += token
                        if room_id:
                            await manager.broadcast(
                                room_id, "llm_chunk",
                                {"token": token, "model": model_label},
                                user="assistant",
                            )
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

    # Broadcast completion
    if room_id:
        await manager.broadcast(
            room_id, "llm_done",
            {"model": model_label, "full_response": full_response},
            user="assistant",
        )

    # Unit 9: clear the agent-thinking pill — success path.
    mark_agent_idle()
    return full_response


@router.post("/chat")
async def chat(req: LLMChatRequest, user: User = Depends(get_current_user),
               repo: Repository = Depends(get_repo)) -> dict:
    """Send prompt to a single LLM, stream response via WebSocket."""
    model = req.model
    # Resolve alias
    for alias, full_model in MODEL_ALIASES.items():
        if model.lower() == alias:
            model = full_model
            break

    model_label = model.split("/")[-1] if "/" in model else model
    # Stamp call metadata BEFORE the stream so we can record both success
    # and failure with the same revision/start-time pair.
    _t0 = time.monotonic()
    _thesis_id = _resolve_thesis_id(req.room_id, repo)
    _revision_at_call = (
        get_latest_revision(_thesis_id) if _thesis_id else None
    )
    try:
        full_response = await _stream_llm(model, req.prompt, req.room_id, user.username, model_label, repo)
        record_agent_call(
            model=model_label,
            prompt=req.prompt,
            tool_calls=[],
            latency_ms=(time.monotonic() - _t0) * 1000.0,
            status="success",
            room_id=req.room_id,
            thesis_id=_thesis_id,
            snapshot_revision=_revision_at_call,
        )
    except HTTPException as e:
        error_msg = e.detail if hasattr(e, "detail") else str(e)
        if isinstance(error_msg, bytes):
            error_msg = error_msg.decode(errors="replace")
        if len(str(error_msg)) > 200:
            error_msg = str(error_msg)[:200] + "..."
        record_agent_call(
            model=model_label,
            prompt=req.prompt,
            tool_calls=[],
            latency_ms=(time.monotonic() - _t0) * 1000.0,
            status="error",
            room_id=req.room_id,
            thesis_id=_thesis_id,
            snapshot_revision=_revision_at_call,
        )
        if req.room_id:
            msg = repo.save_message(
                room_id=req.room_id, user="system",
                content=f"LLM error: {error_msg}", msg_type="system",
            )
            await manager.broadcast(req.room_id, "message", msg, user="system")
            await manager.broadcast(req.room_id, "llm_done", {"model": model_label, "full_response": ""}, user="assistant")
        return {"model": model_label, "response": "", "error": error_msg}
    except Exception as e:
        log.exception("Unexpected error in LLM chat for model %s", model_label)
        error_msg = str(e)[:200]
        record_agent_call(
            model=model_label,
            prompt=req.prompt,
            tool_calls=[],
            latency_ms=(time.monotonic() - _t0) * 1000.0,
            status="error",
            room_id=req.room_id,
            thesis_id=_thesis_id,
            snapshot_revision=_revision_at_call,
        )
        if req.room_id:
            msg = repo.save_message(
                room_id=req.room_id, user="system",
                content=f"LLM error: {error_msg}", msg_type="system",
            )
            await manager.broadcast(req.room_id, "message", msg, user="system")
            await manager.broadcast(req.room_id, "llm_done", {"model": model_label, "full_response": ""}, user="assistant")
        return {"model": model_label, "response": "", "error": error_msg}

    # Persist LLM response as a message in the room and broadcast it
    # WHY: llm_done clears the streaming bubble on the frontend. The persisted
    # message must arrive via WS so it appears in the chat history immediately.
    # Without this broadcast the response vanishes after streaming completes.
    if req.room_id:
        msg = repo.save_message(
            room_id=req.room_id,
            user="assistant",
            content=full_response,
            msg_type="llm",
            model=model_label,
        )
        await manager.broadcast(req.room_id, "message", msg, user="assistant")

    return {"model": model_label, "response": full_response}


@router.post("/compare")
async def compare(req: LLMCompareRequest, user: User = Depends(get_current_user),
                  repo: Repository = Depends(get_repo)) -> dict:
    """Send same prompt to multiple models, stream all responses concurrently."""
    async def _run_model(model: str) -> tuple[str, str]:
        # WHY resolve aliases here too: /chat does the same so callers can pass
        # plain "claude" / "gpt" / "gemini". Without this, the frontend has to
        # hardcode full IDs (and any third-party caller breaks).
        for alias, full_model in MODEL_ALIASES.items():
            if model.lower() == alias:
                model = full_model
                break
        model_label = model.split("/")[-1] if "/" in model else model
        _t0 = time.monotonic()
        _thesis_id = _resolve_thesis_id(req.room_id, repo)
        _revision_at_call = (
            get_latest_revision(_thesis_id) if _thesis_id else None
        )
        try:
            full_response = await _stream_llm(model, req.prompt, req.room_id, user.username, model_label, repo)
            record_agent_call(
                model=model_label,
                prompt=req.prompt,
                tool_calls=[],
                latency_ms=(time.monotonic() - _t0) * 1000.0,
                status="success",
                room_id=req.room_id,
                thesis_id=_thesis_id,
                snapshot_revision=_revision_at_call,
            )
            if req.room_id:
                msg = repo.save_message(
                    room_id=req.room_id, user="assistant",
                    content=full_response, msg_type="llm", model=model_label,
                )
                await manager.broadcast(req.room_id, "message", msg, user="assistant")
            return model_label, full_response
        except Exception as e:
            error_msg = e.detail if hasattr(e, "detail") else str(e)
            record_agent_call(
                model=model_label,
                prompt=req.prompt,
                tool_calls=[],
                latency_ms=(time.monotonic() - _t0) * 1000.0,
                status="error",
                room_id=req.room_id,
                thesis_id=_thesis_id,
                snapshot_revision=_revision_at_call,
            )
            if req.room_id:
                msg = repo.save_message(
                    room_id=req.room_id, user="system",
                    content=f"LLM error ({model_label}): {error_msg}", msg_type="system",
                )
                await manager.broadcast(req.room_id, "message", msg, user="system")
            return model_label, f"Error: {error_msg}"

    # WHY: Run all model streams concurrently so users see interleaved tokens
    # from all models simultaneously. Wall-clock time = max(latency) not sum.
    pairs = await asyncio.gather(*[_run_model(m) for m in req.models])
    return {"results": dict(pairs)}
