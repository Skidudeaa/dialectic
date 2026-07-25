"""
Contracts for ConnectionManager when one user holds several connections.

WHY this file exists: the registry used to keep a `(user_id, room_id) ->
Connection` index holding exactly ONE connection per user per room, while
`_rooms` held them all. A second tab overwrote the first tab's entry and
closing *either* tab deleted the shared key, so the surviving tab kept
receiving broadcasts while every directed send to it silently failed.

These tests drive the real connect()/disconnect() flow rather than seeding
`_rooms` directly — the bug lived in the transitions, so a fixture that
pre-seeded the end state would have passed against the broken code.
"""

from uuid import uuid4

import pytest

from transport.websocket import Connection, ConnectionManager, OutboundMessage


class FakeWebSocket:
    """Records what was sent; can be told to fail like a closed socket."""

    def __init__(self, name="ws"):
        self.name = name
        self.sent = []
        self.fail_with = None

    async def send_text(self, payload: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(payload)

    def types(self) -> list[str]:
        import json
        return [json.loads(p)["type"] for p in self.sent]


class SilentlyClosed(Exception):
    """Stringifies to '' — the shape that produced blank warning logs."""


def msg(type_="ping"):
    return OutboundMessage(type=type_, payload={})


@pytest.mark.asyncio
async def test_second_tab_still_receives_directed_sends_after_first_closes():
    """The original bug, end to end."""
    mgr = ConnectionManager()
    room_id, user_id = uuid4(), uuid4()

    tab_a = FakeWebSocket("a")
    tab_b = FakeWebSocket("b")
    conn_a = await mgr.connect(tab_a, user_id, room_id)
    await mgr.connect(tab_b, user_id, room_id)

    # Close the FIRST tab — under the old index this deleted the key that
    # had been overwritten to point at tab B.
    await mgr.disconnect(conn_a)

    assert mgr.is_user_connected(user_id, room_id) is True
    delivered = await mgr.send_to_user(user_id, room_id, msg("llm_done"))

    assert delivered is True
    assert "llm_done" in tab_b.types()


@pytest.mark.asyncio
async def test_directed_send_reaches_every_tab():
    mgr = ConnectionManager()
    room_id, user_id = uuid4(), uuid4()

    tab_a, tab_b = FakeWebSocket("a"), FakeWebSocket("b")
    await mgr.connect(tab_a, user_id, room_id)
    await mgr.connect(tab_b, user_id, room_id)

    assert await mgr.send_to_user(user_id, room_id, msg("llm_streaming")) is True
    assert "llm_streaming" in tab_a.types()
    assert "llm_streaming" in tab_b.types()


@pytest.mark.asyncio
async def test_send_to_user_is_false_when_user_has_no_connections():
    mgr = ConnectionManager()
    assert await mgr.send_to_user(uuid4(), uuid4(), msg()) is False


@pytest.mark.asyncio
async def test_user_joined_announced_only_for_first_connection():
    """A second tab is not a join event for the other participant."""
    mgr = ConnectionManager()
    room_id = uuid4()
    watcher_id, user_id = uuid4(), uuid4()

    watcher = FakeWebSocket("watcher")
    await mgr.connect(watcher, watcher_id, room_id)

    await mgr.connect(FakeWebSocket("a"), user_id, room_id)
    await mgr.connect(FakeWebSocket("b"), user_id, room_id)

    assert watcher.types().count("user_joined") == 1


@pytest.mark.asyncio
async def test_user_left_announced_only_when_last_connection_closes():
    mgr = ConnectionManager()
    room_id = uuid4()
    watcher_id, user_id = uuid4(), uuid4()

    watcher = FakeWebSocket("watcher")
    await mgr.connect(watcher, watcher_id, room_id)

    conn_a = await mgr.connect(FakeWebSocket("a"), user_id, room_id)
    conn_b = await mgr.connect(FakeWebSocket("b"), user_id, room_id)

    await mgr.disconnect(conn_a)
    assert watcher.types().count("user_left") == 0, "still present in the other tab"

    await mgr.disconnect(conn_b)
    assert watcher.types().count("user_left") == 1


@pytest.mark.asyncio
async def test_room_users_deduplicates_multi_tab_user():
    mgr = ConnectionManager()
    room_id, user_id = uuid4(), uuid4()

    await mgr.connect(FakeWebSocket("a"), user_id, room_id)
    await mgr.connect(FakeWebSocket("b"), user_id, room_id)

    assert mgr.get_room_users(room_id) == [user_id]
    assert len(mgr.get_user_connections(user_id, room_id)) == 2


@pytest.mark.asyncio
async def test_broadcast_evicts_dead_socket_and_logs_it(caplog):
    mgr = ConnectionManager()
    room_id = uuid4()
    live_id, dead_id = uuid4(), uuid4()

    live = FakeWebSocket("live")
    dead = FakeWebSocket("dead")
    await mgr.connect(live, live_id, room_id)
    await mgr.connect(dead, dead_id, room_id)
    dead.fail_with = SilentlyClosed()

    with caplog.at_level("WARNING"):
        await mgr.broadcast(room_id, msg("message_created"))

    # Failure is diagnosable even though str(exc) is empty.
    assert "SilentlyClosed" in caplog.text

    # And the dead socket is gone rather than retried forever.
    assert mgr.is_user_connected(dead_id, room_id) is False
    assert mgr.get_room_users(room_id) == [live_id]
    assert "message_created" in live.types()


@pytest.mark.asyncio
async def test_failed_directed_send_evicts_only_that_connection():
    mgr = ConnectionManager()
    room_id, user_id = uuid4(), uuid4()

    good, bad = FakeWebSocket("good"), FakeWebSocket("bad")
    await mgr.connect(good, user_id, room_id)
    await mgr.connect(bad, user_id, room_id)
    bad.fail_with = SilentlyClosed()

    # One tab dead, one alive -> still counts as delivered.
    assert await mgr.send_to_user(user_id, room_id, msg("llm_done")) is True
    assert len(mgr.get_user_connections(user_id, room_id)) == 1
    assert "llm_done" in good.types()


def test_removal_is_by_identity_not_dataclass_equality():
    """
    Connection is a dataclass, so `==` is field-by-field. Two connections
    that happen to compare equal must not both be dropped when one closes.
    """
    mgr = ConnectionManager()
    room_id, user_id = uuid4(), uuid4()
    shared_ws = FakeWebSocket("shared")

    first = Connection(websocket=shared_ws, user_id=user_id, room_id=room_id)
    twin = Connection(
        websocket=shared_ws,
        user_id=user_id,
        room_id=room_id,
        connected_at=first.connected_at,
    )
    assert first == twin, "precondition: these are equal but distinct objects"

    mgr._rooms[room_id] = [first, twin]
    mgr._remove_connection(first)

    remaining = mgr.get_user_connections(user_id, room_id)
    assert len(remaining) == 1
    assert remaining[0] is twin
