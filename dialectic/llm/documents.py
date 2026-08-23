# llm/documents.py — the LLM participant's one way to hand the room a file
"""
ARCHITECTURE: markdown (what the model writes) → HTML → PDF (headless Chrome)
→ an `attachments` row with uploader_user_id NULL (NULL = the LLM, the same
convention messages.user_id uses) and message_id NULL until the turn's
message lands, when the orchestrator binds it — see bind_documents.

WHY Chrome and not a PDF library: nothing PDF-shaped is installed, Chrome is,
and its print engine handles real typography, tables and page breaks for
free. WHY the attachments table and not a new one: the room already knows how
to list, authenticate, stream and render an attachment; a document is a
`kind=file` attachment whose author happens to be the machine.
"""

import asyncio
import hashlib
import html
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from markdown_it import MarkdownIt

from api.attachments import attachment_payload, media_root, sanitize_original_name

logger = logging.getLogger(__name__)

MAX_MARKDOWN_CHARS = 60_000
RENDER_TIMEOUT_S = 20.0

_CHROME_CANDIDATES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
)

# commonmark + tables/strikethrough, raw HTML OFF: the model's markdown is
# untrusted input to a renderer that will happily execute a <script>.
_md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
@page {{ size: Letter; margin: 22mm 20mm; }}
body {{ font: 11pt/1.55 Georgia, "Times New Roman", serif; color: #1a1a1a; max-width: 100%; }}
h1 {{ font: 700 22pt/1.2 Helvetica, Arial, sans-serif; margin: 0 0 4pt; }}
h2 {{ font: 700 14pt/1.3 Helvetica, Arial, sans-serif; margin: 22pt 0 6pt; border-bottom: 1px solid #bbb; padding-bottom: 3pt; }}
h3 {{ font: 700 11.5pt/1.3 Helvetica, Arial, sans-serif; margin: 16pt 0 4pt; }}
.meta {{ font: 9pt Helvetica, Arial, sans-serif; color: #666; margin: 0 0 18pt; }}
p {{ margin: 0 0 9pt; }} li {{ margin: 0 0 3pt; }}
table {{ border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 10pt; }}
th, td {{ border: 1px solid #ccc; padding: 4pt 6pt; text-align: left; vertical-align: top; }}
th {{ background: #f2f2f2; font-family: Helvetica, Arial, sans-serif; }}
blockquote {{ margin: 8pt 0; padding: 2pt 12pt; border-left: 3px solid #999; color: #444; }}
code {{ font: 9.5pt Menlo, Consolas, monospace; background: #f4f4f4; padding: 0 3pt; }}
pre {{ background: #f4f4f4; padding: 8pt; overflow-x: auto; white-space: pre-wrap; }}
h1, h2, h3 {{ page-break-after: avoid; }} table, blockquote, pre {{ page-break-inside: avoid; }}
</style></head><body>
<h1>{title}</h1><div class="meta">Dialectic &middot; {stamp}</div>
{body}
</body></html>"""


def chrome_binary() -> Optional[str]:
    override = os.environ.get("DIALECTIC_CHROME_BIN", "").strip()
    if override:
        return override if os.path.isfile(override) else None
    for name in _CHROME_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


# A leading "# Heading" line. The page already prints `title` as the H1, and
# the model nearly always opens the body by repeating it — measured on the
# first live render (2026-08-22: "Probe memo" twice, stacked).
_LEADING_H1 = re.compile(r"\A\s*#(?!#)[ \t]+[^\n]*\n?")


def render_html(title: str, markdown: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = _LEADING_H1.sub("", markdown, count=1)
    return _PAGE.format(title=html.escape(title), stamp=stamp, body=_md.render(body))


async def render_pdf(title: str, markdown: str) -> bytes:
    """HTML → PDF through headless Chrome. Raises RuntimeError with a reason
    the model can repeat honestly ("no renderer on this host") — never a
    half-written file."""
    binary = chrome_binary()
    if binary is None:
        raise RuntimeError("no Chrome/Chromium binary on this host")
    with tempfile.TemporaryDirectory(prefix="dialectic-doc-") as tmp:
        src = os.path.join(tmp, "doc.html")
        out = os.path.join(tmp, "doc.pdf")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(render_html(title, markdown))
        proc = await asyncio.create_subprocess_exec(
            binary, "--headless=new", "--no-sandbox", "--disable-gpu",
            "--no-first-run", "--no-default-browser-check",
            # Own profile dir: two turns rendering at once must not fight
            # over a profile lock; the service runs as root, hence no-sandbox.
            f"--user-data-dir={os.path.join(tmp, 'profile')}",
            "--no-pdf-header-footer", f"--print-to-pdf={out}", f"file://{src}",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=RENDER_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"PDF render timed out after {RENDER_TIMEOUT_S:g}s")
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            tail = (err or b"")[-300:].decode("utf-8", "replace").strip()
            raise RuntimeError(f"PDF render produced no file (exit {proc.returncode}): {tail}")
        with open(out, "rb") as fh:
            return fh.read()


def _filename(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()[:60] or "document"
    return sanitize_original_name(f"{slug}.pdf")


async def store_document(db, room_id: UUID, title: str, markdown: str) -> dict:
    """Render and file one document for the room. Returns the attachment
    payload (AttachmentResponse-shaped) with message_id still NULL."""
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    if not (markdown or "").strip():
        raise ValueError("content is required")
    if len(markdown) > MAX_MARKDOWN_CHARS:
        raise ValueError(f"content exceeds {MAX_MARKDOWN_CHARS} characters")

    data = await render_pdf(title, markdown)
    sha = hashlib.sha256(data).hexdigest()
    relative = os.path.join(str(room_id), sha[:2], f"{sha}.pdf")
    final = os.path.join(media_root(), relative)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    # Same bytes → same path; identical content rewrites identical bytes.
    tmp = f"{final}.{uuid4().hex}.part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, final)

    row = await db.fetchrow(
        """INSERT INTO attachments
               (id, room_id, message_id, uploader_user_id, kind, mime,
                bytes, sha256, width, height, original_name, storage_path, created_at)
           VALUES ($1, $2, NULL, NULL, 'file', 'application/pdf',
                   $3, $4, NULL, NULL, $5, $6, $7)
           RETURNING *""",
        uuid4(), room_id, len(data), sha, _filename(title), relative,
        datetime.now(timezone.utc),
    )
    return attachment_payload(row)


def document_ids_from_calls(calls: Optional[list]) -> list[UUID]:
    """Attachment ids of every write_document in a tool trace."""
    out: list[UUID] = []
    for entry in calls or []:
        prov = entry.get("provenance") if isinstance(entry, dict) else None
        if isinstance(prov, dict) and prov.get("kind") == "document":
            try:
                out.append(UUID(str(prov.get("attachment_id"))))
            except (ValueError, TypeError):
                continue
    return out


async def bind_documents(db, room_id: UUID, message_id: UUID, calls: Optional[list]) -> list[dict]:
    """Tie the turn's documents to the message that carries them. Only
    unbound, LLM-authored rows in THIS room — a model can not name a human's
    upload here. Returns the bound attachment payloads (empty when none)."""
    ids = document_ids_from_calls(calls)
    if not ids:
        return []
    rows = await db.fetch(
        """UPDATE attachments SET message_id = $1
           WHERE id = ANY($2::uuid[]) AND room_id = $3
             AND message_id IS NULL AND uploader_user_id IS NULL
           RETURNING *""",
        message_id, ids, room_id,
    )
    return [attachment_payload(r) for r in rows]
