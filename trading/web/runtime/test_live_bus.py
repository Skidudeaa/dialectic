"""
Tests for LiveBus — in-process pub/sub for the live tape.

WHY: The bus is the single serialization point between coordinator commits
and WS fan-out. These tests verify the contracts stated in live_bus.py:
non-blocking publish, per-thesis isolation, bounded queues with drop-on-
overflow, idempotent unsubscribe, and "live tape, not replay" semantics.
"""

import asyncio

import pytest

from web.runtime.live_bus import LiveBus, get_live_bus, reset_live_bus_for_tests


@pytest.fixture
def bus():
    """Fresh bus per test — singletons leak state across tests."""
    reset_live_bus_for_tests()
    return LiveBus(queue_maxsize=4)


# ══════════════════════════════════════════════════════════════════════
# BASIC PUB/SUB
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop(bus):
    """Publish without any subscribers returns 0 and does not raise."""
    delivered = await bus.publish("iran-hormuz-graph", {"type": "price.tick"})
    assert delivered == 0
    # Still no subscribers — channel was never created
    assert bus.subscriber_count("iran-hormuz-graph") == 0


@pytest.mark.asyncio
async def test_two_subscribers_both_receive(bus):
    """Both subscribers on the same thesis receive every publish."""
    tok_a, stream_a = await bus.subscribe("iran-hormuz-graph")
    tok_b, stream_b = await bus.subscribe("iran-hormuz-graph")

    payload = {"type": "price.tick", "changes": {"brent": {"prev": 80, "curr": 82}}}
    delivered = await bus.publish("iran-hormuz-graph", payload)
    assert delivered == 2

    got_a = await asyncio.wait_for(stream_a.__anext__(), timeout=1.0)
    got_b = await asyncio.wait_for(stream_b.__anext__(), timeout=1.0)
    assert got_a == payload
    assert got_b == payload

    await bus.unsubscribe(tok_a)
    await bus.unsubscribe(tok_b)


# ══════════════════════════════════════════════════════════════════════
# SLOW SUBSCRIBER / DROP BEHAVIOR
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_slow_subscriber_drops_frames_past_cap(bus, caplog):
    """When a subscriber's queue fills, excess frames are dropped, not blocked."""
    tok, _stream = await bus.subscribe("iran-hormuz-graph")  # noqa: F841

    # queue_maxsize=4 on the fixture. Push 7 frames without consuming.
    with caplog.at_level("WARNING"):
        for i in range(7):
            await bus.publish("iran-hormuz-graph", {"i": i})

    # Publisher never blocks — it returns immediately every time.
    # 4 frames should be sitting in the queue; 3 should have been dropped.
    sub = bus._by_token[tok]
    assert sub.queue.qsize() == 4
    assert sub.dropped == 3
    # WARNING emitted on each drop
    drops = [r for r in caplog.records if "dropped frame" in r.getMessage()]
    assert len(drops) == 3

    await bus.unsubscribe(tok)


@pytest.mark.asyncio
async def test_publisher_never_blocks_on_full_queue(bus):
    """A full queue must not delay the publisher — hard latency requirement."""
    tok, _stream = await bus.subscribe("iran-hormuz-graph")  # noqa: F841
    # Fill past the cap. If publish() blocked, this would hang the test.
    async def fire_many():
        for i in range(100):
            await bus.publish("iran-hormuz-graph", {"i": i})
    await asyncio.wait_for(fire_many(), timeout=2.0)
    await bus.unsubscribe(tok)


# ══════════════════════════════════════════════════════════════════════
# UNSUBSCRIBE
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery(bus):
    """After unsubscribe, the subscriber receives no further frames."""
    tok, stream = await bus.subscribe("iran-hormuz-graph")
    await bus.publish("iran-hormuz-graph", {"i": 1})
    first = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    assert first == {"i": 1}

    await bus.unsubscribe(tok)

    # Iterator should terminate via sentinel (StopAsyncIteration)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1.0)

    # Subsequent publishes should not deliver to this token
    delivered = await bus.publish("iran-hormuz-graph", {"i": 2})
    assert delivered == 0
    assert bus.subscriber_count("iran-hormuz-graph") == 0


@pytest.mark.asyncio
async def test_unsubscribe_unknown_token_is_noop(bus):
    """Double-unsubscribe or unknown token must not raise."""
    await bus.unsubscribe(999999)  # never issued
    tok, _ = await bus.subscribe("t")
    await bus.unsubscribe(tok)
    # Second call is a no-op
    await bus.unsubscribe(tok)


# ══════════════════════════════════════════════════════════════════════
# CROSS-THESIS ISOLATION
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cross_thesis_isolation(bus):
    """A publish on one thesis never reaches subscribers of another."""
    tok_hormuz, stream_hormuz = await bus.subscribe("iran-hormuz-graph")
    tok_tariffs, stream_tariffs = await bus.subscribe("trump-tariffs-graph")

    delivered = await bus.publish("iran-hormuz-graph", {"source": "hormuz"})
    assert delivered == 1  # only the hormuz subscriber

    got = await asyncio.wait_for(stream_hormuz.__anext__(), timeout=1.0)
    assert got == {"source": "hormuz"}

    # Tariffs subscriber's queue is empty — assert without blocking.
    sub_tariffs = bus._by_token[tok_tariffs]
    assert sub_tariffs.queue.empty()

    await bus.unsubscribe(tok_hormuz)
    await bus.unsubscribe(tok_tariffs)


# ══════════════════════════════════════════════════════════════════════
# LATE-SUBSCRIBE SEMANTICS (LIVE TAPE, NOT REPLAY)
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_publish_then_subscribe_race_no_backfill(bus):
    """A subscriber joining after a publish gets no backfill — live tape only."""
    # Publish with nobody listening
    await bus.publish("iran-hormuz-graph", {"stale": True})
    await bus.publish("iran-hormuz-graph", {"stale": True, "i": 2})

    # Now subscribe
    tok, stream = await bus.subscribe("iran-hormuz-graph")

    # Next publish should be the first frame the subscriber sees.
    await bus.publish("iran-hormuz-graph", {"fresh": True})
    got = await asyncio.wait_for(stream.__anext__(), timeout=1.0)
    assert got == {"fresh": True}

    await bus.unsubscribe(tok)


# ══════════════════════════════════════════════════════════════════════
# CONCURRENT PUBLISHERS
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_publishers(bus):
    """Interleaved publishes from multiple tasks all land intact."""
    # Use a bus with plenty of headroom for this test — the fixture's cap
    # of 4 would force drops under concurrency.
    big_bus = LiveBus(queue_maxsize=512)
    tok, stream = await big_bus.subscribe("t")

    N_PUBLISHERS = 10
    N_PER = 20

    async def publisher(p_id: int) -> None:
        for i in range(N_PER):
            await big_bus.publish("t", {"p": p_id, "i": i})

    await asyncio.gather(*[publisher(i) for i in range(N_PUBLISHERS)])

    received = []
    for _ in range(N_PUBLISHERS * N_PER):
        frame = await asyncio.wait_for(stream.__anext__(), timeout=2.0)
        received.append(frame)

    assert len(received) == N_PUBLISHERS * N_PER
    # Each publisher's own stream should be in order
    for p_id in range(N_PUBLISHERS):
        per_p = [f["i"] for f in received if f["p"] == p_id]
        assert per_p == list(range(N_PER))

    await big_bus.unsubscribe(tok)


# ══════════════════════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_close_tears_down_all_subscriptions(bus):
    """bus.close() unsubscribes every subscriber and breaks every stream."""
    tok_a, stream_a = await bus.subscribe("t1")
    tok_b, stream_b = await bus.subscribe("t1")
    tok_c, stream_c = await bus.subscribe("t2")

    assert bus.subscriber_count() == 3

    await bus.close()

    assert bus.subscriber_count() == 0
    for stream in (stream_a, stream_b, stream_c):
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(stream.__anext__(), timeout=1.0)

    # Post-close publish is a no-op
    assert await bus.publish("t1", {"x": 1}) == 0


# ══════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════


def test_get_live_bus_is_singleton():
    """get_live_bus() returns the same instance across calls."""
    reset_live_bus_for_tests()
    a = get_live_bus()
    b = get_live_bus()
    assert a is b
    reset_live_bus_for_tests()
    c = get_live_bus()
    assert c is not a
