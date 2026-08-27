"""F-002 (protocol_state snapshot) and F-003 (real synthesis memory)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from llm.protocol_manager import ProtocolManager
from models import ProtocolState, ProtocolStatus, ProtocolType
from tests.test_collaboration_contracts import make_handler
from transport.websocket import Connection, MessageTypes


def _active(thread_id, room_id, phase=1):
    return ProtocolState(
        id=uuid4(), thread_id=thread_id, room_id=room_id,
        protocol_type=ProtocolType.STEELMAN, status=ProtocolStatus.ACTIVE,
        current_phase=phase, total_phases=4, invoked_by_user_id=None,
        invoked_at=datetime.now(timezone.utc), config={},
    )


def _conn(room_id, thread_id):
    return Connection(websocket=None, user_id=uuid4(), room_id=room_id, thread_id=thread_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_protocol", [True, False])
async def test_switch_thread_sends_protocol_state_snapshot(has_protocol):
    room_id, thread_id = uuid4(), uuid4()
    db = SimpleNamespace(fetchval=AsyncMock(return_value=thread_id))
    handler, conns = make_handler(db=db)
    proto = _active(thread_id, room_id) if has_protocol else None
    handler.protocols.get_active = AsyncMock(return_value=proto)

    await handler._handle_switch_thread(_conn(room_id, None), {"thread_id": str(thread_id)})

    msgs = [m for _, _, m in conns.direct if m.type == MessageTypes.PROTOCOL_STATE]
    assert len(msgs) == 1
    handler.protocols.get_active.assert_awaited_once_with(thread_id)
    if has_protocol:
        assert msgs[0].payload["protocol"]["id"] == str(proto.id)
        assert msgs[0].payload["protocol"]["current_phase"] == 1
    else:
        assert msgs[0].payload["protocol"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("has_message", [True, False])
async def test_conclude_persists_final_message_as_synthesis(has_message):
    room_id, thread_id, protocol_id, msg_id = uuid4(), uuid4(), uuid4(), uuid4()
    proto_row = {"protocol_type": "steelman", "thread_id": thread_id, "invoked_by_user_id": None}
    final = {"id": msg_id, "content": "## Verdict\nSurvived."} if has_message else None
    db = SimpleNamespace(fetchrow=AsyncMock(side_effect=[proto_row, final]))
    memory = SimpleNamespace(add_memory=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    handler, conns = make_handler(db=db, memory=memory)
    handler.protocols.conclude = AsyncMock(return_value=SimpleNamespace(
        id=protocol_id, protocol_type=ProtocolType.STEELMAN))

    await handler._conclude_protocol(room_id, protocol_id)

    kw = memory.add_memory.await_args.kwargs
    if has_message:
        assert kw["content"] == "## Verdict\nSurvived."
        assert kw["source_message_id"] == msg_id
    else:
        assert "synthesis pending" in kw["content"]
        assert kw["source_message_id"] is None
    assert any(m.type == MessageTypes.PROTOCOL_CONCLUDED for _, m, _ in conns.broadcasts)
