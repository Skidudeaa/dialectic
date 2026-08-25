"""
HTTP contract for api/field.py — the Field's write door.

Strategy is split, deliberately:
  - Auth/routing/shape (401/403, the kind-filter-less GET, "no other write
    route") use FastAPI dependency overrides + a fake db, mirroring
    tests/test_workspace_api.py and tests/test_home_membership_api.py — the
    house pattern for pinning a DOOR without live Postgres.
  - The write semantics (six actions, 404/409/422, one-transaction atomicity,
    the field_mark_reviewed event) call the route functions DIRECTLY against
    real Postgres (tests/test_field_marks_pg.py's fixture style) rather than
    through TestClient — a hand-mocked sequence of ~6 different SQL
    statements per action would assert a query shape that never ran; the
    actual transactional behavior is a property of the real database.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.field as field_mod
import api.main as main_mod
from api.auth.dependencies import AuthenticatedUser, get_current_user
from field_marks import FieldMarkService, compute_dedup_key

CALLER_ID = UUID("00000000-0000-0000-0000-000000000601")
ROOM_ID = UUID("00000000-0000-0000-0000-000000000602")
MARK_ID = UUID("00000000-0000-0000-0000-000000000603")
FIELD_PATH = f"/rooms/{ROOM_ID}/field"
CREATE_PATH = f"/rooms/{ROOM_ID}/field/marks"
REVIEW_PATH = f"/rooms/{ROOM_ID}/field/marks/{MARK_ID}/review"
HEADERS = {"X-Room-Token": "room-token"}


class _DirectPool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    main_mod.app.dependency_overrides.clear()


def _caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )


def _client(*, authenticated: bool = True, room: bool = True,
            member: bool = True) -> TestClient:
    db = AsyncMock()

    async def fetchrow(sql, *args):
        if "SELECT 1 FROM rooms" in sql:
            return {"?column?": 1} if room else None
        if "SELECT 1 FROM room_memberships" in sql:
            return {"?column?": 1} if member else None
        return None

    db.fetchrow.side_effect = fetchrow
    db.fetch.return_value = []
    db.fetchval.return_value = 0

    async def db_dependency() -> AsyncIterator[object]:
        yield db

    async def pool_dependency() -> _DirectPool:
        return _DirectPool(db)

    main_mod.app.dependency_overrides[field_mod.get_db] = db_dependency
    main_mod.app.dependency_overrides[field_mod.get_pool] = pool_dependency
    if authenticated:
        main_mod.app.dependency_overrides[get_current_user] = lambda: _caller()
    return TestClient(main_mod.app)


# ---------------------------------------------------------------------------
# auth matrix (both credentials, on both routes)
# ---------------------------------------------------------------------------

def test_get_field_requires_bearer_auth():
    assert _client(authenticated=False).get(FIELD_PATH, headers=HEADERS).status_code == 401


def test_get_field_requires_a_room_token():
    assert _client().get(FIELD_PATH).status_code in (401, 422)


def test_get_field_refuses_a_wrong_room_token():
    assert _client(room=False).get(FIELD_PATH, headers=HEADERS).status_code == 401


def test_get_field_refuses_a_nonmember():
    assert _client(member=False).get(FIELD_PATH, headers=HEADERS).status_code == 403


def test_get_field_returns_an_empty_projection_envelope():
    response = _client().get(FIELD_PATH, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["room_id"] == str(ROOM_ID)
    assert body["marks"] == []
    assert body["generated_at"]


def test_review_requires_bearer_auth():
    body = {"action": "confirm"}
    resp = _client(authenticated=False).post(REVIEW_PATH, json=body, headers=HEADERS)
    assert resp.status_code == 401


def test_review_requires_a_room_token():
    assert _client().post(REVIEW_PATH, json={"action": "confirm"}).status_code in (401, 422)


def test_review_refuses_a_wrong_room_token():
    resp = _client(room=False).post(REVIEW_PATH, json={"action": "confirm"}, headers=HEADERS)
    assert resp.status_code == 401


def test_review_refuses_a_nonmember():
    resp = _client(member=False).post(REVIEW_PATH, json={"action": "confirm"}, headers=HEADERS)
    assert resp.status_code == 403


def test_review_refuses_an_unknown_action():
    resp = _client().post(REVIEW_PATH, json={"action": "delete"}, headers=HEADERS)
    assert resp.status_code == 422


def test_create_auth_precedes_relation_validation():
    response = _client(room=False).post(
        CREATE_PATH,
        json={
            "relation": "not-a-relation",
            "subjects": [{"entity": "messages", "id": str(MARK_ID)}],
        },
        headers=HEADERS,
    )
    assert response.status_code == 401


def test_the_routers_write_surface_is_exactly_these_two():
    """C4-style guard, asserted where it lives: the mutating routes are
    ENUMERATED, so a third arrives as a failing test rather than a surprise.

    AMENDED 2026-08-16: was "exactly one". Human origination
    (POST .../field/marks) is the second, and it had to exist — Release 3
    gave humans review only, so production accumulated 85 marks, every one
    `origin='inferred'`, with no way for a person to assert anything the
    inference engine had not proposed first.

    Still no PUT, PATCH or DELETE anywhere: field_marks is append-only, and
    that is the invariant this guard actually protects.
    """
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    mutating = {
        (route.path, tuple(sorted(route.methods & write_methods)))
        for route in field_mod.router.routes
        if getattr(route, "methods", set()) & write_methods
    }
    assert mutating == {
        ("/rooms/{room_id}/field/marks/{mark_id}/review", ("POST",)),
        ("/rooms/{room_id}/field/marks", ("POST",)),
    }
    assert not any(
        m in route.methods for route in field_mod.router.routes
        for m in ("PUT", "PATCH", "DELETE")
        if getattr(route, "methods", None)
    ), "field_marks is append-only — nothing here may update or delete"


# ---------------------------------------------------------------------------
# real-Postgres: write semantics, called directly (not through TestClient)
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


AMO = _uid(0xFA01)
DAN = _uid(0xFA02)
ROOM = _uid(0xFA11)
FOREIGN_ROOM = _uid(0xFA12)
TH = _uid(0xFA21)
FOREIGN_TH = _uid(0xFA22)
MSG_A = _uid(0xFA31)
MSG_B = _uid(0xFA32)
FOREIGN_MSG = _uid(0xFA33)

BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


def _amo_caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=AMO, email="amo@test", email_verified=True, display_name="Amo",
    )


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as e:
        pytest.skip(f"test database unavailable: {e}")
        return
    import json
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads,
            schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def field_api_room(db):
    tx = db.transaction()
    await tx.start()
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo'),($3,$2,'Dan')",
        AMO, _d(40), DAN)
    for rid, nm in ((ROOM, "API Room"), (FOREIGN_ROOM, "Foreign Room")):
        await db.execute(
            "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
            rid, _d(30), f"field-api-{rid}", nm)
    for uid in (AMO, DAN):
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            ROOM, uid, _d(30))
    for tid, rid in ((TH, ROOM), (FOREIGN_TH, FOREIGN_ROOM)):
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            tid, rid, _d(30))
    for mid, tid, seq in ((MSG_A, TH, 1), (MSG_B, TH, 2)):
        await db.execute(
            """INSERT INTO messages (id,thread_id,sequence,created_at,speaker_type,
                   user_id,message_type,content,is_deleted)
               VALUES ($1,$2,$3,$4,'human',$5,'text','hi',false)""",
            mid, tid, seq, _d(5), AMO)
    await db.execute(
        """INSERT INTO messages (id,thread_id,sequence,created_at,speaker_type,
               user_id,message_type,content,is_deleted)
           VALUES ($1,$2,1,$3,'human',$4,'text','hi',false)""",
        FOREIGN_MSG, FOREIGN_TH, _d(5), AMO)
    yield db
    await tx.rollback()


async def _seed_mark(db, mid, *, relation="emerging_position", subjects=None,
                     title="A position", at=None, thread=TH, room=ROOM):
    subjects = subjects or [{"entity": "messages", "id": str(MSG_A)}]
    await db.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, created_at, dedup_key)
           VALUES ($1,$2,$3,'relation',$4,'inferred','field_inference',$5,$6,$7,$8)""",
        mid, room, thread, relation, subjects, title, at or _d(1),
        compute_dedup_key(relation, subjects),
    )


def _request(action, **kwargs):
    return field_mod.FieldReviewRequest(action=action, **kwargs)


@pytest.mark.asyncio
async def test_confirm_writes_one_review_row_attributed_to_the_caller(field_api_room):
    await _seed_mark(field_api_room, MARK_ID)
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("confirm", note="looks right"),
        token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "confirmed"
    assert resp.review.action == "confirm"
    assert resp.review.actor_user_id == AMO
    assert resp.review.note == "looks right"

    event = await field_api_room.fetchrow(
        "SELECT payload FROM events WHERE event_type = 'field_mark_reviewed' "
        "AND room_id = $1", ROOM,
    )
    assert event is not None
    assert event["payload"]["action"] == "confirm"
    assert event["payload"]["actor_user_id"] == str(AMO)


@pytest.mark.asyncio
async def test_contest_then_repeat_contest_is_409(field_api_room):
    await _seed_mark(field_api_room, MARK_ID)
    await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("contest"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, MARK_ID, _request("contest"), token=f"field-api-{ROOM}",
            current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 409
    assert "contested" in exc.value.detail


@pytest.mark.asyncio
async def test_repeat_confirm_matching_current_state_is_409(field_api_room):
    await _seed_mark(field_api_room, MARK_ID)
    await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("confirm"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, MARK_ID, _request("confirm"), token=f"field-api-{ROOM}",
            current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_confirm_after_contest_is_allowed_and_flips_state(field_api_room):
    """Confirm/contest are not a single mutually-exclusive terminal pair —
    only a REPEAT of the currently-latest action is refused."""
    await _seed_mark(field_api_room, MARK_ID)
    await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("contest"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("confirm"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "confirmed"


@pytest.mark.asyncio
async def test_correct_writes_a_review_and_one_replacement(field_api_room):
    await _seed_mark(field_api_room, MARK_ID, relation="repeated_definition",
                     subjects=[{"entity": "messages", "id": str(MSG_A)}])
    replacement = field_mod.FieldReplacementRequest(
        relation="repeated_definition",
        subjects=[{"entity": "messages", "id": str(MSG_B)}],
        title="corrected definition",
    )
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("correct", replacement=replacement),
        token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "superseded"
    assert len(resp.replacements) == 1
    assert resp.replacements[0].review == "provisional"
    assert resp.replacements[0].supersedes_id == MARK_ID
    assert resp.replacements[0].caused_by_id == resp.review.id


@pytest.mark.asyncio
async def test_correct_on_an_already_superseded_target_is_409(field_api_room):
    await _seed_mark(field_api_room, MARK_ID, relation="repeated_definition",
                     subjects=[{"entity": "messages", "id": str(MSG_A)}])
    replacement = field_mod.FieldReplacementRequest(
        relation="repeated_definition",
        subjects=[{"entity": "messages", "id": str(MSG_B)}],
        title="corrected once",
    )
    await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("correct", replacement=replacement),
        token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, MARK_ID, _request("correct", replacement=replacement),
            token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 409
    assert "superseded" in exc.value.detail


@pytest.mark.asyncio
async def test_a_foreign_target_is_404(field_api_room):
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, uuid4(), _request("confirm"), token=f"field-api-{ROOM}",
            current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_replacement_subject_outside_the_room_is_422(field_api_room):
    await _seed_mark(field_api_room, MARK_ID)
    replacement = field_mod.FieldReplacementRequest(
        relation="emerging_position",
        subjects=[{"entity": "messages", "id": str(FOREIGN_MSG)}],
        title="borrowed from another room",
    )
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, MARK_ID, _request("correct", replacement=replacement),
            token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_split_writes_one_review_and_n_replacements(field_api_room):
    # Two subjects on the ancestor (a combined claim) so neither single-
    # subject replacement below collides with the ancestor's OWN dedup_key.
    await _seed_mark(
        field_api_room, MARK_ID, relation="claim_group",
        subjects=[{"entity": "messages", "id": str(MSG_A)},
                 {"entity": "messages", "id": str(MSG_B)}],
        title="combined claim",
    )
    r1 = field_mod.FieldReplacementRequest(
        relation="claim_group", subjects=[{"entity": "messages", "id": str(MSG_A)}],
        title="claim one",
    )
    r2 = field_mod.FieldReplacementRequest(
        relation="claim_group", subjects=[{"entity": "messages", "id": str(MSG_B)}],
        title="claim two",
    )
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("split", replacements=[r1, r2]),
        token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "superseded"
    assert len(resp.replacements) == 2
    assert all(r.supersedes_id == MARK_ID for r in resp.replacements)
    assert all(r.review == "provisional" for r in resp.replacements)


@pytest.mark.asyncio
async def test_a_mid_split_failure_leaves_zero_rows(field_api_room):
    """The second replacement's dedup_key collides with an EXISTING mark in
    the room — the DB-level UniqueViolation must roll back the whole
    transaction, including the review row and the first replacement."""
    await _seed_mark(field_api_room, MARK_ID, relation="claim_group",
                     subjects=[{"entity": "messages", "id": str(MSG_A)}],
                     title="the split target")
    collider_subjects = [{"entity": "messages", "id": str(MSG_B)}]
    await _seed_mark(
        field_api_room, uuid4(), relation="claim_group",
        subjects=collider_subjects, title="an unrelated existing mark",
    )
    before = await field_api_room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1", ROOM,
    )
    events_before = await field_api_room.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1 "
        "AND event_type = 'field_mark_reviewed'", ROOM,
    )

    r1 = field_mod.FieldReplacementRequest(
        relation="claim_group", subjects=[{"entity": "messages", "id": str(MSG_A)}],
        title="first replacement, fine on its own",
    )
    r2 = field_mod.FieldReplacementRequest(
        relation="claim_group", subjects=collider_subjects,
        title="second replacement, collides with the existing mark above",
    )
    with pytest.raises(HTTPException) as exc:
        await field_mod.review_field_mark(
            ROOM, MARK_ID, _request("split", replacements=[r1, r2]),
            token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
        )
    assert exc.value.status_code == 409

    after = await field_api_room.fetchval(
        "SELECT count(*) FROM field_marks WHERE room_id = $1", ROOM,
    )
    assert after == before, "a mid-split failure must leave zero new rows"
    # And the target's own state must be untouched -- no orphaned review row.
    state = await field_api_room.fetchval(
        "SELECT count(*) FROM field_marks WHERE mark_kind = 'review' "
        "AND target_mark_id = $1", MARK_ID,
    )
    assert state == 0
    # The event insert is the LAST statement in the transaction -- a failure
    # on the second replacement must never reach it either.
    events_after = await field_api_room.fetchval(
        "SELECT count(*) FROM events WHERE room_id = $1 "
        "AND event_type = 'field_mark_reviewed'", ROOM,
    )
    assert events_after == events_before, "no orphaned field_mark_reviewed event"


@pytest.mark.asyncio
async def test_merge_writes_one_review_per_source_and_one_replacement(field_api_room):
    source_a = uuid4()
    source_b = uuid4()
    await _seed_mark(field_api_room, source_a, relation="claim_group",
                     subjects=[{"entity": "messages", "id": str(MSG_A)}],
                     title="claim one")
    await _seed_mark(field_api_room, source_b, relation="claim_group",
                     subjects=[{"entity": "messages", "id": str(MSG_B)}],
                     title="claim two")
    replacement = field_mod.FieldReplacementRequest(
        relation="claim_group",
        subjects=[{"entity": "messages", "id": str(MSG_A)},
                 {"entity": "messages", "id": str(MSG_B)}],
        title="merged claim",
    )
    resp = await field_mod.review_field_mark(
        ROOM, source_a, _request("merge", replacement=replacement, merge_ids=[source_b]),
        token=f"field-api-{ROOM}", current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "superseded"
    other = (await FieldMarkService(field_api_room).build(ROOM))
    by_id = {m.id: m for m in other.marks}
    assert by_id[f"field_mark:{source_b}"].review == "superseded"
    assert len(resp.replacements) == 1
    assert resp.replacements[0].payload["merged_ids"] == [str(source_a), str(source_b)]

    review_rows = await field_api_room.fetch(
        "SELECT target_mark_id, payload->>'merge_group' AS grp FROM field_marks "
        "WHERE mark_kind = 'review' AND action = 'merge' "
        "AND target_mark_id = ANY($1::uuid[])", [source_a, source_b],
    )
    assert len(review_rows) == 2
    assert review_rows[0]["grp"] == review_rows[1]["grp"]


@pytest.mark.asyncio
async def test_supersede_writes_only_a_review_row_no_replacement(field_api_room):
    await _seed_mark(field_api_room, MARK_ID, relation="unanswered_question")
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("supersede"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "superseded"
    assert resp.replacements == []


@pytest.mark.asyncio
async def test_a_supersede_only_retirement_can_be_reopened_by_a_later_confirm(field_api_room):
    """Documented nuance (field_marks._derive_review_state): 'supersede'
    creates no replacement row, so it is the one action a later confirm can
    genuinely reopen — unlike correct/split/merge, which are permanently
    anchored by a real successor row."""
    await _seed_mark(field_api_room, MARK_ID, relation="unanswered_question")
    await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("supersede"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    resp = await field_mod.review_field_mark(
        ROOM, MARK_ID, _request("confirm"), token=f"field-api-{ROOM}",
        current_user=_amo_caller(), pool=_DirectPool(field_api_room),
    )
    assert resp.mark.review == "confirmed"
