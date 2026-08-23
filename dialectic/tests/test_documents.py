"""write_document — the LLM participant's file output.

Covers the three seams a document crosses: markdown → PDF bytes (real
headless Chrome, skipped where none is installed), the attachments row it
files (uploader NULL, message NULL), and the bind that ties it to the turn's
message — the predicate, not just the outcome, because a NULL-as-category
bind is exactly the kind of thing that drifts silently.
"""

import re
from types import SimpleNamespace
from uuid import uuid4

import pytest

from llm import documents
from llm.tools import build_registry


class FakeDB:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        cols = ["id", "room_id", "message_id", "uploader_user_id", "kind", "mime",
                "bytes", "sha256", "width", "height", "original_name",
                "storage_path", "created_at"]
        # Mirror the INSERT's VALUES: ($1 id, $2 room, NULL, NULL, 'file',
        # 'application/pdf', $3 bytes, $4 sha, NULL, NULL, $5 name, $6 path, $7 ts)
        vals = [args[0], args[1], None, None, "file", "application/pdf",
                args[2], args[3], None, None, args[4], args[5], args[6]]
        return dict(zip(cols, vals))

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


chrome = pytest.mark.skipif(
    documents.chrome_binary() is None, reason="no Chrome/Chromium on this host"
)


def test_render_html_escapes_raw_html_and_renders_tables():
    page = documents.render_html("T <b>x</b>", "| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>")
    assert "<title>T &lt;b&gt;x&lt;/b&gt;</title>" in page
    assert "<table>" in page and "<td>1</td>" in page
    assert "<script>" not in page


def test_render_html_drops_the_models_repeated_title_heading():
    # The page prints `title` as the H1; a body opening with "# Title" would
    # stack it twice. Only a LEADING H1 goes — an H2 or a later H1 stays.
    page = documents.render_html("Probe memo", "# Probe memo\n\n## Purpose\n\ntext\n\n# Appendix")
    assert page.count("<h1>") == 2 and "<h1>Probe memo</h1>" in page and "<h1>Appendix</h1>" in page
    assert "<h2>Purpose</h2>" in page
    page2 = documents.render_html("T", "## Not a title\n\nbody")
    assert page2.count("<h1>") == 1 and "<h2>Not a title</h2>" in page2


@chrome
@pytest.mark.asyncio
async def test_render_pdf_is_a_real_pdf():
    data = await documents.render_pdf("Capex Insider", "# Intro\n\nHello **world**.\n\n- one\n- two")
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000


@chrome
@pytest.mark.asyncio
async def test_store_document_files_an_llm_authored_row(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    db = FakeDB()
    room_id = uuid4()
    doc = await documents.store_document(db, room_id, "Weekly Brief: AI capex", "# Hi\n\ntext")

    assert doc["kind"] == "file" and doc["mime"] == "application/pdf"
    assert doc["uploader_user_id"] is None and doc["message_id"] is None
    assert doc["original_name"] == "weekly-brief-ai-capex.pdf"
    assert doc["url"] == f"/attachments/{doc['id']}"
    on_disk = tmp_path / doc["storage_path"]
    assert on_disk.is_file() and on_disk.read_bytes()[:5] == b"%PDF-"
    assert on_disk.stat().st_size == doc["bytes"]
    insert_sql = db.calls[0][0]
    assert re.search(r"VALUES\s*\(\$1,\s*\$2,\s*NULL,\s*NULL,\s*'file'", insert_sql)


@pytest.mark.asyncio
async def test_store_document_rejects_empty_and_oversize():
    db = FakeDB()
    with pytest.raises(ValueError):
        await documents.store_document(db, uuid4(), "", "x")
    with pytest.raises(ValueError):
        await documents.store_document(db, uuid4(), "t", "   ")
    with pytest.raises(ValueError):
        await documents.store_document(db, uuid4(), "t", "x" * (documents.MAX_MARKDOWN_CHARS + 1))
    assert db.calls == []  # nothing rendered, nothing written


def test_document_ids_from_calls_reads_only_document_provenance():
    a, b = uuid4(), uuid4()
    calls = [
        {"name": "write_document", "ok": True, "provenance": {"kind": "document", "attachment_id": str(a)}},
        {"name": "draft_prediction", "ok": True, "provenance": {"kind": "prediction_draft"}},
        {"name": "write_document", "ok": True, "provenance": {"kind": "document", "attachment_id": "not-a-uuid"}},
        {"name": "get_live_quotes", "ok": True},
        {"name": "write_document", "ok": True, "provenance": {"kind": "document", "attachment_id": str(b)}},
    ]
    assert documents.document_ids_from_calls(calls) == [a, b]
    assert documents.document_ids_from_calls(None) == []


@pytest.mark.asyncio
async def test_bind_documents_binds_only_unbound_llm_rows_in_room():
    db = FakeDB()
    room_id, message_id, att = uuid4(), uuid4(), uuid4()
    calls = [{"name": "write_document", "ok": True,
              "provenance": {"kind": "document", "attachment_id": str(att)}}]
    await documents.bind_documents(db, room_id, message_id, calls)
    (sql, args), = db.calls
    # The predicate IS the safety: a model must not be able to claim a
    # human's upload or re-home a bound one.
    assert re.search(r"^\s*UPDATE attachments SET message_id = \$1", sql, re.M)
    assert "room_id = $3" in sql
    assert "message_id IS NULL" in sql
    assert "uploader_user_id IS NULL" in sql
    assert args == (message_id, [att], room_id)


@pytest.mark.asyncio
async def test_bind_documents_no_documents_no_query():
    db = FakeDB()
    assert await documents.bind_documents(db, uuid4(), uuid4(), [{"name": "get_live_quotes"}]) == []
    assert db.calls == []


@chrome
@pytest.mark.asyncio
async def test_write_document_tool_returns_document_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    room = SimpleNamespace(id=uuid4(), linked_book_id=None, trading_config=None)
    db = FakeDB()
    tool = build_registry(room, db).get("write_document")
    assert tool is not None
    assert tool.timeout_s > documents.RENDER_TIMEOUT_S  # guard outlives the render
    out = await tool.execute({"title": "Memo", "content": "# Memo\n\nBody."})
    assert out["provenance"]["kind"] == "document"
    assert out["document"]["filename"] == "memo.pdf"
    assert documents.document_ids_from_calls([{"provenance": out["provenance"]}])


# ── real Postgres: the row a document files, and the bind that homes it ──

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402

TEST_DATABASE_URL = __import__("os").environ.get(
    "DIALECTIC_TEST_DATABASE_URL", "postgresql://root@localhost/dialectic_test"
)
PG_ROOM = __import__("uuid").UUID("00000000-0000-4000-8000-00000000b320")
PG_THREAD = __import__("uuid").UUID("00000000-0000-4000-8000-00000000c320")
PG_MSG = __import__("uuid").UUID("00000000-0000-4000-8000-00000000d320")


@pytest_asyncio.fixture
async def pg():
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL, timeout=5)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"dialectic_test unavailable: {exc}")
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO rooms (id, created_at, name, token) VALUES ($1, now(), 'Doc Room', 'doc-tok')", PG_ROOM)
        await conn.execute(
            "INSERT INTO threads (id, room_id, created_at, title) VALUES ($1, $2, now(), 'Main')",
            PG_THREAD, PG_ROOM)
        await conn.execute(
            """INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type, message_type, content)
               VALUES ($1, $2, 1, now(), 'llm_primary', 'text', 'Here is the brief.')""",
            PG_MSG, PG_THREAD)
        yield conn
    finally:
        await tx.rollback()
        await conn.close()


@chrome
@pytest.mark.asyncio
async def test_pg_store_then_bind_round_trip(pg, tmp_path, monkeypatch):
    """Migration 020 (uploader nullable) + the bind predicate, against the
    real table: an LLM-authored row is accepted, bound to the turn's message,
    and then visible to the same query GET /rooms/{id}/attachments runs."""
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    doc = await documents.store_document(pg, PG_ROOM, "Capex Insider", "# Hi\n\nbody")
    assert doc["uploader_user_id"] is None and doc["message_id"] is None

    calls = [{"name": "write_document", "ok": True, "provenance": {"kind": "document", "attachment_id": doc["id"]}}]
    bound = await documents.bind_documents(pg, PG_ROOM, PG_MSG, calls)
    assert [b["id"] for b in bound] == [doc["id"]]
    assert bound[0]["message_id"] == str(PG_MSG)

    # Idempotent: a second bind finds nothing unbound and changes nothing.
    assert await documents.bind_documents(pg, PG_ROOM, PG_MSG, calls) == []
    rows = await pg.fetch(
        "SELECT * FROM attachments WHERE room_id = $1 AND message_id = ANY($2::uuid[])",
        PG_ROOM, [PG_MSG])
    assert len(rows) == 1 and rows[0]["kind"] == "file" and rows[0]["uploader_user_id"] is None
