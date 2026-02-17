# operations.py — Core domain operations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from models import (
    Thread, Message, Event, EventType, ThreadForkedPayload
)


async def fork_thread(
    db,
    room_id: UUID,
    source_thread_id: UUID,
    fork_after_message_id: UUID,
    forking_user_id: UUID,
    title: Optional[str] = None
) -> Thread:
    """
    Create a new thread branching from source_thread at the specified message.
    """
    memory_version = await db.fetchval(
        "SELECT COALESCE(MAX(version), 0) FROM memories WHERE room_id = $1",
        room_id
    )

    new_thread_id = uuid4()
    now = datetime.utcnow()

    thread = Thread(
        id=new_thread_id,
        room_id=room_id,
        created_at=now,
        parent_thread_id=source_thread_id,
        fork_point_message_id=fork_after_message_id,
        fork_memory_version=memory_version,
        title=title
    )

    event = Event(
        id=uuid4(),
        timestamp=now,
        event_type=EventType.THREAD_FORKED,
        room_id=room_id,
        thread_id=new_thread_id,
        user_id=forking_user_id,
        payload=ThreadForkedPayload(
            new_thread_id=new_thread_id,
            parent_thread_id=source_thread_id,
            fork_point_message_id=fork_after_message_id,
            fork_memory_version=memory_version,
            title=title
        ).model_dump()
    )

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        event.id, event.timestamp, event.event_type.value,
        event.room_id, event.thread_id, event.user_id, event.payload
    )

    await db.execute(
        """INSERT INTO threads (id, room_id, created_at, parent_thread_id,
                                fork_point_message_id, fork_memory_version, title)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        thread.id, thread.room_id, thread.created_at, thread.parent_thread_id,
        thread.fork_point_message_id, thread.fork_memory_version, thread.title
    )

    return thread


async def get_thread_messages(
    db,
    thread_id: UUID,
    include_ancestry: bool = True
) -> list[Message]:
    """
    Get all messages visible to a thread, including inherited messages from ancestors.
    """
    thread = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )

    if not thread:
        raise ValueError(f"Thread {thread_id} not found")

    messages = []

    if include_ancestry and thread['parent_thread_id']:
        ancestor_messages = await get_thread_messages(
            db,
            thread['parent_thread_id'],
            include_ancestry=True
        )

        fork_point_seq = await db.fetchval(
            "SELECT sequence FROM messages WHERE id = $1",
            thread['fork_point_message_id']
        )

        messages = [m for m in ancestor_messages if m.sequence <= fork_point_seq]

    own_messages = await db.fetch(
        """SELECT * FROM messages
           WHERE thread_id = $1 AND NOT is_deleted
           ORDER BY sequence""",
        thread_id
    )

    messages.extend([Message(**dict(m)) for m in own_messages])

    return messages
