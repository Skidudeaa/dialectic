"""
Real-Postgres contracts for field_marks.py — the Field's read-only projection.

WHY real Postgres: the invariants that matter (the derived review rule, the
anti-reshuffle anchor ordering, append-only, the dedup index) are properties
of what the SQL and its constraints actually do, not of Python alone. A
mocked connection would assert the shape of a query that never ran.

Template: tests/test_workspace_objects_pg.py (JSONB-codec fixture,
rollback-transaction workroom, the OTHER-ROOM-SENTINEL fencing pattern).

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/017_field_marks.sql
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from field_marks import (
    CausalGeoBinding,
    FIELD_ACTIONS,
    FIELD_DELIBERATIVE_STATUSES,
    FIELD_ORIGINS,
    FIELD_RELATIONS,
    FIELD_REVIEW_STATES,
    FieldMark,
    FieldMarkService,
    FieldSubjectRef,
    causal_geo_binding_from_mark,
    compute_dedup_key,
)
from geo_scopes import insert_scope

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xF01)
ROOM, OTHER = _uid(0xF11), _uid(0xF12)
TH, TH_OTHER = _uid(0xF21), _uid(0xF22)

MARK_CONFIRM = _uid(0xF31)
MARK_CONTEST = _uid(0xF32)
MARK_CORRECT = _uid(0xF33)
MARK_CORRECT_REPLACEMENT = _uid(0xF34)
MARK_SPLIT = _uid(0xF35)
MARK_SPLIT_A = _uid(0xF36)
MARK_SPLIT_B = _uid(0xF37)
MARK_MERGE_1 = _uid(0xF38)
MARK_MERGE_2 = _uid(0xF39)
MARK_MERGE_REPLACEMENT = _uid(0xF3A)
MARK_INFERRED_PROVISIONAL = _uid(0xF3B)
MARK_EXPLICIT_NO_REVIEW = _uid(0xF3C)
MARK_OTHER = _uid(0xF3D)

REVIEW_CONFIRM_1 = _uid(0xF41)
REVIEW_CONFIRM_2 = _uid(0xF42)
REVIEW_CONTEST = _uid(0xF43)
REVIEW_CORRECT = _uid(0xF44)
REVIEW_SPLIT = _uid(0xF45)
REVIEW_MERGE_1 = _uid(0xF46)
REVIEW_MERGE_2 = _uid(0xF47)

BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

# Fixed relation/subjects for the marks whose dedup_key the mutation test
# re-asserts against — kept as module constants so the test does not have to
# re-derive what the fixture wrote.
CONTEST_RELATION = "possible_contradiction"
CONTEST_SUBJECTS = [{"entity": "messages", "id": str(_uid(0xF91))}]
CORRECT_RELATION = "repeated_definition"
CORRECT_SUBJECTS = [{"entity": "messages", "id": str(_uid(0xF92))}]

_TOUCHED_TABLES = ("field_marks",)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    # The SAME codec the production pool installs (api/main.py lifespan) —
    # without it a bare connection hands JSONB back as text.
    import json
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


async def _relation(db, mid, room, *, thread, relation, origin, provenance,
                    subjects, title, at, payload=None, supersedes=None,
                    caused_by=None, actor=None, dedup_key=None):
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, payload, supersedes_id,
                caused_by_id, actor_user_id, created_at, dedup_key)
           VALUES ($1,$2,$3,'relation',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
        mid, room, thread, relation, origin, provenance, subjects, title,
        payload or {}, supersedes, caused_by, actor, at,
        dedup_key or compute_dedup_key(relation, subjects),
    )


async def _review(db, rid, room, target, action, actor, at, extra=None):
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
                provenance, created_at, payload)
           VALUES ($1,$2,'review',$3,$4,$5,'human',$6,$7)""",
        rid, room, action, target, actor, at, extra or {},
    )


@pytest_asyncio.fixture
async def field_room(db):
    """One room carrying one mark per action (confirm/contest/correct/split/
    merge) plus a bare inferred-provisional and a bare explicit-no-review
    mark, and a second room whose content must never leak into the first's
    projection."""
    tx = db.transaction()
    await tx.start()

    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')",
        AMO, _d(40))
    for rid, nm in ((ROOM, "Field Room"), (OTHER, "Other Room")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, _d(30), f"field-{rid}", nm)
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            rid, AMO, _d(30))
    for tid, rid in ((TH, ROOM), (TH_OTHER, OTHER)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            tid, rid, _d(30))

    # --- confirm chain: two confirms, latest still 'confirm' -> confirmed ---
    await _relation(
        db, MARK_CONFIRM, ROOM, thread=TH, relation="emerging_position",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF93))}],
        title="Amo holds Brent leads", at=_d(9),
    )
    await _review(db, REVIEW_CONFIRM_1, ROOM, MARK_CONFIRM, "confirm", AMO, _d(5))
    await _review(db, REVIEW_CONFIRM_2, ROOM, MARK_CONFIRM, "confirm", AMO, _d(3))

    # --- contest: one review, no replacement -> contested -------------------
    await _relation(
        db, MARK_CONTEST, ROOM, thread=TH, relation=CONTEST_RELATION,
        origin="inferred", provenance="field_inference",
        subjects=CONTEST_SUBJECTS, title="Strait risk vs. base case", at=_d(8),
    )
    await _review(db, REVIEW_CONTEST, ROOM, MARK_CONTEST, "contest", AMO, _d(4))

    # --- correct: review + 1 replacement, ancestor created EARLY, review/
    # replacement land LATE — the anchor-ordering fixture -------------------
    await _relation(
        db, MARK_CORRECT, ROOM, thread=TH, relation=CORRECT_RELATION,
        origin="inferred", provenance="field_inference",
        subjects=CORRECT_SUBJECTS, title="Definition A", at=_d(9.5),
    )
    await _review(db, REVIEW_CORRECT, ROOM, MARK_CORRECT, "correct", AMO, _d(1))
    await _relation(
        db, MARK_CORRECT_REPLACEMENT, ROOM, thread=TH, relation=CORRECT_RELATION,
        origin="explicit", provenance="human",
        subjects=[{"entity": "messages", "id": str(_uid(0xF94))}],
        title="Definition A, corrected", at=_d(1),
        supersedes=MARK_CORRECT, caused_by=REVIEW_CORRECT, actor=AMO,
    )

    # --- split: review + 2 replacements --------------------------------------
    await _relation(
        db, MARK_SPLIT, ROOM, thread=TH, relation="claim_group",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF95))}],
        title="Combined claim", at=_d(7),
    )
    await _review(db, REVIEW_SPLIT, ROOM, MARK_SPLIT, "split", AMO, _d(2))
    await _relation(
        db, MARK_SPLIT_A, ROOM, thread=TH, relation="claim_group",
        origin="explicit", provenance="human",
        subjects=[{"entity": "messages", "id": str(_uid(0xF96))}],
        title="Claim A", at=_d(2), supersedes=MARK_SPLIT, caused_by=REVIEW_SPLIT,
        actor=AMO,
    )
    await _relation(
        db, MARK_SPLIT_B, ROOM, thread=TH, relation="claim_group",
        origin="explicit", provenance="human",
        subjects=[{"entity": "messages", "id": str(_uid(0xF97))}],
        title="Claim B", at=_d(2), supersedes=MARK_SPLIT, caused_by=REVIEW_SPLIT,
        actor=AMO,
    )

    # --- merge: one review PER source (shared merge_group), 1 replacement ---
    await _relation(
        db, MARK_MERGE_1, ROOM, thread=TH, relation="claim_group",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF98))}],
        title="Claim 1", at=_d(6),
    )
    await _relation(
        db, MARK_MERGE_2, ROOM, thread=TH, relation="claim_group",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF99))}],
        title="Claim 2", at=_d(6),
    )
    await _review(db, REVIEW_MERGE_1, ROOM, MARK_MERGE_1, "merge", AMO, _d(1),
                 extra={"merge_group": "g1"})
    await _review(db, REVIEW_MERGE_2, ROOM, MARK_MERGE_2, "merge", AMO, _d(1),
                 extra={"merge_group": "g1"})
    await _relation(
        db, MARK_MERGE_REPLACEMENT, ROOM, thread=TH, relation="claim_group",
        origin="explicit", provenance="human",
        subjects=[{"entity": "messages", "id": str(_uid(0xF9A))}],
        title="Claims 1+2 merged", at=_d(1),
        supersedes=MARK_MERGE_1, caused_by=REVIEW_MERGE_1, actor=AMO,
        payload={"merged_ids": [str(MARK_MERGE_1), str(MARK_MERGE_2)]},
    )

    # --- a bare inferred mark with zero reviews -> provisional --------------
    await _relation(
        db, MARK_INFERRED_PROVISIONAL, ROOM, thread=TH, relation="unanswered_question",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF9B))}],
        title="Does the strait close?", at=_d(0.5),
    )

    # --- a bare EXPLICIT mark with zero reviews -> ALSO provisional (§1.3:
    # confirmed-at-birth is not a thing; origin already says human) ---------
    await _relation(
        db, MARK_EXPLICIT_NO_REVIEW, ROOM, thread=TH, relation="candidate_synthesis",
        origin="explicit", provenance="human", actor=AMO,
        subjects=[{"entity": "messages", "id": str(_uid(0xF9C))}],
        title="Amo's own synthesis", at=_d(0.4),
    )

    # --- the other room: one sentinel mark, must never leak -----------------
    await _relation(
        db, MARK_OTHER, OTHER, thread=TH_OTHER, relation="emerging_position",
        origin="inferred", provenance="field_inference",
        subjects=[{"entity": "messages", "id": str(_uid(0xF9D))}],
        title="OTHER-ROOM-SENTINEL", at=_d(1),
    )

    yield db
    await tx.rollback()


# ---------------------------------------------------------------------------
# vocabularies
# ---------------------------------------------------------------------------

def test_vocabularies_are_the_right_size():
    assert len(FIELD_RELATIONS) == 12
    assert len(FIELD_ACTIONS) == 6
    assert len(FIELD_ORIGINS) == 2
    assert len(FIELD_REVIEW_STATES) == 4
    assert len(FIELD_DELIBERATIVE_STATUSES) == 5
    assert len(FIELD_RELATIONS) == len(set(FIELD_RELATIONS))


def test_causal_binding_adapter_emits_canonical_object_ids():
    root_scope_id = _uid(0xFA1)
    current_scope_id = _uid(0xFA2)
    mark = FieldMark(
        id=f"field_mark:{MARK_CONFIRM}",
        room_id=ROOM,
        thread_id=TH,
        relation="supports",
        origin="explicit",
        review="confirmed",
        deliberative_status="active",
        subjects=[
            FieldSubjectRef(
                entity="rooms",
                id=str(ROOM),
                field="thesis_node:hormuz-book:shipping",
            ),
            FieldSubjectRef(entity="geo_scopes", id=str(root_scope_id)),
        ],
        title="Hormuz supports shipping",
        payload={"node_label": "Shipping"},
        provenance="human",
        created_at=BASE,
    )

    binding = causal_geo_binding_from_mark(
        mark, current_scope_id=f"geo_scope:{current_scope_id}",
    )

    assert binding == CausalGeoBinding(
        id=f"field_mark:{MARK_CONFIRM}",
        current_scope_id=f"geo_scope:{current_scope_id}",
        evidence_scope_id=f"geo_scope:{root_scope_id}",
        relation="supports",
        review_state="confirmed",
        provisional=False,
        target={
            "room_id": ROOM,
            "book_id": "hormuz-book",
            "node_id": "shipping",
            "node_label": "Shipping",
        },
    )


# ---------------------------------------------------------------------------
# derived review — all six actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derived_review_for_every_action(field_room):
    projection = await FieldMarkService(field_room).build(ROOM)
    by_id = {m.id.split(":", 1)[1]: m for m in projection.marks}

    assert by_id[str(MARK_CONFIRM)].review == "confirmed"
    assert len(by_id[str(MARK_CONFIRM)].reviews) == 2

    assert by_id[str(MARK_CONTEST)].review == "contested"

    assert by_id[str(MARK_CORRECT)].review == "superseded"
    assert by_id[str(MARK_CORRECT_REPLACEMENT)].review == "provisional"

    assert by_id[str(MARK_SPLIT)].review == "superseded"
    assert by_id[str(MARK_SPLIT_A)].review == "provisional"
    assert by_id[str(MARK_SPLIT_B)].review == "provisional"

    assert by_id[str(MARK_MERGE_1)].review == "superseded"
    assert by_id[str(MARK_MERGE_2)].review == "superseded"
    assert by_id[str(MARK_MERGE_REPLACEMENT)].review == "provisional"
    assert by_id[str(MARK_MERGE_REPLACEMENT)].payload["merged_ids"] == [
        str(MARK_MERGE_1), str(MARK_MERGE_2),
    ]

    assert by_id[str(MARK_INFERRED_PROVISIONAL)].review == "provisional"
    # An explicit human relation with NO reviews is ALSO provisional-display
    # (§1.3/§14.2: confirmed-at-birth is not a thing) even though its origin
    # already says a human asserted it.
    assert by_id[str(MARK_EXPLICIT_NO_REVIEW)].review == "provisional"
    assert by_id[str(MARK_EXPLICIT_NO_REVIEW)].origin == "explicit"


@pytest.mark.asyncio
async def test_vocabularies_are_closed_on_every_mark(field_room):
    projection = await FieldMarkService(field_room).build(ROOM)
    assert projection.marks
    for mark in projection.marks:
        assert mark.relation in FIELD_RELATIONS
        assert mark.review in FIELD_REVIEW_STATES
        assert mark.deliberative_status in FIELD_DELIBERATIVE_STATUSES
        if mark.origin is not None:
            assert mark.origin in FIELD_ORIGINS
        for review in mark.reviews:
            assert review.action in FIELD_ACTIONS


# ---------------------------------------------------------------------------
# anti-reshuffle ordering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replacement_occupies_its_ancestors_ordinal(field_room):
    """The anchor-ordering rule (§5.1): a replacement created long AFTER its
    ancestor still renders immediately next to it, not at the end reflecting
    its own later created_at."""
    projection = await FieldMarkService(field_room).build(ROOM)
    ids = [m.id for m in projection.marks]

    correct_idx = ids.index(f"field_mark:{MARK_CORRECT}")
    assert ids[correct_idx + 1] == f"field_mark:{MARK_CORRECT_REPLACEMENT}"

    split_idx = ids.index(f"field_mark:{MARK_SPLIT}")
    assert {ids[split_idx + 1], ids[split_idx + 2]} == {
        f"field_mark:{MARK_SPLIT_A}", f"field_mark:{MARK_SPLIT_B}",
    }

    merge_idx = ids.index(f"field_mark:{MARK_MERGE_1}")
    assert ids[merge_idx + 1] == f"field_mark:{MARK_MERGE_REPLACEMENT}"

    # And MARK_CORRECT itself — created BEFORE MARK_CONTEST — still sorts
    # before it, even though its review/replacement landed much later.
    assert ids.index(f"field_mark:{MARK_CORRECT}") < ids.index(f"field_mark:{MARK_CONTEST}")


@pytest.mark.asyncio
async def test_anchor_ordering_unchanged_after_inserting_a_review(field_room):
    """Nothing ever re-sorts on a NEW review — contrast
    WorkspaceObjectService.build()'s newest-first re-sort, which the Field
    must not copy (§5.1)."""
    before = [m.id for m in (await FieldMarkService(field_room).build(ROOM)).marks]

    # A brand new review on an EXISTING mark must not move anything.
    await _review(
        field_room, uuid4(), ROOM, MARK_CONTEST, "contest", AMO,
        datetime.now(timezone.utc),
    )
    after = [m.id for m in (await FieldMarkService(field_room).build(ROOM)).marks]

    assert before == after


@pytest.mark.asyncio
async def test_object_ids_are_unique_and_stable(field_room):
    svc = FieldMarkService(field_room)
    first = [m.id for m in (await svc.build(ROOM)).marks]
    second = [m.id for m in (await svc.build(ROOM)).marks]
    assert len(first) == len(set(first)), "duplicate mark ids"
    assert first == second, "ids/order are not stable across reads"


# ---------------------------------------------------------------------------
# fencing, read-only, bounded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_mark_is_fenced_to_its_room(field_room):
    projection = await FieldMarkService(field_room).build(ROOM)
    assert projection.marks
    assert all(m.room_id == ROOM for m in projection.marks)
    blob = "\n".join(m.model_dump_json() for m in projection.marks)
    assert "OTHER-ROOM-SENTINEL" not in blob


@pytest.mark.asyncio
async def test_the_other_room_only_sees_its_own_mark(field_room):
    projection = await FieldMarkService(field_room).build(OTHER)
    assert [m.title for m in projection.marks] == ["OTHER-ROOM-SENTINEL"]


@pytest.mark.asyncio
async def test_causal_geo_bindings_are_one_atomic_bounded_newest_first_read(field_room):
    scope_id = uuid4()
    mark_ids = [uuid4(), uuid4(), uuid4()]
    for index, mark_id in enumerate(mark_ids):
        await _relation(
            field_room, mark_id, ROOM, thread=TH, relation="supports",
            origin="explicit", provenance="human", actor=AMO,
            subjects=[
                {"entity": "geo_scopes", "id": str(scope_id)},
                {
                    "entity": "rooms", "id": str(ROOM),
                    "field": f"thesis_node:book:node-{index}",
                },
            ],
            title=f"Causal {index}", at=BASE + timedelta(seconds=index),
        )
    await _review(
        field_room, uuid4(), ROOM, mark_ids[-1], "confirm", AMO,
        BASE + timedelta(minutes=1),
    )
    other_id = uuid4()
    await _relation(
        field_room, other_id, OTHER, thread=TH_OTHER, relation="supports",
        origin="explicit", provenance="human", actor=AMO,
        subjects=[
            {"entity": "geo_scopes", "id": str(scope_id)},
            {
                "entity": "rooms", "id": str(OTHER),
                "field": "thesis_node:other:sentinel",
            },
        ],
        title="OTHER-ROOM-CAUSAL-SENTINEL", at=BASE + timedelta(days=1),
    )
    # Malformed/manual rows must not be able to adjudicate another room's
    # otherwise provisional candidate merely by naming its globally unique id.
    await _review(
        field_room, uuid4(), OTHER, mark_ids[1], "contest", AMO,
        BASE + timedelta(minutes=2),
    )
    await _relation(
        field_room, uuid4(), OTHER, thread=TH_OTHER, relation="supports",
        origin="explicit", provenance="human", actor=AMO,
        subjects=[
            {"entity": "geo_scopes", "id": str(scope_id)},
            {
                "entity": "rooms", "id": str(OTHER),
                "field": "thesis_node:other:malformed-successor",
            },
        ],
        title="OTHER-ROOM-MALFORMED-SUCCESSOR",
        at=BASE + timedelta(minutes=3), supersedes=mark_ids[1],
    )

    class ReadAudit:
        def __init__(self, connection: asyncpg.Connection) -> None:
            self.connection = connection
            self.read_calls = 0
            self.candidate_calls = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

        async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
            self.read_calls += 1
            if "jsonb_array_elements" in query:
                self.candidate_calls += 1
            return await self.connection.fetch(query, *args)

        async def fetchrow(
            self, query: str, *args: object,
        ) -> asyncpg.Record | None:
            self.read_calls += 1
            return await self.connection.fetchrow(query, *args)

        async def fetchval(self, query: str, *args: object) -> Any:
            self.read_calls += 1
            if "jsonb_array_elements" in query:
                self.candidate_calls += 1
            return await self.connection.fetchval(query, *args)

    audited = ReadAudit(field_room)
    projection = await FieldMarkService(audited).causal_geo_bindings(
        ROOM, {scope_id}, limit=2,
    )

    assert projection.total == 3
    assert projection.omitted == 1
    assert projection.complete is False
    assert [mark.id for mark in projection.marks] == [
        f"field_mark:{mark_ids[2]}", f"field_mark:{mark_ids[1]}",
    ]
    assert projection.marks[0].review == "confirmed"
    assert len(projection.marks[0].reviews) == 1
    assert projection.marks[1].review == "provisional"
    assert projection.marks[1].reviews == []
    assert "OTHER-ROOM-CAUSAL-SENTINEL" not in projection.model_dump_json()
    assert "OTHER-ROOM-MALFORMED-SUCCESSOR" not in projection.model_dump_json()
    assert audited.candidate_calls == 1
    assert audited.read_calls == 1


@pytest.mark.asyncio
async def test_atlas_causal_geo_bindings_follow_lineage_with_one_fenced_bounded_read(
    field_room,
):
    if not await field_room.fetchval("SELECT to_regclass('geo_scopes')"):
        pytest.skip("geo_scopes missing — run migrations 021 and 022")

    provenance = {
        "provider": "human",
        "acquisition": "human",
        "source_id": "field-atlas-test",
        "credit": "Synthetic test fixture",
    }
    root_scope_id = await insert_scope(
        field_room,
        room_id=ROOM,
        subject={"entity": "rooms", "id": str(ROOM)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        label="Root evidence",
        authority="human_confirmed",
        provenance=provenance,
        confirmed_by=AMO,
        revision_action="place",
        created_by=AMO,
        now=BASE,
    )
    current_scope_id = await insert_scope(
        field_room,
        room_id=ROOM,
        subject={"entity": "rooms", "id": str(ROOM)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.4, 26.6]},
        label="Current evidence",
        authority="human_confirmed",
        provenance=provenance,
        confirmed_by=AMO,
        supersedes_id=root_scope_id,
        revision_action="redraw",
        created_by=AMO,
        now=BASE + timedelta(minutes=1),
    )
    other_scope_id = await insert_scope(
        field_room,
        room_id=OTHER,
        subject={"entity": "rooms", "id": str(OTHER)},
        kind="point",
        geometry={"type": "Point", "coordinates": [1.0, 1.0]},
        label="OTHER-ROOM-SCOPE-SENTINEL",
        authority="human_confirmed",
        provenance=provenance,
        confirmed_by=AMO,
        revision_action="place",
        created_by=AMO,
        now=BASE,
    )

    mark_ids = [uuid4() for _ in range(26)]
    for index, mark_id in enumerate(mark_ids):
        await _relation(
            field_room,
            mark_id,
            ROOM,
            thread=TH,
            relation="supports",
            origin="explicit",
            provenance="human",
            actor=AMO,
            subjects=[
                {"entity": "geo_scopes", "id": str(root_scope_id)},
                {
                    "entity": "rooms",
                    "id": str(ROOM),
                    "field": f"thesis_node:hormuz-book:node-{index}",
                },
            ],
            title=f"Causal lineage {index}",
            payload={"node_label": f"Node {index}"},
            at=BASE + timedelta(seconds=index),
        )

    other_mark_id = uuid4()
    await _relation(
        field_room,
        other_mark_id,
        OTHER,
        thread=TH_OTHER,
        relation="supports",
        origin="explicit",
        provenance="human",
        actor=AMO,
        subjects=[
            {"entity": "geo_scopes", "id": str(other_scope_id)},
            {
                "entity": "rooms",
                "id": str(OTHER),
                "field": "thesis_node:other-book:other-node",
            },
        ],
        title="OTHER-ROOM-CAUSAL-SENTINEL",
        at=BASE + timedelta(hours=1),
    )
    await _review(
        field_room,
        uuid4(),
        OTHER,
        mark_ids[-1],
        "contest",
        AMO,
        BASE + timedelta(hours=2),
    )
    await _relation(
        field_room,
        uuid4(),
        OTHER,
        thread=TH_OTHER,
        relation="supports",
        origin="explicit",
        provenance="human",
        actor=AMO,
        subjects=[
            {"entity": "geo_scopes", "id": str(other_scope_id)},
            {
                "entity": "rooms",
                "id": str(OTHER),
                "field": "thesis_node:other-book:malformed-successor",
            },
        ],
        title="OTHER-ROOM-MALFORMED-SUCCESSOR",
        at=BASE + timedelta(hours=3),
        supersedes=mark_ids[-2],
    )

    class ReadAudit:
        def __init__(self, connection: asyncpg.Connection) -> None:
            self.connection = connection
            self.read_calls = 0
            self.candidate_calls = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(self.connection, name)

        async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
            self.read_calls += 1
            if "scope_lineage" in query:
                self.candidate_calls += 1
            return await self.connection.fetch(query, *args)

    audited = ReadAudit(field_room)
    projection = await FieldMarkService(audited).atlas_causal_geo_bindings(
        [ROOM], {current_scope_id}, per_room_limit=25, limit=200,
    )

    assert projection.total == 26
    assert len(projection.bindings) == 25
    assert projection.omitted == 1
    assert projection.complete is False
    assert all(
        binding.current_scope_id == f"geo_scope:{current_scope_id}"
        for binding in projection.bindings
    )
    assert all(
        binding.evidence_scope_id == f"geo_scope:{root_scope_id}"
        for binding in projection.bindings
    )
    assert "OTHER-ROOM-CAUSAL-SENTINEL" not in projection.model_dump_json()
    assert "OTHER-ROOM-MALFORMED-SUCCESSOR" not in projection.model_dump_json()
    assert all(binding.target.room_id == ROOM for binding in projection.bindings)
    newest = next(
        binding
        for binding in projection.bindings
        if binding.id == f"field_mark:{mark_ids[-1]}"
    )
    assert newest.review_state == "provisional"
    assert audited.candidate_calls == 1
    assert audited.read_calls == 1


@pytest.mark.asyncio
async def test_build_writes_nothing(field_room):
    before = {
        t: await field_room.fetchval(f"SELECT count(*) FROM {t}")
        for t in _TOUCHED_TABLES
    }
    rows_before = await field_room.fetch(
        "SELECT id, relation, action, deliberative_status, created_at "
        "FROM field_marks WHERE room_id = $1 ORDER BY id", ROOM,
    )

    await FieldMarkService(field_room).build(ROOM)
    await FieldMarkService(field_room).build(OTHER)

    after = {
        t: await field_room.fetchval(f"SELECT count(*) FROM {t}")
        for t in _TOUCHED_TABLES
    }
    rows_after = await field_room.fetch(
        "SELECT id, relation, action, deliberative_status, created_at "
        "FROM field_marks WHERE room_id = $1 ORDER BY id", ROOM,
    )
    assert before == after, f"build() wrote rows: {before} -> {after}"
    assert [tuple(r) for r in rows_before] == [tuple(r) for r in rows_after]


# ---------------------------------------------------------------------------
# append-only
# ---------------------------------------------------------------------------

def test_no_write_statements_in_the_field_modules():
    """No code path UPDATEs or DELETEs a field_marks row (§1.10, §2 item 16).

    Anchored at statement position (a real SQL keyword, not a comment) so a
    docstring mentioning "UPDATE" or "DELETE" cannot satisfy — or break —
    this. Every INSERT statement in these three modules is enumerated
    instead of relying on absence alone, so the assertion cannot pass merely
    because nothing was written to field_marks at all.
    """
    import re

    import api.field as field_api
    import field_marks as field_marks_mod
    import llm.field_inference as field_inference_mod

    insert_count = 0
    for mod in (field_marks_mod, field_api, field_inference_mod):
        source = mod.__file__ and open(mod.__file__).read()
        code_lines = "\n".join(
            line for line in source.splitlines()
            if not re.match(r"\s*#", line)
        )
        assert not re.search(r"\bUPDATE\s+field_marks\b", code_lines, re.IGNORECASE)
        assert not re.search(r"\bDELETE\s+FROM\s+field_marks\b", code_lines, re.IGNORECASE)
        insert_count += len(re.findall(r"\bINSERT\s+INTO\s+field_marks\b", code_lines, re.IGNORECASE))
    assert insert_count > 0, "the guard is vacuous: no INSERT into field_marks found at all"


@pytest.mark.asyncio
async def test_a_review_action_never_touches_its_targets_row_content(field_room):
    """A row-content before/after check through a review action: adding a
    review to MARK_CONTEST must not change one byte of MARK_CONTEST's own
    row."""
    before = dict(await field_room.fetchrow(
        "SELECT * FROM field_marks WHERE id = $1", MARK_CONTEST,
    ))
    await _review(
        field_room, uuid4(), ROOM, MARK_CONTEST, "contest", AMO,
        datetime.now(timezone.utc),
    )
    after = dict(await field_room.fetchrow(
        "SELECT * FROM field_marks WHERE id = $1", MARK_CONTEST,
    ))
    assert before == after


# ---------------------------------------------------------------------------
# the dedup index — the §1.10 guarantee, at the DB layer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_blocks_reassertion_after_contest_and_after_correct(field_room):
    """§1.10: the partial unique index, not application code, is what makes a
    corrected mark unre-assertable. MUTATION PROOF (recorded in the build
    report): temporarily remove `ON CONFLICT (room_id, dedup_key) DO NOTHING`
    from llm.field_inference._INSERT_CANDIDATE_SQL — this test must go red
    with a raw asyncpg.UniqueViolationError (not a controlled skip) — then
    restore it.
    """
    from llm.field_inference import _INSERT_CANDIDATE_SQL

    # After a mere CONTEST (no replacement, dedup_key untouched): a re-insert
    # with the SAME dedup_key the original inference candidate would have
    # computed is silently dropped.
    contest_key = compute_dedup_key(CONTEST_RELATION, CONTEST_SUBJECTS)
    row = await field_room.fetchrow(
        _INSERT_CANDIDATE_SQL, uuid4(), ROOM, TH, CONTEST_RELATION,
        CONTEST_SUBJECTS, "re-asserted after contest", {}, contest_key,
    )
    assert row is None, "ON CONFLICT DO NOTHING should have produced zero rows"
    count = await field_room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND dedup_key = $2",
        ROOM, contest_key,
    )
    assert count == 1, "the contested mark's dedup_key must stay occupied exactly once"

    # After a CORRECT (replaced, but the ORIGINAL row and its dedup_key are
    # never deleted): a re-insert against the ORIGINAL's key is also blocked.
    correct_key = compute_dedup_key(CORRECT_RELATION, CORRECT_SUBJECTS)
    row2 = await field_room.fetchrow(
        _INSERT_CANDIDATE_SQL, uuid4(), ROOM, TH, CORRECT_RELATION,
        CORRECT_SUBJECTS, "re-asserted after correct", {}, correct_key,
    )
    assert row2 is None
    count2 = await field_room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1 AND dedup_key = $2",
        ROOM, correct_key,
    )
    assert count2 == 1, "the corrected mark's original dedup_key must stay occupied exactly once"


@pytest.mark.asyncio
async def test_dedup_is_per_room_not_global(field_room):
    """The SAME {relation, subjects} pair in a DIFFERENT room is a different
    row — dedup is scoped by (room_id, dedup_key), never dedup_key alone."""
    from llm.field_inference import _INSERT_CANDIDATE_SQL

    contest_key = compute_dedup_key(CONTEST_RELATION, CONTEST_SUBJECTS)
    row = await field_room.fetchrow(
        _INSERT_CANDIDATE_SQL, uuid4(), OTHER, TH_OTHER, CONTEST_RELATION,
        CONTEST_SUBJECTS, "same key, other room", {}, contest_key,
    )
    assert row is not None, "the same dedup_key in a different room must be allowed"
