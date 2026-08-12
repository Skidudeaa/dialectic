"""
Real-Postgres contracts for the Home activity projection (home_activity.py).

WHY real Postgres: the privacy invariant (membership intersection), the
soft-delete truth, the receipt boundaries, and the recursive branch lineage
all live in SQL — a mocked DB would test nothing.

Fixtures select the one Home committed to dialectic_test by migration 013
and add every scenario row inside a rollback transaction; no fixture
inserts a second is_home row or leaves anything behind.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/013_home_base.sql
"""

import os
import random
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

from home_activity import HomeActivityService, HomeUnavailable

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xA01)
DAN = _uid(0xA02)
OUTSIDER = _uid(0xA03)
SHARED = _uid(0xB01)
AMO_ONLY = _uid(0xB02)
T1, T2, T3, TA = _uid(0xC01), _uid(0xC02), _uid(0xC03), _uid(0xC04)
M1, M2, M4, M6, M_DEL, MA = (
    _uid(0xD01), _uid(0xD02), _uid(0xD04), _uid(0xD06), _uid(0xD07), _uid(0xD08),
)

BASE = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    yield conn
    await conn.close()


async def _insert_message(
    db, mid, thread_id, seq, created_at, speaker, user_id, content,
    *, message_type="text", is_deleted=False,
):
    await db.execute(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, is_deleted)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        mid, thread_id, seq, created_at, speaker, user_id, message_type,
        content, is_deleted,
    )


@pytest_asyncio.fixture
async def scenario(db):
    """
    Two Home members (Amo, Dan). One shared scheme room both belong to,
    one Amo-only room. Branch chain T1 <- T2 <- T3. A soft-deleted newest
    message, viewer-specific receipts, and one due commitment.
    """
    tx = db.transaction()
    await tx.start()

    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    assert home_id is not None

    for uid, name in ((AMO, "Amo"), (DAN, "Dan"), (OUTSIDER, "Outsider")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)",
            uid, _d(40), name,
        )
    for uid in (AMO, DAN):
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            home_id, uid, _d(30),
        )

    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, $4)",
        SHARED, _d(30), "scenario-shared-room", "Shared Scheme",
    )
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, $4)",
        AMO_ONLY, _d(30), "scenario-amo-room", "Amo Solo",
    )
    for room, members in ((SHARED, (AMO, DAN)), (AMO_ONLY, (AMO,))):
        for uid in members:
            await db.execute(
                "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
                room, uid, _d(30),
            )

    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, $3, $4)",
        T1, SHARED, _d(30), "Main",
    )
    await db.execute(
        """INSERT INTO threads (id, room_id, created_at, parent_thread_id, title)
           VALUES ($1, $2, $3, $4, $5)""",
        T2, SHARED, _d(20), T1, "Fork Alpha",
    )
    await db.execute(
        """INSERT INTO threads (id, room_id, created_at, parent_thread_id, title)
           VALUES ($1, $2, $3, $4, $5)""",
        T3, SHARED, _d(15), T2, "Fork Beta",
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, $3, $4)",
        TA, AMO_ONLY, _d(30), "Main",
    )

    await _insert_message(db, M1, T1, 1, _d(10), "human", AMO,
                          "Opening position on the cascade")
    await _insert_message(db, M6, T3, 1, _d(9.2), "human", AMO,
                          "Beta branch diverges here")
    await _insert_message(db, M2, T1, 2, _d(9), "human", DAN,
                          "What is the timeline for the first trigger?",
                          message_type="question")
    await _insert_message(db, M4, T2, 1, _d(2), "human", DAN,
                          "Does the second leg survive a rate cut?",
                          message_type="question")
    await _insert_message(db, M_DEL, T2, 2, _d(1), "human", DAN,
                          "DELETED-SENTINEL should never surface",
                          is_deleted=True)
    await _insert_message(db, MA, TA, 1, _d(5), "human", AMO,
                          "Solo room note")

    for mid, uid, at in (
        (M1, AMO, _d(9.5)),
        (M2, DAN, _d(8.9)),
        (M6, DAN, _d(7)),
    ):
        await db.execute(
            """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
               VALUES ($1, $2, 'read', $3)""",
            mid, uid, at,
        )

    await db.execute(
        """INSERT INTO commitments
               (room_id, thread_id, claim, resolution_criteria, category,
                deadline, status)
           VALUES
               ($1, $2, 'Close the hedge before CPI', 'position flat', 'commitment',
                $3, 'active'),
               ($1, $2, 'Far-future call', 'later', 'prediction', $4, 'active'),
               ($1, $2, 'Already settled', 'done', 'prediction', $3, 'resolved')""",
        SHARED, T1, BASE + timedelta(hours=24), BASE + timedelta(days=10),
    )

    yield SimpleNamespace(db=db, home_id=home_id)
    await tx.rollback()


def _room(projection, room_id):
    matches = [r for r in projection.rooms if r.id == room_id]
    return matches[0] if matches else None


# ── The nine projection contracts ──

@pytest.mark.asyncio
async def test_only_the_shared_room_appears(scenario):
    projection = await HomeActivityService(scenario.db).build(AMO)
    assert [r.id for r in projection.rooms] == [SHARED]


@pytest.mark.asyncio
async def test_third_home_member_contracts_the_intersection(scenario):
    await scenario.db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
        scenario.home_id, OUTSIDER, _d(1),
    )
    projection = await HomeActivityService(scenario.db).build(AMO)
    assert projection.rooms == []


@pytest.mark.asyncio
async def test_no_serialized_projection_contains_token(scenario):
    projection = await HomeActivityService(scenario.db).build(AMO)
    assert "token" not in projection.model_dump_json().lower()


@pytest.mark.asyncio
async def test_unread_counts_differ_by_viewer(scenario):
    """
    Per-thread receipt boundaries — the SAME semantics the room rail uses
    (amendment 2026-08-12: the plan's room-scoped unread boundary would
    disagree with the rail badge one panel away; branch unread needs
    per-thread boundaries anyway).
    """
    amo_view = _room(await HomeActivityService(scenario.db).build(AMO), SHARED)
    dan_view = _room(await HomeActivityService(scenario.db).build(DAN), SHARED)

    assert amo_view.unread_count == 2  # M2 in Main, M4 in Fork Alpha
    assert dan_view.unread_count == 0  # own messages never count

    by_title = {b.title: b for b in amo_view.branches}
    assert by_title["Main"].unread_count == 1
    assert by_title["Fork Alpha"].unread_count == 1
    assert by_title["Fork Beta"].unread_count == 0


@pytest.mark.asyncio
async def test_unresolved_questions_differ_with_viewer_boundary(scenario):
    amo_view = _room(await HomeActivityService(scenario.db).build(AMO), SHARED)
    dan_view = _room(await HomeActivityService(scenario.db).build(DAN), SHARED)

    assert {q.thread_id for q in amo_view.unresolved_questions} == {T1, T2}
    assert {q.thread_id for q in dan_view.unresolved_questions} == {T2}


@pytest.mark.asyncio
async def test_deleted_newest_message_leaks_through_no_field(scenario):
    projection = await HomeActivityService(scenario.db).build(AMO)
    room = _room(projection, SHARED)

    assert room.last_message_preview.startswith("Does the second leg")
    assert room.last_message_at == _d(2)
    by_title = {b.title: b for b in room.branches}
    assert by_title["Fork Alpha"].message_count == 1
    assert by_title["Fork Alpha"].last_message_at == _d(2)
    assert room.unread_count == 2
    assert "DELETED-SENTINEL" not in projection.model_dump_json()


@pytest.mark.asyncio
async def test_only_active_commitments_due_within_72h(scenario):
    room = _room(await HomeActivityService(scenario.db).build(AMO), SHARED)
    assert [c.claim for c in room.commitments_due] == [
        "Close the hedge before CPI"
    ]
    assert room.commitments_due[0].category == "commitment"


@pytest.mark.asyncio
async def test_branch_lineage_survives_ordering(scenario):
    room = _room(await HomeActivityService(scenario.db).build(AMO), SHARED)
    by_title = {b.title: b for b in room.branches}

    assert by_title["Main"].depth == 0
    assert by_title["Main"].parent_thread_id is None
    assert by_title["Fork Alpha"].depth == 1
    assert by_title["Fork Alpha"].parent_thread_id == T1
    assert by_title["Fork Beta"].depth == 2
    assert by_title["Fork Beta"].parent_thread_id == T2
    # Sorted by latest activity while lineage metadata rides along.
    assert room.branches[0].title == "Fork Alpha"


@pytest.mark.asyncio
async def test_prompt_rendering_is_capped_and_viewer_derived(scenario):
    projection = await HomeActivityService(scenario.db).build(AMO)

    full = projection.to_prompt_section()
    assert "DATA-ONLY-BLOCK-" in full
    assert "viewer" in full
    assert "Shared Scheme" in full
    assert "DELETED-SENTINEL" not in full

    tight = projection.to_prompt_section(max_chars=300)
    assert "[Home activity truncated at 300 characters]" in tight
    assert "Shared Scheme" not in tight


# ── Authorization and snapshot behavior ──

@pytest.mark.asyncio
async def test_nonmember_raises_home_unavailable(scenario):
    with pytest.raises(HomeUnavailable):
        await HomeActivityService(scenario.db).build(OUTSIDER)


@pytest.mark.asyncio
async def test_build_outside_transaction_opens_explicit_snapshot(db):
    """
    On a bare connection the service opens its own REPEATABLE READ
    read-only transaction — this proves that path against the real server
    (the committed Home has zero members, so the answer is HomeUnavailable).
    """
    assert not db.is_in_transaction()
    with pytest.raises(HomeUnavailable):
        await HomeActivityService(db).build(_uid(0xFFF))


# ── Performance gate (Task 4 Step 8) ──

N_ROOMS = 25
THREADS_PER_ROOM = 4
MESSAGES_PER_ROOM = 100


@pytest_asyncio.fixture
async def production_scale(db):
    """Deterministic production-scale fixture, seed 20260811 (printed)."""
    seed = 20260811
    print(f"\nproduction-scale fixture seed: {seed}")
    rng = random.Random(seed)

    tx = db.transaction()
    await tx.start()

    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    for uid, name in ((AMO, "Amo"), (DAN, "Dan")):
        await db.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1, $2, $3)",
            uid, _d(40), name,
        )
        await db.execute(
            "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
            home_id, uid, _d(30),
        )

    message_rows, receipt_rows = [], []
    for r in range(N_ROOMS):
        room_id = _uid(0x1000 + r)
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1, $2, $3, $4)",
            room_id, _d(30), f"scale-{r}", f"Scale Room {r}",
        )
        for uid in (AMO, DAN):
            await db.execute(
                "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1, $2, $3)",
                room_id, uid, _d(30),
            )
        threads = []
        for t in range(THREADS_PER_ROOM):
            tid = _uid(0x10000 + r * 16 + t)
            parent = threads[-1] if threads else None
            await db.execute(
                """INSERT INTO threads (id, room_id, created_at, parent_thread_id, title)
                   VALUES ($1, $2, $3, $4, $5)""",
                tid, room_id, _d(29 - t), parent, f"Branch {t}",
            )
            threads.append(tid)

        seq = {tid: 0 for tid in threads}
        for m in range(MESSAGES_PER_ROOM):
            tid = rng.choice(threads)
            seq[tid] += 1
            mid = _uid(0x100000 + r * 4096 + m)
            speaker = rng.choice((AMO, DAN))
            message_rows.append((
                mid, tid, seq[tid], _d(28 - (m * 0.25)), "human", speaker,
                "question" if rng.random() < 0.1 else "text",
                f"Message {m} in scale room {r}", False,
            ))
            if rng.random() < 0.3:
                receipt_rows.append((mid, AMO, _d(27.5 - (m * 0.25))))
        if r % 5 == 0:
            await db.execute(
                """INSERT INTO commitments
                       (room_id, claim, resolution_criteria, category, deadline, status)
                   VALUES ($1, $2, 'criteria', 'prediction', $3, 'active')""",
                room_id, f"Scale commitment {r}", BASE + timedelta(hours=48),
            )

    await db.executemany(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, is_deleted)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        message_rows,
    )
    await db.executemany(
        """INSERT INTO message_receipts (message_id, user_id, receipt_type, timestamp)
           VALUES ($1, $2, 'read', $3)""",
        receipt_rows,
    )

    yield SimpleNamespace(db=db)
    await tx.rollback()


@pytest.mark.asyncio
async def test_projection_meets_p95_gate(production_scale):
    db = production_scale.db
    service = HomeActivityService(db)

    projection = await service.build(AMO)  # warmup
    assert len(projection.rooms) == N_ROOMS

    timings = []
    for _ in range(20):
        start = time.perf_counter()
        await service.build(AMO)
        timings.append(time.perf_counter() - start)

    timings.sort()
    p95 = timings[18]
    print(
        f"\nHomeActivityService.build over {N_ROOMS} rooms: "
        f"min {timings[0]*1000:.1f} ms, median {timings[10]*1000:.1f} ms, "
        f"p95 {p95*1000:.1f} ms"
    )
    assert p95 <= 0.150, f"p95 {p95*1000:.1f} ms exceeds the 150 ms gate"


@pytest.mark.asyncio
async def test_explain_captures_each_service_query(production_scale):
    """EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) for every fenced read."""
    import home_activity as ha

    db = production_scale.db
    home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    eligible = await db.fetch(ha._ELIGIBLE_SQL, AMO, home_id)
    ids = [r["id"] for r in eligible]
    joined = [r["joined_at"] for r in eligible]

    plans = {}
    for label, sql, params in (
        ("eligible", ha._ELIGIBLE_SQL, (AMO, home_id)),
        ("branches", ha._BRANCH_SQL, (AMO, ids, joined)),
        ("window", ha._WINDOW_SQL, (AMO, ids, joined)),
        ("latest", ha._LATEST_SQL, (ids,)),
        ("commitments", ha._COMMITMENTS_SQL, (ids,)),
    ):
        raw = await db.fetchval(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}", *params
        )
        import json as _json
        plan = _json.loads(raw)[0]
        plans[label] = plan
        print(
            f"\nEXPLAIN {label}: planning {plan['Planning Time']:.2f} ms, "
            f"execution {plan['Execution Time']:.2f} ms, "
            f"shared hit {plan['Plan'].get('Shared Hit Blocks')}, "
            f"read {plan['Plan'].get('Shared Read Blocks')}"
        )
    assert set(plans) == {"eligible", "branches", "window", "latest", "commitments"}


@pytest.mark.asyncio
async def test_thread_counts_share_soft_delete_truth_with_projection(scenario):
    """
    list_threads, the genealogy tree, and the Home projection must agree on
    a branch's message count — the deleted newest message is invisible to
    all three (Task 7 Step 1).
    """
    import api.main as main_mod

    threads = await main_mod.list_threads(
        SHARED, token="scenario-shared-room", db=scenario.db
    )
    by_id = {t.id: t for t in threads}
    assert by_id[T2].message_count == 1  # M4 only; M_DEL is soft-deleted

    genealogy = await main_mod.get_thread_genealogy(
        SHARED, token="scenario-shared-room", max_depth=20, db=scenario.db
    )

    def flatten(nodes):
        collected = []
        for node in nodes:
            collected.append(node)
            collected.extend(flatten(node.children))
        return collected

    gen_by_id = {n.id: n for n in flatten(genealogy)}
    assert gen_by_id[T2].message_count == 1

    room = _room(await HomeActivityService(scenario.db).build(AMO), SHARED)
    branch = {b.id: b for b in room.branches}[T2]
    assert branch.message_count == gen_by_id[T2].message_count == by_id[T2].message_count
