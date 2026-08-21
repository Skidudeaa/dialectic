"""
Real-Postgres contract for the Mirror (api/mirror.py).

WHY real Postgres: the fence IS the feature, and the fence is a WHERE clause.
The only honest test of "Amo can never read Dan's profile" is to seed both
profiles into one database and assert that everything Amo's three endpoints
return, serialised whole, contains nothing of Dan's — not the prose, not a
count, not the existence of a room where only Dan is modelled. A mocked DB
would assert a query string, which is exactly the thing that cannot tell a
fence from a comment about a fence.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

from api.mirror import get_mirror, get_mirror_diff, get_mirror_versions

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-b000-{n:012x}")


AMO, DAN = _uid(0x001), _uid(0x002)
ROOM_BOTH, ROOM_AMO_ONLY, ROOM_DAN_ONLY = _uid(0x011), _uid(0x012), _uid(0x013)
MEM_AMO_BOTH, MEM_DAN_BOTH = _uid(0x021), _uid(0x022)
MEM_AMO_SOLO, MEM_DAN_SOLO = _uid(0x023), _uid(0x024)

# Sentinels, so the fence is asserted by VALUE and not merely by row count.
# DAN_MARK appears in Dan's prose AND in the name of the room only Dan is
# modelled in — a leak of either is a leak.
AMO_MARK = "AMO-MIRROR-SENTINEL"
DAN_MARK = "DAN-MIRROR-SENTINEL"

AMO_VERSIONS = 4
DAN_VERSIONS = 9  # deliberately different, so a count cannot be a coincidence


class _Caller:
    """The two fields api/mirror.py reads off AuthenticatedUser."""

    def __init__(self, user_id: UUID):
        self.user_id = user_id
        self.display_name = "test"


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    yield conn
    await conn.close()


async def _seed_model(db, mem_id, room_id, user_id, mark, n_versions, base):
    """One `user_model:` memory plus its full rewrite history, exactly the
    shape llm/identity.py leaves behind: LLM-authored, so owner_user_id and
    created_by_user_id are NULL and the KEY is the only carrier of whose
    model this is."""
    def revision(v):
        return f"## Thinking Style\n{mark} revision {v}\n\n## Blind Spots\nline {v}"

    latest_at = base + timedelta(hours=n_versions)
    await db.execute(
        """INSERT INTO memories (id, room_id, created_at, updated_at,
               version, scope, key, content, status)
           VALUES ($1,$2,$3,$4,$5,'llm',$6,$7,'active')""",
        mem_id, room_id, base, latest_at, n_versions, f"user_model:{user_id}",
        revision(n_versions),
    )
    for v in range(1, n_versions + 1):
        await db.execute(
            """INSERT INTO memory_versions (memory_id, version, content, updated_at)
               VALUES ($1,$2,$3,$4)""",
            mem_id, v, revision(v), base + timedelta(hours=v),
        )


@pytest_asyncio.fixture
async def mirror_world(db):
    """Three rooms: one where the participant models BOTH humans, one where it
    models only Amo, one where it models only Dan."""
    tx = db.transaction()
    await tx.start()
    base = datetime.now(timezone.utc) - timedelta(days=30)

    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo'),($3,$2,'Dan')",
        AMO, base, DAN,
    )
    for rid, name in (
        (ROOM_BOTH, "Shared Room"),
        (ROOM_AMO_ONLY, f"{AMO_MARK} room"),
        (ROOM_DAN_ONLY, f"{DAN_MARK} room"),
    ):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, base, f"mirror-{rid}", name,
        )
    # Both humans are members of all three rooms: membership must NOT be what
    # separates them, or the test would pass on the wrong mechanism.
    for rid in (ROOM_BOTH, ROOM_AMO_ONLY, ROOM_DAN_ONLY):
        for uid in (AMO, DAN):
            await db.execute(
                "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
                rid, uid, base,
            )

    await _seed_model(db, MEM_AMO_BOTH, ROOM_BOTH, AMO, AMO_MARK, AMO_VERSIONS, base)
    await _seed_model(db, MEM_DAN_BOTH, ROOM_BOTH, DAN, DAN_MARK, DAN_VERSIONS, base)
    await _seed_model(db, MEM_AMO_SOLO, ROOM_AMO_ONLY, AMO, AMO_MARK, 2, base)
    await _seed_model(db, MEM_DAN_SOLO, ROOM_DAN_ONLY, DAN, DAN_MARK, 7, base)

    yield db
    await tx.rollback()


def _blob(payload) -> str:
    """Everything the caller receives, serialised whole — the only way to
    assert a leak cannot hide in a field nobody thought to check."""
    return json.dumps(payload, default=str)


async def _amo_everything(db) -> str:
    """Every byte Amo's three endpoints will ever hand him, in one string."""
    caller = _Caller(AMO)
    rooms = await get_mirror(current_user=caller, db=db)
    parts = [_blob([r.model_dump() for r in rooms])]
    for room in rooms:
        versions = await get_mirror_versions(
            room_id=room.room_id, current_user=caller, db=db
        )
        parts.append(_blob([v.model_dump() for v in versions]))
        if len(versions) >= 2:
            diff = await get_mirror_diff(
                room_id=room.room_id,
                from_version=versions[-1].version,
                to_version=versions[0].version,
                current_user=caller,
                db=db,
            )
            parts.append(_blob(diff.model_dump()))
    return "\n".join(parts)


# ---------------------------------------------------------------- the fence


@pytest.mark.asyncio
async def test_nothing_of_the_other_human_appears_anywhere(mirror_world):
    """The whole feature in one assertion: across the list, every version
    history and every diff, Amo receives his own prose and no trace of Dan's
    — including no trace of the ROOM Dan alone is modelled in."""
    everything = await _amo_everything(mirror_world)
    assert AMO_MARK in everything, "Amo cannot see his own mirror"
    assert DAN_MARK not in everything


@pytest.mark.asyncio
async def test_the_room_list_omits_a_room_where_only_the_other_is_modelled(
    mirror_world,
):
    rooms = await get_mirror(current_user=_Caller(AMO), db=mirror_world)
    assert {r.room_id for r in rooms} == {ROOM_BOTH, ROOM_AMO_ONLY}


@pytest.mark.asyncio
async def test_version_count_is_the_callers_own_not_the_rooms(mirror_world):
    """The shared room holds two histories of different lengths. Amo must get
    exactly his own — not Dan's, and not the sum, which is how a leak that
    only ever surfaces as a COUNT would look."""
    versions = await get_mirror_versions(
        room_id=ROOM_BOTH, current_user=_Caller(AMO), db=mirror_world
    )
    assert len(versions) == AMO_VERSIONS
    assert [v.version for v in versions] == list(range(AMO_VERSIONS, 0, -1))


@pytest.mark.asyncio
async def test_versions_of_a_room_modelling_only_the_other_is_a_plain_404(
    mirror_world,
):
    """The 404 must not be an oracle — same answer as a room that does not
    exist at all."""
    with pytest.raises(HTTPException) as leaked:
        await get_mirror_versions(
            room_id=ROOM_DAN_ONLY, current_user=_Caller(AMO), db=mirror_world
        )
    with pytest.raises(HTTPException) as absent:
        await get_mirror_versions(
            room_id=_uid(0xDEAD), current_user=_Caller(AMO), db=mirror_world
        )
    assert leaked.value.status_code == absent.value.status_code == 404
    assert leaked.value.detail == absent.value.detail
    assert DAN_MARK not in str(leaked.value.detail)


@pytest.mark.asyncio
async def test_diff_cannot_reach_across_into_the_other_history(mirror_world):
    """Dan has 9 versions in the shared room and Amo has 4. Asking for v9
    there must 404 rather than quietly diffing against Dan's ninth rewrite."""
    with pytest.raises(HTTPException) as exc:
        await get_mirror_diff(
            room_id=ROOM_BOTH,
            from_version=1,
            to_version=DAN_VERSIONS,
            current_user=_Caller(AMO),
            db=mirror_world,
        )
    assert exc.value.status_code == 404
    assert DAN_MARK not in str(exc.value.detail)


# ------------------------------------------------------------ it also works


@pytest.mark.asyncio
async def test_diff_reports_the_rewrite_between_two_versions(mirror_world):
    diff = await get_mirror_diff(
        room_id=ROOM_BOTH,
        from_version=1,
        to_version=AMO_VERSIONS,
        current_user=_Caller(AMO),
        db=mirror_world,
    )
    body = "\n".join(diff.lines)
    assert f"-{AMO_MARK} revision 1" in body
    assert f"+{AMO_MARK} revision {AMO_VERSIONS}" in body
    # The unchanged heading is context, not a change.
    assert "-## Thinking Style" not in body


@pytest.mark.asyncio
async def test_the_list_carries_the_current_version_and_its_stamp(mirror_world):
    rooms = await get_mirror(current_user=_Caller(AMO), db=mirror_world)
    shared = next(r for r in rooms if r.room_id == ROOM_BOTH)
    assert shared.version == AMO_VERSIONS
    assert f"revision {AMO_VERSIONS}" in shared.content
    assert shared.updated_at  # ISO-8601 stamp of the last rewrite


@pytest.mark.asyncio
async def test_a_human_the_participant_has_never_modelled_sees_nothing(
    mirror_world,
):
    rooms = await get_mirror(current_user=_Caller(_uid(0x0FF)), db=mirror_world)
    assert rooms == []


# ── the two fences added after the 2026-08-20 review ─────────────────────

@pytest.mark.asyncio
async def test_leaving_a_room_closes_the_mirror_onto_it(mirror_world):
    """The key already guarantees the model is Amo's OWN, so this is not
    about whose profile it is. It is that a model written FROM a room's
    conversation quotes what happened there — and `deploy/remove_home_member.sql`
    exists. Without a membership predicate, removing someone would close the
    room and leave its transcript readable through the profile derived from
    it. The older single-room door (api/main.py:1845) checks membership; these
    now agree."""
    db = mirror_world
    before = {str(r.room_id) for r in await get_mirror(current_user=_Caller(AMO), db=db)}
    assert str(ROOM_AMO_ONLY) in before

    await db.execute(
        "DELETE FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        ROOM_AMO_ONLY, AMO,
    )

    after = {str(r.room_id) for r in await get_mirror(current_user=_Caller(AMO), db=db)}
    assert str(ROOM_AMO_ONLY) not in after
    assert str(ROOM_BOTH) in after, "only the room he left may close"
    # And the history door closes with it, rather than staying open behind
    # a list that no longer names the room.
    with pytest.raises(HTTPException) as exc:
        await get_mirror_versions(
            room_id=ROOM_AMO_ONLY, current_user=_Caller(AMO), db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_invalidated_model_is_gone_from_both_doors_not_just_one(
    mirror_world,
):
    """`get_mirror` filtered `status='active'` and `_versions` did not, so an
    invalidated model vanished from the list while staying fully readable at
    /versions — two doors onto the same rows disagreeing about which rows
    count."""
    db = mirror_world
    await db.execute(
        "UPDATE memories SET status = 'invalidated' WHERE id = $1", MEM_AMO_SOLO)

    rooms = {str(r.room_id) for r in await get_mirror(current_user=_Caller(AMO), db=db)}
    assert str(ROOM_AMO_ONLY) not in rooms
    with pytest.raises(HTTPException) as exc:
        await get_mirror_versions(
            room_id=ROOM_AMO_ONLY, current_user=_Caller(AMO), db=db)
    assert exc.value.status_code == 404


def test_the_fence_value_is_the_one_identity_writes():
    """`api.mirror._key` re-declares the format string `llm/identity.py`
    writes. Two copies of one wire format is the class that has bitten this
    repo repeatedly (a prompt in four copies; an enum in two tables). The
    drift direction here is SAFE — the Mirror would show nothing rather than
    show someone else's profile — but nothing would go red, so a reader would
    be told they have no model rather than that the seam broke."""
    from llm.identity import LLMIdentityManager
    import api.mirror as mirror

    uid = UUID("00000000-0000-4000-8000-0000000000ff")
    assert mirror._key(uid) == LLMIdentityManager._user_model_key(None, uid)
