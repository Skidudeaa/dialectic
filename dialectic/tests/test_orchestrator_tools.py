"""The orchestrator's streaming path when tools are in play.

Covers the wiring only — ToolLoop's own behaviour is pinned in
tests/test_tool_loop.py, and the tools themselves in test_tools_registry.py.
What can only break here: which turns get a registry at all, how loop events
become upward events, and whether the trace survives to the database.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import llm.orchestrator as orchestrator_mod
import operations as operations_mod
from llm.heuristics import InterjectionDecision
from llm.orchestrator import LLMOrchestrator
from llm.prompts import AssembledPrompt
from llm.tools import Tool, ToolRegistry
from models import Message, MessageType, SpeakerType
from tests.conftest import make_room, make_thread
# The non-streaming loop path is exercised with the ToolLoop-layer router
# fixture (scripted route() calls), not the streaming one defined below.
from tests.test_tool_loop import (
    FakeRouter as LoopRouter,
    ok as loop_ok,
    text_response,
    tool_use_response,
)
from transport.handlers import MessageHandler
from transport.websocket import Connection, MessageTypes


# ── scriptable transports ────────────────────────────────────────────


class FakeRouter:
    """Both router surfaces, scripted: stream() for the plain path,
    stream_events() for the tool loop."""

    def __init__(self, event_scripts=None, tokens=("hello",)):
        self.event_scripts = list(event_scripts or [])
        self.tokens = list(tokens)
        self.stream_calls = 0
        self.stream_event_calls = 0

    async def stream(self, _request):
        self.stream_calls += 1
        yield "attempt", {"provider": "anthropic", "model": "claude-sonnet-5"}
        for token in self.tokens:
            yield "token", {"token": token}

    async def stream_events(self, _request):
        self.stream_event_calls += 1
        assert self.event_scripts, "stream_events() called more times than scripted"
        for event in self.event_scripts.pop(0):
            yield event


def tool_script(name, payload, text=""):
    """One iteration that asks for a tool."""
    events = []
    raw = []
    if text:
        events.append(("text", {"text": text}))
        raw.append({"type": "text", "text": text})
    events.append(("tool_use", {"id": "toolu_0", "name": name, "input": payload}))
    raw.append({"type": "tool_use", "id": "toolu_0", "name": name, "input": payload})
    events.append(("message_stop", {"stop_reason": "tool_use", "raw_content": raw}))
    return events


def text_script(*chunks):
    events = [("text", {"text": chunk}) for chunk in chunks]
    events.append(("message_stop", {
        "stop_reason": "end_turn",
        "raw_content": [{"type": "text", "text": "".join(chunks)}],
    }))
    return events


def fake_registry():
    async def quotes(args):
        return {"symbol": args.get("symbol", "XOP"), "price": 41.2}

    async def boom(args):
        raise RuntimeError("tradingDesk is on fire")

    return ToolRegistry(tools=[
        Tool(name="get_live_quotes", description="d", label="checking live prices",
             input_schema={"type": "object", "properties": {}}, execute=quotes),
        Tool(name="boom_tool", description="d", label="failing",
             input_schema={"type": "object", "properties": {}}, execute=boom),
    ])


def persisted_message(thread_id):
    return Message(
        id=uuid4(),
        thread_id=thread_id,
        sequence=7,
        created_at=datetime.now(timezone.utc),
        speaker_type=SpeakerType.LLM_PRIMARY,
        user_id=None,
        message_type=MessageType.TEXT,
        content="XOP is 41.2",
    )


def make_orchestrator(router, monkeypatch, registry=None, db=None):
    """An orchestrator whose every collaborator except the code under test is
    scripted. build_registry is patched so no test can reach tradingDesk."""
    monkeypatch.setattr(
        orchestrator_mod, "build_registry",
        lambda room, db_conn: registry if registry is not None else fake_registry(),
    )
    orch = LLMOrchestrator(db if db is not None else SimpleNamespace())
    orch._get_cross_session_context = AsyncMock(return_value=None)
    orch._get_identity_context = AsyncMock(return_value=(None, None))
    orch.prompt_builder.build = MagicMock(return_value=AssembledPrompt("system", []))
    orch._get_router = MagicMock(return_value=router)
    orch._schedule_self_memory_extraction = MagicMock()
    return orch


async def run_stream(orch, thread, use_provoker=False):
    return [
        event
        async for event in orch.stream_response(
            room=make_room(), thread=thread, users=[], messages=[], memories=[],
            use_provoker=use_provoker,
        )
    ]


# ── on_message (non-streaming) helpers ───────────────────────────────


def interject(use_provoker=False):
    return InterjectionDecision(
        should_interject=True, reason="mentioned", confidence=1.0,
        use_provoker=use_provoker,
    )


async def run_on_message(orch, thread, use_provoker=False, protocol=None):
    """Drive on_message with heuristics pinned to 'speak' so the only
    variable under test is the tool wiring."""
    orch.heuristics.decide = MagicMock(return_value=interject(use_provoker))
    return await orch.on_message(
        room=make_room(), thread=thread, users=[], messages=[], memories=[],
        mentioned=True, protocol=protocol,
    )


# ── which turns get tools ────────────────────────────────────────────


class TestToolGate:
    @pytest.mark.asyncio
    async def test_primary_turn_routes_through_the_tool_loop(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[text_script("thinking out loud")])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread)

        assert router.stream_event_calls == 1
        assert router.stream_calls == 0
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is True

    @pytest.mark.asyncio
    async def test_provoker_never_gets_tools(self, monkeypatch):
        """A 1-3 sentence interruption cannot afford a 20s quote check."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter()
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread, use_provoker=True)

        assert router.stream_calls == 1
        assert router.stream_event_calls == 0
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is False

    def test_protocol_turn_never_gets_tools(self, monkeypatch):
        """The facilitator is neutral on substance — fetching evidence is out of role."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        orch = make_orchestrator(FakeRouter(), monkeypatch)
        protocol = SimpleNamespace(id=uuid4(), current_phase=1)
        assert orch._tool_registry_for(make_room(), use_provoker=False, protocol=protocol) is None
        # …and the same room DOES get them on an ordinary turn, so the assertion
        # above is about the protocol and not about the room.
        assert orch._tool_registry_for(make_room(), use_provoker=False) is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF"])
    async def test_env_kill_switch_takes_the_plain_path(self, monkeypatch, value):
        monkeypatch.setenv("DIALECTIC_TOOLS_ENABLED", value)
        thread = make_thread()
        router = FakeRouter()
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread)

        assert router.stream_calls == 1
        assert router.stream_event_calls == 0
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is False

    @pytest.mark.asyncio
    async def test_unset_env_means_on(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        assert orchestrator_mod.tools_enabled() is True

    @pytest.mark.asyncio
    async def test_empty_registry_takes_the_plain_path(self, monkeypatch):
        """A room with no tools available must not pay for the loop."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter()
        orch = make_orchestrator(router, monkeypatch, registry=ToolRegistry(tools=[]))
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread)

        assert router.stream_calls == 1
        assert router.stream_event_calls == 0

    # ── on_message: the same gate on the non-streaming path ─────────

    @pytest.mark.asyncio
    async def test_on_message_primary_turn_routes_through_the_tool_loop(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("thinking out loud"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_on_message(orch, thread)

        assert len(router.requests) == 1
        assert router.requests[0].tools is not None
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is True

    @pytest.mark.asyncio
    async def test_on_message_provoker_turn_stays_plain(self, monkeypatch):
        """The gate is mode-based, not path-based: provoker heuristics still
        get no tools when the turn comes through on_message."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("a quick jab"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_on_message(orch, thread, use_provoker=True)

        assert len(router.requests) == 1
        assert router.requests[0].tools is None
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is False

    @pytest.mark.asyncio
    async def test_on_message_protocol_turn_stays_plain(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("phase one opens"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        protocol = SimpleNamespace(id=uuid4(), current_phase=1)

        await run_on_message(orch, thread, protocol=protocol)

        assert len(router.requests) == 1
        assert router.requests[0].tools is None
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is False

    @pytest.mark.asyncio
    async def test_on_message_kill_switch_takes_the_plain_path(self, monkeypatch):
        monkeypatch.setenv("DIALECTIC_TOOLS_ENABLED", "off")
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("plain answer"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_on_message(orch, thread)

        assert len(router.requests) == 1
        assert router.requests[0].tools is None
        assert orch.prompt_builder.build.call_args.kwargs["tools_enabled"] is False


# ── events and trace ─────────────────────────────────────────────────


class TestToolActivityEvents:
    @pytest.mark.asyncio
    async def test_started_then_finished_reach_the_transport(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("get_live_quotes", {"symbol": "XOP"}, text="let me check. "),
            text_script("XOP is 41.2"),
        ])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)
        activity = [data for kind, data in events if kind == "tool_activity"]

        assert [a["status"] for a in activity] == ["started", "finished"]
        assert all(a["tool"] == "get_live_quotes" for a in activity)
        # The label survives onto BOTH events — tool_result carries none.
        assert all(a["label"] == "checking live prices" for a in activity)
        assert activity[0]["latency_ms"] is None
        assert isinstance(activity[1]["latency_ms"], int)

        # Preamble and answer are one message, streamed in order.
        tokens = "".join(d["token"] for k, d in events if k == "streaming")
        assert tokens == "let me check. XOP is 41.2"

    @pytest.mark.asyncio
    async def test_failed_tool_is_reported_as_failed(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("boom_tool", {}),
            text_script("I could not check that"),
        ])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)
        activity = [data for kind, data in events if kind == "tool_activity"]
        assert [a["status"] for a in activity] == ["started", "failed"]

    @pytest.mark.asyncio
    async def test_midstream_death_becomes_an_error_event_not_an_exception(self, monkeypatch):
        """ToolLoop re-raises after the first token; the room still gets told."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()

        class DyingRouter(FakeRouter):
            async def stream_events(self, _request):
                self.stream_event_calls += 1
                yield ("text", {"text": "half an answ"})
                raise RuntimeError("stream died mid-flight")

        router = DyingRouter()
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)
        kind, data = events[-1]
        assert kind == "error"
        assert "mid-flight" in data["error"]
        assert data["partial_content"] == "half an answ"
        orch._persist_response.assert_not_awaited()


class TestTracePersistence:
    @pytest.mark.asyncio
    async def test_trace_is_persisted_and_echoed_on_done(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("get_live_quotes", {"symbol": "XOP"}),
            text_script("XOP is 41.2"),
        ])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)

        metadata = orch._persist_response.call_args.kwargs["metadata"]
        assert set(metadata) == {"tools"}
        tools = metadata["tools"]
        assert tools["iterations"] == 2
        assert tools["degraded"] is False
        assert len(tools["calls"]) == 1
        call = tools["calls"][0]
        assert call["name"] == "get_live_quotes"
        assert call["ok"] is True
        assert call["input"] == {"symbol": "XOP"}
        assert call["label"] == "checking live prices"
        assert isinstance(call["latency_ms"], int)

        done = next(data for kind, data in events if kind == "done")
        assert done["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_no_metadata_when_no_tool_ran(self, monkeypatch):
        """'used 0 tools' is not a thing to render — the key stays absent."""
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[text_script("no check needed")])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)

        assert orch._persist_response.call_args.kwargs["metadata"] is None
        done = next(data for kind, data in events if kind == "done")
        assert done["metadata"] is None

    @pytest.mark.asyncio
    async def test_failed_call_carries_its_error_into_the_trace(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("boom_tool", {}),
            text_script("could not check"),
        ])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread)

        call = orch._persist_response.call_args.kwargs["metadata"]["tools"]["calls"][0]
        assert call["ok"] is False
        assert "tradingDesk is on fire" in call["error"]

    @pytest.mark.asyncio
    async def test_persist_response_writes_metadata_to_the_insert(self):
        """The real method against a recording connection — the column has to be
        in the statement AND the dict has to be bound to it."""
        recorded = {}

        class RecordingDB:
            async def fetchrow(self, sql, *args):
                recorded["sql"] = sql
                recorded["args"] = args
                return {"sequence": 3}

            async def execute(self, *args):
                return None

        thread = make_thread()
        orch = LLMOrchestrator(RecordingDB())
        trace = {"tools": {"iterations": 2, "degraded": False, "calls": [
            {"name": "get_live_quotes", "ok": True, "latency_ms": 812},
        ]}}

        message = await orch._persist_response(
            thread=thread,
            content="XOP is 41.2",
            speaker_type=SpeakerType.LLM_PRIMARY,
            model_used="claude-sonnet-5",
            prompt_hash="abc",
            token_count=0,
            metadata=trace,
        )

        assert "metadata" in recorded["sql"]
        # Bound as a dict, not a JSON string: the pool's JSONB codec does the
        # encoding, and pre-serializing here would double-encode it.
        assert trace in recorded["args"]
        assert message.metadata == trace

    @pytest.mark.asyncio
    async def test_persist_response_without_metadata_binds_none(self):
        recorded = {}

        class RecordingDB:
            async def fetchrow(self, sql, *args):
                recorded["args"] = args
                return {"sequence": 4}

            async def execute(self, *args):
                return None

        orch = LLMOrchestrator(RecordingDB())
        await orch._persist_response(
            thread=make_thread(),
            content="plain answer",
            speaker_type=SpeakerType.LLM_PRIMARY,
            model_used="claude-sonnet-5",
            prompt_hash="abc",
            token_count=0,
        )
        assert recorded["args"][-1] is None


class TestNonStreamingTracePersistence:
    """on_message must persist the same trace shape the streaming path does,
    and hand it to the self-model's decision log."""

    @pytest.mark.asyncio
    async def test_trace_is_persisted_and_logged_with_the_decision(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[
            loop_ok(tool_use_response([("get_live_quotes", {"symbol": "XOP"})],
                                      text="let me look")),
            loop_ok(text_response("XOP is 41.2")),
        ])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        orch._self_model.log_decision = AsyncMock(return_value=42)

        result = await run_on_message(orch, thread)

        metadata = orch._persist_response.call_args.kwargs["metadata"]
        assert set(metadata) == {"tools"}
        tools = metadata["tools"]
        assert tools["iterations"] == 2
        assert tools["degraded"] is False
        assert len(tools["calls"]) == 1
        call = tools["calls"][0]
        assert call["name"] == "get_live_quotes"
        assert call["ok"] is True
        assert call["input"] == {"symbol": "XOP"}
        assert call["label"] == "checking live prices"
        assert isinstance(call["latency_ms"], int)

        # The self-model sees the same label-stamped trace on the decision row.
        assert orch._self_model.log_decision.call_args.kwargs["tool_calls"] == tools["calls"]
        assert result.routing.response.content == "XOP is 41.2"

    @pytest.mark.asyncio
    async def test_no_metadata_and_no_tool_calls_when_no_tool_ran(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("no check needed"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        orch._self_model.log_decision = AsyncMock(return_value=42)

        await run_on_message(orch, thread)

        # The loop ran (tools were offered) but the model never asked for one.
        assert router.requests[0].tools is not None
        assert orch._persist_response.call_args.kwargs["metadata"] is None
        assert orch._self_model.log_decision.call_args.kwargs["tool_calls"] is None


# ── prediction proposal hoisting ─────────────────────────────


def draft_registry():
    """A registry whose draft_prediction returns provenance like the real
    executor — the hoisting reads the trace entry's input, not the result."""
    async def draft(args):
        return {"proposal": {**args}, "provenance": {"kind": "prediction_draft"}}

    return ToolRegistry(tools=[
        Tool(name="draft_prediction", description="d", label="drafting a prediction",
             input_schema={"type": "object", "properties": {}}, execute=draft),
    ])


DRAFT_INPUT = {"statement": "Brent closes above $90 by end of Q3",
               "confidence": 0.7, "deadline": "2026-09-30"}


class TestProposalHoisting:
    """A prediction draft rides the trace into metadata.proposal — the Accept
    button renders off that key, on BOTH the streaming and on_message paths."""

    @pytest.mark.asyncio
    async def test_streaming_path_hoists_the_proposal(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("draft_prediction", DRAFT_INPUT),
            text_script("drafted it — Brent above 90 by Q3"),
        ])
        orch = make_orchestrator(router, monkeypatch, registry=draft_registry())
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        events = await run_stream(orch, thread)

        metadata = orch._persist_response.call_args.kwargs["metadata"]
        assert set(metadata) == {"tools", "proposal"}
        assert metadata["proposal"] == {**DRAFT_INPUT, "accepted": False}
        done = next(data for kind, data in events if kind == "done")
        assert done["metadata"]["proposal"] == metadata["proposal"]

    @pytest.mark.asyncio
    async def test_non_streaming_path_hoists_the_proposal(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[
            loop_ok(tool_use_response([("draft_prediction", DRAFT_INPUT)])),
            loop_ok(text_response("drafted it")),
        ])
        orch = make_orchestrator(router, monkeypatch, registry=draft_registry())
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        orch._self_model.log_decision = AsyncMock(return_value=42)

        await run_on_message(orch, thread)

        metadata = orch._persist_response.call_args.kwargs["metadata"]
        assert set(metadata) == {"tools", "proposal"}
        assert metadata["proposal"] == {**DRAFT_INPUT, "accepted": False}

    @pytest.mark.asyncio
    async def test_failed_draft_is_not_hoisted(self, monkeypatch):
        """A draft whose executor blew up carries an error, not a proposal."""
        async def boom(args):
            raise RuntimeError("validator exploded")

        registry = ToolRegistry(tools=[
            Tool(name="draft_prediction", description="d", label="drafting a prediction",
                 input_schema={"type": "object", "properties": {}}, execute=boom),
        ])
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = FakeRouter(event_scripts=[
            tool_script("draft_prediction", DRAFT_INPUT),
            text_script("could not draft that"),
        ])
        orch = make_orchestrator(router, monkeypatch, registry=registry)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))

        await run_stream(orch, thread)

        metadata = orch._persist_response.call_args.kwargs["metadata"]
        assert set(metadata) == {"tools"}


# ── transport forwarding ─────────────────────────────────────────────


class RecordingConnections:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, room_id, message, exclude_user=None):
        self.broadcasts.append(message)

    async def send_to_user(self, user_id, room_id, message):
        return True


def scripted_llm(thread_id, metadata=None):
    """An orchestrator stand-in that emits one of every stream event."""
    async def stream_response(**_kwargs):
        yield ("thinking", {})
        yield ("tool_activity", {
            "tool": "get_live_quotes", "label": "checking live prices",
            "status": "started", "latency_ms": None,
        })
        yield ("streaming", {"token": "XOP is 41.2", "index": 0})
        yield ("tool_activity", {
            "tool": "get_live_quotes", "label": "checking live prices",
            "status": "finished", "latency_ms": 812,
        })
        yield ("done", {
            "message_id": str(uuid4()),
            "content": "XOP is 41.2",
            "model_used": "claude-sonnet-5",
            "truncated": False,
            "sequence": 7,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "speaker_type": SpeakerType.LLM_PRIMARY.value,
            "message_type": MessageType.TEXT.value,
            "metadata": metadata,
        })

    return SimpleNamespace(stream_response=stream_response)


def types_of(broadcasts):
    return [message.type for message in broadcasts]


TRACE = {"tools": {"iterations": 2, "degraded": False, "calls": [
    {"name": "get_live_quotes", "ok": True, "latency_ms": 812,
     "label": "checking live prices", "input": {}},
]}}


class TestSummonCallSiteForwarding:
    """_stream_llm_response — the /summon and stop-button path."""

    @pytest.mark.asyncio
    async def test_tool_activity_and_metadata_are_broadcast(self):
        thread = make_thread()
        connections = RecordingConnections()
        handler = MessageHandler(
            db=SimpleNamespace(),
            connection_manager=connections,
            memory_manager=SimpleNamespace(),
            llm_orchestrator=scripted_llm(thread.id, metadata=TRACE),
        )
        conn = Connection(
            websocket=SimpleNamespace(), user_id=uuid4(),
            room_id=thread.room_id, thread_id=thread.id,
        )

        await handler._stream_llm_response(
            conn, thread.id, make_room(), thread, [], [], [], False,
        )

        assert types_of(connections.broadcasts) == [
            MessageTypes.LLM_THINKING,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_STREAMING,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_DONE,
        ]

        started, finished = [
            m.payload for m in connections.broadcasts
            if m.type == MessageTypes.LLM_TOOL_ACTIVITY
        ]
        assert started == {
            "thread_id": str(thread.id), "tool": "get_live_quotes",
            "label": "checking live prices", "status": "started",
        }
        assert finished["status"] == "finished"
        assert finished["latency_ms"] == 812

        done = connections.broadcasts[-1].payload
        assert done["metadata"] == TRACE

    @pytest.mark.asyncio
    async def test_llm_done_omits_metadata_when_no_tool_ran(self):
        thread = make_thread()
        connections = RecordingConnections()
        handler = MessageHandler(
            db=SimpleNamespace(),
            connection_manager=connections,
            memory_manager=SimpleNamespace(),
            llm_orchestrator=scripted_llm(thread.id, metadata=None),
        )
        conn = Connection(
            websocket=SimpleNamespace(), user_id=uuid4(),
            room_id=thread.room_id, thread_id=thread.id,
        )

        await handler._stream_llm_response(
            conn, thread.id, make_room(), thread, [], [], [], False,
        )
        assert "metadata" not in connections.broadcasts[-1].payload


class TestMentionCallSiteForwarding:
    """_trigger_llm's streaming branch — the '@claude' path, a different
    call site that has drifted from the one above before."""

    @pytest.mark.asyncio
    async def test_tool_activity_and_metadata_are_broadcast(self, monkeypatch):
        thread = make_thread()
        room = make_room()
        connections = RecordingConnections()

        db = SimpleNamespace(
            fetchrow=AsyncMock(side_effect=[room.model_dump(), thread.model_dump()]),
            fetch=AsyncMock(return_value=[]),
        )
        memory = SimpleNamespace(get_context_for_prompt=AsyncMock(return_value=[]))
        handler = MessageHandler(
            db=db,
            connection_manager=connections,
            memory_manager=memory,
            llm_orchestrator=scripted_llm(thread.id, metadata=TRACE),
        )
        handler._trigger_push_notifications = AsyncMock()
        monkeypatch.setattr(operations_mod, "get_thread_messages", AsyncMock(return_value=[]))

        await handler._trigger_llm(
            room.id, thread.id, mentioned=True, semantic_novelty=0.5,
        )

        assert types_of(connections.broadcasts) == [
            MessageTypes.LLM_THINKING,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_STREAMING,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_DONE,
        ]
        assert connections.broadcasts[-1].payload["metadata"] == TRACE


# ── force_response: self-aware + logged, no tools ────────────────────


class TestForceResponseSelfModel:
    """The sweep (W6) calls force_response for its follow-ups, so a forced
    turn must know itself and land in the decision log — but the gate still
    keeps tools off every mode that comes through here."""

    @pytest.mark.asyncio
    async def test_forced_turn_is_self_aware_and_logged(self, monkeypatch):
        monkeypatch.delenv("DIALECTIC_TOOLS_ENABLED", raising=False)
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("following up"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        orch._self_model.get_participation_snapshot = AsyncMock(return_value=object())
        orch._self_model.render_self_awareness = MagicMock(
            return_value="YOU HAVE SPOKEN 3 TIMES")
        orch._self_model.log_decision = AsyncMock(return_value=7)

        result = await orch.force_response(
            room=make_room(), thread=thread, users=[], messages=[], memories=[],
            reason="silence_follow_up",
        )

        assert result.decision.reason == "silence_follow_up"
        build_kwargs = orch.prompt_builder.build.call_args.kwargs
        assert build_kwargs["self_awareness"] == "YOU HAVE SPOKEN 3 TIMES"
        log_kwargs = orch._self_model.log_decision.call_args.kwargs
        assert log_kwargs["decision"].reason == "silence_follow_up"
        assert log_kwargs["mode"] == "primary"
        assert log_kwargs["response_message_id"] == result.response.id
        # No tools on this path — the request went out plain.
        assert router.requests[0].tools is None

    @pytest.mark.asyncio
    async def test_reason_defaults_to_forced(self, monkeypatch):
        thread = make_thread()
        router = LoopRouter(results=[loop_ok(text_response("you rang?"))])
        orch = make_orchestrator(router, monkeypatch)
        orch._persist_response = AsyncMock(return_value=persisted_message(thread.id))
        orch._self_model.log_decision = AsyncMock(return_value=None)

        result = await orch.force_response(
            room=make_room(), thread=thread, users=[], messages=[], memories=[],
        )

        assert result.decision.reason == "forced"
