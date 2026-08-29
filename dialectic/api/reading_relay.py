# api/reading_relay.py — the human Accept that files a drafted reading into
# the room's library.
#
# The save_reading tool (llm/tools.py) performs NO write: it validates a
# proposal and the orchestrator hoists it to messages.metadata.reading_proposal.
# This endpoint is the only write path — a room member taps Accept, we
# re-fetch the page through the defuddle sidecar (the library files the page,
# not the model's memory of it), and atomically record the filing plus
# acceptance so later taps replay without duplicating.

import base64
import binascii
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.external_operations import (
    OperationBusy,
    claim_operation,
    fail_operation,
    succeed_operation,
)
from api.token_utils import extract_room_token
from llm import defuddle_client as dc
from llm import reading as reading_mod

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reading"])

CAPTURE_CONTENT_MAX_BYTES = 2_000_000

_db_pool = None


def set_reading_relay_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def get_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError("reading relay database pool is not initialized")
    return _db_pool


async def _verify_room_token(room_id: UUID, token: str, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_room_member(room_id: UUID, user_id: UUID, db) -> None:
    row = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=403, detail="User is not a member of this room")


class AcceptReadingRequest(BaseModel):
    message_id: UUID


class FileReadingRequest(BaseModel):
    """A human files a link THEY pasted — no draft, no proposal, no LLM."""
    message_id: UUID
    url: str
    summary: str = ""


class IngestAttachmentRequest(BaseModel):
    """A human files a PDF/text attachment THEY dropped — the newsletter door."""
    attachment_id: UUID
    summary: str = ""


def _http_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if any(ord(character) < 32 or character.isspace() for character in value):
        raise ValueError("URL contains whitespace or control characters")
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("URL authority is malformed") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
    ):
        raise ValueError("URL must use http or https")
    return value


class CaptureExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str = Field(min_length=1, max_length=100)
    engine_version: str = Field(min_length=1, max_length=100)
    client_version: str = Field(min_length=1, max_length=100)
    fallback_reason: str | None = Field(default=None, max_length=1000)


class CaptureReadingRequest(BaseModel):
    """Exact rendered artifact delivered by the Safari native extension."""

    model_config = ConfigDict(extra="forbid")

    capture_id: UUID
    url: str = Field(min_length=1, max_length=4096)
    canonical_url: str | None = Field(default=None, max_length=4096)
    title: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=500)
    site: str | None = Field(default=None, max_length=500)
    published: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=64)
    word_count: int | None = Field(default=None, ge=0, le=100_000_000)
    capture_mode: Literal["selection", "article", "page_fallback"]
    markdown: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    note: str | None = Field(default=None, max_length=2000)
    extraction: CaptureExtraction

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        validated = _http_url(value)
        if validated is None:
            raise ValueError("URL is required")
        return validated

    @field_validator("canonical_url")
    @classmethod
    def validate_canonical_url(cls, value: str | None) -> str | None:
        return _http_url(value)

    @field_validator("markdown")
    @classmethod
    def validate_markdown(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Markdown must not be empty")
        if "\x00" in value:
            raise ValueError("Markdown must not contain NUL")
        return value

    @field_validator("captured_at")
    @classmethod
    def validate_captured_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        if value > datetime.now(timezone.utc) + timedelta(days=1):
            raise ValueError("captured_at is implausibly far in the future")
        return value


@router.post("/rooms/{room_id}/reading/capture")
async def capture_reading(
    room_id: UUID,
    request: CaptureReadingRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Commit exact browser Markdown without a server fetch or LLM call."""
    try:
        body = request.markdown.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=422, detail="Markdown must be valid UTF-8 text") from exc
    if len(body) > CAPTURE_CONTENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Markdown exceeds 2,000,000 bytes")
    server_hash = hashlib.sha256(body).hexdigest()
    if server_hash != request.content_sha256:
        raise HTTPException(status_code=422, detail="Markdown hash does not match content_sha256")

    capture = request.model_dump(mode="python")
    capture["extraction"] = request.extraction.model_dump(mode="python")
    try:
        async with pool.acquire() as db:
            await _verify_room_token(room_id, token, db)
            await _verify_room_member(room_id, current_user.user_id, db)
            async with db.transaction():
                result = await reading_mod.save_browser_capture(
                    db,
                    room_id=room_id,
                    captured_by_user_id=current_user.user_id,
                    capture=capture,
                )

            # The immutable revision is already committed. Recall enrichment
            # may degrade, but it can never roll back or hide a capture.
            try:
                await reading_mod.ensure_reading_memory_twin(
                    db,
                    room_id=room_id,
                    article={
                        "url": result["reading"]["url"],
                        "title": result["reading"]["title"],
                        "site": request.site,
                        "published": request.published,
                    },
                    summary=reading_mod.deterministic_capture_summary(capture),
                    saved_by_user_id=current_user.user_id,
                )
            except Exception:
                logger.exception(
                    "browser capture twin enrichment failed for capture %s",
                    request.capture_id,
                )
    except reading_mod.BrowserCaptureConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


def _encode_library_cursor(effective_at: datetime, reading_id: UUID) -> str:
    payload = json.dumps(
        {"v": 1, "at": effective_at.isoformat(), "id": str(reading_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def _decode_library_cursor(value: str | None) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        padded = value + ("=" * (-len(value) % 4))
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode())
        if not isinstance(payload, dict):
            raise ValueError("cursor payload is not an object")
        if payload.get("v") != 1:
            raise ValueError("unsupported cursor version")
        timestamp = datetime.fromisoformat(payload["at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("cursor timestamp is naive")
        return timestamp, UUID(payload["id"])
    except (
        KeyError, TypeError, ValueError, UnicodeDecodeError,
        json.JSONDecodeError, binascii.Error,
    ) as exc:
        raise HTTPException(status_code=422, detail="Invalid reading-library cursor") from exc


@router.get("/rooms/{room_id}/reading/library")
async def list_reading_library(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
    q: str | None = Query(default=None, max_length=500),
    site: str | None = Query(default=None, max_length=500),
    source: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    before: str | None = Query(default=None, max_length=1000),
) -> dict:
    """Room-fenced FTS/filter list with stable effective-freshness cursors."""
    query = q.strip() if q and q.strip() else None
    site_filter = site.strip() if site and site.strip() else None
    source_filter = source.strip() if source and source.strip() else None
    before_at, before_id = _decode_library_cursor(before)
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        rows = await db.fetch(
            """WITH library AS (
                   SELECT ri.id, ri.url, ri.title, ri.author, ri.site,
                          ri.published, ri.summary, ri.source,
                          ri.saved_by_user_id, ri.created_at,
                          ri.current_captured_at, ri.content_sha256,
                          ri.current_revision_id,
                          COALESCE(ri.current_captured_at, ri.created_at) AS effective_at,
                          (SELECT count(*)::int FROM reading_revisions revisions
                            WHERE revisions.reading_id = ri.id) AS revision_count,
                          current_revision.capture_mode
                     FROM reading_items ri
                     LEFT JOIN reading_revisions current_revision
                       ON current_revision.id = ri.current_revision_id
                    WHERE ri.room_id = $1
                      AND ($2::text IS NULL OR
                           ri.fts @@ websearch_to_tsquery('english', $2))
                      AND ($3::text IS NULL OR ri.site = $3)
                      AND ($4::text IS NULL OR ri.source = $4)
               )
               SELECT * FROM library
                WHERE ($5::timestamptz IS NULL OR
                       (effective_at, id) < ($5::timestamptz, $6::uuid))
                ORDER BY effective_at DESC, id DESC
                LIMIT $7""",
            room_id, query, site_filter, source_filter,
            before_at, before_id, limit + 1,
        )
    visible = rows[:limit]
    items = [dict(row) for row in visible]
    next_before = None
    if len(rows) > limit and visible:
        next_before = _encode_library_cursor(
            visible[-1]["effective_at"], visible[-1]["id"],
        )
    return {"items": items, "next_before": next_before}


async def _reading_detail_row(db, room_id: UUID, reading_id: UUID):
    return await db.fetchrow(
        """SELECT id, room_id, url, title, author, site, published, word_count,
                  content, summary, key_claims, source, source_message_id,
                  saved_by_user_id, created_at, current_revision_id,
                  current_captured_at, content_sha256
             FROM reading_items
            WHERE room_id = $1 AND id = $2""",
        room_id, reading_id,
    )


@router.get("/rooms/{room_id}/reading/{reading_id}")
async def get_reading_detail(
    room_id: UUID,
    reading_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        reading = await _reading_detail_row(db, room_id, reading_id)
        if reading is None:
            raise HTTPException(status_code=404, detail="Reading not found")
        revisions = await db.fetch(
            """SELECT rr.id, rr.capture_id, rr.capture_mode,
                      rr.content_sha256, rr.captured_at, rr.received_at,
                      rr.captured_by_user_id, u.display_name AS actor_name,
                      rr.metadata, rr.id = $3 AS is_current
                 FROM reading_revisions rr
                 JOIN users u ON u.id = rr.captured_by_user_id
                WHERE rr.room_id = $1 AND rr.reading_id = $2
                ORDER BY rr.captured_at DESC, rr.received_at DESC, rr.id DESC""",
            room_id, reading_id, reading["current_revision_id"],
        )
    revision_items = []
    for row in revisions:
        metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        revision_items.append({
            "id": row["id"],
            "capture_id": row["capture_id"],
            "capture_mode": row["capture_mode"],
            "content_sha256": row["content_sha256"],
            "captured_at": row["captured_at"],
            "received_at": row["received_at"],
            "captured_by_user_id": row["captured_by_user_id"],
            "actor_name": row["actor_name"],
            "is_current": row["is_current"],
            "extraction": metadata.get("extraction") or {},
            "note": metadata.get("note"),
        })
    result = dict(reading)
    result["markdown"] = result.pop("content")
    result["revisions"] = revision_items
    return result


def _markdown_filename(title: str | None, reading_id: UUID) -> str:
    normalized = unicodedata.normalize("NFKD", str(title or ""))
    ascii_title = normalized.encode("ascii", "ignore").decode().strip()
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", ascii_title)
    stem = re.sub(r"\s+", "-", stem).strip("-._")[:100]
    return f"{stem or f'reading-{str(reading_id)[:8]}'}.md"


@router.get("/rooms/{room_id}/reading/{reading_id}/markdown")
async def download_reading_markdown(
    room_id: UUID,
    reading_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Response:
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        reading = await _reading_detail_row(db, room_id, reading_id)
    if reading is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    body = reading["content"].encode("utf-8")
    if reading["content_sha256"] is not None:
        actual_hash = hashlib.sha256(body).hexdigest()
        if actual_hash != reading["content_sha256"]:
            logger.error("reading %s current content hash invariant failed", reading_id)
            raise HTTPException(status_code=500, detail="Stored Markdown hash invariant failed")
    filename = _markdown_filename(reading["title"], reading_id)
    return Response(
        content=body,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/rooms/{room_id}/reading/accept")
async def accept_reading(
    room_id: UUID,
    request: AcceptReadingRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """File a drafted reading into the library. The human tap IS the write."""
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        row = await db.fetchrow(
            """SELECT m.id, m.metadata
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE m.id = $1 AND t.room_id = $2 AND NOT m.is_deleted""",
            request.message_id,
            room_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this room")

    metadata = row["metadata"]
    proposal = metadata.get("reading_proposal") if isinstance(metadata, dict) else None
    if not isinstance(proposal, dict):
        raise HTTPException(
            status_code=404, detail="This message carries no reading draft"
        )
    # Metadata is a document, not a trust boundary — re-validate at the write.
    url = str(proposal.get("url") or "").strip()
    summary = str(proposal.get("summary") or "").strip()
    if not url.startswith(("http://", "https://")) or not summary or len(summary) > 1000:
        raise HTTPException(status_code=422, detail="The stored draft is malformed")
    claims = proposal.get("key_claims")
    claims = [str(c) for c in claims][:10] if isinstance(claims, list) else []

    operation_key = f"reading:{request.message_id}:reading_proposal"
    try:
        operation = await claim_operation(
            pool,
            room_id=room_id,
            kind="reading",
            operation_key=operation_key,
            initiated_by=current_user.user_id,
            source_message_id=request.message_id,
            proposal_slot="reading_proposal",
        )
    except (OperationBusy, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if operation.status == "succeeded":
        if operation.external_result is None:
            raise RuntimeError("Succeeded external operation has no recorded result")
        return operation.external_result
    if proposal.get("accepted"):
        await fail_operation(pool, operation, error="proposal was already accepted")
        raise HTTPException(status_code=409, detail="Reading already filed")

    # The library files the page, not the model's memory of it.
    try:
        article = await dc.extract_article(url)
    except dc.DefuddleError as e:
        await fail_operation(pool, operation, error=str(e))
        logger.warning("reading relay re-fetch failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"article extractor refused the fetch: {e}"
        ) from e
    if not isinstance(article, dict) or not str(article.get("content") or "").strip():
        await fail_operation(
            pool,
            operation,
            error="URL no longer yields a readable article",
        )
        raise HTTPException(
            status_code=422, detail="The URL no longer yields a readable article"
        )

    try:
        async with pool.acquire() as db:
            async with db.transaction():
                saved = await reading_mod.save_reading(
                    db,
                    room_id=room_id,
                    article=article,
                    summary=summary,
                    key_claims=claims,
                    source="proposal",
                    source_message_id=request.message_id,
                    saved_by_user_id=current_user.user_id,
                )
                await succeed_operation(db, operation, result=saved)
    except reading_mod.BrowserCaptureIsCurrent as exc:
        await fail_operation(pool, operation, error=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        await fail_operation(pool, operation, error=str(exc))
        raise
    return saved


@router.post("/rooms/{room_id}/reading/file")
async def file_reading(
    room_id: UUID,
    request: FileReadingRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """File a link a human pasted, without waiting to be offered it.

    WHY this exists: the library had exactly two ways in — the wire and the
    night digest — and production shows it. Every reading_items row is
    `source='wire'` or `source='night_shift'`; not one was filed by a person.
    `save_reading` was reachable only through an LLM proposal a human then
    accepted, so an article somebody pasted and discussed was read aloud into
    the conversation and then evaporated.

    That is also the real answer to "it should not give everything we paste
    equal weight": everything pasted carries the same weight because none of
    it becomes an object that could carry any. This is the door that makes it
    one; what the room then does with it (evidence marks, confirms) is what
    makes weights differ.

    The URL must appear in the named message. Not for security — the caller
    is already a member and could paste it themselves — but because a reading
    filed from a message it does not appear in has a provenance link that
    lies, and `source_message_id` is what the Field's evidence marks point at.
    """
    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        row = await db.fetchrow(
            """SELECT m.id, m.content
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE m.id = $1 AND t.room_id = $2 AND NOT m.is_deleted""",
            request.message_id, room_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this room")

    url = request.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Not a fetchable URL")
    if url not in (row["content"] or ""):
        raise HTTPException(
            status_code=422, detail="That URL does not appear in this message",
        )

    summary = request.summary.strip()
    if len(summary) > 1000:
        raise HTTPException(status_code=422, detail="Summary is too long")

    try:
        article = await dc.extract_article(url)
    except dc.DefuddleError as e:
        logger.warning("reading file re-fetch failed: %s", e)
        raise HTTPException(
            status_code=502, detail=f"article extractor refused the fetch: {e}"
        )
    if not isinstance(article, dict) or not str(article.get("content") or "").strip():
        raise HTTPException(
            status_code=422, detail="The URL no longer yields a readable article"
        )
    # The SAME thin-content gate every automated filing path shares — a
    # cookie wall filed by a human is as useless as one filed by the wire.
    if reading_mod.is_thin(article):
        raise HTTPException(
            status_code=422,
            detail="That page came back too thin to file — a paywall or a bot check",
        )

    try:
        async with pool.acquire() as db:
            saved = await reading_mod.save_reading(
                db,
                room_id=room_id,
                article=article,
                summary=summary or str(article.get("title") or url)[:280],
                key_claims=[],
                source="human",
                source_message_id=request.message_id,
                saved_by_user_id=current_user.user_id,
            )
    except reading_mod.BrowserCaptureIsCurrent as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reading": saved}


@router.post("/rooms/{room_id}/reading/ingest-attachment")
async def ingest_attachment(
    room_id: UUID,
    request: IngestAttachmentRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """File a dropped PDF/text attachment as a reading — the newsletter door.

    WHY here and not a new router: this is /reading/file's sibling — same
    auth, same thin gate, same save_reading — with the article coming off
    the room's own attachment store instead of a re-fetch. The drop IS the
    transport (owner ruling: forward/drop of emails/PDFs, never IMAP); a
    Capex Insider issue lands as source='newsletter' with a content-hashed
    synthetic URL, so re-dropping the same file refreshes rather than
    duplicates (UNIQUE(room_id, url) + the attachment store's own sha256).

    An UNBOUND attachment (uploaded, never sent) is the uploader's in-flight
    state — only they may file it; once bound to a message it is the room's.
    """
    from api.attachments import media_root
    from llm import newsletter_ingest

    async with pool.acquire() as db:
        await _verify_room_token(room_id, token, db)
        await _verify_room_member(room_id, current_user.user_id, db)
        row = await db.fetchrow(
            """SELECT id, message_id, uploader_user_id, mime, sha256,
                      original_name, storage_path
               FROM attachments WHERE id = $1 AND room_id = $2""",
            request.attachment_id, room_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found in this room")
    if row["message_id"] is None and row["uploader_user_id"] != current_user.user_id:
        raise HTTPException(
            status_code=403, detail="Only the uploader can file an unsent attachment",
        )
    if row["mime"] not in newsletter_ingest.INGESTABLE_MIMES:
        raise HTTPException(
            status_code=422,
            detail=f"Only PDF and plain-text attachments can be filed "
                   f"as readings (got {row['mime']})",
        )
    summary = request.summary.strip()
    if len(summary) > 1000:
        raise HTTPException(status_code=422, detail="Summary is too long")

    # Same containment as GET /attachments/{id}: storage_path is
    # server-generated, but a corrupted row must not read outside the root.
    import os

    root = media_root()
    path = os.path.realpath(os.path.join(root, row["storage_path"]))
    if os.path.commonpath([path, os.path.realpath(root)]) != os.path.realpath(root):
        logger.error("attachment %s has an out-of-root storage_path", row["id"])
        raise HTTPException(status_code=404, detail="Attachment not found in this room")
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        raise HTTPException(status_code=404, detail="Attachment file missing")

    try:
        async with pool.acquire() as db:
            saved = await newsletter_ingest.ingest_attachment_reading(
                db,
                room_id=room_id,
                blob=blob,
                mime=row["mime"],
                sha256=row["sha256"],
                original_name=row["original_name"],
                summary=summary,
                source_message_id=row["message_id"],
                saved_by_user_id=current_user.user_id,
            )
    except newsletter_ingest.NewsletterIngestError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"reading": saved}
