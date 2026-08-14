"""Research mode (deep dive) — the long-loop turn.

What can only break here: the loop's research budget (15 / 300 where an
ordinary turn gets 5 / 60), the env gate, question validation, the per-room
concurrency lock, and the persistence/broadcast contract of a successful
dive. ToolLoop's own behaviour is pinned in tests/test_tool_loop.py; here
it is replaced by a scripted stand-in so the wiring around it is what is
under test.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import llm.research as research
from llm.tools import Tool, ToolRegistry
from models import MessageType, SpeakerType
from tests.conftest import make_room, make_thread
from transport.handlers import MessageHandler
from transport.websocket import Connection, MessageTypes


# ── stand-ins ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_dive_locks():
    """The concurrency guard is module-level state — no test may inherit
    another's in-flight mark."""
    research._active_dives.clear()
    yield
    research._active_dives.clear()


class RecordingConnections:
    def __init__(self):
        self.broadcasts = []
        self.direct = []

    async def broadcast(self, room_id, message, exclude_user=None):
        self.broadcasts.append(message)

    async def send_to_user(self, user_id, room_id, message):
        self.direct.append(message)
        return True


class FakeLoop:
    """ToolLoop stand-in: captures construction kwargs and replays a scripted
    stream — a token, one successful tool call, then loop_done carrying a
    trace whose second entry holds save_reading provenance."""

    instances = []

    def __init__(self, router, registry, max_iterations, loop_budget_s):
        self.router = router
        self.registry = registry
        self.max_iterations = max_iterations
        self.loop_budget_s = loop_budget_s
        self.request = None
        FakeLoop.instances.append(self)

    async def run_streaming(self, request):
        self.request = request
        yield ("token", {"token": "Findings: "})
        yield ("tool_start", {
            "name": "read_article",
            "label": "reading the piece",
            "input": {"url": "https://example.com/a"},
        })
        yield ("tool_result", {"name": "read_article", "ok": True, "latency_ms": 120})
        yield ("loop_done", {
            "tool_trace": [
                {"name": "read_article", "input": {"url": "https://example.com/a"},
                 "ok": True, "latency_ms": 120},
                {"name": "save_reading",
                 "input": {"url": "https://example.com/a", "summary": "A piece worth keeping"},
                 "ok": True, "latency_ms": 90,
                 "provenance": {"kind": "reading_draft"}},
            ],
            "iterations": 3,
            "degraded": False,
            "text": "Findings: the claim holds up under a second source.",
        })


def fake_registry():
    async def fetch(args):
        return {"ok": True}

    return ToolRegistry(tools=[
        Tool(name="read_article", description="d", label="reading the piece",
             input_schema={"type": "object", "properties": {}}, execute=fetch),
        Tool(name="save_reading", description="d", label="saving to the library",
             input_schema={"type": "object", "properties": {}}, execute=fetch),
    ])


def patch_dive(monkeypatch):
    """Every collaborator of deep_dive except the code under test, scripted —
    so no test can reach a provider or tradingDesk."""
    monkeypatch.setattr(research, "ToolLoop", FakeLoop)
    monkeypatch.setattr(research, "build_registry", lambda room, db: fake_registry())
    monkeypatch.setattr(research, "ModelRouter", lambda **kwargs: SimpleNamespace())
    FakeLoop.instances.clear()


def fake_db():
    return SimpleNamespace(
        fetchrow=AsyncMock(return_value={"sequence": 7}),
        execute=AsyncMock(),
    )


def make_handler(connections=None):
    return MessageHandler(
        db=SimpleNamespace(),
        connection_manager=connections or RecordingConnections(),
        memory_manager=SimpleNamespace(),
        llm_orchestrator=SimpleNamespace(),
    )


def make_conn(room_id, thread_id):
    return Connection(
        websocket=SimpleNamespace(), user_id=uuid4(),
        room_id=room_id, thread_id=thread_id,
    )


# ── loop budget ──────────────────────────────────────────────────────


class TestLoopBudget:
    @pytest.mark.asyncio
    async def test_loop_built_with_the_research_budget(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        patch_dive(monkeypatch)

        await research.deep_dive(
            db=fake_db(), room=make_room(), thread=make_thread(), users=[],
            question="Does the thesis survive the OPEC print?",
            broadcast=RecordingConnections().broadcast,
        )

        loop = FakeLoop.instances[0]
        assert loop.max_iterations == 15
        assert loop.loop_budget_s == 300.0
        # …and those are the module's published constants, not literals that
        # can drift apart.
        assert loop.max_iterations == research.MAX_ITERATIONS
        assert loop.loop_budget_s == research.LOOP_BUDGET_S

    @pytest.mark.asyncio
    async def test_the_question_is_the_prompt_and_carries_research_identity(self, monkeypatch):
        """No thread window: the dive gathers its own context through tools."""
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        patch_dive(monkeypatch)

        await research.deep_dive(
            db=fake_db(), room=make_room(), thread=make_thread(), users=[],
            question="What is Brent doing?",
            broadcast=RecordingConnections().broadcast,
        )

        request = FakeLoop.instances[0].request
        assert request.messages == [{"role": "user", "content": "What is Brent doing?"}]
        assert research.RESEARCH_IDENTITY in request.system
        assert request.stream is True


# ── gates and refusals (handler) ─────────────────────────────────────


class TestGates:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["0", "false", "no", "off"])
    async def test_disabled_env_gets_an_ephemeral_refusal(self, monkeypatch, value):
        monkeypatch.setenv("DEEP_DIVE_ENABLED", value)
        room, thread = make_room(), make_thread()
        connections = RecordingConnections()
        handler = make_handler(connections)

        await handler._handle_deep_dive(make_conn(room.id, thread.id), {"question": "research this"})

        assert len(connections.direct) == 1
        assert connections.direct[0].type == MessageTypes.ERROR
        assert connections.broadcasts == []
        assert room.id not in research._active_dives

    @pytest.mark.asyncio
    async def test_unset_env_means_on(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        assert research.deep_dive_enabled() is True

    @pytest.mark.asyncio
    async def test_empty_question_is_refused(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        room, thread = make_room(), make_thread()
        connections = RecordingConnections()
        handler = make_handler(connections)

        await handler._handle_deep_dive(make_conn(room.id, thread.id), {"question": "   "})

        assert len(connections.direct) == 1
        assert connections.direct[0].type == MessageTypes.ERROR
        assert connections.broadcasts == []
        assert room.id not in research._active_dives


# ── concurrency ──────────────────────────────────────────────────────


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_a_second_dive_is_refused_while_one_is_in_flight(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        room, thread = make_room(), make_thread()
        assert await research.try_acquire_dive(room.id) is True

        connections = RecordingConnections()
        handler = make_handler(connections)
        await handler._handle_deep_dive(make_conn(room.id, thread.id), {"question": "another one"})

        assert len(connections.direct) == 1
        assert connections.direct[0].type == MessageTypes.ERROR
        assert connections.broadcasts == []

        # Releasing re-arms the room — the refusal was about the in-flight
        # dive, not about this room.
        research.release_dive(room.id)
        assert await research.try_acquire_dive(room.id) is True

    @pytest.mark.asyncio
    async def test_valid_question_marks_the_room_and_the_task_releases_it(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        # Context load finds nothing: the spawned task exits quietly, which
        # is exactly the path that must still release the room's slot.
        monkeypatch.setattr(research, "load_room_context", AsyncMock(return_value=None))
        room, thread = make_room(), make_thread()
        connections = RecordingConnections()
        handler = make_handler(connections)

        await handler._handle_deep_dive(make_conn(room.id, thread.id), {"question": "go deep"})

        # The mark lands synchronously, before the task runs.
        assert room.id in research._active_dives
        assert connections.direct == []
        for _ in range(20):
            await asyncio.sleep(0)
            if room.id not in research._active_dives:
                break
        assert room.id not in research._active_dives

    @pytest.mark.asyncio
    async def test_overlong_question_is_capped_not_refused(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        dive = AsyncMock()
        monkeypatch.setattr(research, "deep_dive", dive)
        room, thread = make_room(), make_thread()
        monkeypatch.setattr(
            research, "load_room_context",
            AsyncMock(return_value=(room, thread, [])),
        )
        handler = make_handler(RecordingConnections())

        await handler._handle_deep_dive(
            make_conn(room.id, thread.id),
            {"question": "x" * (research.MAX_QUESTION_CHARS + 500)},
        )
        for _ in range(20):
            await asyncio.sleep(0)
            if dive.await_count:
                break

        assert dive.await_count == 1
        assert len(dive.call_args.kwargs["question"]) == research.MAX_QUESTION_CHARS


# ── the successful dive ──────────────────────────────────────────────


class TestSuccessfulDive:
    @pytest.mark.asyncio
    async def test_brief_persists_as_llm_primary_with_hoisted_proposals(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        patch_dive(monkeypatch)
        db = fake_db()
        connections = RecordingConnections()
        room, thread = make_room(), make_thread()

        await research.deep_dive(
            db=db, room=room, thread=thread, users=[],
            question="Does the thesis survive the OPEC print?",
            broadcast=connections.broadcast,
        )

        # One llm_primary insert, metadata carrying source + trace + the
        # save_reading proposal hoisted out of the trace.
        sql, *args = db.fetchrow.call_args.args
        assert "INSERT INTO messages" in sql
        assert args[3] == SpeakerType.LLM_PRIMARY.value
        assert args[5] == MessageType.TEXT.value
        metadata = args[10]
        assert metadata["source"] == "deep_dive"
        tools = metadata["tools"]
        assert tools["iterations"] == 3
        assert tools["degraded"] is False
        assert len(tools["calls"]) == 2
        assert tools["calls"][0]["label"] == "reading the piece"
        reading = metadata["reading_proposal"]
        assert reading["url"] == "https://example.com/a"
        assert reading["accepted"] is False
        # The event ledger saw the same birth.
        assert "INSERT INTO events" in db.execute.call_args.args[0]

        # The room watched it happen on the ordinary stream vocabulary,
        # bracketed by the deep-dive pair.
        types = [m.type for m in connections.broadcasts]
        assert types == [
            MessageTypes.DEEP_DIVE_STARTED,
            MessageTypes.LLM_THINKING,
            MessageTypes.LLM_STREAMING,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_TOOL_ACTIVITY,
            MessageTypes.LLM_DONE,
            MessageTypes.DEEP_DIVE_DONE,
        ]
        started, finished = [
            m.payload for m in connections.broadcasts
            if m.type == MessageTypes.LLM_TOOL_ACTIVITY
        ]
        assert started["status"] == "started"
        assert started["label"] == "reading the piece"
        assert finished["status"] == "finished"
        assert finished["latency_ms"] == 120

        done = connections.broadcasts[-2].payload
        assert done["thread_id"] == str(thread.id)
        assert done["content"] == "Findings: the claim holds up under a second source."
        assert done["speaker_type"] == SpeakerType.LLM_PRIMARY.value
        assert done["message_type"] == MessageType.TEXT.value
        assert done["sequence"] == 7
        # llm_done carries the same metadata the insert got — it is the only
        # path by which the live bubble learns the trace.
        assert done["metadata"] == metadata

    @pytest.mark.asyncio
    async def test_a_trace_without_proposals_hoists_nothing(self, monkeypatch):
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        patch_dive(monkeypatch)

        class PlainLoop(FakeLoop):
            async def run_streaming(self, request):
                yield ("loop_done", {
                    "tool_trace": [{"name": "read_article", "input": {},
                                    "ok": True, "latency_ms": 50}],
                    "iterations": 1,
                    "degraded": False,
                    "text": "Read it. Nothing worth filing.",
                })

        monkeypatch.setattr(research, "ToolLoop", PlainLoop)
        db = fake_db()

        await research.deep_dive(
            db=db, room=make_room(), thread=make_thread(), users=[],
            question="q", broadcast=RecordingConnections().broadcast,
        )

        metadata = db.fetchrow.call_args.args[11]
        # §5.1 small repair: the question now rides in metadata alongside the
        # brief itself (it used to travel only over the ephemeral
        # DEEP_DIVE_STARTED broadcast and was lost — workspace_objects.py's
        # research_briefs() docstring names this exact gap).
        assert set(metadata) == {"source", "tools", "question"}
        assert metadata["question"] == "q"


# ── failure posture ──────────────────────────────────────────────────


class TestFailurePosture:
    @pytest.mark.asyncio
    async def test_midstream_death_is_an_error_broadcast_never_a_hang(self, monkeypatch):
        """ToolLoop re-raises a provider death past the first token; the dive
        turns it into llm_error + the done bracket, and persists nothing."""
        monkeypatch.delenv("DEEP_DIVE_ENABLED", raising=False)
        patch_dive(monkeypatch)

        class DyingLoop(FakeLoop):
            async def run_streaming(self, request):
                yield ("token", {"token": "half an answ"})
                raise RuntimeError("provider died mid-flight")

        monkeypatch.setattr(research, "ToolLoop", DyingLoop)
        db = fake_db()
        connections = RecordingConnections()

        await research.deep_dive(
            db=db, room=make_room(), thread=make_thread(), users=[],
            question="q", broadcast=connections.broadcast,
        )

        db.fetchrow.assert_not_called()
        error, done = connections.broadcasts[-2:]
        assert error.type == MessageTypes.LLM_ERROR
        assert error.payload["partial_content"] == "half an answ"
        assert "mid-flight" in error.payload["error"]
        assert done.type == MessageTypes.DEEP_DIVE_DONE
