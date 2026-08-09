"""
Tests for api/attachments — the media upload/fetch/bind API.

Strategy: mount the real router on a bare FastAPI app with the db dependency
replaced by a fake that routes on SQL, and MEDIA_ROOT pointed at tmp_path. The
auth dependencies stay REAL except get_current_user (JWT decoding is
test_auth_utils' subject) — so room-token and membership refusals are exercised
against actual code, not stubbed away.

WHAT THESE TESTS ARE ACTUALLY GUARDING:

  - Bytes never enter a path. The filename is attacker-controlled; every path
    is built from a server-computed sha256 plus an extension taken from the
    mime allowlist. The traversal tests assert the SHAPE of storage_path and
    that nothing lands outside MEDIA_ROOT, because "it didn't crash" is not
    evidence here.
  - A declared Content-Type is not evidence of content. An executable
    announced as image/png would be stored and later served BACK as
    image/png, which is a drive-by delivery. So the sniff is asserted against
    real bytes, both directions: a genuine PNG passes, a fake one is refused.
  - The cap is enforced while streaming, not after. The 413 tests also assert
    the temp directory is empty afterwards — a cap that rejects the request
    but leaves the bytes on disk has not actually protected the volume.
  - Auth is on the endpoint, not just in the fixture. test_fetch_requires_jwt
    runs against an app WITHOUT the get_current_user override, so it fails if
    the dependency is ever dropped from the route.
"""

import hashlib
import os
import struct
import zlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.attachments as attachments
from api.attachments import (
    MIME_POLICY,
    content_disposition,
    image_dimensions,
    max_bytes_for_kind,
    normalize_mime,
    sanitize_original_name,
    sniff_image_mime,
)
from api.auth.dependencies import AuthenticatedUser, get_current_user


ROOM_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ROOM_ID = UUID("22222222-2222-2222-2222-222222222222")
MEMBER_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTSIDER_ID = UUID("44444444-4444-4444-4444-444444444444")
ROOM_TOKEN = "room-token-under-test"


# =========================================================================
# REAL FILE BYTES
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


def make_gif(width: int = 7, height: int = 5) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\x00\x00" + b"\x3b"


def make_jpeg_header(width: int = 640, height: int = 480) -> bytes:
    """SOI + APP0 + SOF0 — enough for header parsing, which is all we parse."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def make_webp_lossless(width: int = 11, height: int = 9) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    payload = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
    return b"RIFF" + struct.pack("<I", len(payload) + 4) + b"WEBP" + payload + b"\x00" * 8


# =========================================================================
# FAKE DB
# =========================================================================


class FakeDB:
    """
    asyncpg-connection stand-in that routes on the SQL the router actually
    sends. WHY not an AsyncMock with scripted side_effects: ordering-sensitive
    scripts silently pass when the code changes which query runs first.
    """

    def __init__(self):
        self.rooms: dict[UUID, str] = {}
        self.members: set[tuple[UUID, UUID]] = set()
        self.messages: dict[UUID, UUID] = {}   # message_id -> room_id
        self.attachments: dict[UUID, dict] = {}
        self.queries: list[str] = []

    @staticmethod
    def _flat(query: str) -> str:
        return " ".join(query.split())

    async def fetchrow(self, query, *args):
        q = self._flat(query)
        self.queries.append(q)

        if "FROM rooms WHERE id = $1 AND token = $2" in q:
            room_id, token = args
            return {"id": room_id} if self.rooms.get(room_id) == token else None

        if "FROM room_memberships WHERE room_id = $1 AND user_id = $2" in q:
            room_id, user_id = args
            return {"exists": 1} if (room_id, user_id) in self.members else None

        if "FROM attachments WHERE room_id = $1 AND sha256 = $2" in q:
            room_id, sha = args
            hits = [
                r for r in self.attachments.values()
                if r["room_id"] == room_id and r["sha256"] == sha
            ]
            hits.sort(key=lambda r: r["created_at"])
            return hits[0] if hits else None

        if "FROM attachments WHERE id = $1 AND room_id = $2" in q:
            attachment_id, room_id = args
            row = self.attachments.get(attachment_id)
            return row if row and row["room_id"] == room_id else None

        if "FROM attachments WHERE id = $1" in q:
            return self.attachments.get(args[0])

        if "INSERT INTO attachments" in q:
            (attachment_id, room_id, uploader, kind, mime, size, sha,
             width, height, original_name, storage_path, created_at) = args
            row = {
                "id": attachment_id,
                "room_id": room_id,
                "message_id": None,
                "uploader_user_id": uploader,
                "kind": kind,
                "mime": mime,
                "bytes": size,
                "sha256": sha,
                "width": width,
                "height": height,
                "original_name": original_name,
                "storage_path": storage_path,
                "created_at": created_at,
            }
            self.attachments[attachment_id] = row
            return row

        if "UPDATE attachments SET message_id = $1 WHERE id = $2" in q:
            message_id, attachment_id = args
            self.attachments[attachment_id]["message_id"] = message_id
            return self.attachments[attachment_id]

        raise AssertionError(f"FakeDB got an unrouted fetchrow: {q}")

    async def fetchval(self, query, *args):
        q = self._flat(query)
        self.queries.append(q)
        if "SELECT t.room_id FROM messages m" in q:
            return self.messages.get(args[0])
        raise AssertionError(f"FakeDB got an unrouted fetchval: {q}")


# =========================================================================
# FIXTURES
# =========================================================================


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """Router mounted alone; MEDIA_ROOT under tmp_path; db + JWT faked."""
    media_root = tmp_path / "media"
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    monkeypatch.delenv("MEDIA_MAX_IMAGE_BYTES", raising=False)
    monkeypatch.delenv("MEDIA_MAX_FILE_BYTES", raising=False)
    monkeypatch.delenv("MEDIA_MAX_VIDEO_BYTES", raising=False)

    db = FakeDB()
    db.rooms[ROOM_ID] = ROOM_TOKEN
    db.rooms[OTHER_ROOM_ID] = "other-token"
    db.members.add((ROOM_ID, MEMBER_ID))

    acting = {"user_id": MEMBER_ID}

    app = FastAPI()
    app.include_router(attachments.router)

    async def _db_dep():
        yield db

    async def _user_dep():
        return AuthenticatedUser(
            user_id=acting["user_id"],
            email="amo@example.com",
            email_verified=True,
            display_name="Amo",
        )

    app.dependency_overrides[attachments._get_db] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep

    return SimpleNamespace(
        client=TestClient(app),
        db=db,
        acting=acting,
        media_root=media_root,
        app=app,
    )


def auth_headers(token: str = ROOM_TOKEN) -> dict:
    return {"X-Room-Token": token}


def upload(ctx, content: bytes, filename: str, mime: str, room_id=ROOM_ID,
           token: str = ROOM_TOKEN):
    return ctx.client.post(
        f"/rooms/{room_id}/attachments",
        files={"file": (filename, content, mime)},
        headers=auth_headers(token),
    )


def stored_files(media_root) -> list[str]:
    """Every file under MEDIA_ROOT except the temp staging area."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(media_root):
        if os.path.basename(dirpath) == ".tmp":
            continue
        for name in filenames:
            found.append(os.path.join(dirpath, name))
    return found


def temp_files(media_root) -> list[str]:
    tmp_dir = os.path.join(media_root, ".tmp")
    if not os.path.isdir(tmp_dir):
        return []
    return [os.path.join(tmp_dir, n) for n in os.listdir(tmp_dir)]


# =========================================================================
# UPLOAD -> FETCH ROUNDTRIP
# =========================================================================


class TestUploadFetchRoundtrip:
    def test_png_upload_then_fetch_returns_the_same_bytes(self, ctx):
        png = make_png(width=3, height=2)
        resp = upload(ctx, png, "chart.png", "image/png")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["kind"] == "image"
        assert body["mime"] == "image/png"
        assert body["bytes"] == len(png)
        assert body["sha256"] == hashlib.sha256(png).hexdigest()
        assert body["width"] == 3 and body["height"] == 2
        assert body["original_name"] == "chart.png"
        assert body["message_id"] is None
        assert body["uploader_user_id"] == str(MEMBER_ID)
        assert body["deduplicated"] is False
        assert body["url"] == f"/attachments/{body['id']}"

        fetched = ctx.client.get(body["url"], headers=auth_headers())
        assert fetched.status_code == 200
        assert fetched.content == png
        assert fetched.headers["content-type"].startswith("image/png")
        assert fetched.headers["content-disposition"].startswith("inline")

    def test_storage_path_is_content_addressed_under_the_room(self, ctx):
        png = make_png()
        body = upload(ctx, png, "chart.png", "image/png").json()
        sha = body["sha256"]
        assert body["storage_path"] == os.path.join(
            str(ROOM_ID), sha[:2], f"{sha}.png"
        )
        on_disk = stored_files(ctx.media_root)
        assert len(on_disk) == 1
        assert on_disk[0].endswith(body["storage_path"])
        assert temp_files(ctx.media_root) == []

    def test_non_image_file_downloads_rather_than_rendering(self, ctx):
        body = upload(ctx, b'{"a": 1}', "data.json", "application/json").json()
        assert body["kind"] == "file"
        assert body["width"] is None and body["height"] is None
        assert body["storage_path"].endswith(".json")

        fetched = ctx.client.get(body["url"], headers=auth_headers())
        assert fetched.status_code == 200
        disposition = fetched.headers["content-disposition"]
        assert disposition.startswith("attachment")
        assert 'filename="data.json"' in disposition

    def test_video_is_classified_and_served_inline(self, ctx):
        body = upload(ctx, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64,
                      "clip.mp4", "video/mp4").json()
        assert body["kind"] == "video"
        assert body["storage_path"].endswith(".mov") is False
        assert body["storage_path"].endswith(".mp4")

        fetched = ctx.client.get(body["url"], headers=auth_headers())
        assert fetched.headers["content-disposition"].startswith("inline")

    def test_gif_dimensions_are_extracted(self, ctx):
        body = upload(ctx, make_gif(7, 5), "loop.gif", "image/gif").json()
        assert (body["width"], body["height"]) == (7, 5)

    def test_jpeg_dimensions_are_extracted(self, ctx):
        body = upload(ctx, make_jpeg_header(640, 480), "photo.jpg", "image/jpeg").json()
        assert (body["width"], body["height"]) == (640, 480)

    def test_webp_dimensions_are_extracted(self, ctx):
        body = upload(ctx, make_webp_lossless(11, 9), "pic.webp", "image/webp").json()
        assert (body["width"], body["height"]) == (11, 9)

    def test_empty_upload_is_rejected(self, ctx):
        resp = upload(ctx, b"", "empty.png", "image/png")
        assert resp.status_code == 400
        assert stored_files(ctx.media_root) == []
        assert temp_files(ctx.media_root) == []


# =========================================================================
# MIME POLICY
# =========================================================================


class TestMimeRejection:
    def test_disallowed_mime_is_415(self, ctx):
        resp = upload(ctx, b"MZ\x90\x00", "payload.exe", "application/x-msdownload")
        assert resp.status_code == 415
        assert "Unsupported media type" in resp.json()["detail"]
        assert stored_files(ctx.media_root) == []
        assert temp_files(ctx.media_root) == []

    def test_svg_is_rejected(self, ctx):
        """SVG is script-capable; it is deliberately outside the image allowlist."""
        resp = upload(ctx, b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                      "x.svg", "image/svg+xml")
        assert resp.status_code == 415

    def test_content_that_is_not_an_image_is_refused_despite_the_header(self, ctx):
        """A declared image/png carrying an executable must not be stored."""
        resp = upload(ctx, b"MZ\x90\x00" + b"\x00" * 512, "innocent.png", "image/png")
        assert resp.status_code == 415
        assert "not a recognized image" in resp.json()["detail"]
        assert stored_files(ctx.media_root) == []
        assert temp_files(ctx.media_root) == []

    def test_image_claiming_the_wrong_image_type_is_refused(self, ctx):
        resp = upload(ctx, make_png(), "actually.gif", "image/gif")
        assert resp.status_code == 415
        assert "does not match file contents" in resp.json()["detail"]

    def test_mime_alias_is_accepted_and_normalized(self, ctx):
        body = upload(ctx, make_png(), "chart.jpg", "image/jpg")
        # image/jpg normalizes to image/jpeg, whose sniff then fails on PNG bytes
        assert body.status_code == 415
        ok = upload(ctx, make_jpeg_header(), "chart.jpg", "image/jpg").json()
        assert ok["mime"] == "image/jpeg"
        assert ok["storage_path"].endswith(".jpg")

    def test_missing_content_type_is_415(self, ctx):
        resp = ctx.client.post(
            f"/rooms/{ROOM_ID}/attachments",
            files={"file": ("mystery", make_png(), None)},
            headers=auth_headers(),
        )
        assert resp.status_code == 415


# =========================================================================
# SIZE CAPS
# =========================================================================


class TestSizeCaps:
    def test_over_cap_upload_is_413(self, ctx, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", "128")
        png = make_png(width=64, height=64)
        assert len(png) > 128
        resp = upload(ctx, png, "big.png", "image/png")
        assert resp.status_code == 413
        assert "128 byte limit" in resp.json()["detail"]

    def test_over_cap_leaves_nothing_on_disk(self, ctx, monkeypatch):
        """A cap that rejects but keeps the bytes has not protected the volume."""
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", "64")
        upload(ctx, make_png(width=64, height=64), "big.png", "image/png")
        assert stored_files(ctx.media_root) == []
        assert temp_files(ctx.media_root) == []
        assert ctx.db.attachments == {}

    def test_at_cap_is_accepted(self, ctx, monkeypatch):
        """The boundary is inclusive — exactly-at-cap must not 413."""
        png = make_png()
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", str(len(png)))
        resp = upload(ctx, png, "exact.png", "image/png")
        assert resp.status_code == 200

    def test_video_cap_is_independent_of_the_image_cap(self, ctx, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", "8")
        monkeypatch.setenv("MEDIA_MAX_VIDEO_BYTES", "4096")
        resp = upload(ctx, b"\x00" * 1024, "clip.mp4", "video/mp4")
        assert resp.status_code == 200

    def test_file_cap_applies_to_documents(self, ctx, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_FILE_BYTES", "16")
        resp = upload(ctx, b"x" * 64, "notes.txt", "text/plain")
        assert resp.status_code == 413


# =========================================================================
# DEDUP
# =========================================================================


class TestDedup:
    def test_same_bytes_in_same_room_return_the_existing_row(self, ctx):
        png = make_png()
        first = upload(ctx, png, "chart.png", "image/png").json()
        second = upload(ctx, png, "chart-copy.png", "image/png").json()

        assert second["id"] == first["id"]
        assert second["deduplicated"] is True
        assert first["deduplicated"] is False
        # The name from the FIRST upload is authoritative — the row is the same row.
        assert second["original_name"] == "chart.png"
        assert len(ctx.db.attachments) == 1

    def test_dedup_writes_no_second_blob_and_leaves_no_temp_file(self, ctx):
        png = make_png()
        upload(ctx, png, "a.png", "image/png")
        assert len(stored_files(ctx.media_root)) == 1
        upload(ctx, png, "b.png", "image/png")
        assert len(stored_files(ctx.media_root)) == 1
        assert temp_files(ctx.media_root) == []

    def test_dedup_is_scoped_to_the_room(self, ctx):
        """Identical bytes in another room are a separate attachment."""
        ctx.db.members.add((OTHER_ROOM_ID, MEMBER_ID))
        png = make_png()
        first = upload(ctx, png, "chart.png", "image/png").json()
        second = upload(ctx, png, "chart.png", "image/png",
                        room_id=OTHER_ROOM_ID, token="other-token").json()
        assert second["id"] != first["id"]
        assert second["deduplicated"] is False
        assert second["storage_path"].startswith(str(OTHER_ROOM_ID))

    def test_different_bytes_are_not_deduplicated(self, ctx):
        a = upload(ctx, make_png(3, 2), "a.png", "image/png").json()
        b = upload(ctx, make_png(4, 2), "b.png", "image/png").json()
        assert a["id"] != b["id"]
        assert a["sha256"] != b["sha256"]
        assert len(stored_files(ctx.media_root)) == 2


# =========================================================================
# AUTHORIZATION
# =========================================================================


class TestAuthorization:
    def test_wrong_room_token_is_401(self, ctx):
        resp = upload(ctx, make_png(), "chart.png", "image/png", token="not-the-token")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid room token"
        assert stored_files(ctx.media_root) == []

    def test_missing_room_token_is_401(self, ctx):
        resp = ctx.client.post(
            f"/rooms/{ROOM_ID}/attachments",
            files={"file": ("chart.png", make_png(), "image/png")},
        )
        assert resp.status_code == 401
        assert "Room token required" in resp.json()["detail"]

    def test_non_member_with_a_valid_room_token_is_403(self, ctx):
        """The room token alone must not let a stranger write to the room."""
        ctx.acting["user_id"] = OUTSIDER_ID
        resp = upload(ctx, make_png(), "chart.png", "image/png")
        assert resp.status_code == 403
        assert "not a member" in resp.json()["detail"]
        assert stored_files(ctx.media_root) == []

    def test_fetch_by_a_non_member_is_403(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        ctx.acting["user_id"] = OUTSIDER_ID
        resp = ctx.client.get(body["url"], headers=auth_headers())
        assert resp.status_code == 403

    def test_fetch_with_another_rooms_token_is_401(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        resp = ctx.client.get(body["url"], headers=auth_headers("other-token"))
        assert resp.status_code == 401

    def test_fetch_requires_jwt(self, tmp_path, monkeypatch):
        """
        Runs WITHOUT the get_current_user override, so it goes red if the JWT
        dependency is ever removed from the route — the fixture cannot mask it.
        """
        monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
        db = FakeDB()
        db.rooms[ROOM_ID] = ROOM_TOKEN
        db.members.add((ROOM_ID, MEMBER_ID))

        app = FastAPI()
        app.include_router(attachments.router)

        async def _db_dep():
            yield db

        app.dependency_overrides[attachments._get_db] = _db_dep
        client = TestClient(app)

        resp = client.get(f"/attachments/{uuid4()}", headers=auth_headers())
        assert resp.status_code == 401

        resp = client.post(
            f"/rooms/{ROOM_ID}/attachments",
            files={"file": ("chart.png", make_png(), "image/png")},
            headers=auth_headers(),
        )
        assert resp.status_code == 401


# =========================================================================
# BIND
# =========================================================================


class TestBind:
    def _bind(self, ctx, attachment_id, message_id, room_id=ROOM_ID):
        return ctx.client.post(
            f"/rooms/{room_id}/attachments/{attachment_id}/bind",
            json={"message_id": str(message_id)},
            headers=auth_headers() if room_id == ROOM_ID
            else {"X-Room-Token": "other-token"},
        )

    def test_bind_sets_message_id(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        message_id = uuid4()
        ctx.db.messages[message_id] = ROOM_ID

        resp = self._bind(ctx, body["id"], message_id)
        assert resp.status_code == 200
        assert resp.json()["message_id"] == str(message_id)
        assert ctx.db.attachments[UUID(body["id"])]["message_id"] == message_id

    def test_rebinding_the_same_message_is_idempotent(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        message_id = uuid4()
        ctx.db.messages[message_id] = ROOM_ID

        first = self._bind(ctx, body["id"], message_id)
        second = self._bind(ctx, body["id"], message_id)
        assert first.status_code == 200 and second.status_code == 200
        assert second.json()["message_id"] == str(message_id)

    def test_binding_to_a_different_message_is_409(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        first_message, second_message = uuid4(), uuid4()
        ctx.db.messages[first_message] = ROOM_ID
        ctx.db.messages[second_message] = ROOM_ID

        self._bind(ctx, body["id"], first_message)
        resp = self._bind(ctx, body["id"], second_message)
        assert resp.status_code == 409
        # The original binding survives the refusal.
        assert ctx.db.attachments[UUID(body["id"])]["message_id"] == first_message

    def test_message_from_another_room_is_rejected(self, ctx):
        """Cross-room bind would leak a private image into another room's view."""
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        foreign_message = uuid4()
        ctx.db.messages[foreign_message] = OTHER_ROOM_ID

        resp = self._bind(ctx, body["id"], foreign_message)
        assert resp.status_code == 400
        assert "does not belong to this room" in resp.json()["detail"]
        assert ctx.db.attachments[UUID(body["id"])]["message_id"] is None

    def test_unknown_message_is_404(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        resp = self._bind(ctx, body["id"], uuid4())
        assert resp.status_code == 404
        assert "Message not found" in resp.json()["detail"]

    def test_unknown_attachment_is_404(self, ctx):
        message_id = uuid4()
        ctx.db.messages[message_id] = ROOM_ID
        resp = self._bind(ctx, uuid4(), message_id)
        assert resp.status_code == 404

    def test_attachment_from_another_room_is_404(self, ctx):
        ctx.db.members.add((OTHER_ROOM_ID, MEMBER_ID))
        body = upload(ctx, make_png(), "chart.png", "image/png",
                      room_id=OTHER_ROOM_ID, token="other-token").json()
        message_id = uuid4()
        ctx.db.messages[message_id] = ROOM_ID
        resp = self._bind(ctx, body["id"], message_id)
        assert resp.status_code == 404

    def test_only_the_uploader_may_bind(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        message_id = uuid4()
        ctx.db.messages[message_id] = ROOM_ID

        ctx.db.members.add((ROOM_ID, OUTSIDER_ID))
        ctx.acting["user_id"] = OUTSIDER_ID
        resp = self._bind(ctx, body["id"], message_id)
        assert resp.status_code == 403
        assert ctx.db.attachments[UUID(body["id"])]["message_id"] is None


# =========================================================================
# FETCH FAILURE MODES
# =========================================================================


class TestFetchFailures:
    def test_unknown_attachment_is_404(self, ctx):
        resp = ctx.client.get(f"/attachments/{uuid4()}", headers=auth_headers())
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Attachment not found"

    def test_row_without_bytes_on_disk_is_404(self, ctx):
        body = upload(ctx, make_png(), "chart.png", "image/png").json()
        os.remove(os.path.join(ctx.media_root, body["storage_path"]))
        resp = ctx.client.get(body["url"], headers=auth_headers())
        assert resp.status_code == 404
        assert "file missing" in resp.json()["detail"]

    def test_storage_path_escaping_the_root_is_404(self, ctx):
        """
        Defense in depth: a corrupted row must not serve /etc/passwd.

        The target EXISTS on disk, so the isfile() check cannot be what
        produces the 404 — asserting the detail string pins the refusal to the
        root-containment guard specifically.
        """
        assert os.path.isfile("/etc/passwd"), "premise: the escape target exists"
        attachment_id = uuid4()
        ctx.db.attachments[attachment_id] = {
            "id": attachment_id,
            "room_id": ROOM_ID,
            "message_id": None,
            "uploader_user_id": MEMBER_ID,
            "kind": "file",
            "mime": "text/plain",
            "bytes": 10,
            "sha256": "0" * 64,
            "width": None,
            "height": None,
            "original_name": "passwd",
            "storage_path": "../../../../etc/passwd",
            "created_at": datetime.now(timezone.utc),
        }
        resp = ctx.client.get(f"/attachments/{attachment_id}", headers=auth_headers())
        assert resp.status_code == 404
        # "file missing" would mean the guard was bypassed and isfile caught it.
        assert resp.json()["detail"] == "Attachment not found"


# =========================================================================
# PATH TRAVERSAL / FILENAME SAFETY
# =========================================================================


class TestFilenameSafety:
    @pytest.mark.parametrize("hostile", [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "/etc/shadow",
        "....//....//root/.ssh/id_rsa",
    ])
    def test_hostile_filename_never_reaches_the_path(self, ctx, hostile):
        png = make_png()
        body = upload(ctx, png, hostile, "image/png").json()
        sha = hashlib.sha256(png).hexdigest()

        assert body["storage_path"] == os.path.join(str(ROOM_ID), sha[:2], f"{sha}.png")
        assert ".." not in body["storage_path"]

        on_disk = stored_files(ctx.media_root)
        assert len(on_disk) == 1
        # Everything written stayed inside MEDIA_ROOT.
        root = os.path.realpath(ctx.media_root)
        assert os.path.commonpath([os.path.realpath(on_disk[0]), root]) == root

    def test_extension_comes_from_the_mime_not_the_filename(self, ctx):
        body = upload(ctx, make_png(), "chart.php.png.exe", "image/png").json()
        assert body["storage_path"].endswith(".png")
        assert ".exe" not in body["storage_path"]

    def test_original_name_is_kept_as_a_label_only(self, ctx):
        body = upload(ctx, make_png(), "../../etc/passwd", "image/png").json()
        assert body["original_name"] == "passwd"

    def test_a_filename_of_only_separators_falls_back(self, ctx):
        body = upload(ctx, make_png(), "../../", "image/png").json()
        assert body["original_name"] == "upload"


# =========================================================================
# HELPER UNITS
# =========================================================================


class TestSanitizeOriginalName:
    @pytest.mark.parametrize("raw,expected", [
        ("chart.png", "chart.png"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\evil.txt", "evil.txt"),
        ("/absolute/path/file.pdf", "file.pdf"),
        ('quote"inject.png', "quoteinject.png"),
        ("line\r\nbreak.png", "linebreak.png"),
        ("", "upload"),
        (None, "upload"),
        ("...", "upload"),
    ])
    def test_reduces_to_a_bare_label(self, raw, expected):
        assert sanitize_original_name(raw) == expected

    def test_length_is_bounded(self):
        assert len(sanitize_original_name("a" * 5000)) == 255

    def test_unicode_survives(self):
        assert sanitize_original_name("гра́фик.png") == "гра́фик.png"


class TestContentDisposition:
    def test_images_render_inline(self):
        assert content_disposition("image", "chart.png").startswith("inline")

    def test_video_renders_inline(self):
        assert content_disposition("video", "clip.mp4").startswith("inline")

    def test_files_download(self):
        assert content_disposition("file", "notes.txt").startswith("attachment")

    def test_unicode_name_is_percent_encoded_in_the_star_form(self):
        header = content_disposition("file", "гра.txt")
        assert "filename*=UTF-8''" in header
        assert "%D0%B3" in header
        # The plain form stays ASCII so a naive parser cannot break the header.
        plain = header.split('filename="')[1].split('"')[0]
        assert plain.isascii()


class TestNormalizeMime:
    @pytest.mark.parametrize("raw,expected", [
        ("image/PNG", "image/png"),
        ("image/jpeg; charset=binary", "image/jpeg"),
        ("image/jpg", "image/jpeg"),
        ("application/x-zip-compressed", "application/zip"),
        (None, None),
        ("", None),
    ])
    def test_normalizes(self, raw, expected):
        assert normalize_mime(raw) == expected

    def test_every_policy_value_has_a_kind_and_dotted_extension(self):
        for mime, (kind, ext) in MIME_POLICY.items():
            assert kind in ("image", "video", "file"), mime
            assert ext.startswith(".") and "/" not in ext and ".." not in ext, mime


class TestSniffImageMime:
    def test_detects_real_files(self):
        assert sniff_image_mime(make_png()) == "image/png"
        assert sniff_image_mime(make_gif()) == "image/gif"
        assert sniff_image_mime(make_jpeg_header()) == "image/jpeg"
        assert sniff_image_mime(make_webp_lossless()) == "image/webp"

    @pytest.mark.parametrize("payload", [
        b"MZ\x90\x00",                       # PE executable
        b"\x7fELF",                          # ELF
        b"<svg xmlns='x'/>",                 # script-capable markup
        b"<!DOCTYPE html><html></html>",
        b"",
        b"PK\x03\x04",                       # zip
    ])
    def test_rejects_non_images(self, payload):
        assert sniff_image_mime(payload) is None


class TestImageDimensions:
    def test_png(self):
        assert image_dimensions(make_png(13, 7), "image/png") == (13, 7)

    def test_gif(self):
        assert image_dimensions(make_gif(21, 3), "image/gif") == (21, 3)

    def test_jpeg(self):
        assert image_dimensions(make_jpeg_header(1920, 1080), "image/jpeg") == (1920, 1080)

    def test_webp_lossless(self):
        assert image_dimensions(make_webp_lossless(300, 200), "image/webp") == (300, 200)

    def test_truncated_header_yields_none_rather_than_raising(self):
        assert image_dimensions(make_png()[:12], "image/png") == (None, None)
        assert image_dimensions(b"\xff\xd8\xff", "image/jpeg") == (None, None)
        assert image_dimensions(b"RIFF\x00\x00\x00\x00WEBP", "image/webp") == (None, None)

    def test_non_image_mime_yields_none(self):
        assert image_dimensions(make_png(), "application/pdf") == (None, None)

    def test_zero_dimensions_are_treated_as_unknown(self):
        blank = b"GIF89a" + struct.pack("<HH", 0, 0) + b"\x80\x00\x00"
        assert image_dimensions(blank, "image/gif") == (None, None)


class TestCapSeam:
    def test_defaults(self, monkeypatch):
        for var in ("MEDIA_MAX_IMAGE_BYTES", "MEDIA_MAX_FILE_BYTES",
                    "MEDIA_MAX_VIDEO_BYTES"):
            monkeypatch.delenv(var, raising=False)
        assert max_bytes_for_kind("image") == 25 * 1024 * 1024
        assert max_bytes_for_kind("file") == 25 * 1024 * 1024
        assert max_bytes_for_kind("video") == 300 * 1024 * 1024

    def test_env_overrides_are_read_at_call_time(self, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", "7")
        assert max_bytes_for_kind("image") == 7
        monkeypatch.setenv("MEDIA_MAX_IMAGE_BYTES", "9")
        assert max_bytes_for_kind("image") == 9

    def test_media_root_is_read_at_call_time(self, monkeypatch):
        monkeypatch.setenv("MEDIA_ROOT", "/tmp/one")
        assert attachments.media_root() == "/tmp/one"
        monkeypatch.setenv("MEDIA_ROOT", "/tmp/two")
        assert attachments.media_root() == "/tmp/two"

    def test_default_media_root(self, monkeypatch):
        monkeypatch.delenv("MEDIA_ROOT", raising=False)
        assert attachments.media_root() == "/var/lib/dialectic/media"


class TestLazyDirectoryCreation:
    def test_upload_creates_a_missing_media_root(self, ctx):
        """Deploy may not have made the volume; the first upload must not 500."""
        assert not os.path.exists(ctx.media_root)
        resp = upload(ctx, make_png(), "chart.png", "image/png")
        assert resp.status_code == 200
        assert os.path.isdir(ctx.media_root)
