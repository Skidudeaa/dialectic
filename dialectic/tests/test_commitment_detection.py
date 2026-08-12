"""
Contracts for the P4 residue: CommitmentDetector wired as PROPOSALS.

Detection is fire-and-forget from the send path and writes only chrome —
metadata.commitment_proposals on the source message plus a MESSAGE_METADATA
broadcast. The commitment itself is created only by the human's Accept,
which travels the ordinary create_commitment WS path carrying
proposal_index so the server stamps `accepted` (a reload must not re-arm
the button into a duplicate).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import transport.handlers as handlers_mod
from stakes.detector import CommitmentDetector
from transport.handlers import MessageHandler

ROOM_ID = uuid4()
MESSAGE_ID = uuid4()


class RecordingConnections:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, room_id, message):
        self.broadcasts.append((room_id, message))


def make_handler(db):
    connections = RecordingConnections()
    handler = MessageHandler(
        db=db,
        connection_manager=connections,
        memory_manager=SimpleNamespace(),
        llm_orchestrator=SimpleNamespace(),
    )
    return handler, connections


def make_message(content="I bet Brent closes above $95 by March"):
    return SimpleNamespace(
        id=MESSAGE_ID,
        content=content,
        speaker_type=SimpleNamespace(value="user"),
    )


class TestParseExtraction:
    def test_parses_structured_output(self):
        out = (
            "CLAIM: Brent closes above $95 by March\n"
            "CRITERIA: Brent front-month settle > 95 on any day before 2027-03-31\n"
            "CATEGORY: bet\n"
            "---\n"
            "CLAIM: Claims spike within a month\n"
            "CRITERIA: ICSA prints above 300k\n"
            "CATEGORY: prediction\n"
        )
        got = CommitmentDetector()._parse_extraction(out, make_message())
        assert len(got) == 2
        assert got[0]["claim"].startswith("Brent closes")
        assert got[0]["category"] == "bet"
        assert got[0]["source_message_id"] == str(MESSAGE_ID)

    def test_none_is_empty(self):
        assert CommitmentDetector()._parse_extraction("NONE", make_message()) == []

    def test_claim_without_criteria_is_dropped(self):
        out = "CLAIM: something vague\n---\n"
        assert CommitmentDetector()._parse_extraction(out, make_message()) == []

    def test_unknown_category_defaults_to_prediction(self):
        out = "CLAIM: X happens\nCRITERIA: X observed\nCATEGORY: vibes\n"
        got = CommitmentDetector()._parse_extraction(out, make_message())
        assert got[0]["category"] == "prediction"


@pytest.mark.asyncio
class TestTriggerGate:
    async def test_no_trigger_phrase_skips_the_llm(self, monkeypatch):
        detector = CommitmentDetector()

        async def boom(*a, **k):
            raise AssertionError("LLM must not be called without a trigger")

        monkeypatch.setattr(detector, "_extract_with_llm", boom)
        got = await detector.detect_commitments(
            make_message("nice weather today"), ROOM_ID
        )
        assert got == []


@pytest.mark.asyncio
class TestDetectionTask:
    async def test_hits_land_in_metadata_and_broadcast(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        handler, connections = make_handler(db)
        candidates = [
            {"claim": "Brent > $95 by March", "resolution_criteria": "settle > 95",
             "category": "bet", "source_message_id": str(MESSAGE_ID),
             "speaker_type": "user"},
        ]
        monkeypatch.setattr(
            handlers_mod.CommitmentDetector, "detect_commitments",
            AsyncMock(return_value=candidates),
        )

        await handler._detect_commitment_proposals(ROOM_ID, make_message())

        update_sql, mid, patch = (
            db.execute.await_args.args[0],
            db.execute.await_args.args[1],
            db.execute.await_args.args[2],
        )
        assert "commitment_proposals" not in update_sql  # patch carries the key
        assert mid == MESSAGE_ID
        proposals = patch["commitment_proposals"]
        assert proposals[0]["accepted"] is False
        assert proposals[0]["claim"] == "Brent > $95 by March"
        # Only the shaped fields travel — no speaker_type/source echo.
        assert set(proposals[0]) == {
            "claim", "resolution_criteria", "category", "accepted",
        }

        assert len(connections.broadcasts) == 1
        room, msg = connections.broadcasts[0]
        assert room == ROOM_ID
        assert msg.type == "message_metadata"
        assert msg.payload["message_id"] == str(MESSAGE_ID)

    async def test_no_hits_writes_nothing(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        handler, connections = make_handler(db)
        monkeypatch.setattr(
            handlers_mod.CommitmentDetector, "detect_commitments",
            AsyncMock(return_value=[]),
        )
        await handler._detect_commitment_proposals(ROOM_ID, make_message())
        db.execute.assert_not_awaited()
        assert connections.broadcasts == []

    async def test_detector_crash_is_contained(self, monkeypatch):
        """Fire-and-forget means a detector fault must die here, quietly."""
        db = SimpleNamespace(execute=AsyncMock())
        handler, connections = make_handler(db)
        monkeypatch.setattr(
            handlers_mod.CommitmentDetector, "detect_commitments",
            AsyncMock(side_effect=RuntimeError("provider down")),
        )
        await handler._detect_commitment_proposals(ROOM_ID, make_message())
        db.execute.assert_not_awaited()

    async def test_junk_candidates_are_filtered(self, monkeypatch):
        db = SimpleNamespace(execute=AsyncMock())
        handler, connections = make_handler(db)
        monkeypatch.setattr(
            handlers_mod.CommitmentDetector, "detect_commitments",
            AsyncMock(return_value=[{"claim": "", "resolution_criteria": ""}]),
        )
        await handler._detect_commitment_proposals(ROOM_ID, make_message())
        db.execute.assert_not_awaited()


class TestDetectionGate:
    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("COMMITMENT_DETECTION_ENABLED", raising=False)
        assert handlers_mod.commitment_detection_enabled() is True

    def test_off_values_disable(self, monkeypatch):
        for v in ("0", "false", "off", "no"):
            monkeypatch.setenv("COMMITMENT_DETECTION_ENABLED", v)
            assert handlers_mod.commitment_detection_enabled() is False
