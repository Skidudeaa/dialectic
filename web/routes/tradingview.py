"""
TradingView FastAPI routes.

WHY this layer is thin: all security verification lives in web/tv_webhook.py,
all mutation logic lives in web/adapters/tradingview.py. This file is HTTP
plumbing + Pydantic validation + WebSocket broadcast + event logging.

Routes:
  POST   /api/tradingview/webhook                              (HMAC-gated, NOT JWT)
  GET    /api/tradingview/status                               (JWT-gated)
  GET    /api/tradingview/events                               (JWT-gated)
  GET    /api/tradingview/events/{book_id}                     (JWT-gated)
  GET    /api/tradingview/indicators/{book_id}                 (JWT-gated)
  GET    /api/thesis/{book_id}/tv-bindings                     (JWT-gated)
  POST   /api/thesis/{book_id}/tv-bindings                     (JWT-gated)
  DELETE /api/thesis/{book_id}/tv-bindings/{binding_id}        (JWT-gated)

The webhook POST is the only route without JWT — it uses HMAC + timestamp
window + nonce replay protection instead, because Pine Script on
TradingView's servers cannot carry a JWT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from web.auth import get_current_user
from web.deps import get_repo
from web.persistence.repository import Repository
from web.adapters import tradingview as tv_adapter
from web.adapters.tradingview import MutationError
from web.models import (
    TVBinding,
    TVBindingCreate,
    TVStatus,
    TVWebhookAck,
    TVWebhookAlert,
    User,
)
from web.tv_webhook import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    DEFAULT_NONCE_TTL_SECONDS,
    VerificationContext,
    VerifyResult,
    nonce_store,
    verify_request,
)
from web.ws import manager

log = logging.getLogger(__name__)

# ── Configuration (env-driven) ────────────────────────────────────────────

# MUST be set in production. Route returns 500 if missing — the webhook
# refuses to operate without a verified secret.
def _read_secret() -> Optional[str]:
    # Read lazily so tests can monkey-patch os.environ between cases.
    return os.environ.get("TV_WEBHOOK_SECRET") or None


def _read_rate_limit() -> int:
    try:
        return max(1, int(os.environ.get("TV_WEBHOOK_RATE_LIMIT_PER_MIN", "60")))
    except ValueError:
        return 60


def _read_nonce_ttl() -> int:
    try:
        return max(60, int(os.environ.get("TV_WEBHOOK_NONCE_TTL_SECONDS", str(DEFAULT_NONCE_TTL_SECONDS))))
    except ValueError:
        return DEFAULT_NONCE_TTL_SECONDS


# ── Rate limiter (stdlib token bucket, per-IP) ────────────────────────────

# WHY in-process dict: single-worker deployment target, same rationale as
# the nonce store. A determined attacker can exhaust memory by cycling
# source IPs — but in the docker-compose deployment an upstream nginx
# reverse proxy is the first defence; this is belt-and-braces.
class _IPRateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, ip: str, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        cutoff = now - 60.0
        with self._lock:
            window = self._windows[ip]
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


rate_limiter = _IPRateLimiter(_read_rate_limit())


# ── Routers ───────────────────────────────────────────────────────────────

# WHY two routers: the webhook route is unauthenticated at the JWT layer,
# so it can't share the global JWT dependency with the other routes.
webhook_router = APIRouter(prefix="/api/tradingview", tags=["tradingview"])
mgmt_router = APIRouter(
    prefix="/api/tradingview",
    tags=["tradingview"],
    dependencies=[Depends(get_current_user)],
)
bindings_router = APIRouter(
    prefix="/api/thesis",
    tags=["tradingview"],
    dependencies=[Depends(get_current_user)],
)


# ── Webhook POST (HMAC-gated) ────────────────────────────────────────────

@webhook_router.post("/webhook")
async def receive_alert(request: Request) -> JSONResponse:
    """Receive a signed Pine Script alert and mutate the book accordingly.

    Flow:
      1. Rate limit (per-IP token bucket)
      2. Read raw body (size-capped)
      3. Pure verify: signature + timestamp + nonce
      4. Pydantic validate body
      5. Adapter: resolve binding + enforce op/type + atomic write
      6. Invalidate thesis cache + append audit event
      7. Broadcast to linked rooms via WebSocket
    """
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    repo: Repository = request.app.state.repo

    if not rate_limiter.allow(client_ip):
        repo.save_tv_event(
            result="rate_limited",
            detail="per-IP rate limit exceeded",
            source_ip=client_ip,
        )
        return JSONResponse(status_code=429, content={"error": "rate limit exceeded"})

    # Read the raw body ONCE — we need the bytes for HMAC verification
    # before Pydantic parses the JSON. 8 KiB cap prevents OOM via huge
    # bodies even if the reverse proxy limit is misconfigured.
    body = await request.body()
    if len(body) == 0:
        repo.save_tv_event(result="empty_body", source_ip=client_ip)
        return JSONResponse(status_code=400, content={"error": "empty body"})
    if len(body) > 8192:
        repo.save_tv_event(result="body_too_large", source_ip=client_ip,
                            detail=f"{len(body)} bytes")
        return JSONResponse(status_code=400, content={"error": "body too large"})

    ctx = VerificationContext(
        body=body,
        signature_header=request.headers.get("X-TV-Signature", ""),
        timestamp_header=request.headers.get("X-TV-Timestamp", ""),
        nonce_header=request.headers.get("X-TV-Nonce", ""),
        secret=_read_secret(),
    )
    verdict = verify_request(ctx)

    if verdict != VerifyResult.OK:
        http_code = {
            VerifyResult.NO_SECRET: 500,
            VerifyResult.BAD_SIGNATURE: 401,
            VerifyResult.BAD_TIMESTAMP: 410,
            VerifyResult.BAD_NONCE: 400,
            VerifyResult.NONCE_REPLAY: 409,
        }[verdict]
        repo.save_tv_event(
            result=verdict.value,
            detail=f"HTTP {http_code}",
            source_ip=client_ip,
        )
        return JSONResponse(status_code=http_code, content={"error": verdict.value})

    # Parse + validate body
    try:
        raw = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        repo.save_tv_event(result="bad_json", source_ip=client_ip)
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    try:
        alert = TVWebhookAlert.model_validate(raw)
    except Exception as e:
        repo.save_tv_event(
            result="bad_body", source_ip=client_ip, detail=str(e)[:300]
        )
        return JSONResponse(status_code=400, content={"error": "invalid body shape"})

    # Apply mutation via adapter
    try:
        result = await tv_adapter.apply_webhook(
            book_id=alert.book,
            binding_id=alert.bindingId,
            alert_value=alert.value,
        )
    except FileNotFoundError as e:
        repo.save_tv_event(
            result="book_not_found", book_id=alert.book, source_ip=client_ip,
            detail=str(e),
        )
        return JSONResponse(status_code=404, content={"error": str(e)})
    except LookupError as e:
        repo.save_tv_event(
            result="binding_not_found", book_id=alert.book,
            binding_id=alert.bindingId, source_ip=client_ip, detail=str(e),
        )
        return JSONResponse(status_code=404, content={"error": str(e)})
    except MutationError as e:
        repo.save_tv_event(
            result="mutation_rejected", book_id=alert.book,
            binding_id=alert.bindingId, source_ip=client_ip, detail=str(e),
        )
        return JSONResponse(status_code=422, content={"error": str(e)})
    except ValueError as e:
        repo.save_tv_event(
            result="validation_failed", book_id=alert.book,
            binding_id=alert.bindingId, source_ip=client_ip, detail=str(e),
        )
        return JSONResponse(status_code=400, content={"error": str(e)})

    # Audit + success event
    repo.save_tv_event(
        result="ok",
        book_id=result.book_id,
        binding_id=result.binding_id,
        node_id=result.node_id,
        op=result.op,
        new_value=result.new_value,
        source_ip=client_ip,
        detail=(
            f"state transitions: {', '.join(result.changed_node_ids())}"
            if result.state_changed() else None
        ),
    )

    # Fire-and-forget broadcast to linked rooms. Failure to broadcast does
    # NOT fail the webhook — the mutation is already durable and audited.
    try:
        await manager.broadcast_to_book_rooms(
            result.book_id,
            "tv-alert",
            {
                "bookId": result.book_id,
                "nodeId": result.node_id,
                "bindingId": result.binding_id,
                "op": result.op,
                "newValue": result.new_value,
                "pineAlertName": alert.pineAlertName,
                "chartSymbol": alert.chartSymbol,
                "thesisStateChanged": result.state_changed(),
                "changedNodes": result.changed_node_ids(),
            },
            user="tradingview",
        )
    except Exception as e:  # pragma: no cover
        log.warning("tv-alert broadcast failed (book=%s): %s", result.book_id, e)

    ack = TVWebhookAck(
        bookId=result.book_id,
        nodeId=result.node_id,
        op=result.op,  # type: ignore[arg-type]
        newValue=result.new_value,
    )
    return JSONResponse(status_code=200, content=ack.model_dump())


# ── Status + events (JWT-gated) ───────────────────────────────────────────

@mgmt_router.get("/status")
async def get_status(request: Request, repo: Repository = Depends(get_repo)) -> TVStatus:
    """Operator-facing config snapshot for the TradingViewPanel."""
    host = request.headers.get("host", "localhost")
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    webhook_url = f"{scheme}://{host}/api/tradingview/webhook"
    events = repo.list_tv_events(limit=1000)
    return TVStatus(
        secretConfigured=_read_secret() is not None,
        rateLimitPerMin=_read_rate_limit(),
        nonceTtlSeconds=_read_nonce_ttl(),
        clockSkewSeconds=DEFAULT_CLOCK_SKEW_SECONDS,
        activeNonces=len(nonce_store),
        webhookUrl=webhook_url,
        recentEventCount=len(events),
    )


@mgmt_router.get("/events")
async def list_events(limit: int = 50, repo: Repository = Depends(get_repo)) -> List[dict]:
    """Return the most recent TradingView events, newest first."""
    capped = max(1, min(500, int(limit)))
    return repo.list_tv_events(limit=capped)


@mgmt_router.get("/events/{book_id}")
async def list_events_for_book(book_id: str, limit: int = 50,
                               repo: Repository = Depends(get_repo)) -> List[dict]:
    """Return recent TradingView events filtered to a single book."""
    try:
        tv_adapter.validate_book_id(book_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    capped = max(1, min(500, int(limit)))
    return repo.list_tv_events(limit=capped, book_id=book_id)


@mgmt_router.get("/indicators/{book_id}")
async def get_indicators(book_id: str) -> Dict[str, dict]:
    """Return the tvIndicators dict per node for the active book."""
    try:
        return await asyncio.to_thread(tv_adapter.get_tv_indicators, book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Binding CRUD (JWT-gated, under /api/thesis/{book_id}/tv-bindings) ─────

@bindings_router.get("/{book_id}/tv-bindings")
async def list_bindings(book_id: str) -> List[dict]:
    try:
        return await asyncio.to_thread(tv_adapter.list_bindings, book_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@bindings_router.post("/{book_id}/tv-bindings")
async def create_binding(book_id: str, req: TVBindingCreate) -> dict:
    try:
        return await asyncio.to_thread(
            tv_adapter.create_binding, book_id, req.model_dump(exclude_none=True)
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@bindings_router.delete("/{book_id}/tv-bindings/{binding_id}")
async def delete_binding(book_id: str, binding_id: str) -> dict:
    # Matching validation: binding_id follows the same kebab-case regex
    if not binding_id or len(binding_id) > 64:
        raise HTTPException(status_code=400, detail="invalid binding id")
    try:
        removed = await asyncio.to_thread(
            tv_adapter.delete_binding, book_id, binding_id
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail=f"unknown bindingId: {binding_id}")
    return {"deleted": True, "bindingId": binding_id}


# ── Single-router re-export so main.py registers one name ─────────────────

# FastAPI's include_router takes a single router, but we need three (the
# webhook is unauthenticated, management is JWT-gated, bindings live under
# /api/thesis/{id}/tv-bindings). Expose all three under `router` so main.py
# can register them in a loop.
routers = [webhook_router, mgmt_router, bindings_router]
router = webhook_router  # backward-compat name for single-include fallback
