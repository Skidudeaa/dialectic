"""The working surface's write path (2026-09-02): anchors and refs.

An ANCHOR is what a message is about on the causal graph; REFS are the
objects it used or attached. These tests pin the four places the slots
touch: the intake gate, the participant's prompt rendering, the tool
loop's lift of refs off a tool result, and the reply's anchor inheritance.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from llm.orchestrator import _hoisted_refs, _inherit_anchor
from llm.prompts import _anchor_prefix, _refs_suffix
from models import Message, MessageType, SpeakerType
from proposal_intake import (
    ProposalMetadataError,
    validate_anchor,
    validate_human_proposal_metadata,
    validate_refs,
)


def _msg(speaker: SpeakerType, metadata: dict | None = None) -> Message:
    return Message(
        thread_id=uuid4(), sequence=1, created_at=datetime.now(timezone.utc),
        speaker_type=speaker, user_id=uuid4() if speaker == SpeakerType.HUMAN else None,
        message_type=MessageType.TEXT, content="x", metadata=metadata,
    )


class TestIntakeGate:
    def test_anchor_is_reshaped_not_passed_through(self):
        out = validate_anchor({"kind": "node", "id": " n1 ", "label": "Hormuz Closure", "extra": 1})
        assert out == {"kind": "node", "id": "n1", "label": "Hormuz Closure"}

    @pytest.mark.parametrize("bad", [None, "node", {"kind": "planet", "id": "x", "label": "y"},
                                     {"kind": "node", "id": "", "label": "y"},
                                     {"kind": "edge", "id": "a->b", "label": ""}])
    def test_anchor_rejects_bad_shapes(self, bad):
        with pytest.raises(ProposalMetadataError):
            validate_anchor(bad)

    def test_refs_dedupe_and_require_uuid_for_rows(self):
        rid = str(uuid4())
        out = validate_refs([
            {"entity": "reading_items", "id": rid, "label": "FT"},
            {"entity": "reading_items", "id": rid, "label": "FT again"},
            {"entity": "thesis_node", "id": "hormuz_closure", "label": "Hormuz Closure"},
        ])
        assert [r["entity"] for r in out] == ["reading_items", "thesis_node"]
        with pytest.raises(ProposalMetadataError):
            validate_refs([{"entity": "reading_items", "id": "not-a-uuid", "label": "x"}])
        with pytest.raises(ProposalMetadataError):
            validate_refs([{"entity": "rooms", "id": str(uuid4()), "label": "x"}])
        with pytest.raises(ProposalMetadataError):
            validate_refs([])

    def test_rest_door_carries_both_slots(self):
        rid = str(uuid4())
        out = validate_human_proposal_metadata({
            "anchor": {"kind": "node", "id": "n1", "label": "N1"},
            "refs": [{"entity": "world_observations", "id": rid, "label": "fire"}],
            "tags": ["bug"],
        })
        assert out["anchor"]["id"] == "n1"
        assert out["refs"][0]["id"] == rid
        assert out["tags"] == ["bug"]


class TestPromptRendering:
    def test_anchor_prefix_and_refs_suffix_are_data(self):
        m = _msg(SpeakerType.HUMAN, {
            "anchor": {"kind": "node", "id": "n1", "label": "Hormuz Closure"},
            "refs": [{"entity": "reading_items", "id": "x", "label": "FT: tankers idle"},
                     {"entity": "thesis_node", "id": "n1", "label": "Hormuz Closure"}],
        })
        assert _anchor_prefix(m) == "[on Hormuz Closure] "
        assert _refs_suffix(m) == "\n(attached: FT: tankers idle; Hormuz Closure)"

    def test_no_metadata_renders_nothing(self):
        m = _msg(SpeakerType.HUMAN, None)
        assert _anchor_prefix(m) == "" and _refs_suffix(m) == ""


class TestHoistAndInherit:
    def test_hoisted_refs_dedupes_across_calls_and_caps(self):
        trace = [
            {"name": "search_reading", "ok": True, "refs": [{"entity": "reading_items", "id": "a", "label": "A"}]},
            {"name": "world_query", "ok": True, "refs": [
                {"entity": "reading_items", "id": "a", "label": "A dup"},
                *[{"entity": "world_observations", "id": f"o{i}", "label": f"O{i}"} for i in range(20)],
            ]},
        ]
        out = _hoisted_refs(trace)
        assert out[0] == {"entity": "reading_items", "id": "a", "label": "A"}
        assert len(out) == 12

    def test_reply_inherits_latest_human_anchor_only(self):
        anchored = _msg(SpeakerType.HUMAN, {"anchor": {"kind": "node", "id": "n1", "label": "N1"}})
        machine = _msg(SpeakerType.LLM_PRIMARY, None)
        assert _inherit_anchor(None, [anchored, machine]) == {"anchor": {"kind": "node", "id": "n1", "label": "N1"}}
        plain = _msg(SpeakerType.HUMAN, None)
        # A later human message without an anchor means the reply is about nothing in particular.
        assert _inherit_anchor({"tools": {}}, [anchored, plain]) == {"tools": {}}
        assert _inherit_anchor(None, []) is None


@pytest.mark.asyncio
async def test_tool_loop_lifts_refs_off_a_tool_result():
    from llm.tool_loop import ToolLoop
    from llm.tools import Tool, ToolRegistry

    async def execute(args: dict) -> dict:
        return {"count": 1, "refs": [{"entity": "memories", "id": "m1", "label": "key"}, "junk"]}

    registry = ToolRegistry([Tool(name="t", description="d", input_schema={"type": "object"}, execute=execute, label="testing")])
    loop = ToolLoop(router=SimpleNamespace(), registry=registry)
    call = SimpleNamespace(id="c1", name="t", input={})
    _block, entry, content = await loop._execute(call)
    assert entry["ok"] is True
    assert entry["refs"] == [{"entity": "memories", "id": "m1", "label": "key"}]
    assert "refs" in content
