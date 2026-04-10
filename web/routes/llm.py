"""
LLM routes — chat and compare via OpenRouter.

WHY: Both analysts need to query multiple LLMs from the trading room.
OpenRouter provides a single API for Claude, GPT-4o, Llama, Gemini.
Responses stream token-by-token via WebSocket for real-time display.
"""

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from web.auth import get_current_user
from web.models import User, LLMChatRequest, LLMCompareRequest
from web import state
from web.ws import manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"], dependencies=[Depends(get_current_user)])

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# WHY: Model aliases for @mention routing in chat.
MODEL_ALIASES = {
    "claude": "anthropic/claude-sonnet-4-20250514",
    "gpt": "openai/gpt-4o",
    "llama": "meta-llama/llama-3.1-405b-instruct",
    "gemini": "google/gemini-2.0-flash-001",
}


def _get_room_context(room_id: Optional[str]) -> list[dict]:
    """Build conversation history from room messages for LLM context."""
    if not room_id:
        return []
    messages = state.list_messages(room_id, limit=20)
    context: list[dict] = []
    for msg in messages:
        role = "assistant" if msg.get("msg_type") == "llm" else "user"
        name = msg.get("user", "unknown")
        content = msg.get("content", "")
        context.append({"role": role, "content": f"[{name}] {content}"})
    return context


def _get_thesis_context(room_id: Optional[str]) -> Optional[str]:
    """If room has a linked book, build thesis state context string."""
    if not room_id:
        return None
    room = state.get_room(room_id)
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
    user: str, model_label: str,
) -> str:
    """Call OpenRouter streaming API, broadcast chunks via WebSocket, return full response."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY not set")

    # Build messages
    system_parts: list[str] = [
        "You are an AI assistant in a macro trading analysis workspace. "
        "Two analysts (Amo and Dan) collaborate on commodities, futures, and geopolitical analysis. "
        "Be concise, data-driven, and opinionated about market structure."
    ]

    thesis_ctx = _get_thesis_context(room_id)
    if thesis_ctx:
        system_parts.append(thesis_ctx)

    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]
    messages.extend(_get_room_context(room_id))
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

    return full_response


@router.post("/chat")
async def chat(req: LLMChatRequest, user: User = Depends(get_current_user)) -> dict:
    """Send prompt to a single LLM, stream response via WebSocket."""
    model = req.model
    # Resolve alias
    for alias, full_model in MODEL_ALIASES.items():
        if model.lower() == alias:
            model = full_model
            break

    model_label = model.split("/")[-1] if "/" in model else model
    try:
        full_response = await _stream_llm(model, req.prompt, req.room_id, user.username, model_label)
    except HTTPException as e:
        error_msg = e.detail if hasattr(e, "detail") else str(e)
        if isinstance(error_msg, bytes):
            error_msg = error_msg.decode(errors="replace")
        if len(str(error_msg)) > 200:
            error_msg = str(error_msg)[:200] + "..."
        if req.room_id:
            msg = state.save_message(
                room_id=req.room_id, user="system",
                content=f"LLM error: {error_msg}", msg_type="system",
            )
            await manager.broadcast(req.room_id, "message", msg, user="system")
            await manager.broadcast(req.room_id, "llm_done", {"model": model_label, "full_response": ""}, user="assistant")
        return {"model": model_label, "response": "", "error": error_msg}
    except Exception as e:
        log.exception("Unexpected error in LLM chat for model %s", model_label)
        error_msg = str(e)[:200]
        if req.room_id:
            msg = state.save_message(
                room_id=req.room_id, user="system",
                content=f"LLM error: {error_msg}", msg_type="system",
            )
            await manager.broadcast(req.room_id, "message", msg, user="system")
            await manager.broadcast(req.room_id, "llm_done", {"model": model_label, "full_response": ""}, user="assistant")
        return {"model": model_label, "response": "", "error": error_msg}

    # Persist LLM response as a message in the room
    if req.room_id:
        state.save_message(
            room_id=req.room_id,
            user="assistant",
            content=full_response,
            msg_type="llm",
            model=model_label,
        )

    return {"model": model_label, "response": full_response}


@router.post("/compare")
async def compare(req: LLMCompareRequest, user: User = Depends(get_current_user)) -> dict:
    """Send same prompt to multiple models, stream all responses concurrently."""
    async def _run_model(model: str) -> tuple[str, str]:
        model_label = model.split("/")[-1] if "/" in model else model
        try:
            full_response = await _stream_llm(model, req.prompt, req.room_id, user.username, model_label)
            if req.room_id:
                state.save_message(
                    room_id=req.room_id, user="assistant",
                    content=full_response, msg_type="llm", model=model_label,
                )
            return model_label, full_response
        except Exception as e:
            error_msg = e.detail if hasattr(e, "detail") else str(e)
            if req.room_id:
                state.save_message(
                    room_id=req.room_id, user="system",
                    content=f"LLM error ({model_label}): {error_msg}", msg_type="system",
                )
            return model_label, f"Error: {error_msg}"

    # WHY: Run all model streams concurrently so users see interleaved tokens
    # from all models simultaneously. Wall-clock time = max(latency) not sum.
    pairs = await asyncio.gather(*[_run_model(m) for m in req.models])
    return {"results": dict(pairs)}
