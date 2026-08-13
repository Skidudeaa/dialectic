# tests/test_tool_loop.py — the agentic loop: round trips, failures, streaming

import asyncio
import json

import pytest

from llm.providers import LLMRequest, LLMResponse, ProviderName, ToolCall
from llm.router import RoutingResult
from llm.tool_loop import ToolLoop, ToolLoopResult
from llm.tools import Tool, ToolRegistry


# ── scriptable router (mirrors FakeProvider in test_router.py, one layer up) ──


class FakeRouter:
    """Scripted ModelRouter: canned RoutingResults and typed event streams."""

    def __init__(self, results=None, streams=None):
        self.results = list(results or [])
        self.streams = list(streams or [])
        self.requests: list[LLMRequest] = []
        self.stream_requests: list[LLMRequest] = []

    async def route(self, request: LLMRequest) -> RoutingResult:
        self.requests.append(request)
        assert self.results, "route() called more times than the script allows"
        return self.results.pop(0)

    async def stream_events(self, request: LLMRequest):
        self.stream_requests.append(request)
        assert self.streams, "stream_events() called more times than the script allows"
        for item in self.streams.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item


def tool_use_response(calls, text=""):
    """calls: list of (name, input). Builds the raw_content the API would send."""
    raw = []
    tool_calls = []
    if text:
        raw.append({"type": "text", "text": text})
    for i, (name, payload) in enumerate(calls):
        call_id = f"toolu_{i}"
        raw.append({"type": "tool_use", "id": call_id, "name": name, "input": payload})
        tool_calls.append(ToolCall(id=call_id, name=name, input=payload))
    return LLMResponse(
        content=text, model="claude-sonnet-5", input_tokens=10, output_tokens=10,
        stop_reason="tool_use", provider=ProviderName.ANTHROPIC,
        tool_calls=tool_calls, raw_content=raw,
    )


def text_response(text):
    return LLMResponse(
        content=text, model="claude-sonnet-5", input_tokens=10, output_tokens=10,
        stop_reason="end_turn", provider=ProviderName.ANTHROPIC,
        raw_content=[{"type": "text", "text": text}],
    )


def ok(response):
    return RoutingResult(response=response, success=True, attempts=[], prompt_hash="h")


def failed():
    return RoutingResult(response=None, success=False,
                         attempts=[{"error": "anthropic down"}], prompt_hash="h")


def stream_script(*, text_chunks=(), tool_calls=(), stop_reason="end_turn"):
    events = [("attempt", {"provider": "anthropic", "model": "claude-sonnet-5"})]
    raw = []
    for chunk in text_chunks:
        events.append(("text", {"text": chunk}))
    if text_chunks:
        raw.append({"type": "text", "text": "".join(text_chunks)})
    for i, (name, payload) in enumerate(tool_calls):
        call_id = f"toolu_{i}"
        events.append(("tool_use", {"id": call_id, "name": name, "input": payload}))
        raw.append({"type": "tool_use", "id": call_id, "name": name, "input": payload})
    events.append(("message_stop", {"stop_reason": stop_reason, "raw_content": raw}))
    return events


# ── registry of scriptable tools ─────────────────────────────────────


def make_registry():
    async def quotes(args):
        return {"symbol": args.get("symbol", "XOP"), "price": 41.2}

    async def slow(args):
        await asyncio.sleep(5)
        return {"never": True}

    async def boom(args):
        raise RuntimeError("tradingDesk is on fire")

    async def whatif(args):
        return {"probability": 0.42, "provenance": {"base_revision": 29395}}

    return ToolRegistry(tools=[
        Tool(name="get_live_quotes", description="d", label="checking live prices",
             input_schema={"type": "object", "properties": {}}, execute=quotes),
        Tool(name="slow_tool", description="d", label="taking its time",
             input_schema={"type": "object", "properties": {}}, execute=slow,
             timeout_s=0.02),
        Tool(name="boom_tool", description="d", label="failing",
             input_schema={"type": "object", "properties": {}}, execute=boom),
        Tool(name="evaluate_scenario", description="d", label="running the what-if",
             input_schema={"type": "object", "properties": {}}, execute=whatif),
    ])


@pytest.fixture
def registry():
    return make_registry()


def make_request(text="what is brent doing?"):
    return LLMRequest(
        messages=[{"role": "user", "content": text}],
        system="you are a participant",
        model="claude-sonnet-5",
    )


# ── non-streaming loop ───────────────────────────────────────────────


class TestSingleRoundTrip:
    @pytest.mark.asyncio
    async def test_tool_use_then_text_answer(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("get_live_quotes", {"symbol": "XOP"})], text="let me look")),
            ok(text_response("XOP is 41.2")),
        ])
        result = await ToolLoop(router, registry).run(make_request())

        assert isinstance(result, ToolLoopResult)
        assert result.routing.response.content == "XOP is 41.2"
        assert result.iterations == 2
        assert result.degraded is False
        assert len(result.tool_trace) == 1
        entry = result.tool_trace[0]
        assert entry["name"] == "get_live_quotes"
        assert entry["ok"] is True
        assert entry["input"] == {"symbol": "XOP"}
        assert entry["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_second_call_echoes_assistant_turn_and_tool_result(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("get_live_quotes", {})])),
            ok(text_response("done")),
        ])
        await ToolLoop(router, registry).run(make_request())

        second = router.requests[1]
        assistant, user = second.messages[-2], second.messages[-1]
        assert assistant["role"] == "assistant"
        assert assistant["content"][0]["type"] == "tool_use"
        assert user["role"] == "user"
        block = user["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "toolu_0"
        assert block.get("is_error") is not True
        assert "41.2" in block["content"]

    @pytest.mark.asyncio
    async def test_tools_and_auto_choice_are_sent(self, registry):
        router = FakeRouter(results=[ok(text_response("no tool needed"))])
        await ToolLoop(router, registry).run(make_request())

        first = router.requests[0]
        assert [t["name"] for t in first.tools] == registry.names()
        assert first.tool_choice == {"type": "auto"}

    @pytest.mark.asyncio
    async def test_plain_answer_short_circuits(self, registry):
        router = FakeRouter(results=[ok(text_response("no check needed"))])
        result = await ToolLoop(router, registry).run(make_request())
        assert result.iterations == 1
        assert result.tool_trace == []

    @pytest.mark.asyncio
    async def test_empty_registry_makes_one_plain_call(self):
        router = FakeRouter(results=[ok(text_response("hi"))])
        result = await ToolLoop(router, ToolRegistry(tools=[])).run(make_request())
        assert result.iterations == 1
        assert router.requests[0].tools is None

    @pytest.mark.asyncio
    async def test_provenance_lands_in_the_trace(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("evaluate_scenario", {"scenario_id": "closed-may"})])),
            ok(text_response("hypothetically, +5%")),
        ])
        result = await ToolLoop(router, registry).run(make_request())
        assert result.tool_trace[0]["provenance"] == {"base_revision": 29395}


class TestParallelCalls:
    @pytest.mark.asyncio
    async def test_two_tools_in_one_response(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([
                ("get_live_quotes", {"symbol": "XOP"}),
                ("evaluate_scenario", {"scenario_id": "closed-may"}),
            ])),
            ok(text_response("both checked")),
        ])
        result = await ToolLoop(router, registry).run(make_request())

        assert [e["name"] for e in result.tool_trace] == [
            "get_live_quotes", "evaluate_scenario"]
        assert all(e["ok"] for e in result.tool_trace)

        blocks = router.requests[1].messages[-1]["content"]
        assert len(blocks) == 2
        assert [b["tool_use_id"] for b in blocks] == ["toolu_0", "toolu_1"]


class TestFailureIsNeverAnException:
    @pytest.mark.asyncio
    async def test_unknown_tool_becomes_is_error_and_loop_continues(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("nonexistent_tool", {"x": 1})])),
            ok(text_response("I do not have that tool")),
        ])
        result = await ToolLoop(router, registry).run(make_request())

        assert result.routing.response.content == "I do not have that tool"
        entry = result.tool_trace[0]
        assert entry["ok"] is False
        assert "unknown tool" in entry["error"]

        block = router.requests[1].messages[-1]["content"][0]
        assert block["is_error"] is True
        assert "not one of your tools" in block["content"]

    @pytest.mark.asyncio
    async def test_executor_timeout_still_lands_a_text_answer(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("slow_tool", {})])),
            ok(text_response("could not check — answering from context")),
        ])
        result = await ToolLoop(router, registry).run(make_request())

        assert result.routing.success
        assert result.routing.response.content.startswith("could not check")
        entry = result.tool_trace[0]
        assert entry["ok"] is False
        assert "timed out" in entry["error"]

        block = router.requests[1].messages[-1]["content"][0]
        assert block["is_error"] is True
        assert "do not call it again" in block["content"]

    @pytest.mark.asyncio
    async def test_executor_exception_becomes_is_error(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("boom_tool", {})])),
            ok(text_response("the desk is down")),
        ])
        result = await ToolLoop(router, registry).run(make_request())
        assert result.tool_trace[0]["ok"] is False
        assert "tradingDesk is on fire" in result.tool_trace[0]["error"]
        assert result.routing.success

    @pytest.mark.asyncio
    async def test_one_tool_failing_does_not_poison_its_sibling(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("boom_tool", {}), ("get_live_quotes", {})])),
            ok(text_response("partial")),
        ])
        result = await ToolLoop(router, registry).run(make_request())
        assert [e["ok"] for e in result.tool_trace] == [False, True]
        blocks = router.requests[1].messages[-1]["content"]
        assert blocks[0]["is_error"] is True
        assert blocks[1].get("is_error") is not True


class TestBudgets:
    @pytest.mark.asyncio
    async def test_iteration_cap_forces_tool_choice_none(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("get_live_quotes", {})])) for _ in range(3)
        ])
        result = await ToolLoop(router, registry, max_iterations=3).run(make_request())

        assert len(router.requests) == 3
        assert result.iterations == 3
        assert [r.tool_choice for r in router.requests] == [
            {"type": "auto"}, {"type": "auto"}, {"type": "none"}]

    @pytest.mark.asyncio
    async def test_exhausted_budget_forces_tool_choice_none_immediately(self, registry):
        router = FakeRouter(results=[ok(text_response("answering now"))])
        await ToolLoop(router, registry, loop_budget_s=0.0).run(make_request())
        assert router.requests[0].tool_choice == {"type": "none"}


class TestDegradedFallback:
    @pytest.mark.asyncio
    async def test_route_failure_retries_text_only(self, registry):
        router = FakeRouter(results=[failed(), ok(text_response("answered without tools"))])
        result = await ToolLoop(router, registry).run(make_request())

        assert result.degraded is True
        assert result.routing.success
        assert result.routing.response.content == "answered without tools"

        retry = router.requests[1]
        assert retry.tools is None
        assert retry.tool_choice is None
        # Original conversation only — tool blocks are invalid without tools
        # and unrepresentable for the OpenAI fallback.
        assert retry.messages == [{"role": "user", "content": "what is brent doing?"}]

    @pytest.mark.asyncio
    async def test_degrade_keeps_data_already_fetched(self, registry):
        router = FakeRouter(results=[
            ok(tool_use_response([("get_live_quotes", {})])),
            failed(),
            ok(text_response("XOP was 41.2 when I last saw it")),
        ])
        result = await ToolLoop(router, registry).run(make_request())

        assert result.degraded is True
        assert len(result.tool_trace) == 1
        retry = router.requests[2]
        assert retry.tools is None
        assert "LIVE DATA ALREADY FETCHED" in retry.system
        assert "41.2" in retry.system
        assert retry.messages == [{"role": "user", "content": "what is brent doing?"}]

    @pytest.mark.asyncio
    async def test_degraded_failure_is_reported_not_raised(self, registry):
        router = FakeRouter(results=[failed(), failed()])
        result = await ToolLoop(router, registry).run(make_request())
        assert result.degraded is True
        assert result.routing.success is False


# ── streaming loop ───────────────────────────────────────────────────


async def collect(loop, request):
    events = []
    async for event in loop.run_streaming(request):
        events.append(event)
    return events


class TestStreaming:
    @pytest.mark.asyncio
    async def test_event_ordering_and_text_accumulation(self, registry):
        router = FakeRouter(streams=[
            stream_script(text_chunks=["Let me ", "check. "],
                          tool_calls=[("get_live_quotes", {"symbol": "XOP"})],
                          stop_reason="tool_use"),
            stream_script(text_chunks=["XOP is ", "41.2."]),
        ])
        events = await collect(ToolLoop(router, registry), make_request())
        kinds = [k for k, _ in events]

        assert kinds == [
            "token", "token", "tool_start", "tool_result", "token", "token", "loop_done"
        ]

        tokens = "".join(p["token"] for k, p in events if k == "token")
        assert tokens == "Let me check. XOP is 41.2."

        start = next(p for k, p in events if k == "tool_start")
        assert start == {"name": "get_live_quotes", "label": "checking live prices",
                         "input": {"symbol": "XOP"}}
        done_kind, done = events[-1]
        assert done_kind == "loop_done"
        assert done["iterations"] == 2
        assert done["degraded"] is False
        assert [e["name"] for e in done["tool_trace"]] == ["get_live_quotes"]
        # The caller persists ONE message: preamble + answer.
        assert done["text"] == tokens

    @pytest.mark.asyncio
    async def test_tool_result_event_reports_outcome(self, registry):
        router = FakeRouter(streams=[
            stream_script(tool_calls=[("boom_tool", {})], stop_reason="tool_use"),
            stream_script(text_chunks=["the check failed"]),
        ])
        events = await collect(ToolLoop(router, registry), make_request())
        result_event = next(p for k, p in events if k == "tool_result")
        assert result_event["name"] == "boom_tool"
        assert result_event["ok"] is False
        assert "latency_ms" in result_event

    @pytest.mark.asyncio
    async def test_second_iteration_carries_tool_result_blocks(self, registry):
        router = FakeRouter(streams=[
            stream_script(tool_calls=[("get_live_quotes", {})], stop_reason="tool_use"),
            stream_script(text_chunks=["ok"]),
        ])
        await collect(ToolLoop(router, registry), make_request())

        second = router.stream_requests[1]
        assert second.stream is True
        assert second.messages[-2]["role"] == "assistant"
        block = second.messages[-1]["content"][0]
        assert block["type"] == "tool_result"
        assert json.loads(block["content"])["price"] == 41.2

    @pytest.mark.asyncio
    async def test_midstream_death_after_first_token_reraises(self, registry):
        router = FakeRouter(streams=[[
            ("attempt", {"provider": "anthropic", "model": "m"}),
            ("text", {"text": "half an answ"}),
            RuntimeError("stream died mid-flight"),
        ]])
        with pytest.raises(RuntimeError, match="mid-flight"):
            await collect(ToolLoop(router, registry), make_request())

    @pytest.mark.asyncio
    async def test_failure_before_first_token_degrades_to_text_only(self, registry):
        router = FakeRouter(streams=[
            [RuntimeError("anthropic chain exhausted")],
            stream_script(text_chunks=["answering ", "without tools"]),
        ])
        events = await collect(ToolLoop(router, registry), make_request())

        tokens = "".join(p["token"] for k, p in events if k == "token")
        assert tokens == "answering without tools"
        done = events[-1][1]
        assert done["degraded"] is True
        assert router.stream_requests[1].tools is None

    @pytest.mark.asyncio
    async def test_streaming_iteration_cap_forces_tool_choice_none(self, registry):
        router = FakeRouter(streams=[
            stream_script(tool_calls=[("get_live_quotes", {})], stop_reason="tool_use")
            for _ in range(2)
        ])
        loop = ToolLoop(router, registry, max_iterations=2)
        events = await collect(loop, make_request())

        assert [r.tool_choice for r in router.stream_requests] == [
            {"type": "auto"}, {"type": "none"}]
        assert events[-1][1]["iterations"] == 2

    @pytest.mark.asyncio
    async def test_plain_stream_needs_no_second_iteration(self, registry):
        router = FakeRouter(streams=[stream_script(text_chunks=["just talking"])])
        events = await collect(ToolLoop(router, registry), make_request())
        assert [k for k, _ in events] == ["token", "loop_done"]
        assert events[-1][1]["iterations"] == 1
        assert len(router.stream_requests) == 1
