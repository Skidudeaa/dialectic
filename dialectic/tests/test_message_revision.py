"""
Contracts for editing, deleting and reacting to messages.

The load-bearing property here is authorship: edit and delete must reach only
the caller's own messages, and a message belonging to someone else — or to
another room — must be indistinguishable from one that does not exist, so these
handlers cannot be used to probe for what exists elsewhere.

Reactions deliberately do NOT carry that restriction: reacting to what the other
person said is the entire point of the feature.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.test_collaboration_contracts import make_connection, make_handler
from models import EventType
from transport.websocket import MessageTypes


def make_db(*, message_row=None, reaction_rows=None):
    """
    Fake db whose fetchrow answers the ownership-scoped lookup.

    `message_row=None` models every rejection case at once — not yours, not in
    this room, or not real — because the handler's query cannot tell them apart
    by design.
    """
    db = SimpleNamespace()
    db.fetchrow = AsyncMock(return_value=message_row)
    db.fetch = AsyncMock(return_value=reaction_rows or [])
    db.execute = AsyncMock()
    db.fetchval = AsyncMock(return_value=None)
    return db


def owned_row(is_deleted=False):
    return {
        "id": uuid4(),
        "thread_id": uuid4(),
        "user_id": uuid4(),
        "speaker_type": "human",
        "is_deleted": is_deleted,
    }


def sent_errors(conn):
    return [c for c in getattr(conn.websocket, "sent", [])]


@pytest.mark.asyncio
async def test_edit_rejects_a_message_the_caller_does_not_own():
    """No UPDATE, and no broadcast, when the ownership-scoped lookup misses."""
    db = make_db(message_row=None)
    handler, connections = make_handler(db=db)
    conn = make_connection()
    handler._send_error = AsyncMock()

    await handler._handle_edit_message(
        conn, {"message_id": str(uuid4()), "content": "overwritten"}
    )

    db.execute.assert_not_awaited()
    assert connections.broadcasts == []
    handler._send_error.assert_awaited_once()
    # Generic on purpose — "not yours" would confirm the message exists.
    assert "not found" in handler._send_error.await_args.args[1].lower()


@pytest.mark.asyncio
async def test_revision_lookup_is_scoped_by_author_and_room_in_sql():
    """
    The rejection tests above feed the handler a miss, so they would still pass
    if the ownership clause were dropped from the query. This one constrains the
    query itself: authorship and room are checked in the same statement, bound
    to the connection's own identity rather than anything from the payload.
    """
    row = owned_row()
    db = make_db(message_row=row)
    handler, _connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_delete_message(conn, {"message_id": str(row["id"])})

    sql, *params = db.fetchrow.await_args.args
    assert "m.user_id = $3" in sql
    assert "t.room_id = $2" in sql
    # The caller's identity comes from the socket, never the payload.
    assert params[1] == conn.room_id
    assert params[2] == conn.user_id


@pytest.mark.asyncio
async def test_delete_rejects_a_message_the_caller_does_not_own():
    db = make_db(message_row=None)
    handler, connections = make_handler(db=db)
    conn = make_connection()
    handler._send_error = AsyncMock()

    await handler._handle_delete_message(conn, {"message_id": str(uuid4())})

    db.execute.assert_not_awaited()
    assert connections.broadcasts == []
    handler._send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_requires_content_and_does_not_double_as_delete():
    """
    An emptied edit must be refused rather than quietly deleting the message —
    otherwise the edit path becomes an undocumented second delete path that
    skips the confirmation the UI puts in front of a real one.
    """
    db = make_db(message_row=owned_row())
    handler, connections = make_handler(db=db)
    conn = make_connection()
    handler._send_error = AsyncMock()

    await handler._handle_edit_message(conn, {"message_id": str(uuid4()), "content": "   "})

    db.execute.assert_not_awaited()
    assert connections.broadcasts == []
    handler._send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_of_own_message_updates_and_broadcasts():
    row = owned_row()
    db = make_db(message_row=row)
    handler, connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_edit_message(
        conn, {"message_id": str(row["id"]), "content": "the corrected text"}
    )

    update_sql = db.execute.await_args_list[0].args[0]
    assert "UPDATE messages" in update_sql and "edited_at" in update_sql

    assert len(connections.broadcasts) == 1
    _room, message, _exclude = connections.broadcasts[0]
    assert message.type == MessageTypes.MESSAGE_EDITED
    assert message.payload["content"] == "the corrected text"
    # The marker the client uses to render "edited".
    assert message.payload["edited_at"]


@pytest.mark.asyncio
async def test_edit_logs_a_lowercase_message_edited_event():
    """The events INSERT hardcoded the literal "MESSAGE_EDITED" (uppercase)
    instead of EventType.MESSAGE_EDITED.value. Every other writer of this
    column uses the enum, which is lowercase, and replay/engine.py only
    recognizes "message_edited" — the uppercase literal made every edit
    silently invisible to replay."""
    row = owned_row()
    db = make_db(message_row=row)
    handler, _connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_edit_message(
        conn, {"message_id": str(row["id"]), "content": "the corrected text"}
    )

    event_sql, *event_params = db.execute.await_args_list[1].args
    assert "INSERT INTO events" in event_sql
    assert event_params[2] == EventType.MESSAGE_EDITED.value
    assert event_params[2] == "message_edited"


@pytest.mark.asyncio
async def test_delete_is_soft():
    """
    A hard DELETE would strip the parent out from under any reply pointing at
    it and rewrite an append-only history. Every read path already filters
    is_deleted, so flipping the flag is sufficient.
    """
    row = owned_row()
    db = make_db(message_row=row)
    handler, connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_delete_message(conn, {"message_id": str(row["id"])})

    update_sql = db.execute.await_args_list[0].args[0]
    assert "is_deleted = TRUE" in update_sql
    assert "DELETE FROM messages" not in update_sql

    assert connections.broadcasts[0][1].type == MessageTypes.MESSAGE_DELETED


@pytest.mark.asyncio
async def test_delete_logs_a_lowercase_message_deleted_event():
    """Sibling of test_edit_logs_a_lowercase_message_edited_event — the
    delete path hardcoded "MESSAGE_DELETED" the same way."""
    row = owned_row()
    db = make_db(message_row=row)
    handler, _connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_delete_message(conn, {"message_id": str(row["id"])})

    event_sql, *event_params = db.execute.await_args_list[1].args
    assert "INSERT INTO events" in event_sql
    assert event_params[2] == EventType.MESSAGE_DELETED.value
    assert event_params[2] == "message_deleted"


@pytest.mark.asyncio
async def test_editing_an_already_deleted_message_is_refused():
    db = make_db(message_row=owned_row(is_deleted=True))
    handler, _connections = make_handler(db=db)
    conn = make_connection()
    handler._send_error = AsyncMock()

    await handler._handle_edit_message(
        conn, {"message_id": str(uuid4()), "content": "resurrect"}
    )

    db.execute.assert_not_awaited()
    handler._send_error.assert_awaited_once()


@pytest.mark.asyncio
async def test_reacting_is_not_restricted_to_your_own_messages():
    """The reaction lookup scopes by room only — reacting to the other person
    is the point of the feature."""
    row = {"id": uuid4(), "thread_id": uuid4()}
    db = make_db(message_row=row)
    handler, connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_add_reaction(
        conn, {"message_id": str(row["id"]), "emoji": "🔥"}
    )

    lookup_sql = db.fetchrow.await_args.args[0]
    assert "t.room_id = $2" in lookup_sql
    # Crucially absent: any constraint on m.user_id.
    assert "m.user_id = $3" not in lookup_sql

    insert_sql = db.execute.await_args.args[0]
    assert "INSERT INTO message_reactions" in insert_sql
    # Re-reacting must not error or double-count.
    assert "ON CONFLICT" in insert_sql and "DO NOTHING" in insert_sql

    assert connections.broadcasts[0][1].type == MessageTypes.REACTION_UPDATED


@pytest.mark.asyncio
async def test_reaction_broadcast_carries_the_full_set_not_a_delta():
    """
    A client that missed an event still converges, because every broadcast is
    the complete grouped state for that message.
    """
    row = {"id": uuid4(), "thread_id": uuid4()}
    user_a, user_b = uuid4(), uuid4()
    db = make_db(
        message_row=row,
        reaction_rows=[
            {"emoji": "🔥", "user_id": user_a, "display_name": "Amo"},
            {"emoji": "🔥", "user_id": user_b, "display_name": "Dan"},
            {"emoji": "👍", "user_id": user_a, "display_name": "Amo"},
        ],
    )
    handler, connections = make_handler(db=db)
    conn = make_connection()

    await handler._handle_add_reaction(conn, {"message_id": str(row["id"]), "emoji": "🔥"})

    payload = connections.broadcasts[0][1].payload
    grouped = {r["emoji"]: r for r in payload["reactions"]}
    assert set(grouped) == {"🔥", "👍"}
    assert grouped["🔥"]["user_names"] == ["Amo", "Dan"]
    assert grouped["👍"]["user_ids"] == [str(user_a)]


@pytest.mark.asyncio
async def test_reaction_emoji_is_length_bounded():
    """Without a bound this is arbitrary per-message text storage."""
    db = make_db(message_row={"id": uuid4(), "thread_id": uuid4()})
    handler, connections = make_handler(db=db)
    conn = make_connection()
    handler._send_error = AsyncMock()

    await handler._handle_add_reaction(
        conn, {"message_id": str(uuid4()), "emoji": "x" * 200}
    )

    db.execute.assert_not_awaited()
    assert connections.broadcasts == []
    handler._send_error.assert_awaited_once()
