"""Message routes + WebSocket endpoint for real-time chat."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from web.auth import get_current_user, decode_token
from web.deps import get_repo
from web.models import User, MessageCreate, PinRequest, RoomCommand
from web.persistence.repository import Repository
from web.ws import manager

log = logging.getLogger(__name__)

router = APIRouter(tags=["messages"])

# Slash commands dispatchable from chat. Kept in sync with the frontend
# SLASH_COMMANDS list in Chat.tsx.
SLASH_COMMANDS = ("/brief", "/thesis", "/diff", "/predict", "/watchlist")


@router.get("/api/rooms/{room_id}/messages")
async def list_messages(
    room_id: str,
    limit: int = Query(default=50, le=200),
    before: Optional[str] = Query(default=None),
    _user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> list:
    if await asyncio.to_thread(repo.get_room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    return await asyncio.to_thread(repo.list_messages, room_id, limit, before)


@router.post("/api/rooms/{room_id}/messages")
async def create_message(
    room_id: str,
    req: MessageCreate,
    user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    if await asyncio.to_thread(repo.get_room, room_id) is None:
        raise HTTPException(status_code=404, detail="Room not found")
    msg = await asyncio.to_thread(
        repo.save_message,
        room_id=room_id,
        user=user.username,
        content=req.content,
        msg_type=req.msg_type,
        model=req.model,
    )
    await manager.broadcast(room_id, "message", msg, user=user.username)
    return msg


async def _execute_slash_command(
    text: str, default_book: str, user: User, repo: Repository
) -> Optional[str]:
    """Execute a chat slash command server-side and return the result text.

    Returns ``None`` for an unrecognised command. Mirrors the formatting that
    previously lived (broken) in the frontend, but runs against the same
    adapters so results are authoritative and postable as a system message.
    """
    import re
    from datetime import date, timedelta

    from web.adapters import outcomes as outcomes_adapter
    from web.adapters import thesis as thesis_adapter
    from web.adapters import market as market_adapter

    parts = text.split()
    cmd = parts[0].lower()
    args = text[len(parts[0]):].strip()

    if cmd == "/brief":
        book = args or default_book
        return await asyncio.to_thread(outcomes_adapter.generate_brief, [book])

    if cmd == "/thesis":
        book = args or default_book
        state = await asyncio.to_thread(thesis_adapter.get_state, book)
        ns = state.get("nodeStates", {}) or {}
        cs = state.get("confluenceScores", {}) or {}
        phase = state.get("cascadePhase", {}) or {}
        fired = [k for k, v in ns.items() if v == "fired"]
        approaching = [k for k, v in ns.items() if v == "approaching"]
        top_conf = sorted(cs.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return "\n".join([
            f"THESIS: {state.get('title') or book}",
            f"Phase {phase.get('number')} ({phase.get('key')}) — {phase.get('status')}",
            f"Fired: {', '.join(fired) or 'none'}",
            f"Approaching: {', '.join(approaching) or 'none'}",
            f"Confluence: {', '.join(f'{k}={v}' for k, v in top_conf)}",
        ])

    if cmd == "/diff":
        book = args or default_book
        await asyncio.to_thread(thesis_adapter.fetch_prices_for_book, book)
        return f"Prices re-fetched for {book}"

    if cmd == "/predict":
        match = re.match(r'^"([^"]+)"\s+(\d+)%$', args)
        if not match:
            return 'Usage: /predict "statement" 75%'
        deadline = (date.today() + timedelta(days=30)).isoformat()
        await asyncio.to_thread(repo.save_prediction, user.username, {
            "statement": match.group(1),
            "confidence": int(match.group(2)) / 100,
            "deadline": deadline,
            "linked_book_id": None,
            "tags": [],
        })
        return f'Prediction created: "{match.group(1)}" at {match.group(2)}%'

    if cmd == "/watchlist":
        items = await asyncio.to_thread(market_adapter.get_watchlist)
        lines = [
            f"{(i.get('symbol') or '').ljust(6)} "
            f"{('%.2f' % i['last_price']) if i.get('last_price') is not None else '--'} "
            f"{i.get('label', '')}"
            for i in items
        ]
        return "WATCHLIST\n" + "\n".join(lines)

    return None


@router.post("/api/rooms/{room_id}/command")
async def run_room_command(
    room_id: str,
    req: RoomCommand,
    user: User = Depends(get_current_user),
    repo: Repository = Depends(get_repo),
) -> dict:
    """Execute a chat slash command and post its result as a system message.

    WHY server-side: command results are ``system`` messages, which clients
    cannot author (``MessageCreate.msg_type`` is locked to ``"user"``). The
    server runs the command against the real adapters, then authors the trusted
    system message and broadcasts it to the room.
    """
    room = await asyncio.to_thread(repo.get_room, room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")

    text = req.text.strip()
    cmd = text.split()[0].lower() if text else ""
    if cmd not in SLASH_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown command: {cmd or '(empty)'}")

    default_book = room.get("linked_book_id") or "iran-hormuz-graph"
    try:
        result = await _execute_slash_command(text, default_book, user, repo)
    except Exception as exc:  # surface failures to the room rather than 500ing
        log.warning("slash command %r failed: %s", cmd, exc)
        result = f"Command failed: {cmd} — {exc}"

    if result is None:
        raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")

    msg = await asyncio.to_thread(
        repo.save_message,
        room_id=room_id,
        user="system",
        content=result,
        msg_type="system",
        model=None,
    )
    await manager.broadcast(room_id, "message", msg, user="system")
    return msg


@router.get("/api/rooms/{room_id}/pins")
async def list_pins(room_id: str, _user: User = Depends(get_current_user),
                    repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.list_pins, room_id)


@router.post("/api/rooms/{room_id}/pins")
async def add_pin(room_id: str, req: PinRequest, _user: User = Depends(get_current_user),
                  repo: Repository = Depends(get_repo)) -> list:
    """Pin a message by passing its typed message object."""
    return await asyncio.to_thread(repo.add_pin, room_id, req.model_dump())


@router.delete("/api/rooms/{room_id}/pins/{message_id}")
async def remove_pin(room_id: str, message_id: str, _user: User = Depends(get_current_user),
                     repo: Repository = Depends(get_repo)) -> list:
    return await asyncio.to_thread(repo.remove_pin, room_id, message_id)


@router.get("/api/rooms/{room_id}/export")
async def export_chat(room_id: str, _user: User = Depends(get_current_user),
                      repo: Repository = Depends(get_repo)) -> dict:
    """Export room chat as markdown."""
    return {"markdown": await asyncio.to_thread(repo.export_room_markdown, room_id)}


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str) -> None:
    """WebSocket connection for real-time room messages.

    WHY: Client sends token as first message after connect for auth.
    Subsequent messages are typed JSON: {"type": "message"|"typing", ...}
    """
    await websocket.accept()
    username = ""
    # WHY: Access repo from app state — Depends() doesn't work on WS endpoints.
    repo: Repository = websocket.app.state.repo

    try:
        # WHY: Accept token via query param (?token=...) or as first WS message.
        token_param = websocket.query_params.get("token")
        if token_param:
            try:
                payload = decode_token(token_param)
                username = payload["sub"]
            except Exception:
                await websocket.send_text('{"type":"error","payload":{"detail":"Invalid token"}}')
                await websocket.close(code=4001)
                return
        else:
            auth_msg = await websocket.receive_text()
            try:
                payload = decode_token(auth_msg)
                username = payload["sub"]
            except Exception:
                await websocket.send_text('{"type":"error","payload":{"detail":"Invalid token"}}')
                await websocket.close(code=4001)
                return

        # WHY: Validate room exists before registering.
        if await asyncio.to_thread(repo.get_room, room_id) is None:
            await websocket.send_text('{"type":"error","payload":{"detail":"Room not found"}}')
            await websocket.close(code=4004)
            return

        await manager.connect(websocket, room_id, username)
        log.info("WS authenticated: %s in room %s", username, room_id)
        await manager.send_to(websocket, "system", {"detail": f"Connected as {username}"}, user="system")

        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, AttributeError):
                parsed = {"type": "message", "content": data}

            msg_type = parsed.get("type", "message")

            # Unit 9: any C2S frame bumps last_activity for idle detection.
            # Fire-and-forget — never blocks a real chat message.
            try:
                await manager.bump_activity(websocket)
            except Exception:
                pass

            if msg_type == "typing":
                await manager.broadcast(
                    room_id, "typing",
                    {"username": username, "typing": parsed.get("typing", True)},
                    user=username, exclude=websocket,
                )
            elif msg_type == "viewing":
                viewing = parsed.get("viewing", "")
                manager.set_user_viewing(username, viewing)
                await manager.broadcast(
                    room_id, "presence", await manager.get_presence(room_id), user="system",
                )
            elif msg_type == "presence.update":
                # Unit 9: client tells us which book it's now viewing.
                payload = parsed.get("payload") or {}
                book_id = payload.get("book_id")
                # Validate — accept None or a non-empty string. Anything else
                # silently coerced to None to avoid storing junk in the roster.
                if book_id is not None and not isinstance(book_id, str):
                    book_id = None
                await manager.update_presence(websocket, book_id)
            else:
                content = parsed.get("content", data)
                msg = await asyncio.to_thread(
                    repo.save_message, room_id=room_id, user=username, content=content
                )
                await manager.broadcast(room_id, "message", msg, user=username)

    except WebSocketDisconnect:
        log.info("WS disconnected: %s from room %s", username, room_id)
    except Exception as e:
        log.warning("WS error in room %s: %s", room_id, e)
    finally:
        if username:
            await manager.disconnect(websocket, room_id, username)
