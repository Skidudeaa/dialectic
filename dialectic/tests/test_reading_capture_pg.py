"""Real-PostgreSQL contracts for immutable direct browser captures.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/013_home_base.sql
    psql dialectic_test -f migrations/014_reading_library.sql
    psql dialectic_test -f migrations/023_reading_capture_revisions.sql
"""

import hashlib
import asyncio
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.reading_relay as relay
from api.auth.dependencies import AuthenticatedUser
from llm import reading


TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test",
)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, USER, OTHER_ROOM = _uid(0xCA01), _uid(0xCA02), _uid(0xCA03)
CONCURRENT_ROOM, CONCURRENT_USER = _uid(0xCD01), _uid(0xCD02)
BASE = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
URL = "https://example.com/browser-truth"


def _capture(
    number: int,
    *,
    captured_at: datetime = BASE,
    markdown: str | None = None,
    title: str | None = None,
) -> dict[str, object]:
    body = markdown or f"# Revision {number}\n\nExact browser body {number}.\n"
    return {
        "capture_id": _uid(0xCB00 + number),
        "url": URL,
        "canonical_url": URL,
        "title": title or f"Revision {number}",
        "author": "A. Reporter",
        "site": "Example",
        "published": "2026-08-28",
        "description": f"Description {number}",
        "language": "en",
        "word_count": len(body.split()),
        "capture_mode": "article",
        "markdown": body,
        "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "captured_at": captured_at,
        "note": None,
        "extraction": {
            "engine": "defuddle",
            "engine_version": "0.19.3",
            "client_version": "0.1.0",
            "fallback_reason": None,
        },
    }


@pytest_asyncio.fixture
async def db():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL)
    except Exception as exc:
        pytest.skip(f"test database unavailable: {exc}")
        return
    if not await conn.fetchval("SELECT to_regclass('reading_revisions')"):
        await conn.close()
        pytest.skip("reading_revisions missing — run migration 023")
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def room(db):
    transaction = db.transaction()
    await transaction.start()
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,'capture-token','Capture')",
        ROOM, BASE,
    )
    await db.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Amo')",
        USER, BASE,
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        ROOM, USER, BASE,
    )
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,'other-token','Other')",
        OTHER_ROOM, BASE,
    )
    await db.execute(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        OTHER_ROOM, USER, BASE,
    )
    yield db
    await transaction.rollback()


@pytest_asyncio.fixture
async def concurrent_room():
    setup = await asyncpg.connect(TEST_DATABASE_URL)
    await setup.execute("DELETE FROM memories WHERE room_id = $1", CONCURRENT_ROOM)
    await setup.execute("DELETE FROM rooms WHERE id = $1", CONCURRENT_ROOM)
    await setup.execute("DELETE FROM users WHERE id = $1", CONCURRENT_USER)
    await setup.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,'race-token','Race')",
        CONCURRENT_ROOM, BASE,
    )
    await setup.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Race User')",
        CONCURRENT_USER, BASE,
    )
    await setup.close()
    yield CONCURRENT_ROOM, CONCURRENT_USER
    cleanup = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        await cleanup.execute("DELETE FROM memories WHERE room_id = $1", CONCURRENT_ROOM)
        await cleanup.execute("DELETE FROM rooms WHERE id = $1", CONCURRENT_ROOM)
        await cleanup.execute("DELETE FROM users WHERE id = $1", CONCURRENT_USER)
    finally:
        await cleanup.close()


async def _save(db: asyncpg.Connection, capture: dict[str, object]) -> dict:
    async with db.transaction():
        return await reading.save_browser_capture(
            db,
            room_id=ROOM,
            captured_by_user_id=USER,
            capture=capture,
        )


async def _concurrent_save(
    room_id: UUID,
    user_id: UUID,
    capture: dict[str, object],
    ready: asyncio.Barrier,
    *,
    application_name: str | None = None,
) -> dict:
    server_settings = (
        {"application_name": application_name} if application_name else None
    )
    connection = await asyncpg.connect(
        TEST_DATABASE_URL, server_settings=server_settings,
    )
    for typename in ("jsonb", "json"):
        await connection.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        await ready.wait()
        async with connection.transaction():
            return await reading.save_browser_capture(
                connection,
                room_id=room_id,
                captured_by_user_id=user_id,
                capture=capture,
            )
    finally:
        await connection.close()


async def _concurrent_ensure_twin(
    room_id: UUID,
    capture: dict[str, object],
    ready: asyncio.Barrier,
) -> None:
    connection = await asyncpg.connect(TEST_DATABASE_URL)
    for typename in ("jsonb", "json"):
        await connection.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        await ready.wait()
        await reading.ensure_reading_memory_twin(
            connection,
            room_id=room_id,
            article={
                "url": capture["canonical_url"],
                "title": capture["title"],
                "site": capture["site"],
                "published": capture["published"],
            },
            summary=str(capture["description"]),
            saved_by_user_id=CONCURRENT_USER,
        )
    finally:
        await connection.close()


async def _wait_for_database_lock(
    monitor: asyncpg.Connection,
    *,
    application_name: str,
    task: asyncio.Task,
) -> None:
    for _ in range(200):
        if task.done():
            error = task.exception()
            if error is not None:
                raise error
            pytest.fail(f"{application_name} completed before reaching the lock")
        waiting = await monitor.fetchval(
            """SELECT wait_event_type = 'Lock'
                 FROM pg_stat_activity
                WHERE application_name = $1""",
            application_name,
        )
        if waiting:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"{application_name} did not reach a database lock")


class _SingleConnectionAcquire:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> asyncpg.Connection:
        return self.connection

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _SingleConnectionPool:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection

    def acquire(self) -> _SingleConnectionAcquire:
        return _SingleConnectionAcquire(self.connection)


def _caller() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=USER,
        email="amo@example.com",
        email_verified=True,
        display_name="Amo",
    )


@pytest.mark.asyncio
async def test_route_returns_committed_capture_when_twin_enrichment_fails(
    room,
    monkeypatch,
):
    capture = _capture(41)
    request = relay.CaptureReadingRequest(**capture)
    twin = AsyncMock(side_effect=RuntimeError("embedding unavailable"))
    monkeypatch.setattr(reading, "ensure_reading_memory_twin", twin)

    result = await relay.capture_reading(
        room_id=ROOM,
        request=request,
        token="capture-token",
        current_user=_caller(),
        pool=_SingleConnectionPool(room),
    )

    assert result["revision"]["capture_id"] == capture["capture_id"]
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE capture_id = $1",
        capture["capture_id"],
    ) == 1
    twin.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_capture_creates_exact_reading_and_revision(room):
    capture = _capture(1, markdown="# Long\n\n" + ("rendered content " * 5_000) + "\n")
    capture["url"] = f"{URL}?utm_source=browser"
    result = await _save(room, capture)

    assert result["idempotent_replay"] is False
    assert result["revision"]["is_current"] is True
    stored = await room.fetchrow(
        """SELECT ri.content, ri.content_sha256, ri.source,
                  ri.current_revision_id, rr.content AS revision_content
             FROM reading_items ri
             JOIN reading_revisions rr ON rr.id = ri.current_revision_id
            WHERE ri.id = $1""",
        result["reading"]["id"],
    )
    assert stored["content"] == capture["markdown"]
    assert stored["revision_content"] == capture["markdown"]
    assert stored["content_sha256"] == capture["content_sha256"]
    assert stored["source"] == "browser_capture"
    assert await room.fetchval(
        "SELECT source_url FROM reading_revisions WHERE id = $1",
        result["revision"]["id"],
    ) == capture["url"]


@pytest.mark.asyncio
async def test_capture_canonicalizes_one_legacy_raw_url_without_duplicate(room):
    raw_url = f"{URL}?utm_source=legacy"
    legacy_id = await room.fetchval(
        """INSERT INTO reading_items
               (room_id, url, title, content, summary, key_claims, source)
           VALUES ($1,$2,'Legacy raw','legacy body','legacy summary','[]','human')
           RETURNING id""",
        ROOM, raw_url,
    )
    capture = _capture(1)
    capture["url"] = raw_url
    capture["canonical_url"] = URL

    saved = await _save(room, capture)

    assert saved["reading"]["id"] == legacy_id
    assert await room.fetchval(
        "SELECT count(*) FROM reading_items WHERE room_id = $1", ROOM,
    ) == 1
    assert await room.fetchval(
        "SELECT url FROM reading_items WHERE id = $1", legacy_id,
    ) == URL


@pytest.mark.asyncio
async def test_capture_id_replays_without_duplicate(room):
    capture = _capture(1)
    first = await _save(room, capture)
    replay = await _save(room, capture)

    assert replay["idempotent_replay"] is True
    assert replay["reading"]["id"] == first["reading"]["id"]
    assert replay["revision"]["id"] == first["revision"]["id"]
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE room_id = $1", ROOM,
    ) == 1


@pytest.mark.asyncio
async def test_capture_id_with_mutated_payload_is_conflict(room):
    capture = _capture(1)
    await _save(room, capture)
    changed = {**capture, "title": "Mutated replay"}

    with pytest.raises(reading.BrowserCaptureConflict):
        await _save(room, changed)
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE room_id = $1", ROOM,
    ) == 1


@pytest.mark.asyncio
async def test_capture_id_cannot_replay_into_another_room(room):
    capture = _capture(1)
    await _save(room, capture)

    with pytest.raises(reading.BrowserCaptureConflict):
        async with room.transaction():
            await reading.save_browser_capture(
                room,
                room_id=OTHER_ROOM,
                captured_by_user_id=USER,
                capture=capture,
            )
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE room_id = $1", ROOM,
    ) == 1


@pytest.mark.asyncio
async def test_newer_and_equal_time_captures_become_current(room):
    first = await _save(room, _capture(1))
    newer = await _save(room, _capture(2, captured_at=BASE + timedelta(minutes=1)))
    tied_later_receipt = await _save(
        room, _capture(3, captured_at=BASE + timedelta(minutes=1)),
    )

    assert first["revision"]["is_current"] is True
    assert newer["revision"]["is_current"] is True
    assert tied_later_receipt["revision"]["is_current"] is True
    current = await room.fetchrow(
        "SELECT content, current_revision_id FROM reading_items WHERE room_id = $1 AND url = $2",
        ROOM, URL,
    )
    assert current["content"] == _capture(3, captured_at=BASE + timedelta(minutes=1))["markdown"]
    assert current["current_revision_id"] == tied_later_receipt["revision"]["id"]
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE room_id = $1", ROOM,
    ) == 3


@pytest.mark.asyncio
async def test_older_delayed_capture_is_historical_only(room):
    newest = await _save(room, _capture(2, captured_at=BASE + timedelta(minutes=2)))
    delayed = await _save(room, _capture(1, captured_at=BASE))

    assert delayed["revision"]["is_current"] is False
    current = await room.fetchrow(
        "SELECT content, current_revision_id FROM reading_items WHERE room_id = $1",
        ROOM,
    )
    assert current["content"] == _capture(2, captured_at=BASE + timedelta(minutes=2))["markdown"]
    assert current["current_revision_id"] == newest["revision"]["id"]
    assert await room.fetchval(
        "SELECT count(*) FROM reading_revisions WHERE room_id = $1", ROOM,
    ) == 2


@pytest.mark.asyncio
async def test_server_refetch_path_cannot_overwrite_current_browser_evidence(room):
    browser = _capture(1)
    result = await _save(room, browser)
    legacy_article = {
        "url": URL,
        "title": "Server refetch",
        "author": None,
        "site": "Example",
        "published": None,
        "word_count": 4,
        "content": "server fetched replacement",
    }

    with pytest.raises(reading.BrowserCaptureIsCurrent):
        await reading.save_reading(
            room,
            room_id=ROOM,
            article=legacy_article,
            summary="server summary",
            key_claims=[],
            source="proposal",
            saved_by_user_id=USER,
        )

    stored = await room.fetchrow(
        """SELECT content, source, current_revision_id, content_sha256
             FROM reading_items WHERE id = $1""",
        result["reading"]["id"],
    )
    assert stored["content"] == browser["markdown"]
    assert stored["source"] == "browser_capture"
    assert stored["current_revision_id"] == result["revision"]["id"]
    assert stored["content_sha256"] == browser["content_sha256"]


@pytest.mark.asyncio
async def test_revision_body_and_hash_cannot_be_updated(room):
    saved = await _save(room, _capture(1))
    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        async with room.transaction():
            await room.execute(
                "UPDATE reading_revisions SET content = 'rewritten' WHERE id = $1",
                saved["revision"]["id"],
            )
    default_expression = await room.fetchval(
        """SELECT pg_get_expr(adbin, adrelid)
             FROM pg_attrdef
            WHERE adrelid = 'reading_revisions'::regclass
              AND adnum = (
                  SELECT attnum FROM pg_attribute
                   WHERE attrelid = 'reading_revisions'::regclass
                     AND attname = 'received_at'
              )"""
    )
    assert "clock_timestamp" in default_expression


@pytest.mark.asyncio
async def test_revision_and_current_pointer_cannot_cross_reading_or_room(room):
    saved = await _save(room, _capture(1))
    revision_id = saved["revision"]["id"]
    reading_id = saved["reading"]["id"]
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with room.transaction():
            await room.execute(
                """INSERT INTO reading_revisions
                       (reading_id, room_id, capture_id, captured_by_user_id,
                        source_url, capture_mode, content, content_sha256,
                        metadata, captured_at)
                   VALUES ($1,$2,$3,$4,$5,'article','wrong room',$6,'{}',$7)""",
                reading_id, OTHER_ROOM, _uid(0xCB99), USER, URL,
                hashlib.sha256(b"wrong room").hexdigest(), BASE,
            )

    other_reading_id = await room.fetchval(
        """INSERT INTO reading_items
               (room_id,url,title,content,summary,key_claims,source)
           VALUES ($1,'https://example.com/other-reading','Other','body','summary','[]','human')
           RETURNING id""",
        ROOM,
    )
    with pytest.raises(asyncpg.RaiseError, match="same reading and room"):
        async with room.transaction():
            await room.execute(
                "UPDATE reading_items SET current_revision_id = $1 WHERE id = $2",
                revision_id, other_reading_id,
            )


@pytest.mark.asyncio
async def test_library_search_filters_and_cursor_are_server_side(room):
    first_capture = _capture(
        1,
        captured_at=BASE,
        markdown="# Alpha\n\nThe quantumterm appears in this rendered body.\n",
    )
    second_capture = _capture(
        2,
        captured_at=BASE + timedelta(minutes=1),
        markdown="# Beta\n\nA separate rendered body.\n",
    )
    second_capture["url"] = "https://example.com/second"
    second_capture["canonical_url"] = second_capture["url"]
    await _save(room, first_capture)
    await _save(room, second_capture)
    pool = _SingleConnectionPool(room)

    search = await relay.list_reading_library(
        room_id=ROOM,
        token="capture-token",
        current_user=_caller(),
        pool=pool,
        q="quantumterm",
        site="Example",
        source="browser_capture",
        limit=50,
        before=None,
    )
    assert [item["url"] for item in search["items"]] == [URL]
    assert search["items"][0]["revision_count"] == 1
    assert search["items"][0]["capture_mode"] == "article"

    first_page = await relay.list_reading_library(
        room_id=ROOM,
        token="capture-token",
        current_user=_caller(),
        pool=pool,
        q=None,
        site=None,
        source=None,
        limit=1,
        before=None,
    )
    assert [item["url"] for item in first_page["items"]] == [second_capture["url"]]
    assert first_page["next_before"]
    second_page = await relay.list_reading_library(
        room_id=ROOM,
        token="capture-token",
        current_user=_caller(),
        pool=pool,
        q=None,
        site=None,
        source=None,
        limit=1,
        before=first_page["next_before"],
    )
    assert [item["url"] for item in second_page["items"]] == [URL]


@pytest.mark.asyncio
async def test_detail_and_download_return_exact_current_markdown(room):
    capture = _capture(1)
    capture["note"] = "Filed from the rendered authenticated page."
    saved = await _save(room, capture)
    pool = _SingleConnectionPool(room)
    reading_id = saved["reading"]["id"]

    detail = await relay.get_reading_detail(
        room_id=ROOM,
        reading_id=reading_id,
        token="capture-token",
        current_user=_caller(),
        pool=pool,
    )
    assert detail["markdown"] == capture["markdown"]
    assert detail["content_sha256"] == capture["content_sha256"]
    assert detail["revisions"][0]["is_current"] is True
    assert detail["revisions"][0]["note"] == capture["note"]
    assert detail["revisions"][0]["extraction"]["engine"] == "defuddle"

    response = await relay.download_reading_markdown(
        room_id=ROOM,
        reading_id=reading_id,
        token="capture-token",
        current_user=_caller(),
        pool=pool,
    )
    assert response.body == str(capture["markdown"]).encode()
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"].endswith('.md"')
    assert hashlib.sha256(response.body).hexdigest() == capture["content_sha256"]


@pytest.mark.asyncio
async def test_detail_is_room_fenced_with_generic_404(room):
    saved = await _save(room, _capture(1))
    with pytest.raises(HTTPException) as exc:
        await relay.get_reading_detail(
            room_id=OTHER_ROOM,
            reading_id=saved["reading"]["id"],
            token="other-token",
            current_user=_caller(),
            pool=_SingleConnectionPool(room),
        )
    assert exc.value.status_code == 404


def test_library_cursor_rejects_nonobject_and_noncanonical_base64():
    list_cursor = base64.urlsafe_b64encode(b"[]").rstrip(b"=").decode()
    with pytest.raises(HTTPException) as list_error:
        relay._decode_library_cursor(list_cursor)
    assert list_error.value.status_code == 422

    with pytest.raises(HTTPException) as garbage_error:
        relay._decode_library_cursor("%%%")
    assert garbage_error.value.status_code == 422


@pytest.mark.asyncio
async def test_equal_capture_time_uses_receipt_time_not_transaction_start():
    room_id, user_id = _uid(0xCC01), _uid(0xCC02)
    setup = await asyncpg.connect(TEST_DATABASE_URL)
    await setup.execute("DELETE FROM rooms WHERE id = $1", room_id)
    await setup.execute("DELETE FROM users WHERE id = $1", user_id)
    await setup.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,'tie-token','Tie')",
        room_id, BASE,
    )
    await setup.execute(
        "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,'Tie User')",
        user_id, BASE,
    )
    await setup.close()

    older_transaction = await asyncpg.connect(TEST_DATABASE_URL)
    later_transaction = await asyncpg.connect(TEST_DATABASE_URL)
    for connection in (older_transaction, later_transaction):
        for typename in ("jsonb", "json"):
            await connection.set_type_codec(
                typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
            )
    first_tx = older_transaction.transaction()
    second_tx = later_transaction.transaction()
    try:
        await first_tx.start()
        await asyncio.sleep(0.02)
        await second_tx.start()
        second = await reading.save_browser_capture(
            later_transaction,
            room_id=room_id,
            captured_by_user_id=user_id,
            capture=_capture(11),
        )
        await second_tx.commit()

        first = await reading.save_browser_capture(
            older_transaction,
            room_id=room_id,
            captured_by_user_id=user_id,
            capture=_capture(12),
        )
        await first_tx.commit()

        assert first["revision"]["received_at"] > second["revision"]["received_at"]
        assert first["revision"]["is_current"] is True
        verifier = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            assert await verifier.fetchval(
                "SELECT content FROM reading_items WHERE room_id = $1", room_id,
            ) == _capture(12)["markdown"]
        finally:
            await verifier.close()
    finally:
        if not older_transaction.is_closed():
            try:
                await first_tx.rollback()
            except Exception:
                pass
            await older_transaction.close()
        if not later_transaction.is_closed():
            try:
                await second_tx.rollback()
            except Exception:
                pass
            await later_transaction.close()
        cleanup = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            await cleanup.execute("DELETE FROM rooms WHERE id = $1", room_id)
            await cleanup.execute("DELETE FROM users WHERE id = $1", user_id)
        finally:
            await cleanup.close()


@pytest.mark.asyncio
async def test_concurrent_same_capture_id_creates_one_revision(concurrent_room):
    room_id, user_id = concurrent_room
    capture = _capture(31)
    ready = asyncio.Barrier(3)
    tasks = [
        asyncio.create_task(_concurrent_save(room_id, user_id, capture, ready))
        for _ in range(2)
    ]
    await ready.wait()
    results = await asyncio.gather(*tasks)

    assert sorted(result["idempotent_replay"] for result in results) == [False, True]
    verify = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        assert await verify.fetchval(
            "SELECT count(*) FROM reading_items WHERE room_id = $1", room_id,
        ) == 1
        assert await verify.fetchval(
            "SELECT count(*) FROM reading_revisions WHERE room_id = $1", room_id,
        ) == 1
    finally:
        await verify.close()


@pytest.mark.asyncio
async def test_concurrent_conflicting_same_id_leaves_no_ghost_reading(concurrent_room):
    room_id, user_id = concurrent_room
    first = _capture(32)
    changed_body = "# Conflicting replay\n\nDifferent immutable body.\n"
    conflict = {
        **first,
        "title": "Conflicting replay",
        "markdown": changed_body,
        "content_sha256": hashlib.sha256(changed_body.encode()).hexdigest(),
    }
    ready = asyncio.Barrier(3)
    tasks = [
        asyncio.create_task(_concurrent_save(room_id, user_id, payload, ready))
        for payload in (first, conflict)
    ]
    await ready.wait()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert sum(isinstance(result, reading.BrowserCaptureConflict) for result in results) == 1
    verify = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        assert await verify.fetchval(
            "SELECT count(*) FROM reading_items WHERE room_id = $1", room_id,
        ) == 1
        assert await verify.fetchval(
            "SELECT count(*) FROM reading_revisions WHERE room_id = $1", room_id,
        ) == 1
    finally:
        await verify.close()


@pytest.mark.asyncio
async def test_concurrent_distinct_first_captures_share_one_logical_reading(concurrent_room):
    room_id, user_id = concurrent_room
    captures = (_capture(33), _capture(34))
    ready = asyncio.Barrier(3)
    tasks = [
        asyncio.create_task(_concurrent_save(room_id, user_id, capture, ready))
        for capture in captures
    ]
    await ready.wait()
    await asyncio.gather(*tasks)

    verify = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        row = await verify.fetchrow(
            """SELECT content, current_revision_id,
                      (SELECT count(*) FROM reading_revisions rr
                        WHERE rr.reading_id = ri.id) AS revision_count
                 FROM reading_items ri WHERE room_id = $1""",
            room_id,
        )
        assert row["revision_count"] == 2
        assert row["current_revision_id"] is not None
        assert row["content"] in {capture["markdown"] for capture in captures}
        assert await verify.fetchval(
            "SELECT count(*) FROM reading_items WHERE room_id = $1", room_id,
        ) == 1
    finally:
        await verify.close()


@pytest.mark.asyncio
async def test_alias_convergence_locks_gap_before_canonical_insert(concurrent_room):
    room_id, user_id = concurrent_room
    raw_url = f"{URL}?utm_source=blocked-legacy"
    parallel_url = f"{URL}?utm_source=parallel-capture"
    setup = await asyncpg.connect(TEST_DATABASE_URL)
    legacy_id = await setup.fetchval(
        """INSERT INTO reading_items
               (room_id, url, title, content, summary, key_claims, source)
           VALUES ($1,$2,'Blocked legacy','legacy body','legacy summary','[]','human')
           RETURNING id""",
        room_id, raw_url,
    )
    await setup.close()

    blocker = await asyncpg.connect(TEST_DATABASE_URL)
    monitor = await asyncpg.connect(TEST_DATABASE_URL)
    blocker_tx = blocker.transaction()
    await blocker_tx.start()
    await blocker.fetchval(
        "SELECT id FROM reading_items WHERE id = $1 FOR UPDATE", legacy_id,
    )
    first = {**_capture(36), "url": raw_url, "canonical_url": URL}
    second = {**_capture(37), "url": parallel_url, "canonical_url": URL}
    first_task: asyncio.Task | None = None
    second_task: asyncio.Task | None = None
    released = False
    try:
        first_task = asyncio.create_task(
            _concurrent_save(
                room_id,
                user_id,
                first,
                asyncio.Barrier(1),
                application_name="reading-alias-first",
            )
        )
        await _wait_for_database_lock(
            monitor,
            application_name="reading-alias-first",
            task=first_task,
        )

        second_task = asyncio.create_task(
            _concurrent_save(
                room_id,
                user_id,
                second,
                asyncio.Barrier(1),
                application_name="reading-alias-second",
            )
        )
        await _wait_for_database_lock(
            monitor,
            application_name="reading-alias-second",
            task=second_task,
        )
        assert await monitor.fetchval(
            "SELECT count(*) FROM reading_items WHERE room_id = $1 AND url = $2",
            room_id, URL,
        ) == 0

        await blocker_tx.commit()
        released = True
        results = await asyncio.gather(first_task, second_task)
        assert {result["reading"]["id"] for result in results} == {legacy_id}
        row = await monitor.fetchrow(
            """SELECT url,
                      (SELECT count(*) FROM reading_revisions rr
                        WHERE rr.reading_id = ri.id) AS revision_count
                 FROM reading_items ri WHERE id = $1""",
            legacy_id,
        )
        assert row["url"] == URL
        assert row["revision_count"] == 2
        assert await monitor.fetchval(
            "SELECT count(*) FROM reading_items WHERE room_id = $1", room_id,
        ) == 1
    finally:
        if not released:
            try:
                await blocker_tx.rollback()
            except Exception:
                pass
        pending = [
            task for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await blocker.close()
        await monitor.close()


@pytest.mark.asyncio
async def test_concurrent_post_commit_twin_creation_yields_one_active_twin(
    concurrent_room,
    monkeypatch,
):
    from memory.manager import MemoryManager

    room_id, user_id = concurrent_room
    capture = _capture(35)
    await _concurrent_save(room_id, user_id, capture, asyncio.Barrier(1))

    async def insert_without_embedding(self, **kwargs):
        await asyncio.sleep(0.03)
        now = datetime.now(timezone.utc)
        await self.db.execute(
            """INSERT INTO memories
                   (id, room_id, created_at, updated_at, version, scope,
                    key, content, created_by_user_id, status)
               VALUES ($1,$2,$3,$3,1,'room',$4,$5,$6,'active')""",
            uuid4(), kwargs["room_id"], now, kwargs["key"], kwargs["content"],
            kwargs["created_by_user_id"],
        )

    monkeypatch.setattr(MemoryManager, "add_memory", insert_without_embedding)
    ready = asyncio.Barrier(3)
    tasks = [
        asyncio.create_task(_concurrent_ensure_twin(room_id, capture, ready))
        for _ in range(2)
    ]
    await ready.wait()
    await asyncio.gather(*tasks)

    verify = await asyncpg.connect(TEST_DATABASE_URL)
    try:
        assert await verify.fetchval(
            """SELECT count(*) FROM memories
                WHERE room_id = $1 AND status = 'active' AND key LIKE 'reading:%'""",
            room_id,
        ) == 1
    finally:
        await verify.close()
