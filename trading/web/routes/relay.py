"""
CORS relay for public market-data endpoints.

WHY this exists: the generated Cytoscape HTML dashboards in `output/*.html`
refresh their prices client-side. Browsers block cross-origin requests to
`query1.finance.yahoo.com`, so the legacy dashboards proxied through
`api.allorigins.win` — a third party we don't control. That proxy has gone
down repeatedly during trading sessions. This relay replaces it with an
endpoint we own on our droplet.

Scope and hardening:
- GET-only. Allowlisted upstream host and path prefixes.
- Per-IP rate limit (RELAY_RATE_LIMIT_PER_MIN, default 60/min) matching the
  TV webhook's limiter pattern. Same threading.Lock + deque approach.
- 30s public cache so repeat clients don't round-trip Yahoo every tick.
- Upstream timeout of 20s; status code and body are proxied transparently.
- No auth — the data is already public, and the legacy HTML dashboards are
  served as static files that cannot carry a JWT.

Non-goals:
- Not a general-purpose proxy. Off-allowlist URLs return 400.
- Not a cache — Cache-Control is advisory for downstream caches (nginx /
  browser); this module holds no response bodies in memory.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

log = logging.getLogger(__name__)

# ── Allowlist ─────────────────────────────────────────────────────────────

# WHY one host only: the relay exists to kill the allorigins dependency for
# Yahoo spark/chart fetches. Other feeds (FRED, Polymarket) already go through
# backend routes or have their own adapters. Widening the allowlist requires
# another audit pass.
ALLOWED_HOST = "query1.finance.yahoo.com"
ALLOWED_PATH_PREFIXES = (
    "/v7/finance/spark",
    "/v8/finance/chart",
)

# Upstream body cap (bytes). Yahoo spark/chart responses are small (~10 KiB
# per batch of 8); 512 KiB is generous and stops a malicious upstream from
# filling memory.
MAX_UPSTREAM_BYTES = 512 * 1024

# Upstream timeout (seconds). Slightly under the TV webhook's default so a
# hung Yahoo request doesn't back up the event loop.
UPSTREAM_TIMEOUT_SECONDS = 20.0


# ── Rate limiter ─────────────────────────────────────────────────────────

# WHY duplicated vs web.routes.tradingview._IPRateLimiter: that class is
# module-private and its deque is per-process. Importing would couple two
# unrelated routes through a shared module private. Copying 20 lines of
# stdlib code is the smaller evil.
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


def _read_rate_limit() -> int:
    try:
        return max(1, int(os.environ.get("RELAY_RATE_LIMIT_PER_MIN", "60")))
    except ValueError:
        return 60


rate_limiter = _IPRateLimiter(_read_rate_limit())


# ── URL validation ───────────────────────────────────────────────────────

def _validate_upstream(url: str) -> Optional[str]:
    """Return None if the upstream URL passes the allowlist, else a reason."""
    if not url or len(url) > 2048:
        return "url missing or too long"
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "scheme must be https"
    # Reject userinfo before host so an attacker can't smuggle a tag like
    # `attacker@allowed.host` past a naive hostname check.
    if parsed.username or parsed.password:
        return "userinfo not permitted"
    if (parsed.hostname or "") != ALLOWED_HOST:
        return f"host not allowlisted: {parsed.hostname!r}"
    if not any(parsed.path.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        return f"path not allowlisted: {parsed.path!r}"
    return None


# ── Router ───────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/relay", tags=["relay"])


@router.get("/yahoo")
async def relay_yahoo(request: Request, url: str) -> Response:
    """Proxy a GET to an allowlisted Yahoo Finance endpoint.

    Query param `url` must be a fully-qualified HTTPS URL to
    `query1.finance.yahoo.com` with a path starting with `/v7/finance/spark`
    or `/v8/finance/chart`. Everything else is 400.
    """
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    if not rate_limiter.allow(client_ip):
        log.info("relay rate-limited ip=%s", client_ip)
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    reason = _validate_upstream(url)
    if reason is not None:
        raise HTTPException(status_code=400, detail=reason)

    headers = {"User-Agent": "tradingDesk-relay/1.0 (+https://github.com)"}
    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECONDS) as client:
            upstream = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        log.warning("relay timeout url=%s", url)
        raise HTTPException(status_code=504, detail="upstream timeout")
    except httpx.HTTPError as e:
        log.warning("relay upstream error url=%s err=%s", url, e)
        raise HTTPException(status_code=502, detail=f"upstream error: {e.__class__.__name__}")

    body = upstream.content
    if len(body) > MAX_UPSTREAM_BYTES:
        log.warning("relay oversize upstream body %d bytes", len(body))
        raise HTTPException(status_code=502, detail="upstream response too large")

    # Pass through the upstream status code and content-type; cap caching
    # so fast-moving quotes don't sit in CDN/browser caches for long.
    out_ct = upstream.headers.get("content-type", "application/json")
    return Response(
        content=body,
        status_code=upstream.status_code,
        media_type=out_ct,
        headers={"Cache-Control": "public, max-age=30"},
    )
