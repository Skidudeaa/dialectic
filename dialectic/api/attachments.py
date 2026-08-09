# api/attachments.py — media attachments (images / video / files) for rooms

"""
ARCHITECTURE: Content-addressed blobs on local disk + a row per upload.
Bytes land at {MEDIA_ROOT}/{room_id}/{sha256[:2]}/{sha256}{ext}; the DB row
carries the metadata (kind, mime, size, dimensions, original name) and the
path RELATIVE to MEDIA_ROOT.

WHY content-addressed: a room re-sharing the same chart four times should
cost one blob, and re-uploading is then free — the second POST hashes to a
row that already exists and returns it. WHY relative paths: MEDIA_ROOT is an
env knob, so an absolute path frozen into the row would break every existing
attachment the day the volume moves.

WHY the extension comes from a mime allowlist and never from the filename:
the filename is attacker-controlled. "chart.png" and "../../etc/passwd" get
identical treatment here — the original name is stored as a display label
only and never participates in building a path.

TRADEOFF: Local disk (not S3) means single-server, and dedup has a benign
race — two simultaneous uploads of identical bytes can both insert, leaving
two rows pointing at one blob. Harmless (the blob is written by content, so
both rows are correct); a UNIQUE (room_id, sha256) would prevent it but also
forbid two users legitimately holding the same file under different names.
"""

import hashlib
import logging
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from typing import Optional, Tuple
from urllib.parse import quote
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.token_utils import extract_room_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["attachments"])


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

_db_pool: Optional[asyncpg.Pool] = None


def set_attachments_db_pool(pool: asyncpg.Pool) -> None:
    """Set the database pool for attachment routes (called from main.py)."""
    global _db_pool
    _db_pool = pool


async def _get_db():
    async with _db_pool.acquire() as conn:
        yield conn


# ============================================================
# POLICY: WHAT MAY BE UPLOADED
# ============================================================

DEFAULT_MEDIA_ROOT = "/var/lib/dialectic/media"

# mime -> (kind, extension). The ONLY source of extensions.
MIME_POLICY: dict[str, Tuple[str, str]] = {
    "image/png": ("image", ".png"),
    "image/jpeg": ("image", ".jpg"),
    "image/webp": ("image", ".webp"),
    "image/gif": ("image", ".gif"),
    "video/mp4": ("video", ".mp4"),
    "video/webm": ("video", ".webm"),
    "video/quicktime": ("video", ".mov"),
    "application/pdf": ("file", ".pdf"),
    "text/plain": ("file", ".txt"),
    "text/csv": ("file", ".csv"),
    "application/json": ("file", ".json"),
    "application/zip": ("file", ".zip"),
}

# Client-sent spellings that mean an allowlisted type.
MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "application/x-zip-compressed": "application/zip",
    "text/json": "application/json",
}

DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_VIDEO_BYTES = 300 * 1024 * 1024

CHUNK_BYTES = 1024 * 1024
# JPEG's SOF marker can sit past an embedded EXIF thumbnail, so dimension
# parsing needs more than a header — but bounded, never the whole file.
DIMENSION_SCAN_BYTES = 128 * 1024


def media_root() -> str:
    """
    The storage root, read at CALL time.

    WHY not a module constant: tests point MEDIA_ROOT at tmp_path via
    monkeypatch, and a value frozen at import would ignore them. This is the
    single reader of the env var — every path in this module is built from it.
    """
    return os.environ.get("MEDIA_ROOT", DEFAULT_MEDIA_ROOT)


def max_bytes_for_kind(kind: str) -> int:
    """
    Size cap for a kind, read at CALL time (same reason as media_root).

    This is the single reader of the cap env vars, so a test that shrinks the
    cap shrinks it for every code path that enforces one.
    """
    if kind == "video":
        return int(os.environ.get("MEDIA_MAX_VIDEO_BYTES", DEFAULT_MAX_VIDEO_BYTES))
    if kind == "image":
        return int(os.environ.get("MEDIA_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE_BYTES))
    return int(os.environ.get("MEDIA_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES))


def normalize_mime(raw: Optional[str]) -> Optional[str]:
    """Strip parameters/case from a client content-type and resolve aliases."""
    if not raw:
        return None
    mime = raw.split(";")[0].strip().lower()
    return MIME_ALIASES.get(mime, mime)


# ============================================================
# MAGIC NUMBERS + IMAGE DIMENSIONS (stdlib only)
# ============================================================

def sniff_image_mime(head: bytes) -> Optional[str]:
    """
    Identify an image from its first bytes; None if it is not one we know.

    WHY: Content-Type is client-supplied. An .exe announced as image/png
    would otherwise be stored and later served back with an image
    content-type, which is the shape of a stored-XSS/drive-by delivery.
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height)


def _gif_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 10:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return (width, height)


def _jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Walk JPEG segments to the first SOF marker, which carries the size."""
    # C4 = DHT, C8 = JPG (reserved), CC = DAC — not frame headers.
    sof_markers = {m for m in range(0xC0, 0xD0)} - {0xC4, 0xC8, 0xCC}
    pos = 2
    end = len(data)
    while pos + 9 < end:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xFF:          # fill byte
            pos += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # standalone
            pos += 2
            continue
        segment_length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if marker in sof_markers:
            height, width = struct.unpack(">HH", data[pos + 5:pos + 9])
            return (width, height)
        if segment_length < 2:
            return None
        pos += 2 + segment_length
    return None


def _webp_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    if len(data) < 30:
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8 ":
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width = struct.unpack("<H", data[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", data[28:30])[0] & 0x3FFF
        return (width, height)
    if fourcc == b"VP8L":
        if len(data) < 25 or data[20] != 0x2F:
            return None
        bits = struct.unpack("<I", data[21:25])[0]
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if fourcc == b"VP8X":
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return (width, height)
    return None


def image_dimensions(data: bytes, mime: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Best-effort (width, height) from an image header.

    TRADEOFF: header parsing keeps this dependency-free, so an exotic or
    truncated file simply yields (None, None) rather than failing the upload.
    Dimensions are a rendering hint (reserve layout space), not a contract.
    """
    try:
        parsers = {
            "image/png": _png_dimensions,
            "image/gif": _gif_dimensions,
            "image/jpeg": _jpeg_dimensions,
            "image/webp": _webp_dimensions,
        }
        parser = parsers.get(mime)
        if parser is None:
            return (None, None)
        result = parser(data)
        if not result:
            return (None, None)
        width, height = result
        if width <= 0 or height <= 0:
            return (None, None)
        return (width, height)
    except Exception:  # a malformed header must never fail an upload
        logger.debug("attachment dimension parse failed for %s", mime, exc_info=True)
        return (None, None)


# ============================================================
# FILENAME HANDLING
# ============================================================

_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\]")


def sanitize_original_name(raw: Optional[str]) -> str:
    """
    Reduce a client filename to a bare display label.

    SECURITY: strips every directory component, so "../../etc/passwd" becomes
    "passwd". This value is stored and echoed in Content-Disposition — it is
    never used to build a path (see MIME_POLICY for where extensions come
    from), but a name carrying quotes or CR/LF could still break out of the
    header, so those go too.
    """
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME_CHARS.sub("", name).strip().strip(".")
    if not name:
        return "upload"
    return name[:255]


def content_disposition(kind: str, original_name: str) -> str:
    """
    inline for renderable media, attachment for everything else.

    WHY: an image or video should render in the chat; a .zip or .json must
    download rather than execute a navigation in the app's own origin.
    """
    disposition = "inline" if kind in ("image", "video") else "attachment"
    ascii_name = original_name.encode("ascii", "replace").decode("ascii")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(original_name, safe='')}"
    )


# ============================================================
# AUTH HELPERS
# ============================================================

# These mirror verify_room_token / verify_room_member in api/main.py. They are
# duplicated rather than imported because main.py imports THIS module to mount
# the router — importing back would be circular. Same SQL, same status codes.

async def _verify_room_token(room_id: UUID, token: str, db) -> None:
    row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")


async def _verify_room_member(room_id: UUID, user_id: UUID, db) -> None:
    """
    SECURITY: Prevents user impersonation on REST endpoints. Without this,
    anyone with a room token could act as any user by supplying their UUID.
    """
    membership = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id,
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="User is not a member of this room",
        )


# ============================================================
# SCHEMAS
# ============================================================

class AttachmentResponse(BaseModel):
    id: UUID
    room_id: UUID
    message_id: Optional[UUID]
    uploader_user_id: UUID
    kind: str
    mime: str
    bytes: int
    sha256: str
    width: Optional[int]
    height: Optional[int]
    original_name: str
    storage_path: str          # relative to MEDIA_ROOT
    created_at: datetime
    url: str                   # where to GET the bytes
    deduplicated: bool = False


class BindAttachmentRequest(BaseModel):
    message_id: UUID


def _to_response(row, deduplicated: bool = False) -> AttachmentResponse:
    return AttachmentResponse(
        id=row["id"],
        room_id=row["room_id"],
        message_id=row["message_id"],
        uploader_user_id=row["uploader_user_id"],
        kind=row["kind"],
        mime=row["mime"],
        bytes=row["bytes"],
        sha256=row["sha256"],
        width=row["width"],
        height=row["height"],
        original_name=row["original_name"],
        storage_path=row["storage_path"],
        created_at=row["created_at"],
        url=f"/attachments/{row['id']}",
        deduplicated=deduplicated,
    )


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/rooms/{room_id}/attachments", response_model=AttachmentResponse)
async def upload_attachment(
    room_id: UUID,
    file: UploadFile = File(...),
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(_get_db),
):
    """
    Upload one file to a room. Returns the attachment record; the client sends
    its message afterwards and then calls /bind.

    ARCHITECTURE: streams to a temp file in CHUNK_BYTES blocks while hashing,
    then renames into the content-addressed location. Never buffers the whole
    upload in RAM — a 300MB video would otherwise be a 300MB resident spike
    per concurrent uploader.

    WHY the rename: a crash mid-write leaves junk in .tmp, not a truncated
    file sitting at a path some row already claims is complete.

    Status is 200 for both a fresh insert and a dedup hit; `deduplicated`
    tells them apart.
    """
    user_id = current_user.user_id
    await _verify_room_token(room_id, token, db)
    await _verify_room_member(room_id, user_id, db)

    claimed_mime = normalize_mime(file.content_type)
    if claimed_mime not in MIME_POLICY:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type: {file.content_type or 'unknown'}",
        )

    kind, extension = MIME_POLICY[claimed_mime]
    cap = max_bytes_for_kind(kind)
    original_name = sanitize_original_name(file.filename)

    root = media_root()
    tmp_dir = os.path.join(root, ".tmp")
    # Lazy-create: the deploy may not have made MEDIA_ROOT, and tests point it
    # at a fresh tmp_path. Same filesystem as the final location so the rename
    # below is atomic rather than a cross-device copy.
    os.makedirs(tmp_dir, exist_ok=True)

    digest = hashlib.sha256()
    total = 0
    head = b""
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > cap:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File exceeds the {cap} byte limit for {kind} uploads"
                        ),
                    )
                if len(head) < DIMENSION_SCAN_BYTES:
                    head += chunk[: DIMENSION_SCAN_BYTES - len(head)]
                digest.update(chunk)
                tmp.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        if kind == "image":
            sniffed = sniff_image_mime(head)
            if sniffed is None:
                raise HTTPException(
                    status_code=415,
                    detail="File content is not a recognized image",
                )
            if sniffed != claimed_mime:
                raise HTTPException(
                    status_code=415,
                    detail=(
                        f"Content-Type {claimed_mime} does not match file "
                        f"contents ({sniffed})"
                    ),
                )

        sha256 = digest.hexdigest()

        existing = await db.fetchrow(
            """SELECT * FROM attachments
               WHERE room_id = $1 AND sha256 = $2
               ORDER BY created_at ASC LIMIT 1""",
            room_id, sha256,
        )
        if existing:
            # Same bytes already in this room — the blob on disk is identical
            # by construction, so drop the temp copy and hand back the row.
            _unlink_quietly(tmp_path)
            tmp_path = None
            return _to_response(existing, deduplicated=True)

        relative_path = os.path.join(str(room_id), sha256[:2], f"{sha256}{extension}")
        final_path = os.path.join(root, relative_path)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        os.replace(tmp_path, final_path)
        tmp_path = None

        width, height = (None, None)
        if kind == "image":
            width, height = image_dimensions(head, claimed_mime)

        # If the INSERT below fails, the blob stays on disk with no row. That is
        # the deliberate direction to fail in: an orphan blob is invisible and
        # gets re-used by the next identical upload, whereas a row pointing at
        # bytes that were rolled back would render as a permanently broken image.
        attachment_id = uuid4()
        now = datetime.now(timezone.utc)
        row = await db.fetchrow(
            """INSERT INTO attachments
                   (id, room_id, message_id, uploader_user_id, kind, mime,
                    bytes, sha256, width, height, original_name, storage_path,
                    created_at)
               VALUES ($1, $2, NULL, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
               RETURNING *""",
            attachment_id, room_id, user_id, kind, claimed_mime,
            total, sha256, width, height, original_name, relative_path, now,
        )
        return _to_response(row)
    finally:
        # Any failure path (cap, sniff, DB error) must not leave the temp file.
        if tmp_path:
            _unlink_quietly(tmp_path)


def _unlink_quietly(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("could not remove attachment temp file %s", path, exc_info=True)


@router.get("/attachments/{attachment_id}")
async def fetch_attachment(
    attachment_id: UUID,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(_get_db),
):
    """
    Stream an attachment's bytes to a member of its room.

    NOTE for clients: this needs BOTH the room token and the JWT, so a bare
    <img src="/attachments/..."> will not authenticate. Fetch with headers and
    render from an object URL.
    """
    row = await db.fetchrow(
        "SELECT * FROM attachments WHERE id = $1", attachment_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    await _verify_room_token(row["room_id"], token, db)
    await _verify_room_member(row["room_id"], current_user.user_id, db)

    root = media_root()
    path = os.path.realpath(os.path.join(root, row["storage_path"]))
    # Defense in depth: storage_path is server-generated, but a corrupted or
    # hand-edited row must not be able to serve /etc/shadow.
    if os.path.commonpath([path, os.path.realpath(root)]) != os.path.realpath(root):
        logger.error("attachment %s has an out-of-root storage_path", attachment_id)
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not os.path.isfile(path):
        # Row without bytes: the volume moved, or a sweep ran ahead of the row.
        raise HTTPException(status_code=404, detail="Attachment file missing")

    return FileResponse(
        path,
        media_type=row["mime"],
        headers={
            "Content-Disposition": content_disposition(
                row["kind"], row["original_name"]
            ),
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


@router.post(
    "/rooms/{room_id}/attachments/{attachment_id}/bind",
    response_model=AttachmentResponse,
)
async def bind_attachment(
    room_id: UUID,
    attachment_id: UUID,
    request: BindAttachmentRequest,
    token: str = Depends(extract_room_token),
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(_get_db),
):
    """
    Attach an uploaded blob to the message that carries it.

    WHY this is a separate call: the bytes are uploaded before the message
    exists (the user picks a file, then types), so message_id cannot be known
    at upload time. The client sends the message, then binds.

    Idempotent for a repeat of the same bind; a bind to a DIFFERENT message is
    409 — re-pointing would silently strip the attachment off the message that
    already displays it.
    """
    user_id = current_user.user_id
    await _verify_room_token(room_id, token, db)
    await _verify_room_member(room_id, user_id, db)

    row = await db.fetchrow(
        "SELECT * FROM attachments WHERE id = $1 AND room_id = $2",
        attachment_id, room_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if row["uploader_user_id"] != user_id:
        # Binding someone else's upload into your own message would misattribute
        # authorship, and the uploader is always the sender in the real flow.
        raise HTTPException(
            status_code=403,
            detail="Only the uploader can bind this attachment",
        )

    message_room_id = await db.fetchval(
        """SELECT t.room_id FROM messages m
           JOIN threads t ON t.id = m.thread_id
           WHERE m.id = $1""",
        request.message_id,
    )
    if message_room_id is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message_room_id != room_id:
        raise HTTPException(
            status_code=400,
            detail="Message does not belong to this room",
        )

    if row["message_id"] is not None:
        if row["message_id"] == request.message_id:
            return _to_response(row)   # already bound — idempotent no-op
        raise HTTPException(
            status_code=409,
            detail="Attachment is already bound to a different message",
        )

    updated = await db.fetchrow(
        "UPDATE attachments SET message_id = $1 WHERE id = $2 RETURNING *",
        request.message_id, attachment_id,
    )
    return _to_response(updated)
