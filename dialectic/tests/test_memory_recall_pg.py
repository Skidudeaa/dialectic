"""
Integration tests for three-lane RRF recall + write-path dedup, against a real
Postgres with pgvector + pg_trgm.

WHY real Postgres: the recall and dedup logic live in SQL (RRF fusion, FTS,
trigram similarity, generated columns) — a mocked DB would test nothing. Uses
MockEmbeddings (deterministic hash vectors), so lane behavior is attributable:
identical text → cosine 1.0, different text → unrelated vectors, while FTS and
trigram operate on the real text.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio

from memory.manager import MemoryManager
from memory.embeddings import MockEmbeddings
from models import MemoryStatus

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _json_encoder(value):
    def default(obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Not JSON serializable: {type(obj)}")
    return json.dumps(value, default=default)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    await conn.set_type_codec(
        'jsonb', encoder=_json_encoder, decoder=json.loads, schema='pg_catalog'
    )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    """Fresh room with members Amo and Dan; returns ids dict."""
    room_id, amo_id, dan_id, thread_id = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    await db.execute(
        "INSERT INTO rooms (id, created_at, token) VALUES ($1, $2, $3)",
        room_id, now, f"test-{room_id}"
    )
    for uid, name in ((amo_id, "Amo"), (dan_id, "Dan")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)",
            uid, now, name
        )
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            room_id, uid, now
        )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at) VALUES ($1, $2, $3)",
        thread_id, room_id, now
    )
    return {"room": room_id, "amo": amo_id, "dan": dan_id, "thread": thread_id}


def make_manager(db) -> MemoryManager:
    mgr = MemoryManager(db)
    mgr._embedder = MockEmbeddings()
    return mgr


# ── Recall lanes ──


@pytest.mark.asyncio
async def test_fts_lane_catches_exact_terms_dense_misses(db, room):
    """A query sharing exact terms must hit via FTS even when embeddings are
    unrelated (mock vectors for different texts are unrelated by construction)."""
    mgr = make_manager(db)
    await mgr.add_memory(room["room"], "boat_deal",
                         "Dan owes Marcus three thousand from the boat deal",
                         created_by_user_id=room["amo"])
    await mgr.add_memory(room["room"], "gym_schedule",
                         "Amo lifts on Tuesday and Thursday mornings",
                         created_by_user_id=room["amo"])

    matches = await mgr.search_memories(room["room"], "boat deal", min_score=0.99)
    keys = {m.key for m in matches}
    assert "boat_deal" in keys
    hit = next(m for m in matches if m.key == "boat_deal")
    assert "fts" in hit.lanes
    # The unrelated memory must not ride in on a text lane
    assert not any(m.key == "gym_schedule" and "fts" in m.lanes for m in matches)


@pytest.mark.asyncio
async def test_speaker_lane_ranks_named_members_memories(db, room):
    """'what did Dan say' must surface Dan-attributed memories via the entity lane."""
    mgr = make_manager(db)
    await mgr.add_memory(room["room"], "dan_view",
                         "The rental property cashflow turns positive in October",
                         created_by_user_id=room["dan"])
    await mgr.add_memory(room["room"], "amo_view",
                         "Better to refinance before the rate window closes",
                         created_by_user_id=room["amo"])

    matches = await mgr.search_memories(
        room["room"], "what did Dan say about the plan", min_score=0.99
    )
    dan_hits = [m for m in matches if m.speaker_user_id == room["dan"]]
    assert dan_hits, f"expected a Dan-attributed hit, got {[(m.key, m.lanes) for m in matches]}"
    assert any("entity" in m.lanes for m in dan_hits)


@pytest.mark.asyncio
async def test_min_score_floor_applies_to_dense_only_hits(db, room):
    """With no text/speaker overlap, mock-embedding cosine (~0.7-0.8) must be
    filtered by a high min_score — dense-only hits respect the floor."""
    mgr = make_manager(db)
    await mgr.add_memory(room["room"], "solar",
                         "Panels on the cabin roof pay back in six years",
                         created_by_user_id=room["amo"])

    matches = await mgr.search_memories(room["room"], "zzqx unrelated nonsense", min_score=0.99)
    assert matches == []


@pytest.mark.asyncio
async def test_speaker_attribution_from_source_message(db, room):
    """speaker_user_id must come from the source message author, not the saver."""
    mgr = make_manager(db)
    msg_id = uuid4()
    await db.execute(
        """INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type,
                                 user_id, message_type, content)
           VALUES ($1, $2, 1, $3, 'human', $4, 'text', $5)""",
        msg_id, room["thread"], datetime.now(timezone.utc), room["dan"],
        "I want us out of the storage-unit lease by January"
    )
    mem = await mgr.add_memory(
        room["room"], "storage_lease",
        "Dan wants out of the storage-unit lease by January",
        created_by_user_id=room["amo"],       # Amo saved it
        source_message_id=msg_id,             # but Dan said it
    )
    assert mem.speaker_user_id == room["dan"]


# ── Write-path dedup ──


@pytest.mark.asyncio
async def test_exact_restatement_is_skipped(db, room):
    mgr = make_manager(db)
    first = await mgr.add_memory(room["room"], "target", "NVDA target is 150",
                                 created_by_user_id=room["dan"])
    second = await mgr.add_memory(room["room"], "target", "NVDA target is 150",
                                  created_by_user_id=room["dan"])
    assert second.id == first.id
    count = await db.fetchval(
        "SELECT count(*) FROM memories WHERE room_id = $1", room["room"])
    assert count == 1


@pytest.mark.asyncio
async def test_near_verbatim_update_supersedes(db, room):
    """A changed number in an otherwise-identical statement must replace the
    old fact, not duplicate it and not silently drop the update."""
    mgr = make_manager(db)
    old_text, new_text = "NVDA price target is 150 by June", "NVDA price target is 155 by June"
    trgm = await db.fetchval("SELECT similarity($1, $2)", old_text, new_text)
    assert trgm >= 0.85, f"fixture premise broken: trigram {trgm} not in verbatim band"

    first = await mgr.add_memory(room["room"], "nvda_target", old_text,
                                 created_by_user_id=room["dan"])
    second = await mgr.add_memory(room["room"], "nvda_target", new_text,
                                  created_by_user_id=room["dan"])
    assert second.id != first.id

    old_row = await db.fetchrow("SELECT * FROM memories WHERE id = $1", first.id)
    assert old_row["status"] == MemoryStatus.SUPERSEDED.value
    assert old_row["superseded_by_memory_id"] == second.id
    assert old_row["superseded_at"] is not None

    event = await db.fetchrow(
        "SELECT * FROM events WHERE event_type = 'memory_superseded' AND room_id = $1",
        room["room"])
    assert event is not None
    assert event["payload"]["memory_id"] == str(first.id)

    # Recall must only surface the current fact
    matches = await mgr.search_memories(room["room"], "NVDA price target", min_score=0.0)
    contents = [m.content for m in matches]
    assert new_text in contents
    assert old_text not in contents


@pytest.mark.asyncio
async def test_cross_speaker_confirmation_keeps_original(db, room):
    """Dan restates Amo's fact in different words, same key: confirmation —
    original memory and attribution are kept, no duplicate row."""
    mgr = make_manager(db)
    a = "we should sell the NVDA position before the March earnings call"
    b = "we should sell our NVDA position ahead of the March earnings"
    trgm = await db.fetchval("SELECT similarity($1, $2)", a, b)
    assert 0.55 <= trgm < 0.85, f"fixture premise broken: trigram {trgm} not mid-band"

    first = await mgr.add_memory(room["room"], "nvda_exit", a,
                                 created_by_user_id=room["amo"])
    second = await mgr.add_memory(room["room"], "nvda_exit", b,
                                  created_by_user_id=room["dan"])
    assert second.id == first.id
    assert second.speaker_user_id == room["amo"]


@pytest.mark.asyncio
async def test_distinct_facts_with_distinct_keys_coexist(db, room):
    """Two speakers with different positions on the same topic must BOTH persist."""
    mgr = make_manager(db)
    a = await mgr.add_memory(room["room"], "dan_nvda_target",
                             "Dan's NVDA exit target is 150",
                             created_by_user_id=room["dan"])
    b = await mgr.add_memory(room["room"], "amo_nvda_target",
                             "Amo's NVDA exit target is 165",
                             created_by_user_id=room["amo"])
    trgm = await db.fetchval(
        "SELECT similarity($1, $2)",
        "Dan's NVDA exit target is 150", "Amo's NVDA exit target is 165")
    assert trgm < 0.85, f"fixture premise broken: trigram {trgm} reached verbatim band"
    assert a.id != b.id
    statuses = await db.fetch(
        "SELECT status FROM memories WHERE room_id = $1", room["room"])
    assert all(r["status"] == "active" for r in statuses)


@pytest.mark.asyncio
async def test_dedup_optout_for_system_slots(db, room):
    """System-managed slots (identical placeholder text, distinct keys) must
    never collapse when the caller opts out of dedup."""
    mgr = make_manager(db)
    text = "[Protocol Dialectical Inquiry concluded — synthesis pending]"
    a = await mgr.add_memory(room["room"], "protocol:di:synthesis:aaaa1111", text,
                             dedup=False)
    b = await mgr.add_memory(room["room"], "protocol:di:synthesis:bbbb2222", text,
                             dedup=False)
    assert a.id != b.id


@pytest.mark.asyncio
async def test_embedding_stored_on_insert(db, room):
    """The single-pass insert must persist the embedding (no post-insert update)."""
    mgr = make_manager(db)
    mem = await mgr.add_memory(room["room"], "k", "some persistent fact",
                               created_by_user_id=room["amo"])
    emb = await db.fetchval("SELECT embedding FROM memories WHERE id = $1", mem.id)
    assert emb is not None
