"""Real-Postgres serialization contracts for causal Field mutations."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.field as field_api
import api.geo as geo_api
from api.auth.dependencies import AuthenticatedUser
from field_marks import compute_dedup_key
from geo_scopes import insert_scope


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test",
)
BOOK_ID = "race-book"
TOKEN = "field-race-token"


class _DirectPool:
    def __init__(self, connection: asyncpg.Connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


@dataclass(frozen=True)
class RaceWorld:
    schema: str
    setup: asyncpg.Connection
    room_id: UUID
    user_id: UUID
    thread_id: UUID
    message_a: UUID
    message_b: UUID
    scope_id: UUID


async def _prepare(conn: asyncpg.Connection, schema: str) -> None:
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    await conn.execute(f'SET search_path TO "{schema}", public')


async def _pool(schema: str, *, size: int) -> asyncpg.Pool:
    async def setup(conn: asyncpg.Connection) -> None:
        await _prepare(conn, schema)

    return await asyncpg.create_pool(
        TEST_DATABASE_URL, min_size=1, max_size=size, setup=setup,
    )


def _caller(world: RaceWorld) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=world.user_id,
        email="race@example.com",
        email_verified=True,
        display_name="Racer",
    )


def _causal_subjects(world: RaceWorld, node_id: str) -> list[field_api.FieldSubjectRef]:
    return [
        field_api.FieldSubjectRef(entity="geo_scopes", id=str(world.scope_id)),
        field_api.FieldSubjectRef(
            entity="rooms",
            id=str(world.room_id),
            field=f"thesis_node:{BOOK_ID}:{node_id}",
        ),
    ]


async def _seed_mark(
    world: RaceWorld,
    mark_id: UUID,
    *,
    relation: str = "claim_group",
    subjects: list[dict] | None = None,
) -> None:
    subjects = subjects or [{"entity": "messages", "id": str(world.message_a)}]
    await world.setup.execute(
        """INSERT INTO field_marks
               (id, room_id, thread_id, mark_kind, relation, origin,
                provenance, subjects, title, payload, created_at, dedup_key)
           VALUES ($1,$2,$3,'relation',$4,'explicit','human',$5,'target','{}',$6,$7)""",
        mark_id,
        world.room_id,
        world.thread_id,
        relation,
        subjects,
        datetime.now(timezone.utc),
        compute_dedup_key(relation, subjects),
    )


async def _field_counts(world: RaceWorld) -> tuple[int, int, int]:
    return (
        await world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind = 'relation'",
            world.room_id,
        ),
        await world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE room_id = $1 AND mark_kind = 'review'",
            world.room_id,
        ),
        await world.setup.fetchval(
            "SELECT count(*) FROM events WHERE room_id = $1 AND "
            "event_type IN ('field_mark_created', 'field_mark_reviewed')",
            world.room_id,
        ),
    )


@pytest_asyncio.fixture
async def race_world() -> RaceWorld:
    schema = f"field_causal_race_{uuid4().hex}"
    try:
        setup = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as exc:
        pytest.skip(f"test database unavailable: {exc}")
    try:
        if not await setup.fetchval("SELECT to_regclass('public.geo_scopes')"):
            pytest.skip("geo_scopes missing — run migrations/021_geo_scopes.sql")
        await setup.execute(f'CREATE SCHEMA "{schema}"')
        for table in (
            "users",
            "rooms",
            "room_memberships",
            "threads",
            "messages",
            "events",
            "geo_scopes",
            "field_marks",
        ):
            await setup.execute(
                f'CREATE TABLE "{schema}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL)',
            )
        await _prepare(setup, schema)
        now = datetime.now(timezone.utc)
        room_id, user_id, thread_id = uuid4(), uuid4(), uuid4()
        message_a, message_b = uuid4(), uuid4()
        await setup.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Racer')",
            user_id,
            now,
        )
        await setup.execute(
            """INSERT INTO rooms
                   (id, created_at, token, name, linked_book_id)
               VALUES ($1,$2,$3,'Race room',$4)""",
            room_id,
            now,
            TOKEN,
            BOOK_ID,
        )
        await setup.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            room_id,
            user_id,
            now,
        )
        await setup.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            thread_id,
            room_id,
            now,
        )
        for sequence, message_id in enumerate((message_a, message_b), start=1):
            await setup.execute(
                """INSERT INTO messages
                       (id,thread_id,sequence,created_at,speaker_type,user_id,
                        message_type,content,is_deleted)
                   VALUES ($1,$2,$3,$4,'human',$5,'text','race evidence',false)""",
                message_id,
                thread_id,
                sequence,
                now,
                user_id,
            )
        scope_id = await insert_scope(
            setup,
            room_id=room_id,
            subject={"entity": "messages", "id": str(message_a)},
            kind="point",
            geometry={"type": "Point", "coordinates": [56.25, 26.55]},
            label="Race scope",
            authority="source_reported",
            provenance={"provider": "test", "acquisition": "adapter:test"},
            now=now,
        )
        yield RaceWorld(
            schema=schema,
            setup=setup,
            room_id=room_id,
            user_id=user_id,
            thread_id=thread_id,
            message_a=message_a,
            message_b=message_b,
            scope_id=scope_id,
        )
    finally:
        if not setup.is_closed():
            await setup.execute("SET search_path TO public")
            await setup.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await setup.close()


def _structure() -> dict:
    return {
        "id": BOOK_ID,
        "nodes": [
            {"id": "node-a", "label": "Node A"},
            {"id": "node-b", "label": "Node B"},
            {"id": "node-c", "label": "Node C"},
        ],
    }


@pytest.mark.asyncio
async def test_size_one_pool_is_released_while_structure_bridge_waits(
    race_world: RaceWorld, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_structure(*_args: object, **_kwargs: object) -> dict:
        entered.set()
        await release.wait()
        return _structure()

    monkeypatch.setattr(field_api.td, "service_get", blocked_structure)
    pool = await _pool(race_world.schema, size=1)
    try:
        request = field_api.FieldMarkCreateRequest(
            relation="supports",
            subjects=_causal_subjects(race_world, "node-a"),
            title="causal",
        )
        create = asyncio.create_task(field_api.create_field_mark(
            race_world.room_id,
            request,
            token=TOKEN,
            current_user=_caller(race_world),
            pool=pool,
        ))
        await asyncio.wait_for(entered.wait(), timeout=2)
        async with asyncio.timeout(1):
            async with pool.acquire() as unrelated:
                assert await unrelated.fetchval("SELECT 1") == 1
        release.set()
        await create
    finally:
        release.set()
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [False, True], ids=["create", "replacement"])
async def test_causal_write_loses_cleanly_when_scope_successor_commits_first(
    race_world: RaceWorld,
    monkeypatch: pytest.MonkeyPatch,
    replacement: bool,
) -> None:
    target_id = uuid4()
    if replacement:
        await _seed_mark(race_world, target_id)
    before = await _field_counts(race_world)
    geo_conn = await asyncpg.connect(TEST_DATABASE_URL)
    field_conn = await asyncpg.connect(TEST_DATABASE_URL)
    await _prepare(geo_conn, race_world.schema)
    await _prepare(field_conn, race_world.schema)
    original_insert = geo_api.insert_scope
    geo_has_lock = asyncio.Event()
    release_geo = asyncio.Event()
    bridge_reached = asyncio.Event()

    async def paused_successor(*args: object, **kwargs: object) -> UUID:
        geo_has_lock.set()
        await release_geo.wait()
        return await original_insert(*args, **kwargs)

    async def structure(*_args: object, **_kwargs: object) -> dict:
        bridge_reached.set()
        return _structure()

    monkeypatch.setattr(geo_api, "insert_scope", paused_successor)
    monkeypatch.setattr(field_api.td, "service_get", structure)
    try:
        retire = asyncio.create_task(geo_api._review(
            race_world.room_id,
            race_world.scope_id,
            "supersede",
            _caller(race_world),
            geo_conn,
        ))
        await asyncio.wait_for(geo_has_lock.wait(), timeout=2)
        if replacement:
            request = field_api.FieldReviewRequest(
                action="correct",
                replacement=field_api.FieldReplacementRequest(
                    relation="supports",
                    subjects=_causal_subjects(race_world, "node-a"),
                    title="causal replacement",
                ),
            )
            write = asyncio.create_task(field_api.review_field_mark(
                race_world.room_id,
                target_id,
                request,
                token=TOKEN,
                current_user=_caller(race_world),
                pool=_DirectPool(field_conn),
            ))
        else:
            request = field_api.FieldMarkCreateRequest(
                relation="supports",
                subjects=_causal_subjects(race_world, "node-a"),
                title="causal create",
            )
            write = asyncio.create_task(field_api.create_field_mark(
                race_world.room_id,
                request,
                token=TOKEN,
                current_user=_caller(race_world),
                pool=_DirectPool(field_conn),
            ))
        await asyncio.wait_for(bridge_reached.wait(), timeout=2)
        release_geo.set()
        await retire
        result = await asyncio.gather(write, return_exceptions=True)
        assert isinstance(result[0], HTTPException)
        assert result[0].status_code == 422
        assert await _field_counts(race_world) == before
    finally:
        release_geo.set()
        await geo_conn.close()
        await field_conn.close()


@pytest.mark.asyncio
async def test_two_concurrent_causal_corrections_leave_one_review_replacement_and_event(
    race_world: RaceWorld, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = uuid4()
    await _seed_mark(
        race_world,
        target_id,
        relation="context",
        subjects=[subject.model_dump() for subject in _causal_subjects(race_world, "node-a")],
    )
    bridge_barrier = asyncio.Barrier(2)

    async def synchronized_structure(*_args: object, **_kwargs: object) -> dict:
        await bridge_barrier.wait()
        return _structure()

    monkeypatch.setattr(field_api.td, "service_get", synchronized_structure)
    contenders = [
        await asyncpg.connect(TEST_DATABASE_URL),
        await asyncpg.connect(TEST_DATABASE_URL),
    ]
    for contender in contenders:
        await _prepare(contender, race_world.schema)

    async def correct(conn: asyncpg.Connection, node_id: str, relation: str) -> object:
        return await field_api.review_field_mark(
            race_world.room_id,
            target_id,
            field_api.FieldReviewRequest(
                action="correct",
                replacement=field_api.FieldReplacementRequest(
                    relation=relation,
                    subjects=_causal_subjects(race_world, node_id),
                    title=f"replacement {node_id}",
                ),
            ),
            token=TOKEN,
            current_user=_caller(race_world),
            pool=_DirectPool(conn),
        )

    try:
        results = await asyncio.wait_for(asyncio.gather(
            correct(contenders[0], "node-b", "supports"),
            correct(contenders[1], "node-c", "challenges"),
            return_exceptions=True,
        ), timeout=5)
        assert len([result for result in results if not isinstance(result, BaseException)]) == 1
        losers = [result for result in results if isinstance(result, HTTPException)]
        assert [loser.status_code for loser in losers] == [409]
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE target_mark_id = $1", target_id,
        ) == 1
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE supersedes_id = $1", target_id,
        ) == 1
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM events WHERE event_type = 'field_mark_reviewed'",
        ) == 1
    finally:
        for contender in contenders:
            await contender.close()


@pytest.mark.asyncio
async def test_two_concurrent_confirms_leave_one_review_and_event(
    race_world: RaceWorld, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_id = uuid4()
    await _seed_mark(race_world, target_id)
    original_state = field_api.current_review_state
    initial_state_barrier = asyncio.Barrier(2)
    calls: dict[asyncio.Task, int] = {}

    async def synchronized_state(db: object, mark_id: UUID) -> str:
        state = await original_state(db, mark_id)
        task = asyncio.current_task()
        assert task is not None
        calls[task] = calls.get(task, 0) + 1
        if calls[task] == 1:
            await initial_state_barrier.wait()
        return state

    monkeypatch.setattr(field_api, "current_review_state", synchronized_state)
    contenders = [
        await asyncpg.connect(TEST_DATABASE_URL),
        await asyncpg.connect(TEST_DATABASE_URL),
    ]
    for contender in contenders:
        await _prepare(contender, race_world.schema)

    async def confirm(conn: asyncpg.Connection) -> object:
        return await field_api.review_field_mark(
            race_world.room_id,
            target_id,
            field_api.FieldReviewRequest(action="confirm"),
            token=TOKEN,
            current_user=_caller(race_world),
            pool=_DirectPool(conn),
        )

    try:
        results = await asyncio.wait_for(asyncio.gather(
            *(confirm(conn) for conn in contenders), return_exceptions=True,
        ), timeout=5)
        assert len([result for result in results if not isinstance(result, BaseException)]) == 1
        losers = [result for result in results if isinstance(result, HTTPException)]
        assert [loser.status_code for loser in losers] == [409]
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE target_mark_id = $1", target_id,
        ) == 1
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM events WHERE event_type = 'field_mark_reviewed'",
        ) == 1
    finally:
        for contender in contenders:
            await contender.close()


@pytest.mark.asyncio
async def test_reversed_concurrent_merges_lock_sources_deterministically(
    race_world: RaceWorld, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_a, source_b = uuid4(), uuid4()
    await _seed_mark(race_world, source_a)
    await _seed_mark(
        race_world,
        source_b,
        subjects=[{"entity": "messages", "id": str(race_world.message_b)}],
    )
    original_state = field_api.current_review_state
    ready = asyncio.Barrier(2)
    calls: dict[asyncio.Task, int] = {}

    async def synchronized_state(db: object, mark_id: UUID) -> str:
        state = await original_state(db, mark_id)
        task = asyncio.current_task()
        assert task is not None
        calls[task] = calls.get(task, 0) + 1
        if calls[task] == 2:
            await ready.wait()
        return state

    monkeypatch.setattr(field_api, "current_review_state", synchronized_state)
    contenders = [
        await asyncpg.connect(TEST_DATABASE_URL),
        await asyncpg.connect(TEST_DATABASE_URL),
    ]
    for contender in contenders:
        await _prepare(contender, race_world.schema)

    async def merge(
        conn: asyncpg.Connection,
        primary: UUID,
        secondary: UUID,
        relation: str,
    ) -> object:
        return await field_api.review_field_mark(
            race_world.room_id,
            primary,
            field_api.FieldReviewRequest(
                action="merge",
                merge_ids=[secondary],
                replacement=field_api.FieldReplacementRequest(
                    relation=relation,
                    subjects=[
                        field_api.FieldSubjectRef(
                            entity="messages", id=str(race_world.message_a),
                        ),
                        field_api.FieldSubjectRef(
                            entity="messages", id=str(race_world.message_b),
                        ),
                    ],
                    title="merged",
                ),
            ),
            token=TOKEN,
            current_user=_caller(race_world),
            pool=_DirectPool(conn),
        )

    try:
        results = await asyncio.wait_for(asyncio.gather(
            merge(contenders[0], source_a, source_b, "claim_group"),
            merge(contenders[1], source_b, source_a, "candidate_synthesis"),
            return_exceptions=True,
        ), timeout=5)
        assert len([result for result in results if not isinstance(result, BaseException)]) == 1
        losers = [result for result in results if isinstance(result, HTTPException)]
        assert [loser.status_code for loser in losers] == [409]
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM field_marks WHERE action = 'merge'",
        ) == 2
        assert await race_world.setup.fetchval(
            "SELECT count(*) FROM events WHERE event_type = 'field_mark_reviewed'",
        ) == 1
    finally:
        for contender in contenders:
            await contender.close()
