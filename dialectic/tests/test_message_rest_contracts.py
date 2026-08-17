"""Persisted and live contracts for the REST message door."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.main as main_mod
from api.token_utils import extract_room_token
from api.auth.dependencies import AuthenticatedUser
from models import Message, MessageType, SpeakerType
from tests.conftest import make_room


ROOM_ID = UUID("00000000-0000-0000-0000-000000000501")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000502")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000503")
PARENT_ID = UUID("00000000-0000-0000-0000-000000000504")
USER_ID = UUID("00000000-0000-0000-0000-000000000505")
CREATED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
EDITED_AT = datetime(2026, 8, 15, 12, 5, tzinfo=timezone.utc)
OTHER_ROOM_ID = UUID("00000000-0000-0000-0000-000000000506")
OTHER_ROOM_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000507")


@pytest.fixture(autouse=True)
def clear_overrides() -> None:
    main_mod.app.dependency_overrides.clear()
    yield
    main_mod.app.dependency_overrides.clear()


def test_history_returns_reply_and_edit_coordinates() -> None:
    message = Message(
        id=MESSAGE_ID,
        thread_id=THREAD_ID,
        sequence=3,
        created_at=CREATED_AT,
        speaker_type=SpeakerType.HUMAN,
        user_id=USER_ID,
        message_type=MessageType.TEXT,
        content="edited reply",
        references_message_id=PARENT_ID,
        edited_at=EDITED_AT,
    )
    db = AsyncMock()

    async def fetchrow(query: str, *params: object) -> object:
        if "FROM threads WHERE id" in query:
            return {"id": THREAD_ID, "room_id": ROOM_ID}
        if "FROM rooms WHERE id" in query:
            return make_room(id=ROOM_ID, token="room-token").model_dump()
        raise AssertionError(f"Unexpected query: {query}")

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    db.fetch = AsyncMock(return_value=[message.model_dump()])

    async def db_dependency() -> AsyncIterator[AsyncMock]:
        yield db

    main_mod.app.dependency_overrides[main_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[extract_room_token] = lambda: "room-token"

    response = TestClient(main_mod.app).get(f"/threads/{THREAD_ID}/messages")
    assert response.status_code == 200
    body = response.json()["messages"][0]
    assert body["references_message_id"] == str(PARENT_ID)
    assert body["edited_at"] == EDITED_AT.isoformat().replace("+00:00", "Z")


class FakeTransaction:
    def __init__(self, db: "SendDB") -> None:
        self.db = db

    async def __aenter__(self) -> "FakeTransaction":
        self.db.transaction_entries += 1
        self.db.in_transaction = True
        self.db.event_inserted_in_transaction = False
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        if exc_info[0] is None:
            self.db.commits += 1
            self.db.event_inserted_before_last_commit = (
                self.db.event_inserted_in_transaction
            )
        self.db.in_transaction = False
        return False


class SendDB:
    def __init__(self, *, collide_once: bool = False) -> None:
        self.collide_once = collide_once
        self.insert_attempts = 0
        self.persisted_messages = 0
        self.transaction_entries = 0
        self.commits = 0
        self.in_transaction = False
        self.event_inserted_in_transaction = False
        self.event_inserted_before_last_commit = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def fetchrow(self, query: str, *params: object) -> object | None:
        if "FROM threads WHERE id" in query:
            return {"id": THREAD_ID, "room_id": ROOM_ID}
        if "FROM rooms WHERE id" in query:
            return make_room(id=ROOM_ID, token="room-token").model_dump()
        if "FROM room_memberships" in query:
            return {"member": True}
        if "INSERT INTO messages" in query:
            self.insert_attempts += 1
            if self.collide_once and self.insert_attempts == 1:
                raise asyncpg.UniqueViolationError("sequence collision")
            self.persisted_messages += 1
            return {"sequence": 7}
        if "SELECT display_name FROM users" in query:
            return {"display_name": "Amo"}
        raise AssertionError(f"Unexpected fetchrow: {query}")

    async def fetchval(self, query: str, *params: object) -> object | None:
        if "JOIN threads" in query and "WHERE m.id" in query:
            return OTHER_ROOM_ID if params[0] == OTHER_ROOM_MESSAGE_ID else ROOM_ID
        if "SELECT sequence FROM messages" in query:
            return 7
        raise AssertionError(f"Unexpected fetchval: {query}")

    async def execute(self, query: str, *params: object) -> str:
        if "INSERT INTO messages" in query:
            self.insert_attempts += 1
            if self.collide_once and self.insert_attempts == 1:
                raise asyncpg.UniqueViolationError("sequence collision")
            self.persisted_messages += 1
            return "INSERT 0 1"
        if "INSERT INTO events" in query:
            self.event_inserted_in_transaction = self.in_transaction
            return "INSERT 0 1"
        raise AssertionError(f"Unexpected execute: {query}")


def caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=USER_ID,
        email="amo@example.com",
        email_verified=True,
        display_name="Amo",
    )


async def send_with(
    db: SendDB,
    *,
    references_message_id: UUID | None = PARENT_ID,
) -> main_mod.MessageResponse:
    return await main_mod.send_message(
        thread_id=THREAD_ID,
        request=main_mod.SendMessageRequest(
            content="A persisted reply",
            references_message_id=references_message_id,
            metadata={"proposal": {
                "statement": "A testable move",
                "confidence": 0.6,
                "deadline": "2026-12-31",
            }},
        ),
        token="room-token",
        current_user=caller(),
        db=db,
    )


@pytest.mark.asyncio
async def test_rest_send_rejects_cross_room_reference() -> None:
    db = SendDB()
    with pytest.raises(HTTPException) as exc_info:
        await send_with(db, references_message_id=OTHER_ROOM_MESSAGE_ID)
    assert exc_info.value.status_code == 404
    assert db.persisted_messages == 0


@pytest.mark.asyncio
async def test_rest_send_retries_one_sequence_collision_and_broadcasts_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SendDB(collide_once=True)
    broadcast = AsyncMock()
    monkeypatch.setattr(main_mod.connection_manager, "broadcast", broadcast)

    response = await send_with(db)

    assert response.sequence == 7
    assert db.transaction_entries == 2
    assert db.event_inserted_before_last_commit is True
    broadcast.assert_awaited_once()
    outbound = broadcast.await_args.args[1]
    assert outbound.payload["references_message_id"] == str(PARENT_ID)
    assert outbound.payload["metadata"] == response.metadata


@pytest.mark.asyncio
async def test_broadcast_failure_does_not_turn_a_committed_send_into_a_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SendDB()
    broadcast = AsyncMock(side_effect=RuntimeError("socket fanout failed"))
    monkeypatch.setattr(main_mod.connection_manager, "broadcast", broadcast)

    response = await send_with(db, references_message_id=None)

    assert response.sequence == 7
    assert db.persisted_messages == 1
    assert db.commits == 1
    broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_message_context_rejects_a_soft_deleted_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncMock()

    async def fetchrow(query: str, *params: object) -> object | None:
        if "FROM threads WHERE id" in query:
            return {"id": THREAD_ID, "room_id": ROOM_ID}
        if "SELECT sequence FROM messages" in query:
            assert "NOT is_deleted" in query
            return None
        raise AssertionError(f"Unexpected query: {query}")

    db.fetchrow = AsyncMock(side_effect=fetchrow)
    monkeypatch.setattr(main_mod, "verify_room_token", AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.get_message_context(
            THREAD_ID,
            message_id=MESSAGE_ID,
            context=25,
            token="room-token",
            db=db,
        )
    assert exc_info.value.status_code == 404
