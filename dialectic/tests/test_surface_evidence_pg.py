"""Persisted source conversations through both message doors, in a rolled-back test room."""
import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.auth.dependencies import AuthenticatedUser
from api.main import SendMessageRequest, get_messages, send_message
from llm.orchestrator import _inherit_anchor
from llm.prompts import _refs_suffix
from models import Message
from proposal_intake import ProposalMetadataError, validate_reading_quotes, validate_refs
from transport.handlers import MessageHandler
from transport.websocket import Connection

TEST_DATABASE_URL = os.environ.get("DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test")
BODY = "# A shared source\n\nTankers **wait outside** the strait.\n\nThe forecast is uncertain.\n"
QUOTE = "Tankers wait outside the strait."
CHECKLIST = "- [ ] Check departures\n- [x] Check freight"
CHECKLIST_QUOTE = "Check departures Check freight"


@pytest_asyncio.fixture
async def scene(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SimpleNamespace]:
    # No skip: this feature needs the PostgreSQL round trip to qualify.
    db = await asyncpg.connect(TEST_DATABASE_URL)
    await db.set_type_codec("jsonb", schema="pg_catalog", encoder=lambda value: json.dumps(value, default=str), decoder=json.loads)
    await db.set_type_codec("json", schema="pg_catalog", encoder=lambda value: json.dumps(value, default=str), decoder=json.loads)
    tx = db.transaction()
    await tx.start()
    room, thread, amo, dan = (uuid4() for _ in range(4))
    token = uuid4().hex
    now = datetime.now(timezone.utc)
    await db.execute("INSERT INTO rooms (id,created_at,token,name) VALUES ($1,$2,$3,'Source room')", room, now, token)
    await db.execute("INSERT INTO threads (id,room_id,created_at) VALUES ($1,$2,$3)", thread, room, now)
    for user_id, name in ((amo, "Amo"), (dan, "Dan")):
        await db.execute("INSERT INTO users (id,created_at,display_name) VALUES ($1,$2,$3)", user_id, now, name)
        await db.execute("INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)", room, user_id, now)
    reading = await db.fetchval(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source)
           VALUES ($1,'https://example.com/strait','Strait report',$2,'The source','test') RETURNING id""", room, BODY,
    )
    monkeypatch.setattr("transport.handlers.schedule_claim_check", lambda **kwargs: None)
    monkeypatch.setattr("transport.handlers.annotator_enabled", lambda: False)
    monkeypatch.setattr("transport.handlers.commitment_detection_enabled", lambda: False)
    manager = SimpleNamespace(broadcast=AsyncMock(), send_to_user=AsyncMock())
    handler = MessageHandler(db, manager, SimpleNamespace(compute_message_novelty=AsyncMock(return_value=0.5)), None)
    handler._trigger_llm = AsyncMock()
    handler._trigger_push_notifications = AsyncMock()
    context = SimpleNamespace(db=db, room=room, thread=thread, amo=amo, dan=dan, token=token,
                              reading=reading, manager=manager, handler=handler)
    try:
        yield context
    finally:
        await tx.rollback()
        await db.close()


def source_ref(scene: SimpleNamespace, **fields: str) -> dict:
    return {"entity": "reading_items", "id": str(scene.reading), "label": "Strait report", **fields}


async def post(scene: SimpleNamespace, door: str, user: UUID, content: str, *, parent: UUID | None = None,
               refs: list[dict] | None = None) -> Message:
    if door == "rest":
        result = await send_message(
            scene.thread, SendMessageRequest(content=content, references_message_id=parent,
                                             metadata={"refs": refs} if refs else None),
            token=scene.token, current_user=AuthenticatedUser(user, "test@example.com", True, "Reader"), db=scene.db,
        )
        ident = result.id
    else:
        conn = Connection(websocket=AsyncMock(), user_id=user, room_id=scene.room, thread_id=scene.thread)
        await scene.handler._handle_send_message(conn, {
            "content": content, "thread_id": str(scene.thread),
            "client_request_id": "receipt-test",
            **({"references_message_id": str(parent)} if parent else {}), **({"refs": refs} if refs else {}),
        })
        payload = scene.manager.broadcast.call_args.args[1].payload
        assert payload["client_request_id"] == "receipt-test"
        ident = UUID(payload["id"])
    return Message(**dict(await scene.db.fetchrow("SELECT * FROM messages WHERE id = $1", ident)))


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["rest", "websocket"])
async def test_quote_reply_reload_and_model_context(scene: SimpleNamespace, door: str) -> None:
    original = await post(scene, door, scene.amo, "This changes the timing.", refs=[source_ref(scene, quote=QUOTE)])
    expected = source_ref(scene, quote=QUOTE, content_sha256=hashlib.sha256(BODY.encode()).hexdigest())
    assert original.metadata["refs"] == [expected]
    # A source can change after Amo speaks. Dan still replies to the original evidence.
    await scene.db.execute("UPDATE reading_items SET content = 'A later version.' WHERE id = $1", scene.reading)
    reply = await post(scene, door, scene.dan, "I read the timing differently.", parent=original.id)
    assert reply.metadata["refs"] == [expected]
    assert reply.references_message_id == original.id
    history = await get_messages(scene.thread, token=scene.token, include_ancestry=True, limit=200,
                                 before_cursor=None, after_cursor=None, before_sequence=None, after_sequence=None, db=scene.db)
    assert [m.metadata["refs"] for m in history.messages] == [[expected], [expected]]
    assert _inherit_anchor(None, [original, reply])["refs"] == [expected]
    assert QUOTE in _refs_suffix(reply)
    if door == "websocket":
        assert scene.manager.broadcast.call_args.args[1].payload["metadata"]["refs"] == [expected]


@pytest.mark.asyncio
async def test_false_or_changed_quote_cannot_create_a_message(scene: SimpleNamespace) -> None:
    with pytest.raises(HTTPException) as error:
        await post(scene, "rest", scene.amo, "A claim", refs=[source_ref(scene, quote="Words the author never wrote")])
    assert error.value.status_code == 422
    assert await scene.db.fetchval("SELECT count(*) FROM messages WHERE thread_id = $1", scene.thread) == 0
    with pytest.raises(ProposalMetadataError, match="source changed"):
        await validate_reading_quotes(scene.db, scene.room, [source_ref(scene, quote=QUOTE, content_sha256="0" * 64)])


@pytest.mark.asyncio
async def test_quoted_reading_is_room_fenced(scene: SimpleNamespace) -> None:
    with pytest.raises(ProposalMetadataError, match="not in this room"):
        await validate_reading_quotes(scene.db, uuid4(), [source_ref(scene, quote=QUOTE)])


@pytest.mark.asyncio
@pytest.mark.parametrize("body,quote", [(BODY, QUOTE), (CHECKLIST, CHECKLIST_QUOTE)])
async def test_stored_revision_still_accepts_its_original_passage(scene: SimpleNamespace, body: str, quote: str) -> None:
    digest = hashlib.sha256(body.encode()).hexdigest()
    await scene.db.execute(
        """INSERT INTO reading_revisions (reading_id,room_id,capture_id,captured_by_user_id,source_url,
              capture_mode,content,content_sha256,captured_at)
           VALUES ($1,$2,$3,$4,'https://example.com/strait','article',$5,$6,now())""",
        scene.reading, scene.room, uuid4(), scene.amo, body, digest,
    )
    await scene.db.execute("UPDATE reading_items SET content = 'A new report' WHERE id = $1", scene.reading)
    original = await post(scene, "rest", scene.amo, "About the earlier report", refs=[source_ref(scene, quote=quote, content_sha256=digest)])
    assert original.metadata["refs"][0]["content_sha256"] == digest


@pytest.mark.asyncio
@pytest.mark.parametrize("door", ["rest", "websocket"])
@pytest.mark.parametrize("body", [
    CHECKLIST,
    "- [ ] Check **departures**\n\n- [x] Check freight",
    "> - [ ] Check departures\n>   - [X] Check freight",
    "1. [ ] Check departures\n2. [X]\tCheck freight",
    "- [ ] Check departures\n- [x] Check [freight](https://example.com)\n\n[x]: https://example.com",
])
async def test_task_list_selection_is_persisted_through_both_doors(scene: SimpleNamespace, door: str, body: str) -> None:
    await scene.db.execute("UPDATE reading_items SET content = $1 WHERE id = $2", body, scene.reading)
    expected = source_ref(scene, quote=CHECKLIST_QUOTE, content_sha256=hashlib.sha256(body.encode()).hexdigest())
    original = await post(scene, door, scene.amo, "About this checklist", refs=[expected])
    assert original.metadata["refs"] == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,visible,erased", [
    ("- \\[ ] Check departures\n- \\[x] Check freight", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    ("- `[ ]` Check departures\n- `[x]` Check freight", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    (f"```markdown\n{CHECKLIST}\n```", "- [ ] Check departures - [x] Check freight", CHECKLIST_QUOTE),
    ("[ ] Check departures\n\n[x] Check freight", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    ("-\n  [ ] Check departures\n-\n  [x] Check freight", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    ("- [ ]\n  Check departures\n- [x]\n  Check freight", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    ("<ul><li>[ ] Check departures</li><li>[x] Check freight</li></ul>", "[ ] Check departures [x] Check freight", CHECKLIST_QUOTE),
    ("- [ ] Start [x] marker\n- [x] Finish", "Start [x] marker Finish", "Start marker Finish"),
])
async def test_task_list_extraction_preserves_literal_markers(scene: SimpleNamespace, body: str, visible: str, erased: str) -> None:
    await scene.db.execute("UPDATE reading_items SET content = $1 WHERE id = $2", body, scene.reading)
    digest = hashlib.sha256(body.encode()).hexdigest()
    refs = [source_ref(scene, quote=visible, content_sha256=digest)]
    await validate_reading_quotes(scene.db, scene.room, refs)
    assert refs[0]["quote"] == visible
    assert refs[0]["content_sha256"] == digest
    with pytest.raises(ProposalMetadataError, match="does not match"):
        await validate_reading_quotes(scene.db, scene.room, [source_ref(scene, quote=erased, content_sha256=digest)])


@pytest.mark.asyncio
async def test_rejected_websocket_quote_returns_correlated_failure_without_storage(scene: SimpleNamespace) -> None:
    conn = Connection(websocket=AsyncMock(), user_id=scene.amo, room_id=scene.room, thread_id=scene.thread)
    await scene.handler._handle_send_message(conn, {
        "content": "Keep my draft", "client_request_id": "rejected-quote",
        "refs": [source_ref(scene, quote="This passage is not in the source")],
    })
    error = scene.manager.send_to_user.call_args.args[2].payload
    assert error["client_request_id"] == "rejected-quote"
    assert "does not match" in error["error"]
    scene.manager.broadcast.assert_not_called()
    assert await scene.db.fetchval("SELECT count(*) FROM messages WHERE thread_id = $1", scene.thread) == 0


@pytest.mark.parametrize("fields", [{"quote": "a" * 301}, {"content_sha256": "nope"}, {"quote": " "}])
def test_invalid_quote_metadata_is_rejected(fields: dict) -> None:
    with pytest.raises(ProposalMetadataError):
        validate_refs([{"entity": "reading_items", "id": str(uuid4()), "label": "Reading", **fields}])
