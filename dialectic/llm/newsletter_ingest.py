# llm/newsletter_ingest.py — a dropped PDF/text attachment becomes a reading

"""
ARCHITECTURE: pure pipeline, no transport. A room attachment of MIME
application/pdf or text/plain (the Capex Insider drop path — owner ruling
2026-08-17: newsletters enter by FORWARD/DROP, never IMAP) is extracted to
text and filed through the one library door every other producer uses:
save_reading. The synthetic URL `newsletter://<slug>/<sha256[:12]>` is built
from the attachment's OWN content hash, so re-dropping the same file lands
on UNIQUE(room_id, url) and refreshes the row instead of duplicating it —
the drop is idempotent because the storage is content-addressed.

WHY a synthetic URL: reading_items keys on (room_id, url) and the memory
twin derives its key from urlparse(url).netloc — `newsletter://capex-insider/
ab12cd34ef56` gives the twin the slug as its domain, so recall groups a
newsletter's issues the way it groups a site's articles.

WHY the thin gate applies here: a newsletter is long-form prose. A PDF that
extracts to under 80 words is a scan (images, no text layer) or a cover
page, and filing it teaches recall nothing — same policy, same constant,
same is_thin as every fetched page.

TRADEOFF: pypdf, imported lazily. Text extraction from PDFs is genuinely
not a stdlib job; pypdf is pure-Python and the import stays inside the PDF
branch so text/plain ingestion (and importing this module) never needs it.
"""

import logging
import re
from typing import Optional
from uuid import UUID

from llm.reading import is_thin, save_reading

logger = logging.getLogger(__name__)

INGESTABLE_MIMES = ("application/pdf", "text/plain")

# Bounded work: a pathological PDF can carry thousands of pages; the library
# stores 40k chars anyway (reading.CONTENT_STORE_CAP), so extraction past
# this many pages buys nothing.
PDF_PAGE_CAP = 60

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TITLE_LINE_CAP = 120


class NewsletterIngestError(Exception):
    """Extraction refused — carries a human-readable reason."""


def extract_attachment_text(blob: bytes, mime: str) -> str:
    """Text of a PDF or plain-text blob; raises NewsletterIngestError when
    the bytes cannot yield any."""
    if mime == "text/plain":
        return blob.decode("utf-8", errors="replace")
    if mime == "application/pdf":
        try:
            import io

            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(blob))
            pages = []
            for page in reader.pages[:PDF_PAGE_CAP]:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    # One corrupt page must not void the rest of the issue.
                    logger.debug("pdf page extraction failed", exc_info=True)
            return "\n".join(pages)
        except NewsletterIngestError:
            raise
        except Exception as e:
            raise NewsletterIngestError(f"PDF could not be parsed: {e}") from e
    raise NewsletterIngestError(f"unsupported mime for ingest: {mime}")


def _slugify(raw: str) -> str:
    slug = _SLUG_RE.sub("-", raw.lower()).strip("-")[:50].strip("-")
    return slug or "newsletter"


def title_from_text(text: str, fallback_filename: str) -> str:
    """First heading-looking line, else the filename without its extension.

    "Heading-looking" is deliberately loose: the first non-empty line short
    enough to be a title. Newsletters open with their masthead; a line that
    runs past the cap is body prose and the filename is the honest label.
    """
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if len(candidate) <= _TITLE_LINE_CAP:
            return candidate
        break
    stem = fallback_filename.rsplit(".", 1)[0].strip()
    return stem or "newsletter"


def newsletter_url(slug_source: str, sha256: str) -> str:
    """`newsletter://<slug>/<sha256[:12]>` — idempotent per content."""
    return f"newsletter://{_slugify(slug_source)}/{sha256[:12]}"


async def ingest_attachment_reading(
    db,
    *,
    room_id: UUID,
    blob: bytes,
    mime: str,
    sha256: str,
    original_name: str,
    summary: str = "",
    source_message_id: Optional[UUID] = None,
    saved_by_user_id: Optional[UUID] = None,
) -> dict:
    """Extract, gate, file. Returns the stored reading row.

    Raises NewsletterIngestError for anything the caller should surface as
    a 422: unsupported mime, unparseable PDF, or a thin extraction.
    """
    if mime not in INGESTABLE_MIMES:
        raise NewsletterIngestError(f"unsupported mime for ingest: {mime}")

    text = extract_attachment_text(blob, mime)
    title = title_from_text(text, original_name)
    word_count = len(text.split())
    # Slug from the filename STEM (extension stripped — 'issue.pdf' must not
    # slug to 'issue-pdf'), falling back to the extracted title.
    stem = (original_name or "").rsplit(".", 1)[0].strip()
    article = {
        "url": newsletter_url(stem or title, sha256),
        "title": title,
        "author": None,
        "site": "newsletter",
        "published": None,
        "word_count": word_count,
        "content": text,
    }
    # The one thin-content policy every filing path shares — a text-layer-less
    # scan is this door's cookie wall.
    if is_thin(article):
        raise NewsletterIngestError(
            f"extracted only {word_count} words — a scan or a cover page, "
            "not a filable issue"
        )

    return await save_reading(
        db,
        room_id=room_id,
        article=article,
        summary=summary.strip() or title[:280],
        key_claims=[],
        source="newsletter",
        source_message_id=source_message_id,
        saved_by_user_id=saved_by_user_id,
    )
