"""Focused contracts for two-user WebSocket collaboration safety."""

import asyncio

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import api.main as main_mod
import operations
import transport.handlers as handlers_mod
from api.attachments import AttachmentBindError
from memory.cross_session import CrossSessionMemoryManager
from llm.orchestrator import LLMOrchestrator
from llm.prompts import AssembledPrompt
from models import Message, MessageType, SpeakerType, Thread
from tests.conftest import make_room, make_thread
from transport.handlers import MessageHandler, _llm_done_payload, _message_type_from_payload
from transport.redis_manager import RedisConnectionManager
from transport.websocket import Connection, MessageTypes


class RecordingConnections:
    def __init__(self):
        self.broadcasts = []
        self.direct = []

    async def broadcast(self, room_id, message, exclude_user=None):
        self.broadcasts.append((room_id, message, exclude_user))

    async def send_to_user(self, user_id, room_id, message):
        self.direct.append((user_id, room_id, message))
        return True


def make_handler(db=None, memory=None, llm=None):
    db = db or SimpleNamespace()
    connections = RecordingConnections()
    handler = MessageHandler(
        db=db,
        connection_manager=connections,
        memory_manager=memory or SimpleNamespace(),
        llm_orchestrator=llm or SimpleNamespace(),
    )
    return handler, connections


class FakeTransaction:
    """asyncpg Connection.transaction() stand-in: commit/rollback are no-ops."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def make_send_db(thread_id, *, display_name="Amo", member_count=1):
    """db mock for the _handle_send_message happy path (insert + user lookup)."""
    return SimpleNamespace(
        fetchval=AsyncMock(side_effect=[thread_id, member_count]),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}, {"display_name": display_name}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )


def make_attachment_row(attachment_id, room_id, user_id, message_id):
    """An attachments-table row, as bind_attachment_to_message returns it."""
    return {
        "id": attachment_id,
        "room_id": room_id,
        "message_id": message_id,
        "uploader_user_id": user_id,
        "kind": "image",
        "mime": "image/png",
        "bytes": 10,
        "sha256": "a" * 64,
        "width": 3,
        "height": 2,
        "original_name": "chart.png",
        "storage_path": "x/aa/y.png",
        "created_at": datetime.now(timezone.utc),
    }


def make_connection(room_id=None, user_id=None, thread_id=None):
    return Connection(
        websocket=SimpleNamespace(),
        room_id=room_id or uuid4(),
        user_id=user_id or uuid4(),
        thread_id=thread_id,
    )


def test_message_type_prefers_canonical_field_and_accepts_legacy_field():
    assert _message_type_from_payload({"message_type": "question", "type": "claim"}) is MessageType.QUESTION
    assert _message_type_from_payload({"type": "claim"}) is MessageType.CLAIM
    assert _message_type_from_payload({}) is MessageType.TEXT


@pytest.mark.asyncio
async def test_send_message_uses_validated_payload_thread_and_canonical_type():
    room_id = uuid4()
    thread_id = uuid4()
    db = SimpleNamespace(
        fetchval=AsyncMock(side_effect=[thread_id, 1]),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}, {"display_name": "Amo"}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )
    memory = SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4))
    handler, _ = make_handler(db=db, memory=memory)
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()
    conn = make_connection(room_id=room_id)

    await handler._handle_send_message(conn, {
        "content": "Is this the branch?",
        "message_type": "question",
        "type": "claim",
        "thread_id": str(thread_id),
    })

    assert conn.thread_id == thread_id
    insert_args = db.fetchrow.await_args_list[0].args
    assert insert_args[2] == thread_id
    assert insert_args[6] == MessageType.QUESTION.value
    handler._trigger_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_with_attachment_ids_binds_and_broadcasts_attachments(monkeypatch):
    room_id = uuid4()
    thread_id = uuid4()
    attachment_id = uuid4()
    conn = make_connection(room_id=room_id)
    db = make_send_db(thread_id)
    memory = SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4))
    handler, connections = make_handler(db=db, memory=memory)
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()

    async def fake_bind(db_conn, *, room_id, user_id, attachment_id, message_id):
        return make_attachment_row(attachment_id, room_id, user_id, message_id)

    bind = AsyncMock(side_effect=fake_bind)
    monkeypatch.setattr(handlers_mod, "bind_attachment_to_message", bind)

    await handler._handle_send_message(conn, {
        "content": "look at this",
        "thread_id": str(thread_id),
        "attachment_ids": [str(attachment_id)],
    })

    bind.assert_awaited_once()
    bind_kwargs = bind.await_args.kwargs
    assert bind_kwargs["room_id"] == room_id
    assert bind_kwargs["user_id"] == conn.user_id
    assert bind_kwargs["attachment_id"] == attachment_id

    broadcast = connections.broadcasts[-1][1]
    # Bound to the message the send minted, and carried on the broadcast.
    assert bind_kwargs["message_id"] == UUID(broadcast.payload["id"])
    attachments = broadcast.payload["attachments"]
    assert [a["id"] for a in attachments] == [str(attachment_id)]
    assert attachments[0]["message_id"] == broadcast.payload["id"]
    assert attachments[0]["url"] == f"/attachments/{attachment_id}"
    handler._trigger_llm.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_content_is_accepted_when_attachments_ride_along(monkeypatch):
    room_id = uuid4()
    thread_id = uuid4()
    attachment_id = uuid4()
    conn = make_connection(room_id=room_id)
    db = make_send_db(thread_id)
    memory = SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.4))
    handler, connections = make_handler(db=db, memory=memory)
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()

    async def fake_bind(db_conn, *, room_id, user_id, attachment_id, message_id):
        return make_attachment_row(attachment_id, room_id, user_id, message_id)

    monkeypatch.setattr(
        handlers_mod, "bind_attachment_to_message", AsyncMock(side_effect=fake_bind)
    )

    await handler._handle_send_message(conn, {
        "content": "",
        "thread_id": str(thread_id),
        "attachment_ids": [str(attachment_id)],
    })

    broadcast = connections.broadcasts[-1][1]
    assert broadcast.payload["content"] == ""
    assert [a["id"] for a in broadcast.payload["attachments"]] == [str(attachment_id)]


@pytest.mark.asyncio
async def test_empty_content_without_attachments_is_still_dropped():
    handler, connections = make_handler()
    conn = make_connection()

    await handler._handle_send_message(conn, {"content": "   "})

    assert connections.broadcasts == []
    assert connections.direct == []


@pytest.mark.asyncio
async def test_bind_failure_sends_error_to_sender_and_broadcasts_nothing(monkeypatch):
    room_id = uuid4()
    thread_id = uuid4()
    attachment_id = uuid4()
    conn = make_connection(room_id=room_id)
    # Only the thread validation and the insert run before the bind refuses.
    db = SimpleNamespace(
        fetchval=AsyncMock(return_value=thread_id),
        fetchrow=AsyncMock(side_effect=[{"sequence": 7}]),
        execute=AsyncMock(),
        transaction=lambda: FakeTransaction(),
    )
    handler, connections = make_handler(db=db)
    handler._trigger_push_notifications = AsyncMock()
    handler._trigger_llm = AsyncMock()
    monkeypatch.setattr(
        handlers_mod,
        "bind_attachment_to_message",
        AsyncMock(side_effect=AttachmentBindError(404, "Attachment not found")),
    )

    await handler._handle_send_message(conn, {
        "content": "look at this",
        "thread_id": str(thread_id),
        "attachment_ids": [str(attachment_id)],
    })

    assert connections.broadcasts == []
    handler._trigger_push_notifications.assert_not_awaited()
    handler._trigger_llm.assert_not_awaited()
    assert connections.direct[-1][2].type == MessageTypes.ERROR
    assert "Attachment not found" in connections.direct[-1][2].payload["error"]


@pytest.mark.asyncio
async def test_switch_thread_rejects_foreign_room_thread():
    original_thread = uuid4()
    db = SimpleNamespace(fetchval=AsyncMock(return_value=None))
    handler, connections = make_handler(db=db)
    conn = make_connection(thread_id=original_thread)

    await handler._handle_switch_thread(conn, {"thread_id": str(uuid4())})

    assert conn.thread_id == original_thread
    assert connections.direct[-1][2].type == MessageTypes.ERROR
    assert "not found in this room" in connections.direct[-1][2].payload["error"]


@pytest.mark.asyncio
async def test_typing_events_emit_new_and_legacy_fields_with_display_name():
    db = SimpleNamespace(fetchrow=AsyncMock(return_value={"display_name": "Dan"}))
    handler, connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_typing_start(conn, {})
    await handler._handle_typing_stop(conn, {})

    started = connections.broadcasts[0][1].payload
    stopped = connections.broadcasts[1][1].payload
    assert started == {
        "user_id": str(conn.user_id),
        "typing": True,
        "is_typing": True,
        "display_name": "Dan",
    }
    assert stopped["typing"] is False
    assert stopped["is_typing"] is False
    assert stopped["display_name"] == "Dan"


@pytest.mark.asyncio
async def test_fork_accepts_legacy_message_key_and_emits_complete_thread(monkeypatch):
    room_id = uuid4()
    source_thread_id = uuid4()
    fork_message_id = uuid4()
    new_thread_id = uuid4()
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    visible_message = Message(
        id=fork_message_id,
        thread_id=source_thread_id,
        sequence=3,
        created_at=now,
        speaker_type=SpeakerType.HUMAN,
        user_id=user_id,
        message_type=MessageType.TEXT,
        content="fork here",
    )
    new_thread = Thread(
        id=new_thread_id,
        room_id=room_id,
        created_at=now,
        parent_thread_id=source_thread_id,
        fork_point_message_id=fork_message_id,
        title="Branch",
    )
    db = SimpleNamespace(fetchval=AsyncMock(side_effect=[source_thread_id, room_id]))
    monkeypatch.setattr(operations, "get_thread_messages", AsyncMock(return_value=[visible_message]))
    fork_mock = AsyncMock(return_value=new_thread)
    monkeypatch.setattr(operations, "fork_thread", fork_mock)
    handler, connections = make_handler(db=db)
    conn = make_connection(room_id=room_id, user_id=user_id, thread_id=source_thread_id)

    await handler._handle_fork_thread(conn, {
        "source_thread_id": str(source_thread_id),
        "fork_message_id": str(fork_message_id),
        "title": "Branch",
    })

    fork_mock.assert_awaited_once()
    event = connections.broadcasts[-1][1]
    assert event.type == MessageTypes.THREAD_CREATED
    assert event.payload["room_id"] == str(room_id)
    assert event.payload["message_count"] == 0
    assert event.payload["created_by_user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_fork_rejects_message_from_another_room(monkeypatch):
    room_id = uuid4()
    source_thread_id = uuid4()
    db = SimpleNamespace(
        fetchval=AsyncMock(side_effect=[source_thread_id, uuid4()]),
    )
    fork_mock = AsyncMock()
    monkeypatch.setattr(operations, "fork_thread", fork_mock)
    handler, connections = make_handler(db=db)
    conn = make_connection(room_id=room_id, thread_id=source_thread_id)

    await handler._handle_fork_thread(conn, {
        "source_thread_id": str(source_thread_id),
        "fork_after_message_id": str(uuid4()),
    })

    fork_mock.assert_not_awaited()
    assert "not found in this room" in connections.direct[-1][2].payload["error"]


@pytest.mark.asyncio
async def test_memory_edit_is_scoped_to_connected_room():
    db = SimpleNamespace(fetchval=AsyncMock(return_value=uuid4()))
    memory = SimpleNamespace(edit_memory=AsyncMock())
    handler, connections = make_handler(db=db, memory=memory)
    conn = make_connection()

    await handler._handle_edit_memory(conn, {
        "memory_id": str(uuid4()),
        "content": "foreign edit",
    })

    memory.edit_memory.assert_not_awaited()
    assert "not found in this room" in connections.direct[-1][2].payload["error"]


def test_llm_done_payload_contains_authoritative_persisted_fields():
    thread_id = uuid4()
    created_at = datetime.now(timezone.utc).isoformat()
    payload = _llm_done_payload(thread_id, {
        "message_id": str(uuid4()),
        "content": "answer",
        "model_used": "claude-sonnet-5",
        "truncated": False,
        "sequence": 9,
        "created_at": created_at,
        "speaker_type": SpeakerType.LLM_PROVOKER.value,
        "message_type": MessageType.COUNTEREXAMPLE.value,
    })
    assert payload["sequence"] == 9
    assert payload["created_at"] == created_at
    assert payload["speaker_type"] == SpeakerType.LLM_PROVOKER.value
    assert payload["message_type"] == MessageType.COUNTEREXAMPLE.value


@pytest.mark.asyncio
async def test_orchestrator_done_event_uses_persisted_message_metadata():
    persisted = Message(
        id=uuid4(),
        thread_id=uuid4(),
        sequence=12,
        created_at=datetime.now(timezone.utc),
        speaker_type=SpeakerType.LLM_PROVOKER,
        user_id=None,
        message_type=MessageType.COUNTEREXAMPLE,
        content="counterpoint",
    )

    class FakeRouter:
        async def stream(self, _request):
            yield "attempt", {"provider": "anthropic", "model": "claude-sonnet-5"}
            yield "token", {"token": "counterpoint"}

    orchestrator = LLMOrchestrator(SimpleNamespace())
    orchestrator._get_cross_session_context = AsyncMock(return_value=None)
    orchestrator._get_identity_context = AsyncMock(return_value=(None, None))
    orchestrator.prompt_builder.build = MagicMock(return_value=AssembledPrompt("system", []))
    orchestrator._get_router = MagicMock(return_value=FakeRouter())
    orchestrator._persist_response = AsyncMock(return_value=persisted)
    orchestrator._schedule_self_memory_extraction = MagicMock()
    room = make_room(provoker_model="claude-sonnet-5")
    thread = make_thread(id=persisted.thread_id)

    events = [
        event
        async for event in orchestrator.stream_response(
            room=room,
            thread=thread,
            users=[],
            messages=[],
            memories=[],
            use_provoker=True,
        )
    ]

    done = next(data for event_type, data in events if event_type == "done")
    assert done["sequence"] == persisted.sequence
    assert done["created_at"] == persisted.created_at.isoformat()
    assert done["speaker_type"] == SpeakerType.LLM_PROVOKER.value
    assert done["message_type"] == MessageType.COUNTEREXAMPLE.value


@pytest.mark.asyncio
async def test_commitment_created_payload_has_timestamp_and_confidence_history(monkeypatch):
    room_id = uuid4()
    user_id = uuid4()
    commitment_id = uuid4()
    created_at = datetime.now(timezone.utc)

    class FakeCommitmentManager:
        def __init__(self, _db):
            pass

        async def create_commitment(self, **kwargs):
            return {
                "id": commitment_id,
                "room_id": room_id,
                "claim": kwargs["claim"],
                "resolution_criteria": kwargs["resolution_criteria"],
                "category": kwargs["category"],
                "deadline": None,
                "created_at": created_at,
                "initial_confidence": kwargs["initial_confidence"],
            }

    monkeypatch.setattr(handlers_mod, "CommitmentManager", FakeCommitmentManager)
    db = SimpleNamespace(fetchrow=AsyncMock(return_value={"display_name": "Amo"}))
    handler, connections = make_handler(db=db)
    conn = make_connection(room_id=room_id, user_id=user_id)

    await handler._handle_create_commitment(conn, {
        "claim": "Ship by Friday",
        "resolution_criteria": "Deployment is live",
        "initial_confidence": 0.7,
    })

    payload = connections.broadcasts[-1][1].payload
    assert payload["created_at"] == created_at.isoformat()
    assert payload["confidence_history"] == [{
        "user_id": str(user_id),
        "display_name": "Amo",
        "confidence": 0.7,
        "reasoning": None,
        "recorded_at": created_at.isoformat(),
    }]


@pytest.mark.asyncio
async def test_confidence_update_is_broadcast_to_all_collaborators(monkeypatch):
    room_id = uuid4()
    user_id = uuid4()
    commitment_id = uuid4()
    recorded_at = datetime.now(timezone.utc)

    class FakeCommitmentManager:
        def __init__(self, _db):
            pass

        async def record_confidence(self, **kwargs):
            return {
                "confidence": kwargs["confidence"],
                "reasoning": kwargs["reasoning"],
                "recorded_at": recorded_at,
            }

    monkeypatch.setattr(handlers_mod, "CommitmentManager", FakeCommitmentManager)
    db = SimpleNamespace(fetchval=AsyncMock(return_value=room_id))
    handler, connections = make_handler(db=db)
    conn = make_connection(room_id=room_id, user_id=user_id)

    await handler._handle_record_confidence(conn, {
        "commitment_id": str(commitment_id),
        "confidence": 0.72,
        "reasoning": "new evidence",
    })

    event = connections.broadcasts[-1][1]
    assert event.type == MessageTypes.COMMITMENT_CONFIDENCE_UPDATED
    assert event.payload == {
        "commitment_id": str(commitment_id),
        "user_id": str(user_id),
        "confidence": 0.72,
        "reasoning": "new evidence",
        "recorded_at": recorded_at.isoformat(),
    }


@pytest.mark.asyncio
async def test_background_persona_owns_a_fresh_pool_connection():
    foreground_db = object()
    background_db = object()

    class AcquireContext:
        async def __aenter__(self):
            return background_db

        async def __aexit__(self, *_args):
            return False

    pool = SimpleNamespace(acquire=lambda: AcquireContext())
    llm = SimpleNamespace(db_pool=pool)
    handler, _ = make_handler(db=foreground_db, llm=llm)
    handler._run_persona_response = AsyncMock()

    await handler._trigger_persona_response(
        uuid4(), uuid4(), [], [], "trigger",
    )

    assert handler._run_persona_response.await_args.args[0] is background_db


@pytest.mark.asyncio
async def test_redis_listener_does_not_spin_before_first_subscription():
    class EmptyPubSub:
        def __init__(self):
            self.listen_calls = 0

        def listen(self):
            self.listen_calls += 1

            async def iterator():
                if False:
                    yield None

            return iterator()

    manager = RedisConnectionManager()
    manager._pubsub = EmptyPubSub()
    task = asyncio.create_task(manager._listen())
    await asyncio.sleep(0.02)
    task.cancel()
    await task

    assert manager._pubsub.listen_calls == 0


def test_presence_ttl_expires_stale_rows_but_live_socket_wins():
    now = datetime.now(timezone.utc)
    stale = now - timedelta(seconds=91)
    assert main_mod._effective_presence_status(
        "online", stale, locally_connected=False, now=now,
    ) == "offline"
    assert main_mod._effective_presence_status(
        "online", stale, locally_connected=True, now=now,
    ) == "online"
    assert main_mod._effective_presence_status(
        "away", now, locally_connected=False, now=now,
    ) == "away"


@pytest.mark.asyncio
async def test_handshake_thread_must_belong_to_room():
    room_id = uuid4()
    thread_id = uuid4()
    db = SimpleNamespace(fetchval=AsyncMock(return_value=None))
    assert await main_mod._websocket_thread_belongs_to_room(db, None, room_id)
    assert not await main_mod._websocket_thread_belongs_to_room(db, thread_id, room_id)
    db.fetchval.assert_awaited_once_with(
        "SELECT id FROM threads WHERE id = $1 AND room_id = $2",
        thread_id,
        room_id,
    )


@pytest.mark.asyncio
async def test_automatic_cross_room_search_requires_personal_promotion():
    db = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    manager = CrossSessionMemoryManager(db)
    manager._embedder = SimpleNamespace(
        embed=AsyncMock(return_value=SimpleNamespace(vector=[0.1, 0.2]))
    )

    await manager.search_user_memories(
        user_id=uuid4(),
        query="shared concept",
        current_room_id=uuid4(),
        include_current_room=False,
        require_global_scope=True,
    )

    query = db.fetch.await_args.args[0]
    assert "user_memory_promotions" in query
    assert "ump.user_id = $1" in query
    assert "m.scope = 'global'" not in query
    assert db.fetch.await_args.args[-1] is True

    search_mock = AsyncMock(return_value=[])
    manager.search_user_memories = search_mock
    await manager.get_relevant_cross_room_memories(
        user_id=uuid4(),
        current_room_id=uuid4(),
        context="shared concept",
    )
    assert search_mock.await_args.kwargs["require_global_scope"] is True


@pytest.mark.asyncio
async def test_auto_inject_collections_require_personal_promotion():
    db = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    manager = CrossSessionMemoryManager(db)
    assert await manager.get_auto_inject_memories(uuid4()) == []
    query = db.fetch.await_args.args[0]
    assert "user_memory_promotions" in query
    assert "ump.user_id = $1" in query
    assert "JOIN room_memberships" in query
    assert "rm.user_id = $1" in query
    assert "m.scope = 'global'" not in query
