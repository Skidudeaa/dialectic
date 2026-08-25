"""
Real-Postgres contract for POST /rooms/{room_id}/field/marks — the door that
lets a HUMAN originate a Field mark.

WHY this door exists: Release 3 shipped review (confirm/contest/correct/
supersede/split/merge), which all act on a mark the inference engine proposed
first. Production shows the consequence exactly — 85 marks, every one
`origin='inferred'`, zero human reviews ever. A person could correct the
machine's reading and could not assert anything it had not thought of.

WHY real Postgres: two things here are properties of the DATABASE, not of
Python. The ON CONFLICT clause must match a PARTIAL unique index, which
Postgres refuses to infer unless the clause repeats the index's own WHERE —
and it fails by RAISING, not by skipping dedup. And `_subject_token` folds
`field` into the dedup key, which is the whole reason two highlights on
different passages of one message can coexist; nothing but a real insert
proves that.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/017_field_marks.sql
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.auth.dependencies import AuthenticatedUser
import api.field as field_api
from api.field import FieldMarkCreateRequest, create_field_mark
from field_marks import FIELD_RELATIONS, FieldSubjectRef, compute_dedup_key
from geo_scopes import insert_scope
from llm.tradingdesk_client import TradingDeskError

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, OTHER_ROOM = _uid(0xA01), _uid(0xA02)
THREAD, OTHER_THREAD = _uid(0xA03), _uid(0xA04)
AMO, STRANGER = _uid(0xA05), _uid(0xA06)
MSG_A, MSG_B, MSG_OTHER = _uid(0xA07), _uid(0xA08), _uid(0xA09)
TOKEN = "field-origination-token"
BASE = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
BOOK_ID = "hormuz-cascade"
NODE_ID = "shipping-chokepoint"
NODE_2_ID = "freight-rates"


class _DirectPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def row_id(mark) -> UUID:
    """`FieldMark.id` is the workspace-object form `field_mark:<uuid>`; the
    row's primary key is the bare uuid. Peeling it here rather than in five
    assertions keeps the prefix contract in one place."""
    return UUID(mark.id.split(":", 1)[1])


def caller(user_id=AMO):
    return AuthenticatedUser(
        user_id=user_id, email="amo@example.com",
        email_verified=True, display_name="Amo",
    )


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    if not await conn.fetchval("SELECT to_regclass('field_marks')"):
        await conn.close()
        pytest.skip("field_marks missing — run migrations/017_field_marks.sql")
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    tx = db.transaction()
    await tx.start()
    for room_id, token in ((ROOM, TOKEN), (OTHER_ROOM, "other-token")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            room_id, BASE, token, f"room-{room_id}",
        )
    for thread_id, room_id in ((THREAD, ROOM), (OTHER_THREAD, OTHER_ROOM)):
        await db.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,'Main')",
            thread_id, room_id, BASE,
        )
    for user_id, name in ((AMO, "Amo"), (STRANGER, "Stranger")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
            user_id, BASE, name,
        )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        ROOM, AMO, BASE,
    )
    # (thread_id, sequence) is UNIQUE — two messages in one thread need
    # distinct sequences, which is exactly what production does too.
    for seq, (msg_id, thread_id, content) in enumerate((
        (MSG_A, THREAD, "tanker rates moved before crude did, twice this month"),
        (MSG_B, THREAD, "that is a correlation, not a mechanism"),
        (MSG_OTHER, OTHER_THREAD, "a message in a room the caller cannot see"),
    ), start=1):
        await db.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at,
                   speaker_type, user_id, message_type, content)
               VALUES ($1,$2,$3,$4,'human',$5,'text',$6)""",
            msg_id, thread_id, seq, BASE, AMO, content,
        )
    yield db
    await tx.rollback()


@pytest_asyncio.fixture
async def causal_room(room, monkeypatch):
    """A bound room plus every scope-liveness state the causal door fences."""
    if not await room.fetchval("SELECT to_regclass('geo_scopes')"):
        pytest.skip("geo_scopes missing — run migrations/021_geo_scopes.sql")
    await room.execute(
        "UPDATE rooms SET linked_book_id = $1 WHERE id = $2", BOOK_ID, ROOM,
    )
    point = {"type": "Point", "coordinates": [56.25, 26.55]}
    common = {
        "room_id": ROOM,
        "subject": {"entity": "messages", "id": str(MSG_A)},
        "kind": "point",
        "geometry": point,
        "provenance": {"provider": "test", "acquisition": "adapter:test"},
        "now": BASE,
    }
    seeded = {
        "live": await insert_scope(
            room, **common, label="Hormuz evidence", authority="source_reported",
        ),
        "proposed": await insert_scope(
            room, **{
                **common,
                "provenance": {"provider": "test", "acquisition": "llm"},
            },
            label="Machine guess", authority="machine_proposed",
        ),
        "rejected": await insert_scope(
            room, **{
                **common,
                "provenance": {"provider": "human", "acquisition": "human"},
            },
            label="Rejected placement", authority="human_confirmed",
            confirmed_by=AMO, revision_action="reject",
        ),
        "expired": await insert_scope(
            room, **common, label="Expired evidence", authority="source_reported",
            expires_at=BASE - timedelta(seconds=1),
        ),
    }
    superseded_id = await insert_scope(
        room, **common, label="Retired evidence", authority="source_reported",
    )
    await insert_scope(
        room,
        **common,
        label="Replacement evidence",
        authority="source_reported",
        supersedes_id=superseded_id,
        revision_action="redraw",
    )
    seeded["superseded"] = superseded_id

    async def structure(path: str, **_kwargs):
        assert path == f"/api/bridge/structure/{BOOK_ID}"
        return {
            "id": BOOK_ID,
            "meta": {"title": "Hormuz Cascade"},
            "nodes": [
                {"id": NODE_ID, "label": "Shipping chokepoint"},
                {"id": NODE_2_ID, "label": "Freight rates"},
            ],
            "edges": [],
        }

    monkeypatch.setattr(
        field_api, "td", SimpleNamespace(service_get=structure), raising=False,
    )
    return room, seeded


def _request(**overrides):
    body = dict(
        relation="emerging_position",
        subjects=[FieldSubjectRef(entity="messages", id=str(MSG_A))],
        title="tanker rates lead crude",
        payload={},
        thread_id=THREAD,
    )
    body.update(overrides)
    return FieldMarkCreateRequest(**body)


async def _create(db, **overrides):
    return await create_field_mark(
        room_id=overrides.pop("room_id", ROOM),
        request=_request(**overrides),
        token=overrides.pop("token", TOKEN),
        current_user=overrides.pop("current_user", caller()),
        pool=_DirectPool(db),
    )


@pytest.mark.asyncio
async def test_a_human_can_originate_a_mark(room):
    mark = await _create(room)
    assert mark.origin == "explicit"
    assert mark.title == "tanker rates lead crude"
    assert mark.id.startswith("field_mark:"), "workspace-object id form"
    stored = await room.fetchrow(
        "SELECT origin, provenance, actor_user_id FROM field_marks WHERE id = $1",
        row_id(mark),
    )
    assert stored["origin"] == "explicit"
    assert stored["provenance"] == "human"
    # No mark may be "by nobody" — the same rule acceptance_stamp enforces.
    assert stored["actor_user_id"] == AMO


@pytest.mark.asyncio
async def test_marking_the_same_thing_twice_is_idempotent(room):
    """The ON CONFLICT must MATCH the partial index, not raise against it.

    If the clause omitted `WHERE dedup_key IS NOT NULL`, this call raises
    InvalidColumnReferenceError rather than deduplicating — a double-tap on a
    highlighter would 500.
    """
    first = await _create(room)
    second = await _create(room)
    assert first.id == second.id, "the second call returns the existing mark"
    count = await room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind = 'relation'",
        ROOM,
    )
    assert count == 1


@pytest.mark.asyncio
async def test_two_passages_of_one_message_do_not_collide(room):
    """`field` is folded into the dedup key — this is what makes a passage
    highlighter possible at all, since every highlight on a message shares
    its entity and id."""
    a = await _create(room, subjects=[
        FieldSubjectRef(entity="messages", id=str(MSG_A), field="quote:tanker-rates"),
    ])
    b = await _create(room, subjects=[
        FieldSubjectRef(entity="messages", id=str(MSG_A), field="quote:before-crude"),
    ])
    assert a.id != b.id
    assert await room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind='relation'", ROOM,
    ) == 2


@pytest.mark.asyncio
async def test_a_subject_in_another_room_fails_closed(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, subjects=[
            FieldSubjectRef(entity="messages", id=str(MSG_OTHER)),
        ])
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_thread_in_another_room_fails_closed(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, thread_id=OTHER_THREAD)
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_relation_outside_the_vocabulary_is_refused(room):
    """FIELD_RELATIONS is the guard; nothing downstream re-checks it."""
    with pytest.raises(HTTPException) as exc:
        await _create(room, relation="meta")
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_non_member_cannot_mark(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, current_user=caller(STRANGER))
    assert exc.value.status_code == 403
    assert await room.fetchval("SELECT count(*) FROM field_marks") == 0


@pytest.mark.asyncio
async def test_a_wrong_room_token_is_refused(room):
    with pytest.raises(HTTPException) as exc:
        await _create(room, token="not-the-token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_the_dedup_key_matches_what_inference_would_compute(room):
    """A human's mark and a later inference candidate over the same subjects
    must collide, or the machine re-proposes what a person already asserted."""
    subjects = [{"entity": "messages", "id": str(MSG_A)}]
    mark = await _create(room)
    stored_key = await room.fetchval(
        "SELECT dedup_key FROM field_marks WHERE id = $1", row_id(mark),
    )
    assert stored_key == compute_dedup_key("emerging_position", subjects)


@pytest.mark.asyncio
async def test_the_creation_is_evented(room):
    mark = await _create(room)
    row = await room.fetchrow(
        """SELECT event_type, payload FROM events
           WHERE room_id = $1 AND event_type = 'field_mark_created'""",
        ROOM,
    )
    assert row is not None
    assert row["payload"]["mark_id"] == str(row_id(mark))
    assert row["payload"]["origin"] == "explicit"


def _causal_subjects(scope_id: UUID, *, room_id: UUID = ROOM,
                     book_id: str = BOOK_ID, node_id: str = NODE_ID,
                     reverse: bool = False, field: str | None = None):
    subjects = [
        FieldSubjectRef(entity="geo_scopes", id=str(scope_id)),
        FieldSubjectRef(
            entity="rooms", id=str(room_id),
            field=field or f"thesis_node:{book_id}:{node_id}",
        ),
    ]
    return list(reversed(subjects)) if reverse else subjects


async def _causal_create(db, scope_id: UUID, **overrides):
    return await _create(
        db,
        relation=overrides.pop("relation", "supports"),
        subjects=overrides.pop("subjects", _causal_subjects(scope_id)),
        title=overrides.pop("title", "Hormuz evidence supports shipping chokepoint"),
        payload=overrides.pop("payload", {"node_label": "client forgery"}),
        **overrides,
    )


async def _causal_counts(db) -> tuple[int, int]:
    return (
        await db.fetchval(
            "SELECT count(*) FROM field_marks WHERE room_id = $1", ROOM,
        ),
        await db.fetchval(
            "SELECT count(*) FROM events WHERE room_id = $1 AND "
            "event_type IN ('field_mark_created', 'field_mark_reviewed')", ROOM,
        ),
    )


def test_context_is_part_of_the_field_vocabulary():
    assert "context" in FIELD_RELATIONS


@pytest.mark.asyncio
async def test_causal_roles_are_resolved_by_entity_not_subject_order(causal_room):
    db, scopes = causal_room
    mark = await _causal_create(
        db, scopes["live"], subjects=_causal_subjects(scopes["live"], reverse=True),
    )
    stored = await db.fetchrow(
        "SELECT subjects, payload FROM field_marks WHERE id = $1", row_id(mark),
    )
    assert [subject["entity"] for subject in stored["subjects"]] == ["rooms", "geo_scopes"]
    assert stored["payload"]["node_label"] == "Shipping chokepoint"
    assert stored["payload"]["scope_label"] == "Hormuz evidence"
    assert mark.actor_user_id == AMO
    assert mark.review == "provisional"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "thesis_node:hormuz-cascade",
    "thesis_node:hormuz-cascade:shipping-chokepoint:extra",
    "thesis_node::shipping-chokepoint",
    "thesis_node:hormuz-cascade:",
    "node:hormuz-cascade:shipping-chokepoint",
])
async def test_causal_room_subject_requires_exact_field_grammar(causal_room, field):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(
            db, scopes["live"],
            subjects=_causal_subjects(scopes["live"], field=field),
        )
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("subjects", [
    lambda scope: [
        *_causal_subjects(scope),
        FieldSubjectRef(entity="messages", id=str(MSG_A)),
    ],
    lambda _scope: [
        FieldSubjectRef(entity="messages", id=str(MSG_A)),
        FieldSubjectRef(
            entity="rooms", id=str(ROOM),
            field=f"thesis_node:{BOOK_ID}:{NODE_ID}",
        ),
    ],
    lambda scope: [
        FieldSubjectRef(entity="geo_scopes", id=str(scope)),
        FieldSubjectRef(entity="rooms", id=str(ROOM)),
    ],
])
async def test_causal_mark_requires_exactly_scope_and_room_roles(causal_room, subjects):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(db, scopes["live"], subjects=subjects(scopes["live"]))
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_room_field_subject_is_only_legal_for_causal_relations(causal_room):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(db, scopes["live"], relation="evidence_attachment")
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_causal_room_subject_must_name_the_current_room(causal_room):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(
            db, scopes["live"],
            subjects=_causal_subjects(scopes["live"], room_id=OTHER_ROOM),
        )
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_causal_book_must_be_the_rooms_current_binding(causal_room):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(
            db, scopes["live"],
            subjects=_causal_subjects(scopes["live"], book_id="old-book"),
        )
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_causal_node_must_exist_in_authenticated_structure(causal_room):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(
            db, scopes["live"],
            subjects=_causal_subjects(scopes["live"], node_id="missing-node"),
        )
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("structure", [
    {"id": "wrong-book", "nodes": []},
    {"id": BOOK_ID, "nodes": {"id": NODE_ID, "label": "not a list"}},
    {"id": BOOK_ID, "nodes": ["not a node"]},
    {"id": BOOK_ID, "nodes": [{"id": NODE_ID, "label": ""}]},
    {"id": BOOK_ID, "nodes": [
        {"id": NODE_ID, "label": "Shipping chokepoint"},
        {"id": NODE_ID, "label": "Duplicate"},
    ]},
], ids=[
    "mismatched-book",
    "nodes-not-list",
    "malformed-node",
    "malformed-matching-node",
    "duplicate-node-ids",
])
async def test_malformed_structure_contract_fails_before_any_write(
    causal_room, monkeypatch, structure,
):
    db, scopes = causal_room

    async def malformed(*_args, **_kwargs):
        return structure

    monkeypatch.setattr(field_api.td, "service_get", malformed, raising=False)
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(db, scopes["live"])
    assert exc.value.status_code == 502
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["proposed", "rejected", "expired"])
async def test_only_accepted_canonically_live_scope_can_bind(causal_room, state):
    db, scopes = causal_room
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(db, scopes[state])
    assert exc.value.status_code == 422
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_unavailable_structure_bridge_fails_without_mark_or_event(
    causal_room, monkeypatch,
):
    db, scopes = causal_room

    async def unavailable(*_args, **_kwargs):
        raise TradingDeskError("bridge unavailable")

    monkeypatch.setattr(field_api.td, "service_get", unavailable, raising=False)
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await _causal_create(db, scopes["live"])
    assert exc.value.status_code == 502
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope_state", "book_id", "node_id", "status"),
    [
        ("live", "old-book", NODE_2_ID, 422),
        ("live", BOOK_ID, "missing-node", 422),
        ("expired", BOOK_ID, NODE_2_ID, 422),
        ("superseded", BOOK_ID, NODE_2_ID, 422),
    ],
    ids=["wrong-book", "wrong-node", "dead-scope", "superseded-scope"],
)
async def test_causal_replacement_validation_failure_leaves_no_review_replacement_or_event(
    causal_room, scope_state, book_id, node_id, status,
):
    db, scopes = causal_room
    original = await _causal_create(db, scopes["live"])
    before = await _causal_counts(db)
    request = field_api.FieldReviewRequest(
        action="correct",
        replacement=field_api.FieldReplacementRequest(
            relation="context",
            subjects=_causal_subjects(
                scopes[scope_state], book_id=book_id, node_id=node_id,
            ),
            title="invalid causal replacement",
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await field_api.review_field_mark(
            ROOM, row_id(original), request,
            token=TOKEN, current_user=caller(), pool=_DirectPool(db),
        )
    assert exc.value.status_code == status
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_causal_replacement_bridge_failure_leaves_no_review_replacement_or_event(
    causal_room, monkeypatch,
):
    db, scopes = causal_room
    original = await _causal_create(db, scopes["live"])

    async def unavailable(*_args, **_kwargs):
        raise TradingDeskError("bridge unavailable")

    monkeypatch.setattr(field_api.td, "service_get", unavailable, raising=False)
    before = await _causal_counts(db)
    with pytest.raises(HTTPException) as exc:
        await field_api.review_field_mark(
            ROOM,
            row_id(original),
            field_api.FieldReviewRequest(
                action="correct",
                replacement=field_api.FieldReplacementRequest(
                    relation="context",
                    subjects=_causal_subjects(scopes["live"], node_id=NODE_2_ID),
                    title="bridge-dependent replacement",
                ),
            ),
            token=TOKEN,
            current_user=caller(),
            pool=_DirectPool(db),
        )
    assert exc.value.status_code == 502
    assert await _causal_counts(db) == before


@pytest.mark.asyncio
async def test_causal_confirm_contest_and_correct_preserve_roles_and_attribution(
    causal_room,
):
    db, scopes = causal_room
    original = await _causal_create(
        db, scopes["live"], subjects=_causal_subjects(scopes["live"], reverse=True),
    )
    original_subjects = [subject.model_dump() for subject in original.subjects]

    confirmed = await field_api.review_field_mark(
        ROOM, row_id(original), field_api.FieldReviewRequest(action="confirm"),
        token=TOKEN, current_user=caller(), pool=_DirectPool(db),
    )
    assert [subject.model_dump() for subject in confirmed.mark.subjects] == original_subjects
    assert confirmed.mark.review == "confirmed"
    assert confirmed.review.actor_user_id == AMO

    contested = await field_api.review_field_mark(
        ROOM, row_id(original), field_api.FieldReviewRequest(action="contest"),
        token=TOKEN, current_user=caller(), pool=_DirectPool(db),
    )
    assert [subject.model_dump() for subject in contested.mark.subjects] == original_subjects
    assert contested.mark.review == "contested"
    assert contested.review.actor_user_id == AMO

    replacement_subjects = _causal_subjects(
        scopes["live"], node_id=NODE_2_ID, reverse=False,
    )
    corrected = await field_api.review_field_mark(
        ROOM,
        row_id(original),
        field_api.FieldReviewRequest(
            action="correct",
            replacement=field_api.FieldReplacementRequest(
                relation="context",
                subjects=replacement_subjects,
                title="Hormuz evidence is context for freight rates",
                payload={"node_label": "client forgery"},
            ),
        ),
        token=TOKEN,
        current_user=caller(),
        pool=_DirectPool(db),
    )
    assert corrected.mark.review == "superseded"
    assert corrected.review.actor_user_id == AMO
    assert len(corrected.replacements) == 1
    replacement = corrected.replacements[0]
    assert {subject.entity for subject in replacement.subjects} == {"geo_scopes", "rooms"}
    assert replacement.payload["node_label"] == "Freight rates"
    assert replacement.payload["scope_label"] == "Hormuz evidence"
    assert replacement.actor_user_id == AMO
    assert replacement.caused_by_id == corrected.review.id
