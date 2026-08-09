# llm/vision.py — the image attachments the participant can actually SEE

"""
ARCHITECTURE: attachments row -> blob on disk -> base64 Anthropic image block,
returned keyed by the message that carries it. The prompt builder splices those
blocks into that message's turn; nothing else in the LLM layer needs to know
images exist.

WHY the DB is the source of truth: `attachments.message_id` is what the client
binds and what the frontend renders from. `messages.metadata` is not — a turn
whose metadata was written before the bind landed would silently show the model
an empty chart wall while the humans are looking at a picture.

WHY caps at all: an image costs roughly (width x height) / 750 tokens — about
1.1k for a 1000x800 screenshot, and a phone photo can be several times that.
Four of them is the difference between a normal turn and one that pushes real
conversation out of the context window, on EVERY subsequent turn in the room.
So: newest-first, four at most, 5MB each, 12MB total.

TRADEOFF: the newest four win and the rest are simply absent, rather than
downscaled. Resizing would need a real image library (Pillow) and a decode of
attacker-supplied bytes in the request path; recency is a cheap heuristic that
happens to match how the room works — you ask about the chart you just posted.
"""

import asyncio
import base64
import logging
import os
from typing import Optional
from uuid import UUID

# WHY import rather than re-declare: media_root() is the SINGLE reader of the
# MEDIA_ROOT env var (see api/attachments.py). A second copy of the default
# would drift the day the volume moves, and a test that monkeypatches the env
# would then move only one of them.
from api.attachments import media_root

logger = logging.getLogger(__name__)


# The image formats the Anthropic API accepts. Every kind='image' attachment is
# one of these today (api.attachments.MIME_POLICY allows exactly png/jpeg/webp/
# gif), but this is Anthropic's contract rather than ours, so it is checked
# explicitly: the day image/svg+xml or image/avif joins that allowlist, the API
# starts 400ing on a prompt with nothing visibly wrong with it.
VISION_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})

MAX_IMAGE_BYTES = 5 * 1024 * 1024        # per image, BEFORE base64 expansion
MAX_IMAGES = 4                           # per prompt, newest first
TOTAL_BUDGET_BYTES = 12 * 1024 * 1024    # across the whole prompt
DEFAULT_MESSAGE_WINDOW = 10              # only the newest N messages are scanned

# WHY these reach the model as text instead of being silently dropped: a
# participant that cannot see an image must say so. Given nothing, it answers
# from the caption and sounds like it looked at the chart.
NOTE_UNAVAILABLE = "[image attachment unavailable]"
NOTE_TOO_LARGE = "[image attachment too large to show]"

# Kill switch. Unset means ON — the feature ships enabled, and the env var
# exists so vision can be taken off the prompt in one restart if it misbehaves.
_VISION_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def vision_enabled() -> bool:
    """Whether image attachments may be put in front of the model at all."""
    return (
        os.getenv("DIALECTIC_VISION_ENABLED", "").strip().lower()
        not in _VISION_OFF_VALUES
    )


def image_block(mime: str, b64_data: str) -> dict:
    """One Anthropic image content block."""
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": b64_data},
    }


def note_block(text: str) -> dict:
    """A text block standing in for an image that could not be shown."""
    return {"type": "text", "text": text}


def count_images(message_images: Optional[dict[UUID, list[dict]]]) -> int:
    """How many real images (not notes) are in a build() payload."""
    if not message_images:
        return 0
    return sum(
        1
        for blocks in message_images.values()
        for block in blocks
        if block.get("type") == "image"
    )


def _load_encoded(path: str, cap: int) -> Optional[tuple[str, int]]:
    """(base64 text, raw byte count) for a blob on disk, or None.

    None covers every reason the bytes are not usable — the row's volume moved,
    a sweep ran ahead of the row, permissions, or a file that disagrees with the
    size its row claims. The caller turns all of them into one honest note; the
    log line below is where the distinction lives.

    Runs on a worker thread (see the to_thread call): a 5MB read plus its
    base64 pass is tens of milliseconds, and the event loop is holding a live
    WebSocket at the time.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        logger.warning("vision: attachment blob missing at %s", path)
        return None
    if size > cap:
        # The row's `bytes` is server-computed at upload, so a disagreement
        # here means a corrupted row or a replaced blob, not a big upload —
        # the big-upload case is caught before we ever touch the disk.
        logger.warning(
            "vision: blob at %s is %d bytes, over the %d cap its row did not "
            "declare — skipping", path, size, cap,
        )
        return None
    try:
        with open(path, "rb") as handle:
            # Bounded read: "never hold more than the cap in memory" is then
            # true by construction rather than by argument about the row.
            data = handle.read(cap + 1)
    except OSError:
        logger.warning("vision: could not read attachment blob at %s", path, exc_info=True)
        return None
    if len(data) > cap:
        return None
    if not data:
        # An empty base64 payload is a 400 from the API, not a blank picture.
        # Uploads reject zero bytes, so this is a truncated or zeroed blob.
        logger.warning("vision: attachment blob at %s is empty", path)
        return None
    return base64.b64encode(data).decode("ascii"), len(data)


async def load_message_images(
    db,
    room_id: UUID,
    message_ids: list[UUID],
    *,
    window: int = DEFAULT_MESSAGE_WINDOW,
    max_images: int = MAX_IMAGES,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    total_budget_bytes: int = TOTAL_BUDGET_BYTES,
) -> dict[UUID, list[dict]]:
    """Image content blocks for the newest messages, keyed by message id.

    `message_ids` is the prompt's message window in CHRONOLOGICAL order — the
    same list, in the same order, that the prompt builder is about to render.
    Only the last `window` of them are considered; within those, images are
    taken newest-message-first until a cap is hit.

    WHY room_id is in the WHERE clause rather than assumed: the ids arrive from
    a thread that belongs to this room, so today it filters nothing. It means a
    future path that hands this function ids from anywhere else cannot put one
    room's photograph in front of another room's participant — a cross-room
    leak should be impossible by clause, not by an argument about fork
    ancestry. Matches the shape of the attachments query in api/main.py.

    Returns {} when vision is off, when there are no ids, or when no message in
    the window carries an image — so the caller's plain-text path is unchanged
    in the overwhelmingly common case, at the cost of one indexed query.
    """
    if not message_ids or not vision_enabled():
        return {}

    window_ids = list(message_ids)[-window:]
    rows = await db.fetch(
        """SELECT id, message_id, mime, bytes, storage_path, original_name,
                  created_at
           FROM attachments
           WHERE kind = 'image' AND room_id = $1 AND message_id = ANY($2::uuid[])""",
        room_id, window_ids,
    )
    if not rows:
        return {}

    # Recency by POSITION IN THE WINDOW, not by attachment created_at: dedup
    # hands back the row of the FIRST upload of identical bytes, so re-posting
    # last week's chart today produces an attachment whose created_at is a week
    # old while the message carrying it is the newest thing in the room.
    position = {mid: i for i, mid in enumerate(window_ids)}
    ordered = sorted(
        rows,
        # -position => newest message first. Within one message, upload order,
        # so two charts in one post reach the model the way they were sent.
        key=lambda r: (-position.get(r["message_id"], -10**9), r["created_at"], str(r["id"])),
    )

    root = media_root()
    real_root = os.path.realpath(root)
    out: dict[UUID, list[dict]] = {}
    used_bytes = 0
    shown = 0

    def add(message_id: UUID, block: dict) -> None:
        out.setdefault(message_id, []).append(block)

    for row in ordered:
        message_id = row["message_id"]
        mime = row["mime"]

        if mime not in VISION_MIMES:
            logger.warning(
                "vision: attachment %s is %s, which the API cannot render — skipping",
                row["id"], mime,
            )
            add(message_id, note_block(NOTE_UNAVAILABLE))
            continue

        if shown >= max_images:
            # Everything from here back is older than four images the model can
            # already see. No note: a wall of "not shown" on every old message
            # is noise, and the newest four are the ones being talked about.
            break

        declared = int(row["bytes"] or 0)
        if declared > max_image_bytes:
            logger.info(
                "vision: attachment %s (%s) is %d bytes, over the %d cap — noting instead",
                row["id"], row["original_name"], declared, max_image_bytes,
            )
            add(message_id, note_block(NOTE_TOO_LARGE))
            continue

        path = os.path.realpath(os.path.join(root, row["storage_path"]))
        # Defense in depth, mirroring api/attachments.fetch_attachment: the
        # storage_path is server-generated, but a corrupted or hand-edited row
        # must not be able to read /etc/shadow into a prompt — which here would
        # also hand it to a third party's API.
        if os.path.commonpath([path, real_root]) != real_root:
            logger.error(
                "vision: attachment %s has an out-of-root storage_path", row["id"]
            )
            add(message_id, note_block(NOTE_UNAVAILABLE))
            continue

        loaded = await asyncio.to_thread(_load_encoded, path, max_image_bytes)
        if loaded is None:
            add(message_id, note_block(NOTE_UNAVAILABLE))
            continue

        b64_data, raw_size = loaded
        if used_bytes + raw_size > total_budget_bytes:
            # Skip THIS one and keep scanning rather than stopping: one 4.9MB
            # phone photo must not hide the three small charts posted behind it.
            logger.info(
                "vision: attachment %s (%d bytes) does not fit the remaining "
                "budget (%d of %d used) — skipping",
                row["id"], raw_size, used_bytes, total_budget_bytes,
            )
            continue

        used_bytes += raw_size
        shown += 1
        add(message_id, image_block(mime, b64_data))

    if shown:
        logger.info(
            "vision: %d image(s), %d KB pre-encoding, across %d message(s)",
            shown, used_bytes // 1024, len(out),
        )
    return out
