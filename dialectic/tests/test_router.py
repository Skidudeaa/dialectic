# tests/test_router.py — ModelRouter fallback chain + streaming fallback

import pytest

from llm.providers import LLMProvider, LLMRequest, LLMResponse, ProviderName
from llm.router import ModelRouter
import llm.router as router_module


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setattr(router_module, "RETRY_DELAYS", [0.0, 0.0, 0.0])


def make_response(content: str, model: str, provider: ProviderName) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        input_tokens=10,
        output_tokens=10,
        stop_reason="end_turn",
        provider=provider,
    )


class FakeProvider(LLMProvider):
    """Scriptable provider: fail N times, optionally stream tokens."""

    def __init__(self, name: ProviderName, fail_completes: int = 0,
                 stream_tokens: list[str] | None = None,
                 stream_error_after: int | None = None):
        self.name = name
        self.fail_completes = fail_completes
        self.stream_tokens = stream_tokens if stream_tokens is not None else ["hello", " world"]
        self.stream_error_after = stream_error_after
        self.complete_calls: list[LLMRequest] = []
        self.stream_calls: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.complete_calls.append(request)
        if self.fail_completes > 0:
            self.fail_completes -= 1
            raise RuntimeError("provider down")
        return make_response("ok", request.model, self.name)

    async def stream(self, request: LLMRequest):
        self.stream_calls.append(request)
        if self.stream_error_after == 0:
            raise RuntimeError("stream failed before first token")
        for i, token in enumerate(self.stream_tokens):
            yield token
            if self.stream_error_after is not None and i + 1 >= self.stream_error_after:
                raise RuntimeError("stream died mid-flight")


def make_router(primary: FakeProvider, fallback: FakeProvider) -> ModelRouter:
    router = ModelRouter(
        primary_provider=primary.name,
        fallback_provider=fallback.name,
        primary_model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5-20251001",
    )
    # Inject fakes into the router's provider cache
    router._providers[primary.name] = primary
    router._providers[fallback.name] = fallback
    return router


@pytest.fixture
def primary():
    return FakeProvider(ProviderName.ANTHROPIC)


@pytest.fixture
def fallback():
    return FakeProvider(ProviderName.OPENAI)


class TestRouteChain:
    @pytest.mark.asyncio
    async def test_route_honors_requested_model(self, primary, fallback):
        """A provoker-model request must hit that model, not the chain's frozen primary."""
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-haiku-4-5-20251001")
        result = await router.route(request)
        assert result.success
        assert primary.complete_calls[0].model == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    async def test_route_falls_back_to_secondary_provider(self, primary, fallback):
        primary.fail_completes = 99  # exhaust all retries on primary
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6")
        result = await router.route(request)
        assert result.success
        assert result.response.provider == ProviderName.OPENAI
        # primary retried, then fallback succeeded
        assert len(fallback.complete_calls) == 1

    @pytest.mark.asyncio
    async def test_route_failure_returns_attempt_trace(self, primary, fallback):
        primary.fail_completes = 99
        fallback.fail_completes = 99
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6")
        result = await router.route(request)
        assert not result.success
        assert result.response is None
        assert len(result.attempts) > 0
        assert all(a["error"] for a in result.attempts)


class TestStreamChain:
    async def collect(self, router, request):
        events = []
        async for event in router.stream(request):
            events.append(event)
        return events

    @pytest.mark.asyncio
    async def test_stream_happy_path(self, primary, fallback):
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6", stream=True)
        events = await self.collect(router, request)
        tokens = [d["token"] for t, d in events if t == "token"]
        assert tokens == ["hello", " world"]
        assert len(fallback.stream_calls) == 0

    @pytest.mark.asyncio
    async def test_stream_falls_back_before_first_token(self, primary, fallback):
        primary.stream_error_after = 0  # fail before yielding anything
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6", stream=True)
        events = await self.collect(router, request)
        tokens = [d["token"] for t, d in events if t == "token"]
        assert tokens == ["hello", " world"]
        assert len(fallback.stream_calls) == 1
        # the attempt events record the actual provider used last
        attempts = [d for t, d in events if t == "attempt"]
        assert attempts[-1]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_stream_midflight_failure_raises(self, primary, fallback):
        """Once tokens reached the client, switching providers would splice answers."""
        primary.stream_error_after = 1
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6", stream=True)
        with pytest.raises(RuntimeError, match="mid-flight"):
            await self.collect(router, request)
        assert len(fallback.stream_calls) == 0

    @pytest.mark.asyncio
    async def test_empty_stream_falls_back(self, primary, fallback):
        primary.stream_tokens = []  # completes without yielding — e.g. silent API error
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6", stream=True)
        events = await self.collect(router, request)
        tokens = [d["token"] for t, d in events if t == "token"]
        assert tokens == ["hello", " world"]
        assert len(fallback.stream_calls) == 1

    @pytest.mark.asyncio
    async def test_all_streams_fail_raises_last_error(self, primary, fallback):
        primary.stream_error_after = 0
        fallback.stream_error_after = 0
        router = make_router(primary, fallback)
        request = LLMRequest(messages=[{"role": "user", "content": "hi"}],
                             system="s", model="claude-sonnet-4-6", stream=True)
        with pytest.raises(RuntimeError):
            await self.collect(router, request)


class TestToolAwareChain:
    """Tools are Anthropic-only: the chain filters and fields ride along."""

    def test_chain_filters_openai_when_tools_requested(self, primary, fallback):
        router = make_router(primary, fallback)
        chain = router._build_chain("claude-sonnet-4-6", tools_requested=True)
        assert all(p == ProviderName.ANTHROPIC for p, _ in chain)
        assert len(chain) >= 1

    def test_chain_unfiltered_without_tools(self, primary, fallback):
        router = make_router(primary, fallback)
        chain = router._build_chain("claude-sonnet-4-6", tools_requested=False)
        assert any(p == ProviderName.OPENAI for p, _ in chain)

    @pytest.mark.asyncio
    async def test_route_passes_tools_through(self, primary, fallback):
        """route() rebuilds the request per chain entry — tools must survive."""
        router = make_router(primary, fallback)
        tools = [{"name": "get_live_quotes", "input_schema": {"type": "object"}}]
        req = LLMRequest(messages=[], system="s", model="claude-sonnet-4-6",
                         tools=tools, tool_choice={"type": "auto"})
        result = await router.route(req)
        assert result.success
        routed = primary.complete_calls[0]
        assert routed.tools == tools
        assert routed.tool_choice == {"type": "auto"}

    @pytest.mark.asyncio
    async def test_route_with_tools_never_reaches_openai(self, fallback):
        """Primary down + tools requested -> fail without touching OpenAI."""
        bad_primary = FakeProvider(ProviderName.ANTHROPIC, fail_completes=99)
        router = make_router(bad_primary, fallback)
        req = LLMRequest(messages=[], system="s", model="claude-sonnet-4-6",
                         tools=[{"name": "t", "input_schema": {}}])
        result = await router.route(req)
        assert not result.success
        assert fallback.complete_calls == []

    @pytest.mark.asyncio
    async def test_stream_events_yields_typed_events(self, primary, fallback):
        """stream_events wraps the default provider stream into typed events."""
        router = make_router(primary, fallback)
        req = LLMRequest(messages=[], system="s", model="claude-sonnet-4-6")
        events = []
        async for kind, payload in router.stream_events(req):
            events.append((kind, payload))
        kinds = [k for k, _ in events]
        assert kinds[0] == "attempt"
        assert "text" in kinds
        assert kinds[-1] == "message_stop"

    @pytest.mark.asyncio
    async def test_stream_events_falls_back_before_first_event(self, fallback):
        """Pre-first-event failure falls through to the next chain entry."""
        bad_primary = FakeProvider(ProviderName.ANTHROPIC, stream_error_after=0)
        router = make_router(bad_primary, fallback)
        req = LLMRequest(messages=[], system="s", model="claude-sonnet-4-6")
        events = []
        async for kind, payload in router.stream_events(req):
            events.append((kind, payload))
        texts = [p["text"] for k, p in events if k == "text"]
        assert texts == ["hello", " world"]  # from the fallback provider
