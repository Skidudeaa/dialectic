"""Tests for llm/vision.py + the image seam in prompts and the orchestrator.

WHAT THESE ARE ACTUALLY GUARDING:

  - The caps are the whole feature. An image costs ~1-1.5k tokens, so a helper
    that quietly hands the API five of them, or one 20MB phone photo, does not
    fail loudly — it just makes every turn in that room slower and dumber until
    someone reads a bill. Each cap is therefore tested in ISOLATION, with the
    other caps left at values that cannot fire, so a passing test means THAT
    guard held rather than a neighbour covering for it.
  - Bytes are read from disk and base64'd, so the encode is asserted against a
    real PNG's real bytes — "it returned a dict with a data key" is not
    evidence that the model would see a picture.
  - An image the model cannot see must become a SENTENCE, not silence. A
    participant handed a caption and no picture describes the chart anyway.
  - Recency is by message position, never by attachment created_at: dedup
    returns the row of the FIRST upload of identical bytes, so re-posting last
    week's chart today yields a week-old created_at on the newest message.
"""

import base64
import hashlib
import os
import struct
import zlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import llm.orchestrator as orchestrator_mod
from llm.orchestrator import LLMOrchestrator
from llm.prompts import AssembledPrompt, PromptBuilder
from llm.providers import LLMRequest, OpenAIProvider, flatten_content_blocks
from llm.tools import ToolRegistry
from llm.vision import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    NOTE_TOO_LARGE,
    NOTE_UNAVAILABLE,
    TOTAL_BUDGET_BYTES,
    count_images,
    load_message_images,
    vision_enabled,
)
from models import SpeakerType
from tests.conftest import USER_A_ID, make_message, make_room, make_thread, make_user


ROOM_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
OTHER_ROOM_ID = UUID("aaaaaaaa-0000-0000-0000-000000000002")


# =========================================================================
# REAL BYTES
# =========================================================================


def make_png(width: int = 3, height: int = 2) -> bytes:
    """A genuinely valid PNG — real IHDR, real deflate IDAT, real CRCs."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_blob(root, room_id: UUID, data: bytes, ext: str = ".png") -> str:
    """Write bytes where a real upload would put them; return storage_path.

    Mirrors api/attachments.upload_attachment exactly ({room}/{sha[:2]}/{sha}
    {ext}) so the fixture exercises the same join the production row produces.
    """
    sha = hashlib.sha256(data).hexdigest()
    relative = os.path.join(str(room_id), sha[:2], f"{sha}{ext}")
    path = os.path.join(str(root), relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return relative


# =========================================================================
# FAKE DB
# =========================================================================


class FakeDB:
    """asyncpg-connection stand-in that routes on the SQL vision.py sends.

    WHY it asserts the shape of the query rather than returning canned rows for
    anything: a filter silently dropped from the WHERE clause (room scoping,
    kind='image') would otherwise be invisible here.
    """

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.queries: list[str] = []
        self.args: list[tuple] = []

    async def fetch(self, query, *args):
        flat = " ".join(query.split())
        self.queries.append(flat)
        self.args.append(args)
        assert "FROM attachments" in flat, flat
        assert "kind = 'image'" in flat, flat
        assert "room_id = $1" in flat, flat
        room_id, message_ids = args
        wanted = set(message_ids)
        return [
            row for row in self.rows
            if row["room_id"] == room_id and row["message_id"] in wanted
        ]


def row(
    message_id: UUID,
    storage_path: str,
    *,
    nbytes: int,
    mime: str = "image/png",
    room_id: UUID = ROOM_ID,
    created_at: datetime = None,
    name: str = "chart.png",
) -> dict:
    return {
        "id": uuid4(),
        "room_id": room_id,
        "message_id": message_id,
        "mime": mime,
        "bytes": nbytes,
        "storage_path": storage_path,
        "original_name": name,
        "created_at": created_at or datetime.now(timezone.utc),
    }


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    monkeypatch.delenv("DIALECTIC_VISION_ENABLED", raising=False)
    return tmp_path


def image_blocks(result, message_id) -> list[dict]:
    return [b for b in result.get(message_id, []) if b["type"] == "image"]


def note_texts(result, message_id) -> list[str]:
    return [b["text"] for b in result.get(message_id, []) if b["type"] == "text"]


# =========================================================================
# ENCODING — does the model actually get the picture?
# =========================================================================


class TestEncoding:
    @pytest.mark.asyncio
    async def test_real_png_round_trips_to_its_own_bytes(self, media_root):
        """The base64 in the block decodes back to the file that is on disk."""
        png = make_png(4, 3)
        path = write_blob(media_root, ROOM_ID, png)
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=len(png))])

        result = await load_message_images(db, ROOM_ID, [mid])

        blocks = image_blocks(result, mid)
        assert len(blocks) == 1
        source = blocks[0]["source"]
        assert source["type"] == "base64"
        assert source["media_type"] == "image/png"
        assert base64.b64decode(source["data"]) == png
        # …and the decoded bytes are a real PNG, not an empty file that would
        # also "round trip".
        assert png.startswith(b"\x89PNG\r\n\x1a\n")

    @pytest.mark.asyncio
    async def test_two_images_on_one_message_keep_upload_order(self, media_root):
        first = make_png(2, 2)
        second = make_png(5, 5)
        mid = uuid4()
        base = datetime.now(timezone.utc)
        db = FakeDB([
            row(mid, write_blob(media_root, ROOM_ID, second), nbytes=len(second),
                created_at=base + timedelta(seconds=1)),
            row(mid, write_blob(media_root, ROOM_ID, first), nbytes=len(first),
                created_at=base),
        ])

        result = await load_message_images(db, ROOM_ID, [mid])

        decoded = [base64.b64decode(b["source"]["data"]) for b in image_blocks(result, mid)]
        assert decoded == [first, second]

    @pytest.mark.asyncio
    async def test_no_rows_means_no_key_and_no_disk_access(self, media_root):
        db = FakeDB([])
        assert await load_message_images(db, ROOM_ID, [uuid4()]) == {}

    @pytest.mark.asyncio
    async def test_empty_id_list_never_queries(self, media_root):
        db = FakeDB([])
        assert await load_message_images(db, ROOM_ID, []) == {}
        assert db.queries == []


# =========================================================================
# CAPS — each one isolated so a pass means THAT guard held
# =========================================================================


class TestCaps:
    @pytest.mark.asyncio
    async def test_oversized_image_is_noted_and_never_read_from_disk(self, media_root):
        """The declared size short-circuits before any file I/O.

        storage_path points at a file that does not exist, so if the cap ever
        stopped firing this test would go NOTE_UNAVAILABLE rather than passing
        — the note text is what distinguishes "refused" from "couldn't find".
        """
        mid = uuid4()
        db = FakeDB([row(mid, "nope/does-not-exist.png", nbytes=MAX_IMAGE_BYTES + 1)])

        result = await load_message_images(db, ROOM_ID, [mid])

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_TOO_LARGE]

    @pytest.mark.asyncio
    async def test_image_exactly_at_the_cap_is_still_shown(self, media_root):
        """The cap is a ceiling, not a fence one byte inside it."""
        png = make_png(3, 2)
        path = write_blob(media_root, ROOM_ID, png)
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=len(png))])

        result = await load_message_images(
            db, ROOM_ID, [mid], max_image_bytes=len(png),
        )

        assert len(image_blocks(result, mid)) == 1

    @pytest.mark.asyncio
    async def test_blob_larger_than_its_row_claims_is_refused(self, media_root):
        """A row that under-declares must not smuggle bytes past the cap."""
        png = make_png(20, 20)
        path = write_blob(media_root, ROOM_ID, png)
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=1)])   # row lies about the size

        result = await load_message_images(
            db, ROOM_ID, [mid], max_image_bytes=len(png) - 1,
        )

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_UNAVAILABLE]

    @pytest.mark.asyncio
    async def test_only_the_newest_four_images_are_sent(self, media_root):
        """Five tiny images, default budget — the count cap is the only limiter."""
        mids = [uuid4() for _ in range(5)]
        rows = []
        for index, mid in enumerate(mids):
            png = make_png(2 + index, 2)
            rows.append(row(mid, write_blob(media_root, ROOM_ID, png), nbytes=len(png)))
        db = FakeDB(rows)

        result = await load_message_images(db, ROOM_ID, mids)

        assert sum(len(image_blocks(result, m)) for m in mids) == MAX_IMAGES == 4
        # The one that loses is the OLDEST, and it gets no note — a wall of
        # "not shown" on every old message is noise.
        assert mids[0] not in result
        assert all(len(image_blocks(result, m)) == 1 for m in mids[1:])

    @pytest.mark.asyncio
    async def test_budget_skips_what_does_not_fit_and_keeps_scanning(self, media_root):
        """One fat screenshot must not hide the small chart posted behind it.

        Sizes newest->oldest are big/big/small with a budget that admits one
        big and then the small: the middle one is skipped and the scan
        CONTINUES, which a `break` would fail.
        """
        big_a, big_b, small = make_png(30, 30), make_png(31, 30), make_png(2, 2)
        assert len(small) < len(big_a) and len(small) < len(big_b)
        mids = [uuid4() for _ in range(3)]   # chronological: [oldest, mid, newest]
        db = FakeDB([
            row(mids[2], write_blob(media_root, ROOM_ID, big_a), nbytes=len(big_a)),
            row(mids[1], write_blob(media_root, ROOM_ID, big_b), nbytes=len(big_b)),
            row(mids[0], write_blob(media_root, ROOM_ID, small), nbytes=len(small)),
        ])
        budget = len(big_a) + len(small)

        result = await load_message_images(
            db, ROOM_ID, mids, total_budget_bytes=budget,
        )

        assert len(image_blocks(result, mids[2])) == 1   # newest, fits
        assert mids[1] not in result                     # skipped, over budget
        assert len(image_blocks(result, mids[0])) == 1   # older but small — kept

    @pytest.mark.asyncio
    async def test_only_the_newest_window_of_messages_is_queried(self, media_root):
        """A picture twelve turns back is not re-sent on every turn since."""
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        mids = [uuid4() for _ in range(12)]
        db = FakeDB([row(mids[0], path, nbytes=len(png))])

        result = await load_message_images(db, ROOM_ID, mids, window=10)

        assert result == {}
        _, queried_ids = db.args[0]
        assert mids[0] not in queried_ids
        assert list(queried_ids) == mids[2:]

    @pytest.mark.asyncio
    async def test_shipped_defaults_are_the_documented_budget(self):
        """The constants the caller relies on when it passes no overrides."""
        assert MAX_IMAGES == 4
        assert MAX_IMAGE_BYTES == 5 * 1024 * 1024
        assert TOTAL_BUDGET_BYTES == 12 * 1024 * 1024


# =========================================================================
# RECENCY — position in the window, not attachment created_at
# =========================================================================


class TestRecency:
    @pytest.mark.asyncio
    async def test_a_deduplicated_reupload_still_counts_as_newest(self, media_root):
        """Re-posting last week's chart hands back a week-old attachment row.

        Ordering by created_at would drop the image the room is looking at RIGHT
        NOW in favour of four older ones.
        """
        mids = [uuid4() for _ in range(5)]
        old = datetime.now(timezone.utc) - timedelta(days=7)
        rows = []
        for index, mid in enumerate(mids):
            png = make_png(2 + index, 2)
            # The NEWEST message carries the oldest attachment row.
            stamp = old if index == len(mids) - 1 else datetime.now(timezone.utc)
            rows.append(row(
                mid, write_blob(media_root, ROOM_ID, png),
                nbytes=len(png), created_at=stamp,
            ))
        db = FakeDB(rows)

        result = await load_message_images(db, ROOM_ID, mids)

        assert len(image_blocks(result, mids[-1])) == 1   # the re-post survives
        assert mids[0] not in result                      # the oldest message loses


# =========================================================================
# WHAT THE MODEL IS TOLD WHEN IT CANNOT SEE
# =========================================================================


class TestNotes:
    @pytest.mark.asyncio
    async def test_missing_file_becomes_a_note(self, media_root):
        mid = uuid4()
        db = FakeDB([row(mid, os.path.join(str(ROOM_ID), "ab", "gone.png"), nbytes=100)])

        result = await load_message_images(db, ROOM_ID, [mid])

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_UNAVAILABLE]

    @pytest.mark.asyncio
    async def test_out_of_root_storage_path_is_refused(self, media_root, tmp_path):
        """A corrupted row must not read a file outside MEDIA_ROOT into a prompt
        — which here would also hand it to a third party's API."""
        outside = tmp_path.parent / "outside-secret.png"
        outside.write_bytes(make_png())
        mid = uuid4()
        db = FakeDB([row(mid, "../outside-secret.png", nbytes=outside.stat().st_size)])

        result = await load_message_images(db, ROOM_ID, [mid])

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_UNAVAILABLE]

    @pytest.mark.asyncio
    async def test_empty_blob_is_refused(self, media_root):
        """Empty base64 is a 400 from the API, not a blank picture."""
        path = write_blob(media_root, ROOM_ID, b"")
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=0)])

        result = await load_message_images(db, ROOM_ID, [mid])

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_UNAVAILABLE]

    @pytest.mark.asyncio
    async def test_mime_the_api_cannot_render_is_refused(self, media_root):
        """kind='image' is not the same claim as "Anthropic can decode it"."""
        payload = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        path = write_blob(media_root, ROOM_ID, payload, ext=".svg")
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=len(payload), mime="image/svg+xml")])

        result = await load_message_images(db, ROOM_ID, [mid])

        assert image_blocks(result, mid) == []
        assert note_texts(result, mid) == [NOTE_UNAVAILABLE]

    @pytest.mark.asyncio
    async def test_a_broken_image_does_not_cost_a_slot(self, media_root):
        """The four viewable images are four PICTURES, not four rows.

        The broken one is on the NEWEST message, so it is evaluated before the
        count cap fills: if it consumed a slot only three pictures would arrive.
        """
        mids = [uuid4() for _ in range(6)]   # chronological
        rows = [row(mids[-1], "gone/missing.png", nbytes=10)]
        for mid in mids[:-1]:
            png = make_png()
            rows.append(row(mid, write_blob(media_root, ROOM_ID, png), nbytes=len(png)))
        db = FakeDB(rows)

        result = await load_message_images(db, ROOM_ID, mids)

        assert note_texts(result, mids[-1]) == [NOTE_UNAVAILABLE]
        assert sum(len(image_blocks(result, m)) for m in mids) == 4
        assert mids[0] not in result   # the oldest is the one pushed out


# =========================================================================
# ROOM SCOPING + KILL SWITCH
# =========================================================================


class TestGates:
    @pytest.mark.asyncio
    async def test_another_rooms_attachment_is_not_loaded(self, media_root):
        png = make_png()
        path = write_blob(media_root, OTHER_ROOM_ID, png)
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=len(png), room_id=OTHER_ROOM_ID)])

        assert await load_message_images(db, ROOM_ID, [mid]) == {}
        # …and the same row IS returned for its own room, so the assertion
        # above is about scoping and not about a broken fixture.
        assert image_blocks(await load_message_images(db, OTHER_ROOM_ID, [mid]), mid)

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " Off "])
    def test_kill_switch_off_values(self, monkeypatch, value):
        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", value)
        assert vision_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
    def test_kill_switch_on_values(self, monkeypatch, value):
        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", value)
        assert vision_enabled() is True

    def test_kill_switch_defaults_on_when_unset(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_VISION_ENABLED", raising=False)
        assert vision_enabled() is True

    @pytest.mark.asyncio
    async def test_kill_switch_skips_the_query_entirely(self, media_root, monkeypatch):
        """Off means no DB round trip and no disk read, not a filtered result."""
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        mid = uuid4()
        db = FakeDB([row(mid, path, nbytes=len(png))])

        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "off")
        assert await load_message_images(db, ROOM_ID, [mid]) == {}
        assert db.queries == []

        # …and with the switch back on the SAME fixture yields an image, so the
        # assertion above cannot pass because the fixture was empty.
        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "1")
        assert image_blocks(await load_message_images(db, ROOM_ID, [mid]), mid)


def test_count_images_ignores_notes():
    payload = {
        uuid4(): [{"type": "image", "source": {}}, {"type": "text", "text": NOTE_UNAVAILABLE}],
        uuid4(): [{"type": "image", "source": {}}],
    }
    assert count_images(payload) == 2
    assert count_images(None) == 0
    assert count_images({}) == 0


# =========================================================================
# PROMPT SEAM — image blocks in the transcript
# =========================================================================


IMG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}


@pytest.fixture
def builder():
    return PromptBuilder()


class TestPromptSeam:
    def test_images_come_before_the_speaker_text(self, builder):
        alice = make_user("Alice", user_id=USER_A_ID)
        msg = make_message("what's wrong with this chart", user_id=USER_A_ID)

        prompt = builder.build(
            make_room(), [alice], [msg], [], message_images={msg.id: [IMG]},
        )

        content = prompt.messages[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image"
        assert content[1] == {
            "type": "text",
            "text": "[Alice] what's wrong with this chart",
        }
        assert prompt.messages[0]["role"] == "user"

    def test_messages_without_images_keep_the_plain_string_form(self, builder):
        alice = make_user("Alice", user_id=USER_A_ID)
        with_image = make_message("look", user_id=USER_A_ID, sequence=1)
        without = make_message("and also", user_id=USER_A_ID, sequence=2)

        prompt = builder.build(
            make_room(), [alice], [with_image, without], [],
            message_images={with_image.id: [IMG]},
        )

        assert isinstance(prompt.messages[0]["content"], list)
        assert prompt.messages[1]["content"] == "[Alice] and also"

    def test_no_message_images_is_byte_identical_to_before(self, builder):
        """The default path must not change shape for any existing room."""
        alice = make_user("Alice", user_id=USER_A_ID)
        msgs = [
            make_message("one", user_id=USER_A_ID),
            make_message("two", speaker_type=SpeakerType.LLM_PRIMARY),
        ]
        room = make_room()

        baseline = builder.build(room, [alice], msgs, [])
        with_none = builder.build(room, [alice], msgs, [], message_images=None)
        with_empty = builder.build(room, [alice], msgs, [], message_images={})
        # A payload keyed by a message that is NOT in this prompt changes nothing.
        with_stranger = builder.build(
            room, [alice], msgs, [], message_images={uuid4(): [IMG]},
        )

        assert baseline.messages == with_none.messages == with_empty.messages
        assert baseline.messages == with_stranger.messages
        assert all(isinstance(m["content"], str) for m in baseline.messages)

    def test_caption_less_upload_still_carries_a_non_empty_text_block(self, builder):
        """An image with no words is the common case; the API rejects an empty
        text block, and the room's transcript needs the attribution anyway."""
        alice = make_user("Alice", user_id=USER_A_ID)
        msg = make_message("", user_id=USER_A_ID)

        prompt = builder.build(
            make_room(), [alice], [msg], [], message_images={msg.id: [IMG]},
        )

        text = prompt.messages[0]["content"][-1]["text"]
        assert text.strip() == "[Alice]"
        assert text.strip()

    def test_deleted_message_with_images_is_still_excluded(self, builder):
        alice = make_user("Alice", user_id=USER_A_ID)
        msg = make_message("gone", user_id=USER_A_ID, is_deleted=True)

        prompt = builder.build(
            make_room(), [alice], [msg], [], message_images={msg.id: [IMG]},
        )

        assert prompt.messages == []

    def test_trailing_assistant_still_gets_a_synthetic_user_turn(self, builder):
        """The strip/append logic reads role, never content — a block-form human
        turn earlier in the list must not confuse it."""
        alice = make_user("Alice", user_id=USER_A_ID)
        human = make_message("look at this", user_id=USER_A_ID, sequence=1)
        llm = make_message("I see", speaker_type=SpeakerType.LLM_PRIMARY, sequence=2)

        prompt = builder.build(
            make_room(), [alice], [human, llm], [], message_images={human.id: [IMG]},
        )

        assert isinstance(prompt.messages[0]["content"], list)
        assert prompt.messages[-1]["role"] == "user"
        assert prompt.messages[-1]["content"] == "[SYSTEM] Continue the dialogue."

    def test_block_form_last_turn_does_not_get_a_synthetic_turn(self, builder):
        """A user turn is a user turn whether it is a string or blocks."""
        alice = make_user("Alice", user_id=USER_A_ID)
        msg = make_message("last word", user_id=USER_A_ID)

        prompt = builder.build(
            make_room(), [alice], [msg], [], message_images={msg.id: [IMG]},
        )

        assert len(prompt.messages) == 1
        assert prompt.messages[0]["role"] == "user"

    def test_notes_ride_in_the_same_block_list(self, builder):
        alice = make_user("Alice", user_id=USER_A_ID)
        msg = make_message("see attached", user_id=USER_A_ID)
        note = {"type": "text", "text": NOTE_UNAVAILABLE}

        prompt = builder.build(
            make_room(), [alice], [msg], [], message_images={msg.id: [note]},
        )

        content = prompt.messages[0]["content"]
        assert content[0]["text"] == NOTE_UNAVAILABLE
        assert content[1]["text"].startswith("[Alice]")


# =========================================================================
# ORCHESTRATOR GATE
# =========================================================================


THREAD_ROOM_ID = make_thread().room_id


def make_orchestrator(monkeypatch, db=None):
    # An EMPTY registry, not None: _tool_registry_for calls .schemas() on what
    # build_registry returns, and these tests are about images, not tools.
    monkeypatch.setattr(
        orchestrator_mod, "build_registry", lambda room, db_conn: ToolRegistry(tools=[]),
    )
    orch = LLMOrchestrator(db if db is not None else SimpleNamespace())
    orch._get_cross_session_context = AsyncMock(return_value=None)
    orch._get_identity_context = AsyncMock(return_value=(None, None))
    orch.prompt_builder.build = MagicMock(return_value=AssembledPrompt("system", []))
    orch._persist_response = AsyncMock(return_value=make_message("ok"))
    orch._schedule_self_memory_extraction = MagicMock()
    return orch


class FakeStreamRouter:
    async def stream(self, _request):
        yield "attempt", {"provider": "anthropic", "model": "claude-sonnet-5"}
        yield "token", {"token": "hi"}


async def drain_stream(orch, messages, use_provoker=False):
    thread = make_thread()
    orch._get_router = MagicMock(return_value=FakeStreamRouter())
    return [
        event
        async for event in orch.stream_response(
            room=make_room(), thread=thread, users=[], messages=messages,
            memories=[], use_provoker=use_provoker,
        )
    ]


class TestOrchestratorGate:
    @pytest.mark.asyncio
    async def test_primary_stream_passes_images_into_the_prompt(
        self, media_root, monkeypatch,
    ):
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        msg = make_message("what is this", user_id=USER_A_ID)
        db = FakeDB([row(msg.id, path, nbytes=len(png), room_id=THREAD_ROOM_ID)])
        orch = make_orchestrator(monkeypatch, db=db)

        await drain_stream(orch, [msg])

        images = orch.prompt_builder.build.call_args.kwargs["message_images"]
        assert count_images(images) == 1
        assert base64.b64decode(images[msg.id][0]["source"]["data"]) == png

    @pytest.mark.asyncio
    async def test_provoker_never_gets_images(self, media_root, monkeypatch):
        """Same line the tool registry draws: a 1-3 sentence jab cannot carry a
        1.5k-token picture, and the provoker's context is stripped by design."""
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        msg = make_message("what is this", user_id=USER_A_ID)
        db = FakeDB([row(msg.id, path, nbytes=len(png), room_id=THREAD_ROOM_ID)])
        orch = make_orchestrator(monkeypatch, db=db)

        await drain_stream(orch, [msg], use_provoker=True)

        assert orch.prompt_builder.build.call_args.kwargs["message_images"] is None
        assert db.queries == []   # not merely filtered — never asked

    @pytest.mark.asyncio
    async def test_protocol_facilitator_never_gets_images(self, media_root, monkeypatch):
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        msg = make_message("what is this", user_id=USER_A_ID)
        db = FakeDB([row(msg.id, path, nbytes=len(png), room_id=THREAD_ROOM_ID)])
        orch = make_orchestrator(monkeypatch, db=db)
        protocol = SimpleNamespace(id=uuid4(), current_phase=1)

        assert await orch._load_message_images(
            THREAD_ROOM_ID, [msg], use_provoker=False, protocol=protocol,
        ) is None
        assert db.queries == []
        # …and the identical call WITHOUT a protocol does load it, so the
        # assertion above is about the protocol and not about the fixture.
        assert await orch._load_message_images(
            THREAD_ROOM_ID, [msg], use_provoker=False,
        ) is not None

    @pytest.mark.asyncio
    async def test_a_broken_attachment_query_costs_the_picture_not_the_turn(
        self, media_root, monkeypatch,
    ):
        class ExplodingDB:
            queries: list = []

            async def fetch(self, *_args):
                raise RuntimeError("attachments volume is unmounted")

        orch = make_orchestrator(monkeypatch, db=ExplodingDB())
        msg = make_message("what is this", user_id=USER_A_ID)

        events = await drain_stream(orch, [msg])

        assert orch.prompt_builder.build.call_args.kwargs["message_images"] is None
        assert [kind for kind, _ in events][-1] == "done"

    @pytest.mark.asyncio
    async def test_kill_switch_reaches_the_streaming_path(self, media_root, monkeypatch):
        png = make_png()
        path = write_blob(media_root, ROOM_ID, png)
        msg = make_message("what is this", user_id=USER_A_ID)
        db = FakeDB([row(msg.id, path, nbytes=len(png), room_id=THREAD_ROOM_ID)])
        orch = make_orchestrator(monkeypatch, db=db)

        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "0")
        await drain_stream(orch, [msg])
        assert orch.prompt_builder.build.call_args.kwargs["message_images"] is None

        monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "1")
        await drain_stream(orch, [msg])
        assert count_images(
            orch.prompt_builder.build.call_args.kwargs["message_images"]
        ) == 1


# =========================================================================
# OPENAI FALLBACK — Anthropic image blocks are not its shape
# =========================================================================


def openai_provider(monkeypatch) -> OpenAIProvider:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    return OpenAIProvider()


def image_request() -> LLMRequest:
    return LLMRequest(
        messages=[
            {"role": "user", "content": [IMG, {"type": "text", "text": "[Alice] look"}]},
            {"role": "assistant", "content": "I see"},
        ],
        system="be a participant",
        model="gpt-4o",
    )


class CapturingClient:
    """httpx.AsyncClient stand-in that records the JSON body it was handed.

    WHY the real client is replaced rather than the network mocked: the thing
    under test is what OpenAI would RECEIVE, and nothing short of the request
    body answers that.
    """

    COMPLETION = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }

    def __init__(self):
        self.bodies: list[dict] = []

    async def post(self, _url, headers=None, json=None):
        self.bodies.append(json)
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: self.COMPLETION,
        )

    def stream(self, _method, _url, headers=None, json=None):
        self.bodies.append(json)

        async def lines():
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}'
            yield "data: [DONE]"

        class Ctx:
            async def __aenter__(self):
                return SimpleNamespace(
                    raise_for_status=lambda: None, aiter_lines=lines,
                )

            async def __aexit__(self, *_args):
                return False

        return Ctx()


class TestOpenAIFlattening:
    def test_plain_strings_pass_through_untouched(self):
        assert flatten_content_blocks("[Alice] hello") == "[Alice] hello"

    def test_image_blocks_become_an_honest_note(self):
        """Forwarding {"type":"image"} verbatim is a deterministic 400, and the
        router would burn three retries plus ~7s of backoff finding that out."""
        flat = flatten_content_blocks([IMG, {"type": "text", "text": "[Alice] look"}])
        assert IMG["source"]["data"] not in flat
        assert "cannot see it" in flat
        assert "[Alice] look" in flat

    def test_tool_blocks_are_dropped_rather_than_rendered(self):
        blocks = [
            {"type": "tool_use", "id": "t1", "name": "get_live_quotes", "input": {}},
            {"type": "text", "text": "answer"},
        ]
        assert flatten_content_blocks(blocks) == "answer"

    def test_provider_flattens_every_turn_it_sends(self, monkeypatch):
        provider = openai_provider(monkeypatch)

        sent = provider._messages(image_request())

        assert sent[0] == {"role": "system", "content": "be a participant"}
        assert all(isinstance(m["content"], str) for m in sent)
        assert [m["role"] for m in sent] == ["system", "user", "assistant"]
        assert sent[2]["content"] == "I see"

    # The two below go to the WIRE BODY rather than the helper. A test of
    # _messages() alone passes happily while complete()/stream() still extend
    # request.messages verbatim — which is precisely the 400 this exists to
    # stop. (Caught by mutation: flattening removed from complete(), helper
    # test still green.)

    @pytest.mark.asyncio
    async def test_complete_sends_flattened_content_over_the_wire(self, monkeypatch):
        provider = openai_provider(monkeypatch)
        client = CapturingClient()
        provider.client = client

        await provider.complete(image_request())

        body_messages = client.bodies[0]["messages"]
        assert all(isinstance(m["content"], str) for m in body_messages)
        assert IMG["source"]["data"] not in str(client.bodies[0])

    @pytest.mark.asyncio
    async def test_stream_sends_flattened_content_over_the_wire(self, monkeypatch):
        provider = openai_provider(monkeypatch)
        client = CapturingClient()
        provider.client = client

        tokens = [token async for token in provider.stream(image_request())]

        assert tokens == ["hi"]
        body_messages = client.bodies[0]["messages"]
        assert all(isinstance(m["content"], str) for m in body_messages)
        assert IMG["source"]["data"] not in str(client.bodies[0])
