"""Shared fixtures for Dialectic unit tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from models import (
    Message,
    Room,
    User,
    Thread,
    Memory,
    SpeakerType,
    MessageType,
    MemoryScope,
    MemoryStatus,
)


# ── Reusable IDs ──

ROOM_ID = uuid4()
THREAD_ID = uuid4()
USER_A_ID = uuid4()
USER_B_ID = uuid4()


# ── Factory helpers ──


def make_message(
    content: str = "Hello",
    speaker_type: SpeakerType = SpeakerType.HUMAN,
    message_type: MessageType = MessageType.TEXT,
    user_id=None,
    sequence: int = 1,
    is_deleted: bool = False,
) -> Message:
    """Create a Message with sensible defaults."""
    return Message(
        id=uuid4(),
        thread_id=THREAD_ID,
        sequence=sequence,
        created_at=datetime.now(timezone.utc),
        speaker_type=speaker_type,
        user_id=user_id or USER_A_ID,
        message_type=message_type,
        content=content,
        is_deleted=is_deleted,
    )


def make_room(**overrides) -> Room:
    """Create a Room with sensible defaults."""
    defaults = dict(
        id=ROOM_ID,
        created_at=datetime.now(timezone.utc),
        token="test-room-token",
        name="Test Room",
        global_ontology=None,
        global_rules=None,
    )
    defaults.update(overrides)
    return Room(**defaults)


def make_user(
    display_name: str = "Alice",
    aggression_level: float = 0.5,
    metaphysics_tolerance: float = 0.5,
    style_modifier: str | None = None,
    custom_instructions: str | None = None,
    user_id=None,
) -> User:
    """Create a User with sensible defaults."""
    return User(
        id=user_id or uuid4(),
        created_at=datetime.now(timezone.utc),
        display_name=display_name,
        aggression_level=aggression_level,
        metaphysics_tolerance=metaphysics_tolerance,
        style_modifier=style_modifier,
        custom_instructions=custom_instructions,
    )


def make_thread(**overrides) -> Thread:
    """Create a Thread with sensible defaults."""
    defaults = dict(
        id=THREAD_ID,
        room_id=ROOM_ID,
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Thread(**defaults)


def make_memory(
    key: str = "test-fact",
    content: str = "Some remembered fact",
    **overrides,
) -> Memory:
    """Create a Memory with sensible defaults."""
    defaults = dict(
        id=uuid4(),
        room_id=ROOM_ID,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        version=1,
        scope=MemoryScope.ROOM,
        key=key,
        content=content,
        created_by_user_id=USER_A_ID,
        status=MemoryStatus.ACTIVE,
    )
    defaults.update(overrides)
    return Memory(**defaults)


# ── Pytest fixtures ──


@pytest.fixture
def room():
    return make_room()


@pytest.fixture
def thread():
    return make_thread()


@pytest.fixture
def user_alice():
    return make_user(display_name="Alice", user_id=USER_A_ID)


@pytest.fixture
def user_bob():
    return make_user(display_name="Bob", user_id=USER_B_ID)


@pytest.fixture
def users(user_alice, user_bob):
    return [user_alice, user_bob]
