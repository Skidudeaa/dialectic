"""
Real-Postgres contracts for the Atlas projection (atlas_objects.py).

WHY real Postgres: the invariant that matters most — the PER-VIEWER fence,
on both sides of a cross-room edge — is a property of what the SQL returns
under two DIFFERENT eligible-room arrays. A mocked DB would assert a query
shape, not that two different viewers of the SAME data get two different
answers.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/014_reading_library.sql
    psql dialectic_test -f migrations/017_field_marks.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from atlas_objects import (
    ATLAS_EDGE_KINDS,
    ATLAS_NODE_KINDS,
    AtlasService,
)
from field_marks import compute_dedup_key
from geo_scopes import insert_scope
from world_signals import WorldSignal, WorldSignalSnapshot, WorldSignalStore

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-a000-{n:012x}")


AMO, DAN = _uid(0x001), _uid(0x002)
ROOM_SHARED, ROOM_AMO, ROOM_DAN = _uid(0x011), _uid(0x012), _uid(0x013)
TH_SHARED, TH_SHARED_CHILD, TH_AMO, TH_DAN = (
    _uid(0x021), _uid(0x022), _uid(0x023), _uid(0x024),
)
M_BRIEF, M_READING_SRC, M_CLAIM = _uid(0x031), _uid(0x032), _uid(0x033)
R_SHARED, R_CLAIM, R_AMO, R_DAN = (
    _uid(0x041), _uid(0x042), _uid(0x043), _uid(0x044),
)
MEM_A, MEM_A_SUCCESSOR, MEM_B, MEM_B_SUCCESSOR, MEM_ECHO = (
    _uid(0x051), _uid(0x052), _uid(0x053), _uid(0x054), _uid(0x055),
)
C_DUE, C_NOTDUE = _uid(0x061), _uid(0x062)
FM_OPEN, FM_SUPERSEDED, FM_OTHER_RELATION, FM_REVIEW = (
    _uid(0x071), _uid(0x072), _uid(0x073), _uid(0x081),
)
CLAIM_URL = "https://example.test/atlas/claim-checked-article"


def _d(days: float, base: datetime) -> datetime:
    return base - timedelta(days=days)


# Every table an Atlas statement reads. Read-only is asserted against this
# exact list, the same style test_workspace_objects_pg.py uses.
_TOUCHED_TABLES = (
    "rooms", "threads", "messages", "reading_items", "memories",
    "commitments", "field_marks", "memory_references", "geo_scopes",
)

# What entity → (table, id_column) an edge endpoint may resolve against, for
# the "every edge's endpoints resolve to a real row" contract below.
_ENTITY_TABLES = {
    "rooms": ("rooms", "id"),
    "threads": ("threads", "id"),
    "messages": ("messages", "id"),
    "memories": ("memories", "id"),
    "reading_items": ("reading_items", "id"),
}


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


async def _msg(db, mid, thread, seq, at, content, metadata=None,
               speaker="human", user_id=None):
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at,
               speaker_type, user_id, message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,$5,$6,'text',$7,false,$8::jsonb)""",
        mid, thread, seq, at, speaker, user_id, content, metadata,
    )


async def _relation_mark(db, mid, room, thread, relation, title, at,
                          subjects=None, origin="explicit", provenance="human",
                          actor=None):
    subjects = subjects or []
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, created_at, dedup_key,
                actor_user_id)
           VALUES ($1,$2,$3,'relation',$4,$5,$6,$7::jsonb,$8,$9,$10,$11)""",
        mid, room, thread, relation, origin, provenance, subjects, title, at,
        compute_dedup_key(relation, subjects), actor,
    )


@pytest_asyncio.fixture
async def atlas_world(db):
    """Two users of OVERLAPPING-BUT-DIFFERENT memberships, plus one room each
    that only ONE of them can see. Every entity kind Atlas projects gets at
    least one row, and the sentinel-only rooms carry sentinel-marked content
    so the fence test can assert by VALUE, not just by id."""
    tx = db.transaction()
    await tx.start()
    NOW = datetime.now(timezone.utc)

    def d(days):
        return _d(days, NOW)

    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo'),($3,$2,'Dan')",
        AMO, d(60), DAN,
    )
    for rid, name in (
        (ROOM_SHARED, "Shared Room"),
        (ROOM_AMO, "AMO-ONLY-SENTINEL"),
        (ROOM_DAN, "DAN-ONLY-SENTINEL"),
    ):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, d(40), f"atlas-{rid}", name,
        )
    for rid, uid in (
        (ROOM_SHARED, AMO), (ROOM_SHARED, DAN),
        (ROOM_AMO, AMO), (ROOM_DAN, DAN),
    ):
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            rid, uid, d(40),
        )

    # --- branches: a genealogy pair in the shared room -----------------
    await db.execute(
        "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
        TH_SHARED, ROOM_SHARED, d(30),
    )
    await db.execute(
        """INSERT INTO threads (id,room_id,created_at,parent_thread_id,title)
           VALUES ($1,$2,$3,$4,'A branch')""",
        TH_SHARED_CHILD, ROOM_SHARED, d(10), TH_SHARED,
    )
    await db.execute(
        "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
        TH_AMO, ROOM_AMO, d(30),
    )
    await db.execute(
        "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
        TH_DAN, ROOM_DAN, d(30),
    )

    # --- thesis: shared room only ---------------------------------------
    await db.execute(
        """UPDATE rooms SET linked_book_id = 'atlas-thesis-graph',
               trading_config = $2::jsonb WHERE id = $1""",
        ROOM_SHARED,
        {"title": "Atlas Thesis", "cascadePhase": "watching"},
    )

    # --- reading + its source message, in the shared room ---------------
    await _msg(db, M_READING_SRC, TH_SHARED, 1, d(5), "Read this")
    await db.execute(
        """INSERT INTO reading_items (id,room_id,url,title,site,content,summary,
               source,source_message_id,created_at)
           VALUES ($1,$2,$3,'Shared Reading','example.test','b','s','proposal',$4,$5)""",
        R_SHARED, ROOM_SHARED, "https://example.test/atlas/shared",
        M_READING_SRC, d(4),
    )

    # --- research brief, in the shared room ------------------------------
    await _msg(db, M_BRIEF, TH_SHARED, 2, d(3),
               "Does the strait close?\n\nFindings: no.", {"source": "deep_dive"})

    # --- commitments: one due, one not, in the shared room ---------------
    await db.execute(
        """INSERT INTO commitments (id,room_id,thread_id,claim,resolution_criteria,
               category,deadline,status,created_at)
           VALUES ($1,$2,$3,'Close before CPI','flat','commitment',$4,'active',$5)""",
        C_DUE, ROOM_SHARED, TH_SHARED, NOW + timedelta(hours=6), d(2),
    )
    await db.execute(
        """INSERT INTO commitments (id,room_id,thread_id,claim,resolution_criteria,
               category,deadline,status,created_at)
           VALUES ($1,$2,$3,'Long-range bet','flat','commitment',$4,'active',$5)""",
        C_NOTDUE, ROOM_SHARED, TH_SHARED, NOW + timedelta(days=45), d(2),
    )

    # --- unresolved work: one open question, one superseded, one wrong
    #     relation (must NOT surface as unresolved work) -------------------
    # Distinct subjects on each -- compute_dedup_key is relation+subjects, so
    # three empty-subject rows of the same relation would collide on the
    # (room_id, dedup_key) partial unique index.
    await _relation_mark(
        db, FM_OPEN, ROOM_SHARED, TH_SHARED, "unanswered_question",
        "Does the strait close?", d(2),
        subjects=[{"entity": "messages", "id": str(M_BRIEF), "field": None}],
    )
    await _relation_mark(
        db, FM_SUPERSEDED, ROOM_SHARED, TH_SHARED, "unanswered_question",
        "Already answered", d(6),
        subjects=[{"entity": "messages", "id": str(M_CLAIM), "field": None}],
    )
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
                provenance, created_at, payload)
           VALUES ($1,$2,'review','supersede',$3,$4,'human',$5,'{}'::jsonb)""",
        FM_REVIEW, ROOM_SHARED, FM_SUPERSEDED, AMO, d(1),
    )
    await _relation_mark(
        db, FM_OTHER_RELATION, ROOM_SHARED, TH_SHARED, "claim_group",
        "Not a question", d(2),
        subjects=[{"entity": "commitments", "id": str(C_DUE), "field": None}],
    )

    # --- memory supersession: one ordinary restatement, one INVALIDATED
    #     (the contradiction-proxy signal) -- successor inserted FIRST, since
    #     superseded_by_memory_id is a real FK into this same table. --------
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,content,status)
           VALUES ($1,$2,$3,$3,'room','brent-view','New view','active')""",
        MEM_A_SUCCESSOR, ROOM_SHARED, d(1),
    )
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status,superseded_at,superseded_by_memory_id)
           VALUES ($1,$2,$3,$3,'room','brent-view','Old view','superseded',$4,$5)""",
        MEM_A, ROOM_SHARED, d(10), d(1), MEM_A_SUCCESSOR,
    )
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,content,status)
           VALUES ($1,$2,$3,$3,'room','contested-fact','Corrected claim','active')""",
        MEM_B_SUCCESSOR, ROOM_SHARED, d(1),
    )
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,
               content,status,superseded_at,superseded_by_memory_id,
               invalidated_by_user_id,invalidated_at,invalidation_reason)
           VALUES ($1,$2,$3,$3,'room','contested-fact','Wrong claim','superseded',
                   $4,$5,$6,$4,'CONTRADICTS-SENTINEL')""",
        MEM_B, ROOM_SHARED, d(8), d(1), MEM_B_SUCCESSOR, AMO,
    )

    # --- claim_check contradiction proxy: message + matching reading -----
    await _msg(db, M_CLAIM, TH_SHARED, 3, d(1), "Article says X",
               {"claim_check": {"url": CLAIM_URL, "title": "t",
                                 "verdict": "mixed", "note": "overstated"}})
    await db.execute(
        """INSERT INTO reading_items (id,room_id,url,title,site,content,summary,
               source,created_at)
           VALUES ($1,$2,$3,'Claimed Article','example.test','b','s','proposal',$4)""",
        R_CLAIM, ROOM_SHARED, CLAIM_URL, d(1),
    )

    # --- echo citation: a memory in AMO's room-only, citing the shared
    #     room's brief message. This is the fence's sharpest test: it must
    #     appear ONLY for AMO (both endpoints eligible), never for DAN (the
    #     source room, ROOM_AMO, is not in Dan's eligible array at all). ---
    await db.execute(
        """INSERT INTO memories (id,room_id,created_at,updated_at,scope,key,content,status)
           VALUES ($1,$2,$3,$3,'llm','echo','ECHO-SENTINEL content','active')""",
        MEM_ECHO, ROOM_AMO, d(2),
    )
    await db.execute(
        """INSERT INTO memory_references
               (id, source_memory_id, target_room_id, target_message_id,
                referenced_at, citation_context)
           VALUES (gen_random_uuid(),$1,$2,$3,$4,'ECHO-SENTINEL')""",
        MEM_ECHO, ROOM_SHARED, M_BRIEF, d(1),
    )

    # --- sentinel content in each solo room, so the fence test can assert
    #     by VALUE -----------------------------------------------------------
    await db.execute(
        """INSERT INTO reading_items (id,room_id,url,title,site,content,summary,
               source,created_at)
           VALUES ($1,$2,'https://example.test/amo-only','AMO-ONLY-SENTINEL',
                   'example.test','b','AMO-ONLY-SENTINEL','proposal',$3)""",
        R_AMO, ROOM_AMO, d(1),
    )
    await db.execute(
        """INSERT INTO reading_items (id,room_id,url,title,site,content,summary,
               source,created_at)
           VALUES ($1,$2,'https://example.test/dan-only','DAN-ONLY-SENTINEL',
                   'example.test','b','DAN-ONLY-SENTINEL','proposal',$3)""",
        R_DAN, ROOM_DAN, d(1),
    )

    yield db
    await tx.rollback()


def _blob(projection) -> str:
    return "\n".join([n.model_dump_json() for n in projection.nodes]
                      + [e.model_dump_json() for e in projection.edges])


# ---------------------------------------------------------------------------
# the per-viewer fence, by value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_atlas_is_fenced_to_the_callers_own_memberships(atlas_world):
    amo_atlas = await AtlasService(atlas_world).build(AMO)
    dan_atlas = await AtlasService(atlas_world).build(DAN)

    amo_blob, dan_blob = _blob(amo_atlas), _blob(dan_atlas)

    # Each viewer sees their own solo room...
    assert "AMO-ONLY-SENTINEL" in amo_blob
    assert "DAN-ONLY-SENTINEL" in dan_blob
    # ...and never the other's.
    assert "DAN-ONLY-SENTINEL" not in amo_blob
    assert "AMO-ONLY-SENTINEL" not in dan_blob

    # Both see the shared room.
    assert "Shared Room" in amo_blob
    assert "Shared Room" in dan_blob


@pytest.mark.asyncio
async def test_cross_room_edge_is_fenced_on_both_endpoints(atlas_world):
    """The sharpest fence case: an Echo citation whose SOURCE room (AMO-only)
    is not in Dan's eligible array at all, even though its TARGET room
    (Shared) is. Fencing only the target would leak this edge to Dan."""
    amo_atlas = await AtlasService(atlas_world).build(AMO)
    dan_atlas = await AtlasService(atlas_world).build(DAN)

    assert "ECHO-SENTINEL" in _blob(amo_atlas)
    assert "ECHO-SENTINEL" not in _blob(dan_atlas)

    echo_edges = [e for e in amo_atlas.edges if e.kind == "echo_citation"]
    assert echo_edges
    assert all(e.label != "" for e in echo_edges if e.kind == "echo_citation")


@pytest.mark.asyncio
async def test_a_caller_with_no_memberships_is_an_empty_projection(atlas_world):
    """No FK to `users` is touched by the eligible-room query itself -- a
    user id with zero room_memberships rows is a legitimate empty result,
    not an error, and no real row needs to exist to prove it."""
    stranger = _uid(0x999)
    projection = await AtlasService(atlas_world).build(stranger)
    assert projection.nodes == []
    assert projection.edges == []

    now = datetime.now(timezone.utc)
    configured = WorldSignalStore()
    configured.replace(WorldSignalSnapshot(
        provider="ais", configured_room_ids=frozenset({ROOM_AMO}),
        source_state="partial", freshness="current", coverage="PRIVATE-COVERAGE",
        observed_at=now - timedelta(minutes=2), retrieved_at=now,
        expires_at=now + timedelta(minutes=10), signals=(),
    ))
    signal_projection = await AtlasService(
        atlas_world, signal_store=configured,
    ).build(stranger, include_signals=True)
    assert signal_projection.signals == []
    assert signal_projection.signal_sources.status == "not_configured"
    assert signal_projection.signal_sources.sources == []
    assert "PRIVATE-COVERAGE" not in signal_projection.model_dump_json()


@pytest.mark.asyncio
async def test_signal_opt_in_uses_the_exact_atlas_eligible_room_fence(atlas_world):
    now = datetime.now(timezone.utc)
    store = WorldSignalStore()

    def signal(source_id: str, room_id: UUID) -> WorldSignal:
        return WorldSignal(
            id=f"world_signal:ais:{source_id}", provider="ais", source_id=source_id,
            room_id=room_id, layer="vessels", kind="point",
            geometry={"type": "Point", "coordinates": [56.3, 26.5]},
            provenance={
                "provider": "ais", "acquisition": "adapter:ais",
                "source_id": source_id, "credit": "AIS provider credit",
            },
            source_state="partial", freshness="current",
            coverage="receiver footprint", observed_at=now - timedelta(minutes=2),
            retrieved_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=10), label=source_id,
        )

    store.replace(WorldSignalSnapshot(
        provider="ais",
        configured_room_ids=frozenset({ROOM_SHARED, ROOM_AMO, ROOM_DAN}),
        source_state="partial", freshness="current",
        coverage="receiver footprint", retrieved_at=now,
        expires_at=now + timedelta(minutes=10),
        signals=(
            signal("shared", ROOM_SHARED), signal("amo-only", ROOM_AMO),
            signal("dan-only", ROOM_DAN),
        ),
    ))

    amo = await AtlasService(atlas_world, signal_store=store).build(AMO, include_signals=True)
    dan = await AtlasService(atlas_world, signal_store=store).build(DAN, include_signals=True)

    assert {signal.source_id for signal in amo.signals} == {"shared", "amo-only"}
    assert {signal.source_id for signal in dan.signals} == {"shared", "dan-only"}
    assert amo.signal_sources.sources[0].source_state == "partial"
    assert amo.signal_sources.sources[0].freshness == "current"
    assert amo.signal_sources.sources[0].coverage == "receiver footprint"
    assert amo.signal_sources.sources[0].configured_room_ids == frozenset({ROOM_SHARED, ROOM_AMO})
    assert dan.signal_sources.sources[0].configured_room_ids == frozenset({ROOM_SHARED, ROOM_DAN})


@pytest.mark.asyncio
async def test_disjoint_signal_source_envelope_does_not_leak_through_atlas(atlas_world):
    now = datetime.now(timezone.utc)
    store = WorldSignalStore()
    store.replace(WorldSignalSnapshot(
        provider="firms", configured_room_ids=frozenset({ROOM_DAN}),
        source_state="rate_limited", freshness="stale", coverage="DAN-ONLY-COVERAGE",
        observed_at=now - timedelta(hours=1), retrieved_at=now,
        expires_at=now + timedelta(minutes=5), signals=(),
    ))

    amo = await AtlasService(atlas_world, signal_store=store).build(AMO, include_signals=True)
    assert amo.signal_sources.status == "not_configured"
    assert amo.signal_sources.sources == []
    assert "DAN-ONLY-COVERAGE" not in amo.model_dump_json()


@pytest.mark.asyncio
async def test_configured_empty_source_remains_configured_for_an_eligible_room(atlas_world):
    now = datetime.now(timezone.utc)
    store = WorldSignalStore()
    store.replace(WorldSignalSnapshot(
        provider="ais", configured_room_ids=frozenset({ROOM_AMO}),
        source_state="ok", freshness="current", coverage="Amo receiver",
        observed_at=now, retrieved_at=now, expires_at=None, signals=(),
    ))

    amo = await AtlasService(atlas_world, signal_store=store).build(AMO, include_signals=True)
    dan = await AtlasService(atlas_world, signal_store=store).build(DAN, include_signals=True)
    assert amo.signals == []
    assert amo.signal_sources.status == "configured"
    assert amo.signal_sources.sources[0].signal_count == 0
    assert amo.signal_sources.sources[0].configured_room_ids == frozenset({ROOM_AMO})
    assert dan.signal_sources.status == "not_configured"
    assert dan.signal_sources.sources == []


@pytest.mark.asyncio
async def test_signal_fields_do_not_exist_without_opt_in(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    assert set(projection.model_dump()) == {"generated_at", "nodes", "edges", "scopes"}


@pytest.mark.asyncio
async def test_enhanced_atlas_projects_scope_root_and_shared_causal_binding(atlas_world):
    now = datetime.now(timezone.utc)
    provenance = {
        "provider": "human",
        "acquisition": "human",
        "source_id": "atlas-synapse-test",
        "credit": "Synthetic test fixture",
    }
    root_scope_id = await insert_scope(
        atlas_world,
        room_id=ROOM_SHARED,
        subject={"entity": "rooms", "id": str(ROOM_SHARED)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        label="Original Hormuz evidence",
        authority="human_confirmed",
        provenance=provenance,
        confirmed_by=AMO,
        revision_action="place",
        created_by=AMO,
        now=now,
    )
    current_scope_id = await insert_scope(
        atlas_world,
        room_id=ROOM_SHARED,
        subject={"entity": "rooms", "id": str(ROOM_SHARED)},
        kind="point",
        geometry={"type": "Point", "coordinates": [56.4, 26.6]},
        label="Current Hormuz evidence",
        authority="human_confirmed",
        provenance=provenance,
        confirmed_by=AMO,
        supersedes_id=root_scope_id,
        revision_action="redraw",
        created_by=AMO,
        now=now + timedelta(seconds=1),
    )
    mark_id = uuid4()
    subjects = [
        {"entity": "geo_scopes", "id": str(root_scope_id)},
        {
            "entity": "rooms",
            "id": str(ROOM_SHARED),
            "field": "thesis_node:atlas-thesis-graph:shipping",
        },
    ]
    await atlas_world.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, payload, actor_user_id,
                created_at, dedup_key)
           VALUES ($1,$2,$3,'relation','supports','explicit','human',$4,$5,$6,
                   $7,$8,$9)""",
        mark_id,
        ROOM_SHARED,
        TH_SHARED,
        subjects,
        "Hormuz supports shipping",
        {"node_label": "Shipping chokepoint"},
        AMO,
        now + timedelta(seconds=2),
        compute_dedup_key("supports", subjects),
    )
    await atlas_world.execute(
        """INSERT INTO field_marks
               (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
                provenance, created_at, payload)
           VALUES ($1,$2,'review','confirm',$3,$4,'human',$5,'{}'::jsonb)""",
        uuid4(), ROOM_SHARED, mark_id, AMO, now + timedelta(seconds=3),
    )

    projection = await AtlasService(atlas_world).build(AMO, include_signals=True)

    scope = next(
        item for item in projection.scopes
        if item.id == f"geo_scope:{current_scope_id}"
    )
    assert scope.lineage_root_id == f"geo_scope:{root_scope_id}"
    assert projection.causal_bindings_total == 1
    assert projection.causal_bindings_omitted == 0
    assert projection.causal_bindings_complete is True
    assert projection.causal_bindings[0].model_dump(mode="json") == {
        "id": f"field_mark:{mark_id}",
        "current_scope_id": f"geo_scope:{current_scope_id}",
        "evidence_scope_id": f"geo_scope:{root_scope_id}",
        "relation": "supports",
        "review_state": "confirmed",
        "provisional": False,
        "target": {
            "room_id": str(ROOM_SHARED),
            "book_id": "atlas-thesis-graph",
            "node_id": "shipping",
            "node_label": "Shipping chokepoint",
        },
    }


@pytest.mark.asyncio
async def test_enhanced_atlas_causal_binding_never_crosses_viewer_fence(atlas_world):
    now = datetime.now(timezone.utc)
    scope_id = await insert_scope(
        atlas_world,
        room_id=ROOM_AMO,
        subject={"entity": "rooms", "id": str(ROOM_AMO)},
        kind="point",
        geometry={"type": "Point", "coordinates": [10.0, 10.0]},
        label="AMO-ONLY-SCOPE-SENTINEL",
        authority="human_confirmed",
        provenance={
            "provider": "human", "acquisition": "human",
            "source_id": "amo-only", "credit": "Synthetic test fixture",
        },
        confirmed_by=AMO,
        revision_action="place",
        created_by=AMO,
        now=now,
    )
    mark_id = uuid4()
    subjects = [
        {"entity": "geo_scopes", "id": str(scope_id)},
        {
            "entity": "rooms", "id": str(ROOM_AMO),
            "field": "thesis_node:amo-only-book:sentinel",
        },
    ]
    await atlas_world.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, payload, actor_user_id,
                created_at, dedup_key)
           VALUES ($1,$2,$3,'relation','challenges','explicit','human',$4,$5,$6,
                   $7,$8,$9)""",
        mark_id,
        ROOM_AMO,
        TH_AMO,
        subjects,
        "AMO-ONLY-CAUSAL-SENTINEL",
        {"node_label": "AMO-ONLY-NODE-SENTINEL"},
        AMO,
        now,
        compute_dedup_key("challenges", subjects),
    )

    amo = await AtlasService(atlas_world).build(AMO, include_signals=True)
    dan = await AtlasService(atlas_world).build(DAN, include_signals=True)

    assert "AMO-ONLY-CAUSAL-SENTINEL" not in amo.model_dump_json()
    assert f"field_mark:{mark_id}" in amo.model_dump_json()
    assert "AMO-ONLY-NODE-SENTINEL" in amo.model_dump_json()
    assert f"field_mark:{mark_id}" not in dan.model_dump_json()
    assert "AMO-ONLY-NODE-SENTINEL" not in dan.model_dump_json()


# ---------------------------------------------------------------------------
# node/edge coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_node_kind_is_projected(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    kinds = {n.kind for n in projection.nodes}
    assert kinds == set(ATLAS_NODE_KINDS), kinds


@pytest.mark.asyncio
async def test_unresolved_work_excludes_superseded_and_wrong_relation(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    questions = {n.title for n in projection.nodes if n.kind == "field_mark"}
    assert "Does the strait close?" in questions
    assert "Already answered" not in questions
    assert "Not a question" not in questions


@pytest.mark.asyncio
async def test_due_commitment_is_flagged_and_not_due_is_not(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    commitments = {n.title: n.due for n in projection.nodes if n.kind == "commitment"}
    assert commitments["Close before CPI"] is True
    assert commitments["Long-range bet"] is False


@pytest.mark.asyncio
async def test_every_edge_kind_backing_is_present(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    kinds = {e.kind for e in projection.edges}
    # contradiction_proxy fires from BOTH its sources here (an invalidated
    # memory and a claim_check verdict) -- both must be represented, not just
    # whichever one happened first.
    assert kinds == set(ATLAS_EDGE_KINDS), kinds
    contradiction_labels = {
        e.label for e in projection.edges if e.kind == "contradiction_proxy"
    }
    assert "CONTRADICTS-SENTINEL" in contradiction_labels
    assert "mixed" in contradiction_labels


@pytest.mark.asyncio
async def test_every_edge_endpoint_resolves_to_a_real_row(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    assert projection.edges
    for edge in projection.edges:
        for ref in (edge.source, edge.target):
            table, id_col = _ENTITY_TABLES[ref.entity]
            found = await atlas_world.fetchval(
                f"SELECT 1 FROM {table} WHERE {id_col} = $1", UUID(ref.id),
            )
            assert found, f"{edge.kind}: {ref.entity}:{ref.id} does not resolve"


@pytest.mark.asyncio
async def test_branch_genealogy_edge_names_parent_and_child(atlas_world):
    projection = await AtlasService(atlas_world).build(AMO)
    genealogy = [e for e in projection.edges if e.kind == "branch_genealogy"]
    assert any(
        e.source.id == str(TH_SHARED_CHILD) and e.target.id == str(TH_SHARED)
        for e in genealogy
    )


@pytest.mark.asyncio
async def test_atlas_writes_nothing(atlas_world):
    """Read-only by construction -- a count snapshot across every touched
    table, before and after a build, must be identical."""
    async def counts():
        return {
            t: await atlas_world.fetchval(f"SELECT count(*) FROM {t}")
            for t in _TOUCHED_TABLES
        }

    before = await counts()
    await AtlasService(atlas_world).build(AMO)
    after = await counts()
    assert before == after


# ---------------------------------------------------------------------------
# bounds: per-partition, in SQL (§1.6)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_kind_can_starve_another_across_rooms(atlas_world):
    """Bounds are per (room, kind), not one global cut -- a room with a glut
    of readings must not evict a commitment from the SAME room, and must not
    evict another room's rows either."""
    from atlas_objects import _ATLAS_PER_ROOM_CAP

    for i in range(_ATLAS_PER_ROOM_CAP + 10):
        await atlas_world.execute(
            """INSERT INTO reading_items (room_id,url,title,content,summary,
                   source,created_at)
               VALUES ($1,$2,'Glut','b','s','proposal',now())""",
            ROOM_SHARED, f"https://example.test/atlas/glut/{i}",
        )

    projection = await AtlasService(atlas_world).build(AMO)
    shared_readings = [
        n for n in projection.nodes if n.kind == "reading" and n.room_id == ROOM_SHARED
    ]
    assert len(shared_readings) == _ATLAS_PER_ROOM_CAP

    # The commitment from the SAME room must still be present -- not starved
    # by the glut of readings.
    assert any(n.kind == "commitment" for n in projection.nodes)
    # The other user's solo room must still be untouched by the glut.
    dan_atlas = await AtlasService(atlas_world).build(DAN)
    assert any(n.kind == "reading" and n.title == "DAN-ONLY-SENTINEL"
               for n in dan_atlas.nodes)
