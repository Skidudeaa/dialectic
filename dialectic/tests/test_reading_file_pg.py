"""
Real-Postgres contract for POST /rooms/{room_id}/reading/file — a human files
a link they pasted.

WHY it exists: production's reading_items holds `wire` (19) and `night_shift`
(13) rows and NOTHING filed by a person. `save_reading` was reachable only
through an LLM proposal a human then accepted, so an article somebody pasted
and argued about was read into the conversation and then evaporated. That is
the literal mechanism behind "it should not give everything we paste equal
weight" — everything pasted has the same weight because none of it becomes an
object that could carry any.

Setup expected (skipped cleanly when absent):
    createdb dialectic_test && psql dialectic_test -f schema.sql
    psql dialectic_test -f migrations/014_reading_library.sql
"""

import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException

import api.reading_relay as relay
from api.auth.dependencies import AuthenticatedUser
from api.reading_relay import FileReadingRequest, file_reading

TEST_DATABASE_URL = os.environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)

URL = "https://example.test/tanker-rates-lead-crude"


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


ROOM, THREAD, AMO, STRANGER = _uid(0xB01), _uid(0xB02), _uid(0xB03), _uid(0xB04)
MSG_WITH_URL, MSG_WITHOUT = _uid(0xB05), _uid(0xB06)
TOKEN = "reading-file-token"
BASE = datetime(2026, 8, 16, 7, 0, tzinfo=timezone.utc)

ARTICLE = {
    "url": URL,
    "title": "Tanker rates lead crude",
    "site": "example.test",
    "author": "A Reporter",
    "published": "2026-08-15",
    "word_count": 900,
    "content": "Freight rates on the Gulf routes moved first. " * 60,
}


def caller(user_id: UUID = AMO) -> AuthenticatedUser:
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
    if not await conn.fetchval("SELECT to_regclass('reading_items')"):
        await conn.close()
        pytest.skip("reading_items missing — run migrations/014_reading_library.sql")
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
    await db.execute(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,'Reading Room')",
        ROOM, BASE, TOKEN,
    )
    await db.execute(
        "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1,$2,$3,'Main')",
        THREAD, ROOM, BASE,
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
    for seq, (msg_id, content) in enumerate((
        (MSG_WITH_URL, f"worth reading on the freight lead: {URL}"),
        (MSG_WITHOUT, "no link in this one at all"),
    ), start=1):
        await db.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at,
                   speaker_type, user_id, message_type, content)
               VALUES ($1,$2,$3,$4,'human',$5,'text',$6)""",
            msg_id, THREAD, seq, BASE, AMO, content,
        )
    yield db
    await tx.rollback()


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


async def _file(
    db: asyncpg.Connection,
    *,
    article: dict[str, object] = ARTICLE,
    thin: bool = False,
    **overrides: object,
) -> dict:
    body = dict(message_id=MSG_WITH_URL, url=URL, summary="freight moved first")
    body.update({k: v for k, v in overrides.items()
                 if k in ("message_id", "url", "summary")})
    with patch.object(relay.dc, "extract_article", AsyncMock(return_value=article)), \
         patch.object(relay.reading_mod, "is_thin", lambda a: thin):
        return await file_reading(
            room_id=overrides.get("room_id", ROOM),
            request=FileReadingRequest(**body),
            token=overrides.get("token", TOKEN),
            current_user=overrides.get("current_user", caller()),
            pool=_SingleConnectionPool(db),
        )


@pytest.mark.asyncio
async def test_a_human_can_file_a_link_they_pasted(room):
    result = await _file(room)
    assert result["reading"]["url"] == URL
    stored = await room.fetchrow(
        "SELECT source, saved_by_user_id, source_message_id FROM reading_items WHERE url = $1",
        URL,
    )
    assert stored["source"] == "human", "distinguishable from wire and night_shift"
    assert stored["saved_by_user_id"] == AMO
    assert stored["source_message_id"] == MSG_WITH_URL


@pytest.mark.asyncio
async def test_a_url_not_in_the_message_is_refused(room):
    """Provenance that lies is worse than no provenance: source_message_id is
    what the Field's evidence marks point at."""
    with pytest.raises(HTTPException) as exc:
        await _file(room, message_id=MSG_WITHOUT)
    assert exc.value.status_code == 422
    assert await room.fetchval("SELECT count(*) FROM reading_items") == 0


@pytest.mark.asyncio
async def test_thin_content_is_refused_by_the_shared_gate(room):
    """A cookie wall filed by a human is as useless as one filed by the wire —
    is_thin() is the one policy every filing path shares."""
    with pytest.raises(HTTPException) as exc:
        await _file(room, thin=True)
    assert exc.value.status_code == 422
    assert "thin" in exc.value.detail.lower() or "paywall" in exc.value.detail.lower()
    assert await room.fetchval("SELECT count(*) FROM reading_items") == 0


@pytest.mark.asyncio
async def test_a_non_url_is_refused_before_any_fetch(room):
    with pytest.raises(HTTPException) as exc:
        await _file(room, url="javascript:alert(1)")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_non_member_cannot_file(room):
    with pytest.raises(HTTPException) as exc:
        await _file(room, current_user=caller(STRANGER))
    assert exc.value.status_code in (403, 404)
    assert await room.fetchval("SELECT count(*) FROM reading_items") == 0


@pytest.mark.asyncio
async def test_a_wrong_room_token_is_refused(room):
    with pytest.raises(HTTPException) as exc:
        await _file(room, token="not-the-token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_an_empty_summary_falls_back_to_the_title(room):
    """A filed reading with no summary at all is a row nobody can scan."""
    result = await _file(room, summary="")
    assert result["reading"]["summary"] == "Tanker rates lead crude"


@pytest.mark.asyncio
async def test_filing_twice_does_not_duplicate_the_row(room):
    """save_reading upserts on (room, url) — the library holds the article
    once however many people file it."""
    await _file(room)
    await _file(room)
    assert await room.fetchval(
        "SELECT count(*) FROM reading_items WHERE room_id = $1 AND url = $2", ROOM, URL,
    ) == 1
