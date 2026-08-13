"""
Real-Postgres contracts for the workspace-object adapters (workspace_objects.py).

WHY real Postgres: every adapter is a read over a different existing table, and
the invariants that matter — the twin rule, the room fence, the read-only
promise, the per-kind bounds — are all properties of what the SQL returns. A
mocked DB would assert the shape of a query that never ran.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/013_home_base.sql
    psql dialectic_test -f migrations/014_reading_library.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from workspace_objects import (
    WORKSPACE_ACTIONS,
    WORKSPACE_OBJECT_KINDS,
    WORKSPACE_ORIGINS,
    WORKSPACE_REVIEW_STATES,
    WorkspaceObjectService,
    workspace_object_from_movement,
)

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xC01)
ROOM, OTHER = _uid(0xC11), _uid(0xC12)
TH, TH_OTHER = _uid(0xC21), _uid(0xC22)
M_BRIEF, M_PROPOSALS, M_RESOLVE, M_OTHER = (
    _uid(0xC31), _uid(0xC32), _uid(0xC33), _uid(0xC34),
)
READING_URL = "https://example.test/adapters/one"
READING_TITLE = "The Only Reading"
BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)

# Every table an adapter reads. The read-only contract is asserted against
# this exact list, so a new adapter that starts writing cannot hide in a
# table nobody counted.
_TOUCHED_TABLES = (
    "reading_items", "memories", "messages", "commitments", "events",
    "rooms", "threads",
)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    # The SAME codec the production pool installs (api/main.py lifespan). A
    # bare connection returns JSONB as text, so without this the adapters
    # would be tested against a row shape production never produces.
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


async def _msg(db, mid, thread, seq, at, content, metadata=None,
               speaker="llm_primary", user_id=None):
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
               speaker_type, user_id, message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,$5,$6,'text',$7,false,$8::jsonb)""",
        mid, thread, seq, at, speaker, user_id, content, metadata,
    )


@pytest_asyncio.fixture
async def workroom(db):
    """One room carrying every projectable entity, plus a second room whose
    content must never appear in the first room's projection."""
    tx = db.transaction()
    await tx.start()

    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')",
        AMO, _d(40))
    for rid, nm in ((ROOM, "Scheme Room"), (OTHER, "Other Room")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, _d(30), f"workspace-{rid}", nm)
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            rid, AMO, _d(30))
    for tid, rid in ((TH, ROOM), (TH_OTHER, OTHER)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            tid, rid, _d(30))

    # --- reading + its memory twin: TWO rows, ONE thing -------------------
    await db.execute(
        """INSERT INTO reading_items (room_id,url,title,site,content,summary,
               source,created_at)
           VALUES ($1,$2,$3,'example.test','body','What it said','proposal',$4)""",
        ROOM, READING_URL, READING_TITLE, _d(2))
    from llm.reading import _reading_key
    twin_key = _reading_key({"url": READING_URL, "title": READING_TITLE})
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status)
           VALUES ($1,$2,$3,$3,'llm',$4,'What it said — example.test','active')""",
        _uid(0xC41), ROOM, _d(2), twin_key)

    # --- an ordinary room memory: the Dossier entry ------------------------
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status)
           VALUES ($1,$2,$3,$3,'room','Brent crude pricing',
                   'Amo holds that Brent leads the cascade','active')""",
        _uid(0xC42), ROOM, _d(3))

    # --- research brief ----------------------------------------------------
    await _msg(db, M_BRIEF, TH, 1, _d(4),
               "Does the strait close?\n\nFindings: no.", {"source": "deep_dive"})

    # --- proposals: four slots on one message, one on another --------------
    await _msg(db, M_PROPOSALS, TH, 2, _d(1), "Proposal carrier", {
        "proposal": {"statement": "Brent over 90 by October",
                     "confidence": 0.6, "deadline": "2026-10-01",
                     "accepted": False},
        "thesis_proposal": {"title": "Strait risk", "claim": "c",
                            "monthly_budget": 5000},
        "reading_proposal": {"url": "https://example.test/draft",
                             "title": "Draft", "summary": "s",
                             "accepted": False},
        "commitment_proposals": [{"claim": "I close before CPI",
                                  "resolution_criteria": "flat",
                                  "category": "commitment", "accepted": True}],
    })
    await _msg(db, M_RESOLVE, TH, 3, _d(1), "Resolution proposed", {
        "source": "prediction_watch",
        "resolution_proposal": {
            "prediction_id": "p1", "statement": "Brent over 90",
            "verdict": "correct", "rationale": "r", "accepted": False,
        },
    })

    # --- commitment --------------------------------------------------------
    await db.execute(
        """INSERT INTO commitments (id,room_id,thread_id,claim,resolution_criteria,
               category,deadline,status,created_at)
           VALUES ($1,$2,$3,'Close before CPI','flat','commitment',$4,'active',$5)""",
        _uid(0xC51), ROOM, TH, BASE + timedelta(hours=12), _d(5))

    # --- thesis: the room's book, its snapshot, and its state memory -------
    await db.execute(
        """UPDATE rooms SET linked_book_id = 'strait-risk-graph',
               trading_config = $2::jsonb WHERE id = $1""",
        ROOM,
        {"v": 3, "title": "Strait Risk", "thesisId": "strait-risk-graph",
         "revision": 7, "timestamp": "2026-08-12T09:00:00+00:00",
         "cascadePhase": "watching"})
    from api.trading_ingest import THESIS_STATE_MEMORY_KEY
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status)
           VALUES ($1,$2,$3,$3,'llm',$4,'Strait Risk — watching','active')""",
        _uid(0xC43), ROOM, _d(1), THESIS_STATE_MEMORY_KEY)

    # --- record: an operation event ----------------------------------------
    await db.execute(
        """INSERT INTO events (id,timestamp,event_type,room_id,thread_id,payload)
           VALUES ($1,$2,'THESIS_CREATED',$3,$4,'{"book_id":"strait-risk-graph"}'::jsonb)""",
        _uid(0xC61), _d(6), ROOM, TH)

    # --- the other room: one of everything, all sentinel-marked ------------
    await db.execute(
        """INSERT INTO reading_items (room_id,url,title,content,summary,source,created_at)
           VALUES ($1,'https://other.test/1','OTHER-ROOM-SENTINEL','b','OTHER-ROOM-SENTINEL',
                   'proposal',$2)""",
        OTHER, _d(1))
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status)
           VALUES ($1,$2,$3,$3,'room','OTHER-ROOM-SENTINEL','OTHER-ROOM-SENTINEL','active')""",
        _uid(0xC44), OTHER, _d(1))
    await _msg(db, M_OTHER, TH_OTHER, 1, _d(1), "OTHER-ROOM-SENTINEL",
               {"source": "deep_dive"})
    await db.execute(
        """INSERT INTO commitments (id,room_id,thread_id,claim,resolution_criteria,
               category,deadline,status,created_at)
           VALUES ($1,$2,$3,'OTHER-ROOM-SENTINEL','x','commitment',$4,'active',$5)""",
        _uid(0xC52), OTHER, TH_OTHER, BASE + timedelta(hours=12), _d(5))

    yield db
    await tx.rollback()


# ---------------------------------------------------------------------------
# C1 — one contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_adapter_kind_is_projected(workroom):
    """C2: each entity in the adapter list reaches the same shape."""
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    kinds = {o.kind for o in objects}
    expected = set(WORKSPACE_OBJECT_KINDS) - {"house_movement"}
    assert kinds == expected, f"missing: {expected - kinds}"


@pytest.mark.asyncio
async def test_house_movement_reuses_the_house_projection(workroom):
    """C2 says reuse, do not refork: movement projects from B's own model."""
    from home_activity import HomeActivityMovement

    mv = HomeActivityMovement(
        kind="reading_filed", room_id=ROOM, thread_id=TH,
        object_id=_uid(0xC71), title="Filed", state="proposal",
        requires_judgment=False, occurred_at=_d(1),
        destination=f"/?room={ROOM}&thread={TH}",
    )
    obj = workspace_object_from_movement(mv)
    assert obj.kind == "house_movement"
    assert obj.room_id == ROOM and obj.branch_id == TH
    assert obj.status == "proposal"
    assert obj.review_state == "none"
    # The destination the House already computed travels with the object; the
    # adapter does not invent a second URL grammar.
    assert obj.relationships[0].id == mv.destination


@pytest.mark.asyncio
async def test_vocabularies_are_closed(workroom):
    """Every emitted value comes from a frozen vocabulary — no free text in the
    fields a surface switches on."""
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    assert objects
    for o in objects:
        assert o.kind in WORKSPACE_OBJECT_KINDS
        assert o.review_state in WORKSPACE_REVIEW_STATES, o.kind
        assert o.provenance.origin in WORKSPACE_ORIGINS, o.kind
        for action in o.available_actions:
            assert action in WORKSPACE_ACTIONS, (o.kind, action)
        assert o.id and o.title and o.status
        assert o.created_at is not None and o.updated_at is not None


@pytest.mark.asyncio
async def test_object_ids_are_unique_and_stable(workroom):
    svc = WorkspaceObjectService(workroom)
    first = await svc.build(ROOM, AMO)
    second = await svc.build(ROOM, AMO)
    ids = [o.id for o in first]
    assert len(ids) == len(set(ids)), "duplicate object ids"
    assert ids == [o.id for o in second], "ids are not stable across reads"


# ---------------------------------------------------------------------------
# C3 — the twin rule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reading_and_its_twin_project_as_one_object(workroom):
    """THE guard. Two real rows describe one thing; one object carries both.

    A naive adapter emits two entries that both look plausible on screen —
    only the count catches it.
    """
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    readings = [o for o in objects if o.kind == "reading"]
    assert len(readings) == 1, f"the twin split into {len(readings)} objects"

    entities = {(ref.entity, ref.id) for ref in readings[0].source_entity}
    tables = {e for e, _ in entities}
    assert tables == {"reading_items", "memories"}, (
        f"the object does not carry both source references: {tables}")

    # And the twin must not ALSO appear as a Dossier entry.
    dossier_keys = {o.title for o in objects if o.kind == "dossier_entry"}
    assert not any(k.startswith("reading:") for k in dossier_keys), dossier_keys


@pytest.mark.asyncio
async def test_dossier_sql_excludes_the_reading_namespace_by_itself(workroom):
    """Assert the guard WHERE IT LIVES.

    WHY: if the reading adapter's pairing happens to absorb every twin, a
    missing exclusion in the dossier statement is masked at the pipeline level
    — the B lesson, where deleting a fence from one UNION arm killed no test.
    This runs the dossier statement directly, so it is on the hook alone.
    """
    from workspace_objects import _DOSSIER_SQL, _PER_KIND_CAP

    rows = await workroom.fetch(_DOSSIER_SQL, ROOM, AMO, _PER_KIND_CAP)
    assert rows, "fixture produced no memories at all"
    leaked = [r["key"] for r in rows if r["key"].startswith("reading:")]
    assert not leaked, f"reading twins leaked into the dossier: {leaked}"


@pytest.mark.asyncio
async def test_an_orphan_twin_never_becomes_a_second_entry(workroom):
    """A reading re-titled after filing leaves a twin whose key no longer
    computes. It is still a twin — never a second, differently-worded entry."""
    await workroom.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status)
           VALUES ($1,$2,$3,$3,'llm','reading:example.test-an-older-title',
                   'stale twin','active')""",
        _uid(0xC45), ROOM, _d(2))

    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    assert len([o for o in objects if o.kind == "reading"]) == 1
    assert not [o for o in objects
                if o.kind == "dossier_entry" and o.title.startswith("reading:")]


@pytest.mark.asyncio
async def test_thesis_absorbs_its_state_memory(workroom):
    """The SECOND twin, found while building C: api/trading_ingest.py upserts a
    `thesis_state_current` memory that shadows rooms.trading_config. Same rule
    — one thesis, one object, both references."""
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    theses = [o for o in objects if o.kind == "thesis"]
    assert len(theses) == 1
    tables = {ref.entity for ref in theses[0].source_entity}
    assert tables == {"rooms", "memories"}, tables

    from api.trading_ingest import THESIS_STATE_MEMORY_KEY
    assert THESIS_STATE_MEMORY_KEY not in {
        o.title for o in objects if o.kind == "dossier_entry"}


# ---------------------------------------------------------------------------
# C4 — read-only, fenced, bounded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adapters_write_nothing(workroom):
    """C4: projecting changes no row and no lifecycle."""
    before = {t: await workroom.fetchval(f"SELECT count(*) FROM {t}")
              for t in _TOUCHED_TABLES}
    config_before = await workroom.fetchval(
        "SELECT trading_config::text FROM rooms WHERE id = $1", ROOM)
    statuses_before = await workroom.fetch(
        "SELECT id, status FROM memories WHERE room_id = $1 ORDER BY id", ROOM)

    await WorkspaceObjectService(workroom).build(ROOM, AMO)

    after = {t: await workroom.fetchval(f"SELECT count(*) FROM {t}")
             for t in _TOUCHED_TABLES}
    assert before == after, f"a projection wrote rows: {before} -> {after}"
    assert config_before == await workroom.fetchval(
        "SELECT trading_config::text FROM rooms WHERE id = $1", ROOM)
    assert [tuple(r) for r in statuses_before] == [
        tuple(r) for r in await workroom.fetch(
            "SELECT id, status FROM memories WHERE room_id = $1 ORDER BY id", ROOM)
    ], "a projection changed a memory's lifecycle"


@pytest.mark.asyncio
async def test_every_object_is_fenced_to_its_room(workroom):
    """No adapter may reach a room the caller did not ask for — asserted by
    value, not only by id, so a leaked field cannot hide in a preview."""
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    assert objects
    assert all(o.room_id == ROOM for o in objects)
    blob = "\n".join(o.model_dump_json() for o in objects)
    assert "OTHER-ROOM-SENTINEL" not in blob


@pytest.mark.asyncio
async def test_no_kind_can_starve_another(workroom):
    """Bounds are PER KIND, inside each adapter's own statement.

    WHY: B shipped one global newest-N and a loud room blanked every quiet one.
    The same failure here is a prolific kind evicting every other kind.
    """
    from workspace_objects import _PER_KIND_CAP

    for i in range(_PER_KIND_CAP + 10):
        await workroom.execute(
            """INSERT INTO reading_items (room_id,url,title,content,summary,
                   source,created_at)
               VALUES ($1,$2,'bulk','b','s','wire',$3)""",
            ROOM, f"https://bulk.test/{i}", BASE - timedelta(minutes=i))

    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    by_kind: dict[str, int] = {}
    for o in objects:
        by_kind[o.kind] = by_kind.get(o.kind, 0) + 1
    assert by_kind["reading"] == _PER_KIND_CAP, by_kind
    for kind in ("commitment", "thesis", "dossier_entry", "research_brief",
                 "proposal", "record_event"):
        assert by_kind.get(kind, 0) > 0, f"{kind} was starved: {by_kind}"


@pytest.mark.asyncio
async def test_proposals_carry_stable_source_coordinates(workroom):
    """Every proposal slot projects, with the coordinate D's envelope needs."""
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    proposals = [o for o in objects if o.kind == "proposal"]
    kinds = {o.provenance.detail for o in proposals}
    assert kinds == {
        "prediction_draft", "thesis_proposal", "reading_draft",
        "commitment_proposal", "prediction_resolution",
    }, kinds
    for o in proposals:
        # The coordinate D's envelope needs: the message AND the exact
        # metadata slot, so D never re-parses an id string.
        ref = o.source_entity[0]
        assert ref.entity == "messages"
        assert ref.id in (str(M_PROPOSALS), str(M_RESOLVE))
        assert ref.field, f"{o.provenance.detail} lost its metadata slot"
        assert o.relationships, f"{o.provenance.detail} lost its source message"
    accepted = [o for o in proposals if o.review_state == "accepted"]
    assert [o.provenance.detail for o in accepted] == ["commitment_proposal"]
    assert [o.status for o in accepted] == ["accepted"]

    # The status is the ENVELOPE's, so the room's own state reaches the object:
    # this fixture's room already argues `strait-risk-graph`, and one thesis per
    # room means the outstanding thesis proposal has nowhere to land.
    by_detail = {o.provenance.detail: o for o in proposals}
    assert by_detail["thesis_proposal"].status == "expired"
    assert by_detail["thesis_proposal"].review_state == "none"
    assert "accept" not in by_detail["thesis_proposal"].available_actions
    for kind in ("prediction_draft", "reading_draft", "prediction_resolution"):
        assert by_detail[kind].status == "proposed", kind
        assert by_detail[kind].review_state == "awaiting_human", kind


@pytest.mark.asyncio
async def test_every_relationship_id_resolves_to_a_real_object(workroom):
    """A string shaped like an id is not an id.

    WHY this exists: the Brief's link to its proposals was built from the KIND
    while the proposal's id is built from the metadata SLOT. Four of the five
    slots differ, so the link dangled for all but one — and nothing anywhere
    complained, because nobody had followed one yet. Found when Task Group D
    collapsed the two parses into one.
    """
    await _msg(workroom, _uid(0xC35), TH, 9, _d(1), "Brief with proposals", {
        "source": "deep_dive",
        "proposal": {"statement": "s", "accepted": False},
        "reading_proposal": {"url": "https://example.test/b", "summary": "s",
                             "accepted": False},
    })
    objects = await WorkspaceObjectService(workroom).build(ROOM, AMO)
    known = {o.id for o in objects}
    dangling = [
        (o.kind, rel.id)
        for o in objects for rel in o.relationships
        if rel.entity in ("proposal", "workspace_object") and rel.id not in known
    ]
    assert not dangling, f"relationship ids point at nothing: {dangling}"
    # And the guard is not vacuous: the fixture really does carry such links.
    assert [
        rel for o in objects for rel in o.relationships
        if rel.entity == "proposal"
    ], "no brief-to-proposal link in the fixture at all"


@pytest.mark.asyncio
async def test_a_room_without_a_book_projects_no_thesis(db):
    """The adapter is 0-or-1 on the book, not 1-per-room.

    Stated precisely, because the weaker reading would be vacuous: this asserts
    that a room with no linked_book_id yields NO thesis object. That is what
    makes §10.6 hold for Home — Home can never own a thesis, so it can never
    carry a book, so it can never project one. The refusal itself lives in
    api/thesis_relay.py and is tested there.
    """
    tx = db.transaction()
    await tx.start()
    try:
        home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
        assert home_id is not None, "no Home room in the test database"
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,now(),'Amo')",
            AMO)
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,now())",
            home_id, AMO)
        objects = await WorkspaceObjectService(db).build(home_id, AMO)
        assert not [o for o in objects if o.kind == "thesis"]
    finally:
        await tx.rollback()
