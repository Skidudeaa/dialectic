"""
In-process pub/sub bus for live price ticks.

WHY: The coordinator's tick loop already fetches prices and commits
snapshots under a per-thesis lock. When a price changes during commit,
we have everything needed to push a diff-only payload to WS clients —
but the fan-out path doesn't exist yet. MarketTicker still polls.

This bus fills the gap: coordinator publishes `price.tick` payloads
per-thesis on commit; WS manager subscribes per-connection and forwards
to clients. Target end-to-end latency is <500ms fetch-to-pixel.

DESIGN:
- Per-thesis channels keyed by thesis_id. A publish to "iran-hormuz-graph"
  only reaches subscribers of that thesis — no cross-thesis bleed.
- Each subscriber owns an asyncio.Queue (bounded, default 64 frames). If
  the subscriber falls behind, we DROP the newest frame and log a warning
  rather than block the publisher. Live tape > lossless replay.
- No replay on late subscribe: a subscriber that joins after a publish
  does NOT get a backfill. This is intentional — the bus carries a live
  tape, not an event log.

This module is intentionally stdlib-only. No external broker.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import AsyncIterator, Dict, Optional, Set

log = logging.getLogger(__name__)

# WHY: 64 frames is "a few ticks' worth" at the default tick cadence. The
# goal isn't buffering — a slow client should drop and resync via the next
# snapshot bootstrap, not accumulate stale frames.
DEFAULT_QUEUE_MAXSIZE = 64


class _Subscription:
    """Internal per-subscriber record — a bounded queue plus identity."""

    __slots__ = ("token", "thesis_id", "queue", "dropped")

    def __init__(self, token: int, thesis_id: str, maxsize: int) -> None:
        self.token = token
        self.thesis_id = thesis_id
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0


class LiveBus:
    """Asyncio in-process pub/sub, per-thesis channels.

    WHY an object (not module-level state): tests need isolated buses so
    one test's leftover subscribers don't bleed into another. A singleton
    is provided via get_live_bus() for runtime use.
    """

    def __init__(self, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._queue_maxsize = queue_maxsize
        # thesis_id -> set of _Subscription
        self._channels: Dict[str, Set[_Subscription]] = {}
        # token -> _Subscription for O(1) unsubscribe
        self._by_token: Dict[int, _Subscription] = {}
        self._lock = asyncio.Lock()
        self._token_seq = itertools.count(1)

    # ──────────────────────────────────────────────────────────────────
    # PUBLISH
    # ──────────────────────────────────────────────────────────────────

    async def publish(self, thesis_id: str, payload: dict) -> int:
        """Fan out `payload` to every subscriber of `thesis_id`.

        Returns the number of subscribers the frame was delivered to
        (useful for debug/metrics; callers may ignore).

        NEVER raises on slow subscribers. If a subscriber's queue is full,
        the frame is dropped for that subscriber and a warning is logged.
        Publish-with-no-subscribers is a no-op.
        """
        # WHY: Snapshot the subscriber set under the lock, then deliver
        # outside the lock. Delivery is put_nowait so we don't need to
        # hold the lock across awaits anyway — but a concurrent subscribe
        # adding to the set mid-iteration would race.
        async with self._lock:
            subs = list(self._channels.get(thesis_id, ()))

        if not subs:
            return 0

        delivered = 0
        for sub in subs:
            try:
                sub.queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:
                sub.dropped += 1
                # WHY: Log on every drop — an overwhelmed client is a
                # signal worth surfacing. Rate-limiting is the WS layer's
                # problem, not ours.
                log.warning(
                    "live_bus: dropped frame for thesis=%s token=%d (dropped=%d queue=%d/%d)",
                    thesis_id, sub.token, sub.dropped,
                    sub.queue.qsize(), self._queue_maxsize,
                )
        return delivered

    # ──────────────────────────────────────────────────────────────────
    # SUBSCRIBE / UNSUBSCRIBE
    # ──────────────────────────────────────────────────────────────────

    async def subscribe(
        self, thesis_id: str, queue_maxsize: Optional[int] = None,
    ) -> "tuple[int, AsyncIterator[dict]]":
        """Register a subscriber for `thesis_id`; return (token, async iterator).

        Usage:
            token, stream = await bus.subscribe("iran-hormuz-graph")
            try:
                async for frame in stream:
                    ...forward to WS...
            finally:
                await bus.unsubscribe(token)

        The iterator yields published payloads in order. It never terminates
        on its own — callers must unsubscribe and break out when the
        connected WS closes.
        """
        maxsize = queue_maxsize if queue_maxsize is not None else self._queue_maxsize
        async with self._lock:
            token = next(self._token_seq)
            sub = _Subscription(token=token, thesis_id=thesis_id, maxsize=maxsize)
            self._channels.setdefault(thesis_id, set()).add(sub)
            self._by_token[token] = sub

        async def _stream() -> AsyncIterator[dict]:
            # WHY: We yield whatever is in the queue. A sentinel None is
            # posted on unsubscribe to break the loop cleanly without
            # requiring callers to wrap the loop in cancellation handlers.
            while True:
                frame = await sub.queue.get()
                if frame is None:
                    return
                yield frame

        return token, _stream()

    async def unsubscribe(self, token: int) -> None:
        """Tear down subscription `token` and break the iterator.

        Idempotent — unsubscribing an unknown or already-removed token is
        a no-op (the normal case on double-close from a WS cleanup handler).
        """
        async with self._lock:
            sub = self._by_token.pop(token, None)
            if sub is None:
                return
            channel = self._channels.get(sub.thesis_id)
            if channel is not None:
                channel.discard(sub)
                if not channel:
                    del self._channels[sub.thesis_id]

        # WHY: Post a sentinel AFTER removing from the registry so any
        # concurrent publish() can't enqueue new frames behind the None.
        # If the queue was full, put_nowait would raise — we guarantee
        # the sentinel lands by draining one slot first.
        try:
            sub.queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                sub.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                # Give up — the iterator will hang on get() but the caller's
                # await task will be cancelled by WS shutdown in practice.
                log.warning("live_bus: could not post sentinel for token=%d", token)

    # ──────────────────────────────────────────────────────────────────
    # SHUTDOWN / INTROSPECTION
    # ──────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Tear down all subscriptions. Call on app shutdown."""
        async with self._lock:
            tokens = list(self._by_token.keys())
        for tok in tokens:
            await self.unsubscribe(tok)

    def subscriber_count(self, thesis_id: Optional[str] = None) -> int:
        """Return # subscribers for a thesis, or total if thesis_id is None.

        Non-async — safe to call from sync inspection paths. Races with
        concurrent sub/unsub are benign: returns an approximate count.
        """
        if thesis_id is None:
            return sum(len(c) for c in self._channels.values())
        return len(self._channels.get(thesis_id, ()))


# ──────────────────────────────────────────────────────────────────────
# SINGLETON
# ──────────────────────────────────────────────────────────────────────

_singleton: Optional[LiveBus] = None


def get_live_bus() -> LiveBus:
    """Return the process-wide LiveBus.

    WHY a function (not a module-level constant): tests need to swap the
    singleton or reset it between runs. Callers should prefer this
    function over constructing LiveBus() directly.
    """
    global _singleton
    if _singleton is None:
        _singleton = LiveBus()
    return _singleton


def reset_live_bus_for_tests() -> None:
    """Clear the singleton — used only in tests."""
    global _singleton
    _singleton = None
