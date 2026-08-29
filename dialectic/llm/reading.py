# llm/reading.py — the reading library: persistence and recall for articles
# the room has actually read.
#
# Two stores, one save:
#   reading_items  — the whole article (migrations/014_reading_library.sql).
#                    Body, metadata, provenance, FTS. UNIQUE(room_id, url):
#                    re-reading a URL refreshes the row, never duplicates it.
#   memories       — a distilled twin (key 'reading:<domain>-<slug>',
#                    dedup=False) so the existing three-lane recall finds
#                    readings with zero recall changes. The body stays out of
#                    the memory pool: article bodies dwarf conversational
#                    memories, and one embedding per 6k characters is coarse.

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import UUID

logger = logging.getLogger(__name__)

# Bodies are stored whole enough to quote from, capped so a pathological page
# cannot inflate the table. The model-facing cap (tools.ARTICLE_CONTENT_CAP)
# is smaller; this is the storage ceiling.
CONTENT_STORE_CAP = 40_000

# Bot-blocked shells and error pages ("404", cookie walls) parse as near-empty
# content. Filing one teaches recall nothing and litters the morning brief, so
# every filing path skips them before spending an LLM call. The threshold lives
# here, beside save_reading, because it is a property of what deserves to be in
# the library -- not of any one job that fills it.
THIN_CONTENT_MIN_WORDS = 80

# Per-source floors keyed by the SOURCE's declared tag (a watchlist entry's
# `tag`, never the room). A Truth Social post is legitimately 30 words; a
# Reuters page that extracts to 30 words is a bot wall. The map is small and
# explicit ON PURPOSE: every entry is a policy decision that some source's
# short form is signal, and the global floor above never moves for it.
SOURCE_THIN_FLOORS = {"social": 25}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class BrowserCaptureConflict(ValueError):
    """A capture_id was replayed with a different immutable payload."""


class BrowserCaptureIsCurrent(ValueError):
    """A legacy refetch tried to replace a canonical browser artifact."""


def is_thin(article: dict, source_tag: Optional[str] = None) -> bool:
    """True when an extracted page is too empty to be worth filing.

    `source_tag` selects a per-source floor from SOURCE_THIN_FLOORS; an
    unknown or absent tag uses the global THIN_CONTENT_MIN_WORDS, so no
    caller can lower the gate by inventing a tag.
    """
    if not str(article.get("content") or "").strip():
        return True
    floor = SOURCE_THIN_FLOORS.get(source_tag, THIN_CONTENT_MIN_WORDS)
    return (article.get("word_count") or 0) < floor


def _reading_key(article: dict) -> str:
    """Deterministic memory-twin key: upsert-stable across re-reads."""
    domain = urlparse(str(article.get("url") or "")).netloc or "unknown"
    title = str(article.get("title") or "untitled").lower()
    slug = _SLUG_RE.sub("-", title).strip("-")[:50].strip("-") or "untitled"
    return f"reading:{domain}-{slug}"


async def save_reading(
    db,
    room_id: UUID,
    article: dict,
    summary: str,
    key_claims: list[str],
    source: str,
    source_message_id: Optional[UUID] = None,
    saved_by_user_id: Optional[UUID] = None,
) -> dict:
    """Upsert the article into reading_items and maintain its memory twin.

    `article` is the defuddle payload ({url, title, author, site, published,
    word_count, content}) — always freshly fetched by the caller, never
    model-supplied. Returns the stored row as a dict.
    """
    url = str(article.get("url") or "").strip()
    if not url:
        raise ValueError("reading needs a url")
    summary = summary.strip()
    if not summary:
        raise ValueError("reading needs a summary")
    content = str(article.get("content") or "")[:CONTENT_STORE_CAP]
    claims = [str(c) for c in (key_claims or [])][:10]

    # Browser capture may converge a raw URL onto this exact URL. Keep the
    # lock through commit, including for legacy callers that do not open a
    # transaction themselves; otherwise an uncommitted canonical insert can
    # race a raw-to-canonical update into a unique violation.
    async with db.transaction():
        await db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"reading-url:{room_id}:{url}",
        )
        row = await db.fetchrow(
            """INSERT INTO reading_items
                   (room_id, url, title, author, site, published, word_count,
                    content, summary, key_claims, source,
                    source_message_id, saved_by_user_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (room_id, url) DO UPDATE SET
                   title = EXCLUDED.title,
                   author = EXCLUDED.author,
                   site = EXCLUDED.site,
                   published = EXCLUDED.published,
                   word_count = EXCLUDED.word_count,
                   content = EXCLUDED.content,
                   summary = EXCLUDED.summary,
                   key_claims = EXCLUDED.key_claims,
                   source = EXCLUDED.source,
                   source_message_id = EXCLUDED.source_message_id,
                   saved_by_user_id = EXCLUDED.saved_by_user_id
               WHERE reading_items.current_revision_id IS NULL
               RETURNING id, url, title, site, published, summary, source""",
            room_id, url,
            article.get("title"), article.get("author"), article.get("site"),
            article.get("published"), article.get("word_count"),
            content, summary, claims, source,
            source_message_id, saved_by_user_id,
        )

        # A direct browser artifact is stronger evidence than a later server
        # re-fetch of the same URL. Preserve its exact current projection; the
        # immutable revision would otherwise point at a body/hash the legacy
        # upsert had replaced. Legacy-only rows retain their historical upsert.
        if row is None:
            raise BrowserCaptureIsCurrent(
                "This URL already has a canonical browser capture; capture it again to revise it"
            )

        await ensure_reading_memory_twin(
            db,
            room_id=room_id,
            article=article,
            summary=summary,
            source_message_id=source_message_id,
            saved_by_user_id=saved_by_user_id,
        )

        return dict(row)


async def ensure_reading_memory_twin(
    db,
    *,
    room_id: UUID,
    article: dict,
    summary: str,
    source_message_id: Optional[UUID] = None,
    saved_by_user_id: Optional[UUID] = None,
) -> None:
    """Create the recall twin if absent; failure never invalidates a reading."""
    input_url = str(article.get("url") or "")
    lock_key = f"reading-twin:{room_id}:{input_url}"
    try:
        # App and Safari extension are separate processes. A session advisory
        # lock closes the check/insert race without coupling twin enrichment to
        # the already-committed browser-revision transaction.
        await db.execute(
            "SELECT pg_advisory_lock(hashtextextended($1, 0))", lock_key,
        )
        current = await db.fetchrow(
            """SELECT url, title, site, published, summary,
                      source_message_id, saved_by_user_id
                 FROM reading_items WHERE room_id = $1 AND url = $2""",
            room_id, input_url,
        )
        if current is not None:
            article = {
                "url": current["url"],
                "title": current["title"],
                "site": current["site"],
                "published": current["published"],
            }
            summary = current["summary"]
            source_message_id = current["source_message_id"]
            saved_by_user_id = current["saved_by_user_id"]
        key = _reading_key(article)
        existing = await db.fetchval(
            """SELECT 1 FROM memories
               WHERE room_id = $1 AND key = $2 AND status = 'active'""",
            room_id, key,
        )
        if not existing:
            from memory.manager import MemoryManager

            attribution = " — ".join(
                str(part) for part in (
                    article.get("title"), article.get("site"),
                    article.get("published"), article.get("url"),
                ) if part
            )
            await MemoryManager(db).add_memory(
                room_id=room_id,
                key=key,
                content=f"{summary}\n\n{attribution}",
                created_by_user_id=saved_by_user_id,
                source_message_id=source_message_id,
                dedup=False,
            )
    except Exception:
        # The library row is the source of truth; recall degrades, never dies.
        domain = urlparse(str(article.get("url") or "")).netloc or "unknown"
        logger.exception("reading memory twin failed for domain %s", domain)
    finally:
        try:
            await db.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key,
            )
        except Exception:
            logger.exception("reading memory twin advisory unlock failed")


def deterministic_capture_summary(capture: dict) -> str:
    """Return the bounded no-LLM summary for a direct browser capture."""
    for candidate in (capture.get("note"), capture.get("description")):
        text = str(candidate or "").strip()
        if text:
            return text[:1000]

    markdown = str(capture.get("markdown") or "")
    for block in re.split(r"\n\s*\n", markdown):
        text = block.strip()
        if not text or text.startswith(("#", "```", "~~~")):
            continue
        text = re.sub(r"!\[[^]]*\]\([^)]*\)", "", text)
        text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"^[>\-*+\d.\s]+", "", text)
        text = re.sub(r"[`*_~]", "", text).strip()
        if text:
            return text[:1000]

    for candidate in (capture.get("title"), capture.get("canonical_url"), capture.get("url")):
        text = str(candidate or "").strip()
        if text:
            return text[:1000]
    raise ValueError("browser capture needs summary material")


def _capture_fingerprint(capture: dict) -> str:
    """Hash the normalized request so capture_id replay cannot mutate metadata."""
    def normalize(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    canonical = json.dumps(
        normalize(capture), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _capture_metadata(capture: dict, fingerprint: str) -> dict[str, Any]:
    return {
        "url": capture["url"],
        "canonical_url": capture.get("canonical_url"),
        "title": capture.get("title"),
        "author": capture.get("author"),
        "site": capture.get("site"),
        "published": capture.get("published"),
        "description": capture.get("description"),
        "language": capture.get("language"),
        "word_count": capture.get("word_count"),
        "note": capture.get("note"),
        "extraction": capture.get("extraction") or {},
        "request_fingerprint": fingerprint,
    }


async def _browser_capture_result(
    db,
    *,
    capture_id: UUID,
    room_id: UUID,
    captured_by_user_id: UUID,
    fingerprint: str,
    idempotent_replay: bool,
) -> dict[str, Any]:
    row = await db.fetchrow(
        """SELECT
               ri.id AS reading_id, ri.room_id, ri.url, ri.title, ri.site,
               ri.source, ri.current_revision_id, ri.current_captured_at,
               ri.content_sha256 AS current_content_sha256,
               rr.id AS revision_id, rr.capture_id, rr.capture_mode,
               rr.captured_by_user_id,
               rr.content_sha256 AS revision_content_sha256,
               rr.captured_at, rr.received_at, rr.metadata
           FROM reading_revisions rr
           JOIN reading_items ri ON ri.id = rr.reading_id
          WHERE rr.capture_id = $1""",
        capture_id,
    )
    if row is None:
        raise RuntimeError("capture revision disappeared inside its transaction")
    if row["room_id"] != room_id or row["captured_by_user_id"] != captured_by_user_id:
        raise BrowserCaptureConflict("capture_id belongs to a different room or user")
    metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
    if metadata.get("request_fingerprint") != fingerprint:
        raise BrowserCaptureConflict("capture_id belongs to a different payload")
    return {
        "reading": {
            "id": row["reading_id"],
            "room_id": row["room_id"],
            "url": row["url"],
            "title": row["title"],
            "site": row["site"],
            "source": row["source"],
            "current_revision_id": row["current_revision_id"],
            "current_captured_at": row["current_captured_at"],
            "content_sha256": row["current_content_sha256"],
        },
        "revision": {
            "id": row["revision_id"],
            "capture_id": row["capture_id"],
            "capture_mode": row["capture_mode"],
            "content_sha256": row["revision_content_sha256"],
            "captured_at": row["captured_at"],
            "received_at": row["received_at"],
            "is_current": row["current_revision_id"] == row["revision_id"],
        },
        "idempotent_replay": idempotent_replay,
    }


async def save_browser_capture(
    db,
    *,
    room_id: UUID,
    captured_by_user_id: UUID,
    capture: dict,
) -> dict[str, Any]:
    """Store one immutable browser revision and update its logical reading.

    The caller owns the transaction. Missing-row races are resolved with
    conflict-safe inserts; the current projection advances only by captured_at,
    with a later receipt winning an equal timestamp.
    """
    capture_id = capture["capture_id"]
    if not isinstance(capture_id, UUID):
        capture_id = UUID(str(capture_id))
    fingerprint = _capture_fingerprint(capture)

    existing = await db.fetchval(
        "SELECT 1 FROM reading_revisions WHERE capture_id = $1", capture_id,
    )
    if existing:
        return await _browser_capture_result(
            db,
            capture_id=capture_id,
            room_id=room_id,
            captured_by_user_id=captured_by_user_id,
            fingerprint=fingerprint,
            idempotent_replay=True,
        )

    logical_url = str(capture.get("canonical_url") or capture["url"])
    source_url = str(capture["url"])
    title = str(capture.get("title") or "").strip() or logical_url
    summary = deterministic_capture_summary(capture)
    candidate_urls = list(dict.fromkeys((logical_url, source_url)))
    # Lock every alias in deterministic order before looking for candidates.
    # Legacy upserts take the same per-URL lock, while browser captures always
    # share the logical URL lock, closing both raw/canonical gap races.
    for candidate_url in sorted(candidate_urls):
        await db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"reading-url:{room_id}:{candidate_url}",
        )
    existing_readings = await db.fetch(
        """SELECT id, url FROM reading_items
            WHERE room_id = $1 AND url = ANY($2::text[])
            ORDER BY id
            FOR UPDATE""",
        room_id, candidate_urls,
    )
    if len(existing_readings) > 1:
        raise BrowserCaptureConflict(
            "source and canonical URLs already belong to different readings"
        )
    if existing_readings:
        reading_id = existing_readings[0]["id"]
        if existing_readings[0]["url"] != logical_url:
            await db.execute(
                "UPDATE reading_items SET url = $2 WHERE id = $1",
                reading_id, logical_url,
            )
    else:
        reading_id = await db.fetchval(
            """INSERT INTO reading_items
                   (room_id, url, title, author, site, published, word_count,
                    content, summary, key_claims, source, saved_by_user_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'[]'::jsonb,'browser_capture',$10)
               ON CONFLICT (room_id, url) DO NOTHING
               RETURNING id""",
            room_id, logical_url, title, capture.get("author"), capture.get("site"),
            capture.get("published"), capture.get("word_count"), capture["markdown"],
            summary, captured_by_user_id,
        )
        if reading_id is None:
            reading_id = await db.fetchval(
                """SELECT id FROM reading_items
                    WHERE room_id = $1 AND url = $2 FOR UPDATE""",
                room_id, logical_url,
            )
    if reading_id is None:
        raise RuntimeError("logical reading disappeared during capture")

    metadata = _capture_metadata(capture, fingerprint)
    revision = await db.fetchrow(
        """INSERT INTO reading_revisions
               (reading_id, room_id, capture_id, captured_by_user_id,
                source_url, capture_mode, content, content_sha256, metadata,
                captured_at, received_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,clock_timestamp())
           ON CONFLICT (capture_id) DO NOTHING
           RETURNING id, received_at""",
        reading_id, room_id, capture_id, captured_by_user_id,
        source_url, capture["capture_mode"], capture["markdown"],
        capture["content_sha256"], metadata, capture["captured_at"],
    )
    if revision is None:
        return await _browser_capture_result(
            db,
            capture_id=capture_id,
            room_id=room_id,
            captured_by_user_id=captured_by_user_id,
            fingerprint=fingerprint,
            idempotent_replay=True,
        )

    await db.execute(
        """UPDATE reading_items SET
               url = $2,
               title = $3,
               author = $4,
               site = $5,
               published = $6,
               word_count = $7,
               content = $8,
               summary = $9,
               key_claims = '[]'::jsonb,
               source = 'browser_capture',
               source_message_id = NULL,
               saved_by_user_id = $10,
               current_revision_id = $11,
               current_captured_at = $12,
               content_sha256 = $13
           WHERE id = $1
             AND (
                 current_captured_at IS NULL
                 OR $12 > current_captured_at
                 OR (
                     $12 = current_captured_at
                     AND (
                         current_revision_id IS NULL
                         OR $14 > COALESCE(
                             (SELECT received_at FROM reading_revisions
                               WHERE id = current_revision_id),
                             '-infinity'::timestamptz
                         )
                         OR (
                             $14 = COALESCE(
                                 (SELECT received_at FROM reading_revisions
                                   WHERE id = current_revision_id),
                                 '-infinity'::timestamptz
                             )
                             AND $11 > current_revision_id
                         )
                     )
                 )
             )""",
        reading_id, logical_url, title, capture.get("author"), capture.get("site"),
        capture.get("published"), capture.get("word_count"), capture["markdown"],
        summary, captured_by_user_id, revision["id"], capture["captured_at"],
        capture["content_sha256"], revision["received_at"],
    )
    return await _browser_capture_result(
        db,
        capture_id=capture_id,
        room_id=room_id,
        captured_by_user_id=captured_by_user_id,
        fingerprint=fingerprint,
        idempotent_replay=False,
    )


async def search_reading(
    db, room_id: UUID, query: str, limit: int = 5,
) -> list[dict[str, Any]]:
    """FTS over the library, ranked extracts via ts_headline."""
    rows = await db.fetch(
        """SELECT url, title, author, site, published, summary, source,
                  created_at,
                  ts_rank_cd(fts, websearch_to_tsquery('english', $2)) AS rank,
                  ts_headline('english', content,
                              websearch_to_tsquery('english', $2),
                              'MaxWords=60, MinWords=20, MaxFragments=2') AS snippet
           FROM reading_items
           WHERE room_id = $1
             AND fts @@ websearch_to_tsquery('english', $2)
           ORDER BY rank DESC, created_at DESC
           LIMIT $3""",
        room_id, query, limit,
    )
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "author": row["author"],
            "site": row["site"],
            "published": row["published"],
            "summary": row["summary"],
            "snippet": row["snippet"],
            "saved_via": row["source"],
            "saved_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


async def recent_readings(
    db, room_id: UUID, since, limit: int = 10,
) -> list[dict[str, Any]]:
    """Newest-first rows since a timestamp — the briefing's news_digest."""
    rows = await db.fetch(
        """SELECT url, title, site, published, summary, source, created_at
           FROM reading_items
           WHERE room_id = $1 AND created_at >= $2
           ORDER BY created_at DESC
           LIMIT $3""",
        room_id, since, limit,
    )
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "site": row["site"],
            "published": row["published"],
            "summary": row["summary"],
            "saved_via": row["source"],
            "saved_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


async def seen_urls(db, room_id: UUID) -> set[str]:
    """Every URL this room has filed — the dedup set for the feed jobs."""
    rows = await db.fetch(
        "SELECT url FROM reading_items WHERE room_id = $1", room_id,
    )
    return {row["url"] for row in rows}
