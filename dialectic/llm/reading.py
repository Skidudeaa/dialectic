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

import logging
import re
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
           RETURNING id, url, title, site, published, summary, source""",
        room_id, url,
        article.get("title"), article.get("author"), article.get("site"),
        article.get("published"), article.get("word_count"),
        content, summary, claims, source,
        source_message_id, saved_by_user_id,
    )

    # Memory twin: one per (room, url), created on first save only. Embedding
    # failures degrade to text lanes inside add_memory — never fatal here.
    key = _reading_key(article)
    try:
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
                    article.get("published"), url,
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
        logger.exception("reading memory twin failed for %s", url)

    return dict(row)


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
