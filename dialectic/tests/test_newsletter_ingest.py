"""
Tests for llm/newsletter_ingest.py and its door —
POST /rooms/{room_id}/reading/ingest-attachment.

The drop IS the transport (owner ruling: newsletters enter by forward/drop,
never IMAP), so what matters here: a PDF's text actually extracts (real
pypdf against a hand-built fixture — no source-text assertions), the
synthetic URL is content-hashed so a re-drop is idempotent by construction,
the thin gate rejects a text-layer-less scan, and the door 422s anything
that is not a PDF/text attachment. Door strategy mirrors
tests/test_reading_relay_endpoint.py: dependency overrides + a fake db
routed by table; MEDIA_ROOT pointed at tmp_path so the blob read is real.
"""

import hashlib
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

import api.main as main_mod
import api.reading_relay as relay
from api.auth.dependencies import AuthenticatedUser, get_current_user
from llm import newsletter_ingest, reading


ROOM_ID = UUID("00000000-0000-0000-0000-000000000042")
CALLER_ID = UUID("00000000-0000-0000-0000-0000000000aa")
OTHER_ID = UUID("00000000-0000-0000-0000-0000000000bb")
ATTACHMENT_ID = UUID("00000000-0000-0000-0000-0000000000ac")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000ad")


# =========================================================================
# PDF fixture — a real, minimal, single-page PDF with a text layer
# =========================================================================

def make_pdf(lines) -> bytes:
    """Hand-built valid PDF (correct xref) — pypdf must actually parse it,
    so the tests exercise the real extraction path, not a mock of it."""
    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    ops = ["BT /F1 12 Tf 72 720 Td 14 TL"]
    for line in lines:
        ops.append(f"({esc(line)}) Tj T*")
    ops.append("ET")
    stream_content = " ".join(ops).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
         b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"),
        (b"<< /Length " + str(len(stream_content)).encode() + b" >>\nstream\n"
         + stream_content + b"\nendstream"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref_pos).encode()
            + b"\n%%EOF\n")
    return bytes(out)


BODY_WORDS = " ".join(f"thesis{i}" for i in range(120))
GOOD_PDF = make_pdf(["Capex Insider Weekly", BODY_WORDS])
GOOD_PDF_SHA = hashlib.sha256(GOOD_PDF).hexdigest()
THIN_PDF = make_pdf(["Cover Page", "only a few words here"])
GOOD_TEXT = ("Capex Insider Special\n\n" + BODY_WORDS).encode("utf-8")
GOOD_TEXT_SHA = hashlib.sha256(GOOD_TEXT).hexdigest()


@pytest.fixture
def saved(monkeypatch):
    """Record save_reading calls at the pipeline's own import site."""
    calls = []

    async def _save(db, *, room_id, article, summary, key_claims, source,
                    source_message_id=None, saved_by_user_id=None):
        calls.append({"room_id": room_id, "article": article,
                      "summary": summary, "source": source,
                      "source_message_id": source_message_id,
                      "saved_by_user_id": saved_by_user_id})
        return {"id": str(uuid4()), "url": article["url"],
                "title": article["title"], "source": source}

    monkeypatch.setattr(newsletter_ingest, "save_reading", _save)
    return calls


# =========================================================================
# The pipeline
# =========================================================================


@pytest.mark.asyncio
class TestIngestPipeline:
    async def test_pdf_becomes_a_reading_with_synthetic_url(self, saved):
        row = await newsletter_ingest.ingest_attachment_reading(
            None, room_id=ROOM_ID, blob=GOOD_PDF, mime="application/pdf",
            sha256=GOOD_PDF_SHA, original_name="capex-insider-aug.pdf",
            saved_by_user_id=CALLER_ID,
        )
        assert row["source"] == "newsletter"
        [call] = saved
        article = call["article"]
        assert article["url"] == (
            f"newsletter://capex-insider-aug/{GOOD_PDF_SHA[:12]}")
        assert article["title"] == "Capex Insider Weekly"
        assert article["site"] == "newsletter"
        assert article["word_count"] > 80
        assert "thesis0" in article["content"]
        # No explicit summary → the title stands in.
        assert call["summary"] == "Capex Insider Weekly"
        assert call["saved_by_user_id"] == CALLER_ID

    async def test_redrop_is_idempotent_by_url(self, saved):
        """Same bytes → same sha → same synthetic URL. UNIQUE(room_id, url)
        then makes the second drop an upsert, never a duplicate — the
        idempotency is content-addressed, not remembered."""
        for _ in range(2):
            await newsletter_ingest.ingest_attachment_reading(
                None, room_id=ROOM_ID, blob=GOOD_PDF, mime="application/pdf",
                sha256=GOOD_PDF_SHA, original_name="capex-insider-aug.pdf",
            )
        urls = [c["article"]["url"] for c in saved]
        assert urls[0] == urls[1]

    async def test_thin_pdf_is_rejected(self, saved):
        with pytest.raises(newsletter_ingest.NewsletterIngestError):
            await newsletter_ingest.ingest_attachment_reading(
                None, room_id=ROOM_ID, blob=THIN_PDF, mime="application/pdf",
                sha256=hashlib.sha256(THIN_PDF).hexdigest(),
                original_name="scan.pdf",
            )
        assert saved == []

    async def test_text_plain_path(self, saved):
        await newsletter_ingest.ingest_attachment_reading(
            None, room_id=ROOM_ID, blob=GOOD_TEXT, mime="text/plain",
            sha256=GOOD_TEXT_SHA, original_name="capex forward.txt",
            summary="This week's asymmetric trade.",
        )
        [call] = saved
        assert call["article"]["url"] == (
            f"newsletter://capex-forward/{GOOD_TEXT_SHA[:12]}")
        assert call["article"]["title"] == "Capex Insider Special"
        assert call["summary"] == "This week's asymmetric trade."

    async def test_unsupported_mime_refused(self, saved):
        with pytest.raises(newsletter_ingest.NewsletterIngestError):
            await newsletter_ingest.ingest_attachment_reading(
                None, room_id=ROOM_ID, blob=b"GIF89a", mime="image/gif",
                sha256="00" * 32, original_name="chart.gif",
            )
        assert saved == []

    async def test_garbage_pdf_bytes_refused(self, saved):
        with pytest.raises(newsletter_ingest.NewsletterIngestError):
            await newsletter_ingest.ingest_attachment_reading(
                None, room_id=ROOM_ID, blob=b"%PDF-1.4 but then garbage",
                mime="application/pdf", sha256="11" * 32,
                original_name="broken.pdf",
            )
        assert saved == []

    async def test_memory_twin_groups_by_the_slug(self):
        """The twin key derives its 'domain' from the synthetic URL's netloc
        — save_reading's own helper, so recall groups a newsletter's issues
        the way it groups a site's articles."""
        article = {
            "url": f"newsletter://capex-insider-aug/{GOOD_PDF_SHA[:12]}",
            "title": "Capex Insider Weekly",
        }
        key = reading._reading_key(article)
        assert key == "reading:capex-insider-aug-capex-insider-weekly"


class TestTitleExtraction:
    def test_first_heading_line_wins(self):
        text = "\n\nThe Weekly Wrap\nlong body follows here"
        assert newsletter_ingest.title_from_text(text, "x.pdf") == "The Weekly Wrap"

    def test_overlong_first_line_falls_back_to_filename(self):
        text = ("word " * 60).strip() + "\nsecond line"
        assert newsletter_ingest.title_from_text(
            text, "capex-aug-2026.pdf") == "capex-aug-2026"

    def test_empty_text_falls_back_to_filename_stem(self):
        assert newsletter_ingest.title_from_text("", "issue.txt") == "issue"
        assert newsletter_ingest.title_from_text("", "") == "newsletter"


# =========================================================================
# The door
# =========================================================================


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc_info):
        return None


class _Pool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _AsyncContext(self.db)


def _make_db(attachment_row):
    fake_db = AsyncMock()

    async def fetchrow(query, *params):
        if "FROM rooms" in query:
            return {"?column?": 1}
        if "FROM room_memberships" in query:
            return {"?column?": 1}
        if "FROM attachments" in query:
            return attachment_row
        return None

    fake_db.fetchrow = AsyncMock(side_effect=fetchrow)
    fake_db.fetchval = AsyncMock(return_value=None)
    fake_db.execute = AsyncMock()
    return fake_db


def _attachment_row(*, mime="application/pdf", sha256=GOOD_PDF_SHA,
                    storage_path="blob.pdf", message_id=MESSAGE_ID,
                    uploader=CALLER_ID, name="capex-insider-aug.pdf"):
    return {"id": ATTACHMENT_ID, "message_id": message_id,
            "uploader_user_id": uploader, "mime": mime, "sha256": sha256,
            "original_name": name, "storage_path": storage_path}


def _post(fake_db, monkeypatch, tmp_path, blob=GOOD_PDF,
          storage_path="blob.pdf", body=None):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    if blob is not None:
        (tmp_path / storage_path).write_bytes(blob)

    main_mod.app.dependency_overrides[relay.get_pool] = lambda: _Pool(fake_db)
    main_mod.app.dependency_overrides[relay.extract_room_token] = lambda: "tok"
    main_mod.app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        user_id=CALLER_ID, email="caller@test", email_verified=True,
        display_name="Caller",
    )
    try:
        return TestClient(main_mod.app).post(
            f"/rooms/{ROOM_ID}/reading/ingest-attachment",
            json=body or {"attachment_id": str(ATTACHMENT_ID)},
        )
    finally:
        main_mod.app.dependency_overrides.clear()


class TestIngestDoor:
    def test_pdf_attachment_files_a_newsletter_reading(
        self, monkeypatch, tmp_path, saved,
    ):
        resp = _post(_make_db(_attachment_row()), monkeypatch, tmp_path)
        assert resp.status_code == 200
        assert resp.json()["reading"]["source"] == "newsletter"
        [call] = saved
        assert call["source"] == "newsletter"
        assert call["room_id"] == ROOM_ID
        assert call["source_message_id"] == MESSAGE_ID
        assert call["saved_by_user_id"] == CALLER_ID
        assert call["article"]["url"] == (
            f"newsletter://capex-insider-aug/{GOOD_PDF_SHA[:12]}")

    def test_text_plain_attachment_files(self, monkeypatch, tmp_path, saved):
        row = _attachment_row(mime="text/plain", sha256=GOOD_TEXT_SHA,
                              storage_path="blob.txt", name="capex.txt")
        resp = _post(_make_db(row), monkeypatch, tmp_path,
                     blob=GOOD_TEXT, storage_path="blob.txt")
        assert resp.status_code == 200
        assert len(saved) == 1

    def test_non_ingestable_kind_is_422(self, monkeypatch, tmp_path, saved):
        row = _attachment_row(mime="image/png", storage_path="blob.png")
        resp = _post(_make_db(row), monkeypatch, tmp_path,
                     blob=b"\x89PNG", storage_path="blob.png")
        assert resp.status_code == 422
        assert "PDF and plain-text" in resp.json()["detail"]
        assert saved == []

    def test_csv_kind_is_422(self, monkeypatch, tmp_path, saved):
        """CSV uploads are allowed as ATTACHMENTS but are tabular data, not
        a newsletter — the ingest door's allowlist is narrower than the
        upload door's, on purpose."""
        row = _attachment_row(mime="text/csv", storage_path="blob.csv")
        resp = _post(_make_db(row), monkeypatch, tmp_path,
                     blob=b"a,b\n1,2\n", storage_path="blob.csv")
        assert resp.status_code == 422
        assert saved == []

    def test_thin_pdf_is_422(self, monkeypatch, tmp_path, saved):
        row = _attachment_row(sha256=hashlib.sha256(THIN_PDF).hexdigest())
        resp = _post(_make_db(row), monkeypatch, tmp_path, blob=THIN_PDF)
        assert resp.status_code == 422
        assert saved == []

    def test_unknown_attachment_is_404(self, monkeypatch, tmp_path, saved):
        resp = _post(_make_db(None), monkeypatch, tmp_path)
        assert resp.status_code == 404
        assert saved == []

    def test_unbound_attachment_is_uploader_only(
        self, monkeypatch, tmp_path, saved,
    ):
        """Unbound = uploaded but never sent: the uploader's in-flight
        state. Another member cannot file it."""
        row = _attachment_row(message_id=None, uploader=OTHER_ID)
        resp = _post(_make_db(row), monkeypatch, tmp_path)
        assert resp.status_code == 403
        assert saved == []

    def test_unbound_own_attachment_is_fine(self, monkeypatch, tmp_path, saved):
        row = _attachment_row(message_id=None, uploader=CALLER_ID)
        resp = _post(_make_db(row), monkeypatch, tmp_path)
        assert resp.status_code == 200
        [call] = saved
        assert call["source_message_id"] is None

    def test_missing_blob_is_404(self, monkeypatch, tmp_path, saved):
        resp = _post(_make_db(_attachment_row()), monkeypatch, tmp_path,
                     blob=None)
        assert resp.status_code == 404
        assert saved == []
