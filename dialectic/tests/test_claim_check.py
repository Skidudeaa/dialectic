"""Contracts for the claim check: a human message linking an article gets a
background fairness verdict, and only `mixed`/`misrepresented` land — as a
metadata.claim_check patch on the source message plus a MESSAGE_METADATA
broadcast, the same shape commitment proposals use. Everything else
(supported links, no URL, non-human speakers, sidecar down, judge
unavailable) stays silent by design, and no failure may escape the task.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import llm.claim_check as cc
import llm.providers as providers_mod
from llm.defuddle_client import DefuddleError

ROOM_ID = uuid4()
MESSAGE_ID = uuid4()
URL = "https://example.com/fed-note"

ARTICLE = {
    "url": URL,
    "title": "The Fed's next move",
    "content": "The committee signalled that further tightening remains possible.",
}


def make_message(content=f"FOMC is done hiking, says this piece {URL}", speaker="human"):
    return SimpleNamespace(
        id=MESSAGE_ID,
        content=content,
        speaker_type=SimpleNamespace(value=speaker),
    )


class TestUrlExtraction:
    def test_first_url_wins(self):
        text = "see https://a.example/x and then https://b.example/y"
        assert cc.first_url(text) == "https://a.example/x"

    def test_no_url_means_no_check(self, monkeypatch):
        monkeypatch.delenv("CLAIM_CHECK_ENABLED", raising=False)
        assert cc._check_url(make_message("no links here")) is None


class TestGates:
    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("CLAIM_CHECK_ENABLED", raising=False)
        assert cc._check_url(make_message()) == URL

    def test_env_off_is_noop(self, monkeypatch):
        monkeypatch.setenv("CLAIM_CHECK_ENABLED", "0")
        assert cc._check_url(make_message()) is None

    def test_off_values_disable(self, monkeypatch):
        for v in ("0", "false", "no", "off"):
            monkeypatch.setenv("CLAIM_CHECK_ENABLED", v)
            assert cc.claim_check_enabled() is False

    def test_non_human_speaker_skips(self, monkeypatch):
        monkeypatch.delenv("CLAIM_CHECK_ENABLED", raising=False)
        for speaker in ("llm_primary", "llm_annotator", "system"):
            assert cc._check_url(make_message(speaker=speaker)) is None


class TestParseVerdict:
    def test_parses_strict_json(self):
        got = cc._parse_verdict('{"verdict": "misrepresented", "note": "Says the opposite."}')
        assert got == {"verdict": "misrepresented", "note": "Says the opposite."}

    def test_tolerates_a_code_fence(self):
        got = cc._parse_verdict('```json\n{"verdict": "mixed", "note": "Overstated."}\n```')
        assert got == {"verdict": "mixed", "note": "Overstated."}

    def test_junk_returns_none(self):
        assert cc._parse_verdict("I think it's mixed") is None
        assert cc._parse_verdict('{"verdict": "banana", "note": "x"}') is None
        assert cc._parse_verdict('["mixed"]') is None


@pytest.mark.asyncio
class TestJudge:
    async def test_provider_failure_degrades_to_none(self, monkeypatch):
        """No API key / provider down must be silence, not an exception."""
        monkeypatch.setattr(
            providers_mod, "get_provider",
            lambda name: SimpleNamespace(
                complete=AsyncMock(side_effect=RuntimeError("no key"))),
        )
        assert await cc._judge_claim("text", ARTICLE) is None

    async def test_article_body_is_capped(self, monkeypatch):
        captured = {}

        async def complete(request):
            captured["request"] = request
            return SimpleNamespace(content='{"verdict": "supported", "note": ""}')

        monkeypatch.setattr(
            providers_mod, "get_provider",
            lambda name: SimpleNamespace(complete=complete),
        )
        big = {"url": URL, "title": "T", "content": "x" * 9000}
        got = await cc._judge_claim("text", big)
        assert got == {"verdict": "supported", "note": ""}
        prompt = captured["request"].messages[0]["content"]
        assert "x" * cc.ARTICLE_BODY_CAP in prompt
        assert "x" * (cc.ARTICLE_BODY_CAP + 1) not in prompt

    async def test_empty_body_never_calls_the_provider(self, monkeypatch):
        monkeypatch.setattr(
            providers_mod, "get_provider",
            lambda name: SimpleNamespace(
                complete=AsyncMock(side_effect=AssertionError("must not run"))),
        )
        assert await cc._judge_claim("text", {"url": URL, "content": "  "}) is None


@pytest.mark.asyncio
class TestClaimCheckFlow:
    async def test_sidecar_down_is_silent(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        broadcast = AsyncMock()
        monkeypatch.setattr(
            cc.dc, "extract_article",
            AsyncMock(side_effect=DefuddleError("sidecar unreachable")),
        )
        monkeypatch.setattr(
            cc, "_judge_claim",
            AsyncMock(side_effect=AssertionError("judge must not run")),
        )
        await cc.run_claim_check(
            room_id=ROOM_ID, message_id=MESSAGE_ID, text="t", url=URL,
            db=db, db_pool=None, broadcast=broadcast,
        )
        db.execute.assert_not_awaited()
        broadcast.assert_not_awaited()

    async def test_supported_verdict_writes_nothing(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        broadcast = AsyncMock()
        monkeypatch.setattr(cc.dc, "extract_article", AsyncMock(return_value=ARTICLE))
        monkeypatch.setattr(
            cc, "_judge_claim",
            AsyncMock(return_value={"verdict": "supported", "note": ""}),
        )
        await cc.run_claim_check(
            room_id=ROOM_ID, message_id=MESSAGE_ID, text="t", url=URL,
            db=db, db_pool=None, broadcast=broadcast,
        )
        db.execute.assert_not_awaited()
        broadcast.assert_not_awaited()

    async def test_mixed_patches_metadata_and_broadcasts(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        broadcast = AsyncMock()
        monkeypatch.setattr(cc.dc, "extract_article", AsyncMock(return_value=ARTICLE))
        monkeypatch.setattr(
            cc, "_judge_claim",
            AsyncMock(return_value={
                "verdict": "mixed",
                "note": "The piece says hikes may continue.",
            }),
        )
        await cc.run_claim_check(
            room_id=ROOM_ID, message_id=MESSAGE_ID, text="FOMC done", url=URL,
            db=db, db_pool=None, broadcast=broadcast,
        )

        sql, mid, patch = db.execute.await_args.args
        assert "claim_check" not in sql  # the patch carries the key
        assert mid == MESSAGE_ID
        assert patch == {
            "claim_check": {
                "url": URL,
                "title": "The Fed's next move",
                "verdict": "mixed",
                "note": "The piece says hikes may continue.",
            }
        }

        room, msg = broadcast.await_args.args
        assert room == ROOM_ID
        assert msg.type == "message_metadata"
        assert msg.payload["message_id"] == str(MESSAGE_ID)
        assert msg.payload["metadata_patch"] == patch

    async def test_unexpected_fault_is_contained(self, monkeypatch):
        """Fire-and-forget means a fault must die inside the task, quietly."""
        db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db gone")))
        broadcast = AsyncMock()
        monkeypatch.setattr(cc.dc, "extract_article", AsyncMock(return_value=ARTICLE))
        monkeypatch.setattr(
            cc, "_judge_claim",
            AsyncMock(return_value={"verdict": "misrepresented", "note": "n"}),
        )
        await cc.run_claim_check(
            room_id=ROOM_ID, message_id=MESSAGE_ID, text="t", url=URL,
            db=db, db_pool=None, broadcast=broadcast,
        )
        broadcast.assert_not_awaited()

    async def test_pool_path_acquires_its_own_connection(self, monkeypatch):
        """The production branch: the detached task must NOT use the
        per-message connection (it is already back in the pool by then)."""
        pool_conn = SimpleNamespace(execute=AsyncMock())

        class FakeAcquire:
            async def __aenter__(self):
                return pool_conn

            async def __aexit__(self, *exc):
                return False

        pool = SimpleNamespace(acquire=lambda: FakeAcquire())
        stale_conn = SimpleNamespace(
            execute=AsyncMock(side_effect=AssertionError(
                "detached task used the released per-message connection"))
        )
        broadcast = AsyncMock()
        monkeypatch.setattr(cc.dc, "extract_article", AsyncMock(return_value=ARTICLE))
        monkeypatch.setattr(
            cc, "_judge_claim",
            AsyncMock(return_value={"verdict": "mixed", "note": "n"}),
        )
        await cc.run_claim_check(
            room_id=ROOM_ID, message_id=MESSAGE_ID, text="t", url=URL,
            db=stale_conn, db_pool=pool, broadcast=broadcast,
        )
        pool_conn.execute.assert_awaited_once()
        stale_conn.execute.assert_not_awaited()
        broadcast.assert_awaited_once()


@pytest.mark.asyncio
class TestSchedule:
    async def test_gated_message_spawns_the_task(self, monkeypatch):
        monkeypatch.delenv("CLAIM_CHECK_ENABLED", raising=False)
        run = AsyncMock()
        monkeypatch.setattr(cc, "run_claim_check", run)
        cc.schedule_claim_check(
            room_id=ROOM_ID, message=make_message(),
            db=None, db_pool=None, broadcast=AsyncMock(),
        )
        await asyncio.sleep(0)  # let the detached task run
        run.assert_awaited_once()
        assert run.await_args.kwargs["url"] == URL
        assert run.await_args.kwargs["message_id"] == MESSAGE_ID

    async def test_ungated_message_spawns_nothing(self, monkeypatch):
        monkeypatch.delenv("CLAIM_CHECK_ENABLED", raising=False)
        run = AsyncMock()
        monkeypatch.setattr(cc, "run_claim_check", run)
        cc.schedule_claim_check(
            room_id=ROOM_ID, message=make_message("plain text, no link"),
            db=None, db_pool=None, broadcast=AsyncMock(),
        )
        await asyncio.sleep(0)
        run.assert_not_called()
