"""What the WebSocket send_message door accepts from a client — and what it
still refuses.

AMENDED 2026-08-16. This file used to assert the door accepted NO client
metadata at all, and its own docstring said what to do when that went red:
"the WS door has started accepting metadata and needs the SAME
proposal_intake gate the REST door already has — that is the signal this
file exists to raise, not a regression to silence." That is exactly what
happened, so the fence is rewritten rather than deleted.

The door now accepts ONE key, `tags`, validated by proposal_intake's
shared `validate_tags`. Tags ride the ordinary send because a tagged
message is still a message: it must broadcast to the other humans and
reach the participant, and the REST door does neither. A PROPOSAL smuggled
in a `metadata` blob is still ignored outright — that remains the REST
door's business, where an accept path and an acceptance stamp exist.

TG-C's brief was to find EVERY door where client-supplied message metadata
enters the system and gate each one with proposal_intake's shared
validator. The REST door (api/main.py:send_message) is gated —
tests/test_propose_surface_pg.py and tests/test_proposal_intake.py cover
it. This file is the other half of that brief: proof, not just a claim in
a report, that transport/handlers.py._handle_send_message never reads a
`metadata` key out of the inbound payload at all, so there is nothing
there to validate — adding a validation call to a door that ignores the
field it would guard would be dead code. The propose surface's
ProposeMenu component (frontend) therefore posts through the REST door
only; MessageInput's ordinary WS send is unchanged.

If this test ever goes red, the WS door has started accepting metadata and
needs the SAME proposal_intake gate the REST door already has — that is
the signal this file exists to raise, not a regression to silence.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from transport.handlers import MessageHandler
from transport.websocket import Connection


class RecordingConnections:
    def __init__(self):
        self.broadcasts = []
        self.direct = []

    async def broadcast(self, room_id, message, exclude_user=None):
        self.broadcasts.append((room_id, message, exclude_user))

    async def send_to_user(self, user_id, room_id, message):
        self.direct.append((user_id, room_id, message))
        return True


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def make_connection(room_id=None, user_id=None, thread_id=None):
    return Connection(
        websocket=SimpleNamespace(),
        room_id=room_id or uuid4(),
        user_id=user_id or uuid4(),
        thread_id=thread_id,
    )


@pytest.mark.asyncio
async def test_ws_send_message_ignores_a_client_supplied_metadata_field():
    room_id = uuid4()
    thread_id = uuid4()
    db = SimpleNamespace(
        fetchval=AsyncMock(side_effect=[thread_id, 1]),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}, {"display_name": "Amo"}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )
    memory = SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4))
    connections = RecordingConnections()
    handler = MessageHandler(
        db=db, connection_manager=connections,
        memory_manager=memory, llm_orchestrator=SimpleNamespace(),
    )
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()
    conn = make_connection(room_id=room_id)

    await handler._handle_send_message(conn, {
        "content": "sneaking a proposal in over the socket",
        "thread_id": str(thread_id),
        # A client-supplied proposal block — exactly what the REST door's
        # SendMessageRequest.metadata now validates and stores.
        "metadata": {"proposal": {"statement": "x", "confidence": 0.9, "deadline": "2099-01-01"}},
    })

    # The proposal is dropped on the floor: the metadata bound into the
    # INSERT is None, not the client's document.
    bound_metadata = db.fetchrow.await_args_list[0].args[-1]
    assert bound_metadata is None

    # And the broadcast — the first thing every OTHER connected client
    # would see — carries no metadata key either.
    broadcast_payload = connections.broadcasts[-1][1].payload
    assert "metadata" not in broadcast_payload


@pytest.mark.asyncio
async def test_ws_send_message_accepts_validated_tags():
    """The one key the door does take, stored AND broadcast.

    Broadcast matters as much as storage: without it a receiver sees an
    untagged message live and a tagged one only after a reload, which is
    the same defect references_message_id had.
    """
    room_id, thread_id = uuid4(), uuid4()
    db = SimpleNamespace(
        fetchval=AsyncMock(side_effect=[thread_id, 1]),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}, {"display_name": "Amo"}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )
    connections = RecordingConnections()
    handler = MessageHandler(
        db=db, connection_manager=connections,
        memory_manager=SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4)),
        llm_orchestrator=SimpleNamespace(),
    )
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()

    await handler._handle_send_message(make_connection(room_id=room_id), {
        "content": "the mention chips render behind the fold",
        "thread_id": str(thread_id),
        "tags": ["BUG", "bug", " meta "],
    })

    bound_metadata = db.fetchrow.await_args_list[0].args[-1]
    assert bound_metadata == {"tags": ["bug", "meta"]}, "normalised and deduped"
    assert connections.broadcasts[-1][1].payload["metadata"] == {"tags": ["bug", "meta"]}


@pytest.mark.asyncio
async def test_ws_send_message_refuses_an_unknown_tag():
    """A tag outside the vocabulary is an error, not a silently dropped field.

    Silently dropping it would let a client believe a message was filed
    under a category that does not exist — the message would be findable
    by nobody, which is the one thing the tag exists to prevent.
    """
    room_id, thread_id = uuid4(), uuid4()
    db = SimpleNamespace(
        fetchval=AsyncMock(side_effect=[thread_id, 1]),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}, {"display_name": "Amo"}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )
    connections = RecordingConnections()
    handler = MessageHandler(
        db=db, connection_manager=connections,
        memory_manager=SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4)),
        llm_orchestrator=SimpleNamespace(),
    )
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()
    conn = make_connection(room_id=room_id)
    handler._send_error = AsyncMock()

    await handler._handle_send_message(conn, {
        "content": "filed under a category nobody can search",
        "thread_id": str(thread_id),
        "tags": ["wishlist"],
    })

    handler._send_error.assert_awaited_once()
    assert "tag" in handler._send_error.await_args.args[1].lower()
    # Nothing was written and nothing was broadcast.
    assert db.fetchrow.await_count == 0
    assert connections.broadcasts == []
