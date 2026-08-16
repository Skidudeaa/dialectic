"""
Bridge / outbox status + replay endpoints.

WHY: When the dialectic push pipeline can't reach the server (outage,
auth blip, network), snapshots spool to `snapshots/outbox/` and replay
on the next run. Operators need a way to see "is anything stuck?" without
shelling into the droplet — the dashboard surfaces this via a top-bar
badge backed by GET /api/bridge/outbox, and a "drain now" button backed
by POST /api/bridge/outbox/replay so they don't have to wait for cron
once dialectic recovers.

Filename parsing is delegated to push_to_dialectic.parse_outbox_filename
so the format lives in one place.
"""

from __future__ import annotations

import asyncio
import hmac
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tools.bridge.room_tokens import (  # type: ignore[import-untyped]
    register_room_token,
    resolve_room_token,
    unregister_room_token,
)
from web.auth import get_current_user
from web.deps import get_repo
from web.models import User
from web.persistence.repository import Repository

log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/bridge", tags=["bridge"])


# WHY: push_to_dialectic.py uses a hyphen-free filename and is a CLI tool
# in tools/bridge/, not a package. Load it once at import time so the
# endpoint doesn't pay subprocess/import overhead on every request.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PUSH_PATH = _REPO_ROOT / "tools" / "bridge" / "push_to_dialectic.py"


def _load_push_module():
    """Import tools/bridge/push_to_dialectic.py as a module.

    WHY a helper: tests can monkeypatch this to inject a stub, and we keep
    the side-effecting importlib dance out of module top-level so a missing
    file at import time doesn't break the whole web app.
    """
    if "push_to_dialectic" in sys.modules:
        return sys.modules["push_to_dialectic"]
    spec = importlib.util.spec_from_file_location(
        "push_to_dialectic", str(_PUSH_PATH),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_PUSH_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["push_to_dialectic"] = mod
    spec.loader.exec_module(mod)
    return mod


class OutboxStatus(BaseModel):
    """Aggregate state of the snapshot retry queue."""
    queued: int
    byRoom: dict[str, int]
    oldest: Optional[str]   # ISO 8601 UTC, or null if empty
    newest: Optional[str]
    totalBytes: int
    replayCap: int


def _scan_outbox_sync() -> OutboxStatus:
    """Blocking scan of the outbox directory. Wrapped by the route handler."""
    push_mod = _load_push_module()
    outbox: Path = push_mod._outbox_path()
    cap: int = push_mod._resolve_replay_cap()

    if not outbox.is_dir():
        return OutboxStatus(
            queued=0, byRoom={}, oldest=None, newest=None,
            totalBytes=0, replayCap=cap,
        )

    by_room: dict[str, int] = {}
    timestamps: list[str] = []
    total_bytes = 0
    queued = 0

    for path in outbox.glob("*.json"):
        parsed = push_mod.parse_outbox_filename(path.name)
        if not parsed:
            # WHY: silently skip files that don't match the convention --
            # could be a stale temp file, a manual paste, etc. Surfacing them
            # would noise up the badge without operator action.
            continue
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        room = parsed["room"]
        by_room[room] = by_room.get(room, 0) + 1
        timestamps.append(parsed["ts"])
        queued += 1

    timestamps.sort()
    return OutboxStatus(
        queued=queued,
        byRoom=by_room,
        oldest=timestamps[0] if timestamps else None,
        newest=timestamps[-1] if timestamps else None,
        totalBytes=total_bytes,
        replayCap=cap,
    )


@router.get("/outbox", response_model=OutboxStatus)
async def get_outbox_status(
    _user: User = Depends(get_current_user),
) -> OutboxStatus:
    """Return outbox queue summary.

    Empty outbox returns `{queued: 0, byRoom: {}, oldest: null, newest: null,
    totalBytes: 0, replayCap: <cap>}` -- never 404; the badge code distinguishes
    between "loaded and empty" and "failed to load".
    """
    return await asyncio.to_thread(_scan_outbox_sync)


# =========================================================================
# DRAIN NOW — manual outbox replay
#
# WHY: The cron-driven `run-all.py` tick replays the outbox before each
# fresh push, but operators frequently know dialectic has just recovered
# and don't want to wait for the next tick (default Mon/Wed/Fri 08:00).
# This endpoint exposes the same replay machinery via a button on the
# OutboxBadge popover. The endpoint is JWT-gated since it both consumes
# the room token and triggers outbound network IO.
# =========================================================================


_BOOKS_DIR = _REPO_ROOT / "books"


class ReplayRequest(BaseModel):
    """Optional body for the replay endpoint.

    `roomId` omitted -> drain every room with queued spools. Provided ->
    drain only that one room (no error if it has nothing queued).
    """
    roomId: Optional[str] = None


class PerRoomResult(BaseModel):
    roomId: str
    replayed: int
    remaining: int
    errors: list[str]


class ReplayResponse(BaseModel):
    replayed: int
    remaining: int
    perRoom: list[PerRoomResult]
    dialecticUrl: str
    durationMs: int


def _resolve_dialectic_url() -> str:
    """Reuse the same env knob run-all.py already honors, default localhost."""
    return os.environ.get("DIALECTIC_URL", "http://localhost:8002").strip() \
        or "http://localhost:8002"


def _load_book_tokens() -> dict[str, str]:
    """Map dialecticRoomId -> room token for every book that declares a room.

    The books supply the room IDs; `resolve_room_token` supplies the secret,
    which since 2026-08-10 lives in DIALECTIC_ROOM_TOKENS rather than in the
    book (the books are on a public repo).

    WHY lazy + per-call: this fires on a button click, not in a hot loop, and
    reading the env each time means an operator who fixes a token does not
    have to restart the desk to be believed.
    """
    tokens: dict[str, str] = {}
    if not _BOOKS_DIR.is_dir():
        return tokens
    for path in _BOOKS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta", {}) or {}
        room_id = meta.get("dialecticRoomId")
        room_tok = resolve_room_token(meta)
        if room_id and room_tok:
            tokens[room_id] = room_tok
    return tokens


def _discover_queued_rooms() -> list[str]:
    """Scan the outbox dir and return the unique set of room IDs with spools."""
    push_mod = _load_push_module()
    outbox: Path = push_mod._outbox_path()
    if not outbox.is_dir():
        return []
    rooms: set[str] = set()
    for p in outbox.glob("*.json"):
        parsed = push_mod.parse_outbox_filename(p.name)
        if parsed:
            rooms.add(parsed["room"])
    # Stable ordering -> deterministic per-room result list for the UI.
    return sorted(rooms)


def _count_remaining(room_id: str) -> int:
    """Count spools still queued for a room after a replay attempt."""
    push_mod = _load_push_module()
    return len(push_mod.list_outbox(room_id))


def _replay_sync(room_filter: Optional[str]) -> ReplayResponse:
    """Blocking drain. Wrapped in to_thread by the route handler.

    Per-room loop:
      1. Resolve token (book meta -> env fallback).
      2. Call push_mod.replay_outbox(url, room, token).
      3. Re-count remaining spools to surface partial-failure state.

    Errors don't bubble out — they land in the per-room `errors` list and
    the response is still 200, because the operator deserves to see which
    rooms drained vs. which are still stuck.
    """
    push_mod = _load_push_module()
    dialectic_url = _resolve_dialectic_url()
    cap = push_mod._resolve_replay_cap()
    book_tokens = _load_book_tokens()
    env_token = os.environ.get("DIALECTIC_ROOM_TOKEN", "").strip()

    if room_filter:
        target_rooms = [room_filter]
    else:
        target_rooms = _discover_queued_rooms()

    started = time.monotonic()
    per_room: list[PerRoomResult] = []
    total_replayed = 0

    for room in target_rooms:
        errors: list[str] = []
        token = book_tokens.get(room) or env_token
        replayed = 0
        if not token:
            # WHY no token: the spools stay queued; the operator sees a clear
            # error in the UI rather than a 500. Common cause: rotating env
            # without restarting the FastAPI process.
            errors.append("no DIALECTIC_ROOM_TOKEN configured for this room")
        else:
            try:
                # replay_outbox returns (success_count, failure_count).
                # failure_count is 0 or 1 (replay halts on first failure to
                # preserve ordering). Anything halted stays in the spool dir
                # and shows up in the remaining count below.
                replayed, failures = push_mod.replay_outbox(
                    dialectic_url, room, token, max_per_run=cap,
                )
                if failures:
                    errors.append(
                        "replay halted on a queued spool — dialectic likely "
                        "unreachable; remaining spools stay queued for the "
                        "next attempt"
                    )
            except Exception as exc:  # noqa: BLE001 -- surface any fault
                errors.append(f"{type(exc).__name__}: {exc}")

        remaining = _count_remaining(room)
        total_replayed += replayed
        per_room.append(PerRoomResult(
            roomId=room,
            replayed=replayed,
            remaining=remaining,
            errors=errors,
        ))

    total_remaining = sum(r.remaining for r in per_room)
    duration_ms = int((time.monotonic() - started) * 1000)
    return ReplayResponse(
        replayed=total_replayed,
        remaining=total_remaining,
        perRoom=per_room,
        dialecticUrl=dialectic_url,
        durationMs=duration_ms,
    )


@router.post("/outbox/replay", response_model=ReplayResponse)
async def replay_outbox_endpoint(
    body: Optional[ReplayRequest] = None,
    _user: User = Depends(get_current_user),
) -> ReplayResponse:
    """Manually drain queued snapshots from the dialectic outbox.

    Empty outbox returns 200 with zeros (idempotent).
    Dialectic unreachable returns 200 with `errors` populated and
    `remaining > 0` -- the operator sees the partial result instead of
    a generic 5xx.
    """
    room_filter = body.roomId if body else None
    return await asyncio.to_thread(_replay_sync, room_filter)


# =========================================================================
# SERVICE READ ENDPOINTS
#
# WHY a second auth scheme on this router: /outbox and /outbox/replay are
# operator actions behind a human's JWT. These two are machine reads — the
# Dialectic scheduler's trading_reconcile job pulls them every 15 minutes to
# repair a room whose push was missed, and its LLM tools read the news feed.
# A service has no JWT and shouldn't be issued one; it presents a shared
# secret instead.
#
# The dependency is deliberately LOCAL to this module rather than added to
# web/auth.py — service-token auth is a property of the bridge surface, not
# of the desk's user session model.
# =========================================================================


SERVICE_TOKEN_ENV = "TD_SERVICE_TOKEN"


def require_service_token(
    x_service_token: Optional[str] = Header(None, alias="X-Service-Token"),
) -> None:
    """Constant-time shared-secret gate for machine callers.

    503 when the secret is not configured — an unset env var is a
    misconfigured server, not a rejected caller, and answering 401 would
    send Dialectic hunting for a bad token that doesn't exist.

    WHY hmac.compare_digest: a plain `==` on a secret leaks its prefix
    length through timing. The comparison is over a fixed-length token so
    the digest compare is the right primitive.
    """
    expected = os.environ.get(SERVICE_TOKEN_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"{SERVICE_TOKEN_ENV} is not configured on this server",
        )
    supplied = (x_service_token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid service token")


# ── GET /api/bridge/snapshot/{thesis_id} ────────────────────────────────


@router.get("/snapshot/{thesis_id}")
async def get_thesis_snapshot(
    thesis_id: str,
    repo: Repository = Depends(get_repo),
    _svc: None = Depends(require_service_token),
) -> JSONResponse:
    """Latest committed snapshot for a thesis, in the v3 push contract.

    alertEvents is always empty here: events describe a TRANSITION between
    two consecutive cycles, and a point-in-time read has no predecessor to
    diff against. Emitting the last tick's events would tell Dialectic that
    a node just fired when it may have fired hours ago — and would re-fire
    the curator on every 15-minute reconcile. Empty is the honest answer,
    and it is exactly what gates the curator off on the reconcile path.

    Returns an explicit JSONResponse so the content-type is unambiguous:
    Dialectic's reconcile job treats a non-JSON 200 as 'endpoint missing',
    because this app's SPA catch-all answers unknown paths with 200 + HTML.
    """
    snapshot = await asyncio.to_thread(repo.get_latest_snapshot, thesis_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail=f"No snapshot for thesis {thesis_id!r}",
        )

    # get_latest_snapshot stamps the row's revision as `_revision`. Promote it
    # when the stored body predates the coordinator writing `revision` inline.
    row_revision = snapshot.pop("_revision", None)
    if snapshot.get("revision") is None and row_revision is not None:
        snapshot["revision"] = row_revision

    from web.runtime.dialectic_push import build_v3_payload
    payload = build_v3_payload(thesis_id, snapshot, alert_events=[])
    return JSONResponse(content=payload, media_type="application/json")


class RoomTokenRegistration(BaseModel):
    room_id: str
    token: str


@router.post("/room-token")
async def register_room_token_endpoint(
    req: RoomTokenRegistration,
    _svc: None = Depends(require_service_token),
) -> dict:
    """Register a Dialectic room token so a newly bound book can push.

    WHY this write exists on an otherwise read-only bridge: creating a
    thesis FROM Dialectic mints a new room whose token the pushing process
    cannot learn from its environment without a restart. Dialectic (the
    only holder of the service token) hands the token across once, it
    lands in the runtime file under /var/lib/tradingdesk, and the
    coordinator's next cycle resolves it. Re-registering is a rotation,
    not a conflict.
    """
    try:
        register_room_token(req.room_id, req.token)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except OSError as e:
        log.error("room-token registration could not persist: %s", e)
        raise HTTPException(
            status_code=500, detail="could not persist the room token"
        )
    return {"ok": True, "room_id": req.room_id}


class RoomUnbind(BaseModel):
    room_id: str


@router.post("/room-unbind")
async def unbind_room_endpoint(
    req: RoomUnbind,
    request: Request,
    _svc: None = Depends(require_service_token),
) -> dict:
    """Release every book bound to a Dialectic room — the retire flow.

    The book SURVIVES: it stays on the desk as history, it just stops
    claiming the room (meta.dialecticRoomId removed, atomic rewrite), stops
    pushing (re-adopted so the in-memory cfg loses the binding too), and
    the room's runtime token entry is dropped. Idempotent — unbinding a
    room nothing claims returns an empty list, not an error.
    """
    import uuid as _uuid
    try:
        canonical = str(_uuid.UUID(req.room_id.strip()))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="room_id is not a UUID")

    from web.adapters import thesis as thesis_adapter
    coordinator = getattr(request.app.state, "coordinator", None)

    unbound: list[str] = []
    for path in sorted(_BOOKS_DIR.glob("*.json")):
        try:
            with open(path) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            continue
        meta = cfg.get("meta") or {}
        bound_to = meta.get("dialecticRoomId")
        try:
            if not bound_to or str(_uuid.UUID(str(bound_to))) != canonical:
                continue
        except ValueError:
            continue
        meta.pop("dialecticRoomId", None)
        meta.pop("dialecticRoomToken", None)
        cfg["meta"] = meta
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
        thesis_adapter.invalidate_cache(path.stem)
        if coordinator is not None:
            coordinator.adopt_book(path.stem)
        unbound.append(path.stem)
        log.info("room-unbind: %s released from room %s", path.stem, canonical)

    unregister_room_token(canonical)
    return {"unbound": unbound}


# ── GET /api/bridge/news/{thesis_id} ────────────────────────────────────


# WHY a 15-minute TTL: GDELT asks callers for ~1 req/sec and answers 429 when
# pushed. Dialectic's reconcile runs every 15 minutes and an LLM tool call can
# arrive at any moment; without a cache a chatty room would hammer a public
# API on every turn. The window matches the reconcile cadence, so a scheduled
# pull is always a fresh fetch and everything in between is free.
NEWS_TTL_SECONDS = 900.0

# Failures cache for much less: a rate-limit blip should not blank the feed
# for a quarter of an hour, but it should not be retried on every request
# either.
NEWS_ERROR_TTL_SECONDS = 120.0

# WHY a 429 backs off harder than any other failure: every other error is a
# guess about whether the upstream has recovered, but a rate limit is the
# upstream telling us in words that we are asking too often. Retrying it on
# the flat 120s error TTL means five books re-attempt roughly every 24s
# between them, which is what keeps a per-IP throttle warm — the feed then
# stays dark for hours and the retries are the reason. Consecutive rate
# limits double the hold, capped at NEWS_TTL_SECONDS, so a throttled feed is
# never polled harder than a healthy one. One good fetch clears the streak.
#
# Observed 2026-08-10: with the flat TTL, four of five books sat on
# GdeltRateLimitError for hours while each probe drew a fresh 429.
NEWS_RATE_LIMIT_MAX_DOUBLINGS = 8

# GDELT rate-limits by caller IP, so the cooldown must span books and queries.
_news_rate_limit_streak = 0
_news_rate_limit_until = 0.0
_news_fetch_lock = Lock()

NEWS_MAX_HEADLINES = 15
NEWS_CACHE_MAX_ENTRIES = 64

# (thesis_id, exact query or "") -> (expires_at_monotonic, payload)
_news_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _book_path(thesis_id: str) -> Optional[Path]:
    """Resolve books/{thesis_id}.json, refusing anything that escapes the dir.

    WHY the containment check: thesis_id comes off the URL path. FastAPI
    will not match a literal '/' into this segment, but '..' and encoded
    separators are cheap to defend against and the cost of being wrong is
    reading arbitrary JSON off the disk.
    """
    candidate = (_BOOKS_DIR / f"{thesis_id}.json").resolve()
    try:
        candidate.relative_to(_BOOKS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@router.get("/polymarket/{thesis_id}")
async def get_thesis_polymarket(
    thesis_id: str,
    _svc: None = Depends(require_service_token),
) -> JSONResponse:
    """Return book-scoped Polymarket coverage and live probabilities."""
    path = _book_path(thesis_id)
    if path is None:
        raise HTTPException(
            status_code=404, detail=f"No book for thesis {thesis_id!r}",
        )
    try:
        book = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Book {thesis_id!r} is unreadable: {exc}",
        )

    from web.adapters import market as market_adapter

    market_ids = market_adapter.polymarket_markets_from_book(book)
    if not market_ids:
        payload = {
            "status": "not_configured",
            "configured_markets": [],
            "markets": [],
        }
    else:
        markets = await asyncio.to_thread(
            market_adapter.fetch_polymarket_probs, market_ids,
        )
        payload = {
            "status": "ok" if markets else "no_data",
            "configured_markets": market_ids,
            "markets": markets,
        }
    return JSONResponse(content=payload, media_type="application/json")


def _gdelt_query_for_book(book: dict) -> Optional[str]:
    """Find the book's GDELT query, if it declares one.

    Books express feeds per node: nodes[].feeds[] = [{"source": "gdelt",
    "standardQuery": "iran-hormuz-event"}]. A literal `query` wins over
    `standardQuery` so a book can override the shared catalog.
    """
    from tools.data_fetch.gdelt import get_standard_query

    for node in book.get("nodes", []) or []:
        for feed in (node.get("feeds") or []):
            if not isinstance(feed, dict):
                continue
            if (feed.get("source") or "").lower() != "gdelt":
                continue
            literal = (feed.get("query") or "").strip()
            if literal:
                return literal
            named = (feed.get("standardQuery") or "").strip()
            if named:
                resolved = get_standard_query(named)
                if resolved:
                    return resolved
                log.warning("book declares unknown GDELT standardQuery %r", named)
    return None


def _news_payload(
    status: str,
    query: Optional[str],
    *,
    articles: Optional[list[dict[str, Any]]] = None,
    note: Optional[str] = None,
    retry_after_seconds: Optional[int] = None,
) -> dict[str, Any]:
    """Build the stable GDELT response contract for every source state."""
    payload: dict[str, Any] = {
        "status": status,
        "source": "gdelt",
        "query": query,
        "articles": articles if articles is not None else [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cache_hit": False,
    }
    if note is not None:
        payload["note"] = note
    if retry_after_seconds is not None:
        payload["retry_after_seconds"] = retry_after_seconds
    return payload


def _fetch_news_sync(
    thesis_id: str,
    book: dict[str, Any],
    query_override: Optional[str] = None,
) -> tuple[dict[str, Any], float]:
    """Fetch headlines and return their explicit source state plus cache TTL."""
    global _news_rate_limit_streak, _news_rate_limit_until

    query = query_override or _gdelt_query_for_book(book)
    if not query:
        return (
            _news_payload(
                "not_configured", None, note="no gdelt config",
            ),
            NEWS_TTL_SECONDS,
        )

    now = time.monotonic()
    if _news_rate_limit_until > now:
        remaining = max(1, int(_news_rate_limit_until - now + 0.999))
        return (
            _news_payload(
                "rate_limited",
                query,
                note="GDELT source cooldown active",
                retry_after_seconds=remaining,
            ),
            float(remaining),
        )

    from tools.data_fetch import gdelt

    try:
        articles = gdelt.fetch_articles(query, max_records=NEWS_MAX_HEADLINES)
    except gdelt.GdeltRateLimitError as exc:
        _news_rate_limit_streak += 1
        ttl = min(
            NEWS_TTL_SECONDS,
            NEWS_ERROR_TTL_SECONDS
            * (2 ** min(
                _news_rate_limit_streak - 1,
                NEWS_RATE_LIMIT_MAX_DOUBLINGS,
            )),
        )
        _news_rate_limit_until = time.monotonic() + ttl
        log.warning(
            "GDELT rate-limited for %s (source streak %d) — holding requests "
            "%.0fs so the per-IP throttle can lift: %s",
            thesis_id, _news_rate_limit_streak, ttl, exc,
        )
        return (
            _news_payload(
                "rate_limited",
                query,
                note=f"gdelt unavailable: {type(exc).__name__}",
                retry_after_seconds=int(ttl),
            ),
            ttl,
        )
    except Exception as exc:  # noqa: BLE001 — preserve source state in the 200
        log.warning(
            "GDELT fetch failed for %s: %s: %s",
            thesis_id, type(exc).__name__, exc,
        )
        return (
            _news_payload(
                "unavailable",
                query,
                note=f"gdelt unavailable: {type(exc).__name__}",
                retry_after_seconds=int(NEWS_ERROR_TTL_SECONDS),
            ),
            NEWS_ERROR_TTL_SECONDS,
        )

    _news_rate_limit_streak = 0
    _news_rate_limit_until = 0.0
    headlines: list[dict[str, Any]] = [
        {
            "title": article.title,
            "url": article.url,
            "seendate": article.seendate,
            "domain": article.domain,
        }
        for article in articles[:NEWS_MAX_HEADLINES]
    ]
    status = "ok" if headlines else "no_matches"
    return _news_payload(status, query, articles=headlines), NEWS_TTL_SECONDS


def _store_news_cache(
    key: tuple[str, str],
    payload: dict[str, Any],
    ttl: float,
) -> None:
    """Store one bounded query result after pruning expired entries."""
    now = time.monotonic()
    for expired_key, (expires_at, _value) in list(_news_cache.items()):
        if expires_at <= now:
            _news_cache.pop(expired_key, None)
    if key not in _news_cache and len(_news_cache) >= NEWS_CACHE_MAX_ENTRIES:
        evict = min(_news_cache, key=lambda candidate: _news_cache[candidate][0])
        _news_cache.pop(evict)
    _news_cache[key] = (now + ttl, payload)


def _fetch_and_cache_news_sync(
    thesis_id: str,
    book: dict[str, Any],
    focused_query: Optional[str],
    cache_key: tuple[str, str],
) -> dict[str, Any]:
    """Single-flight GDELT fetch with atomic cache and cooldown state."""
    # WHY one process-wide lock: GDELT throttles by source IP. Letting focused
    # queries race can stampede upstream, and a concurrent success can erase a
    # 429 cooldown after another request sets it. Rechecking the cache inside
    # the lock also collapses concurrent calls for the same exact query.
    with _news_fetch_lock:
        now = time.monotonic()
        cached = _news_cache.get(cache_key)
        if cached and cached[0] > now:
            cached_payload = dict(cached[1])
            cached_payload["cache_hit"] = True
            return cached_payload

        payload, ttl = _fetch_news_sync(thesis_id, book, focused_query)
        _store_news_cache(cache_key, payload, ttl)
        return payload


@router.get("/news/{thesis_id}")
async def get_thesis_news(
    thesis_id: str,
    query: Optional[str] = Query(default=None),
    _svc: None = Depends(require_service_token),
) -> JSONResponse:
    """Return status-rich GDELT headlines for a standing or focused query."""
    path = _book_path(thesis_id)
    if path is None:
        raise HTTPException(
            status_code=404, detail=f"No book for thesis {thesis_id!r}",
        )
    try:
        book = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Book {thesis_id!r} is unreadable: {exc}",
        )

    focused_query = query.strip() if query is not None else None
    if focused_query is not None and not 5 <= len(focused_query) <= 500:
        raise HTTPException(
            status_code=422,
            detail="query must be between 5 and 500 characters after trimming",
        )
    resolved_query = focused_query or _gdelt_query_for_book(book)
    cache_key = (thesis_id, resolved_query or "")
    payload = await asyncio.to_thread(
        _fetch_and_cache_news_sync,
        thesis_id,
        book,
        focused_query,
        cache_key,
    )
    return JSONResponse(content=payload, media_type="application/json")


@router.get("/structure/{thesis_id}")
async def get_thesis_structure(
    thesis_id: str,
    _svc: None = Depends(require_service_token),
) -> JSONResponse:
    """Causal structure (nodes + edges) for a thesis book, builder format.

    WHY: the v3 snapshot push carries only nodeStates keyed by id — no
    edges, labels, mechanisms or positions — so Dialectic cannot draw the
    DAG from pushes alone. This read serves the authored structure via the
    same builder serializer the deep-editing surface uses, x/y included
    (persisted positions or the phase-column fallback), so the client
    never invents a layout.

    Node `state` here is the book file's authoring-time state; live state
    is the snapshot's nodeStates and the client overlays it.

    Explicit JSONResponse for the same reason as /snapshot: the SPA
    catch-all answers unknown paths with 200 + HTML.
    """
    path = _book_path(thesis_id)
    if path is None:
        raise HTTPException(
            status_code=404, detail=f"No book for thesis {thesis_id!r}",
        )
    try:
        cfg = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"Book {thesis_id!r} is unreadable: {exc}",
        )
    from web.routes.builder import _engine_to_builder_format
    return JSONResponse(
        content=_engine_to_builder_format(cfg, thesis_id),
        media_type="application/json",
    )
