"""Tests for tool-use support in llm/providers.py — pure parse + fold."""

import pytest

from llm.providers import (
    AnthropicStreamFold,
    LLMRequest,
    ProviderName,
    ToolsUnsupportedError,
    _parse_anthropic_message,
)


def _msg(content, stop_reason="end_turn"):
    return {
        "content": content,
        "model": "claude-sonnet-5",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": stop_reason,
    }


class TestParseAnthropicMessage:
    def test_plain_text(self):
        resp = _parse_anthropic_message(
            _msg([{"type": "text", "text": "hello"}]), ProviderName.ANTHROPIC
        )
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.stop_reason == "end_turn"

    def test_mixed_text_and_tool_use(self):
        resp = _parse_anthropic_message(
            _msg(
                [
                    {"type": "text", "text": "Let me check. "},
                    {"type": "tool_use", "id": "tu_1", "name": "get_live_quotes",
                     "input": {"symbols": ["BZ=F"]}},
                ],
                stop_reason="tool_use",
            ),
            ProviderName.ANTHROPIC,
        )
        assert resp.content == "Let me check. "
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "get_live_quotes"
        assert resp.tool_calls[0].input == {"symbols": ["BZ=F"]}
        assert resp.stop_reason == "tool_use"
        # raw_content preserved verbatim for the echo-back turn
        assert resp.raw_content[1]["type"] == "tool_use"

    def test_tool_use_first_does_not_crash(self):
        """The exact latent crash: old parse read content[0]['text']."""
        resp = _parse_anthropic_message(
            _msg([{"type": "tool_use", "id": "tu_1", "name": "t", "input": {}}],
                 stop_reason="tool_use"),
            ProviderName.ANTHROPIC,
        )
        assert resp.content == ""
        assert resp.tool_calls[0].id == "tu_1"

    def test_multiple_text_blocks_concatenated(self):
        resp = _parse_anthropic_message(
            _msg([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]),
            ProviderName.ANTHROPIC,
        )
        assert resp.content == "ab"


class TestAnthropicStreamFold:
    def test_text_only_stream(self):
        fold = AnthropicStreamFold()
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "hel"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "lo"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]
        out = [item for e in events for item in fold.fold(e)]
        texts = [p["text"] for k, p in out if k == "text"]
        assert texts == ["hel", "lo"]
        stop = [p for k, p in out if k == "message_stop"][0]
        assert stop["stop_reason"] == "end_turn"
        assert stop["raw_content"] == [{"type": "text", "text": "hello"}]

    def test_single_tool_call_chunked_json(self):
        fold = AnthropicStreamFold()
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Checking. "}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "tu_9",
                               "name": "get_live_quotes"}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"symb'}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": 'ols": ["BZ=F"]}'}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
        out = [item for e in events for item in fold.fold(e)]
        tools = [p for k, p in out if k == "tool_use"]
        assert tools == [{"id": "tu_9", "name": "get_live_quotes",
                          "input": {"symbols": ["BZ=F"]}}]
        stop = [p for k, p in out if k == "message_stop"][0]
        assert stop["stop_reason"] == "tool_use"
        # raw_content carries BOTH blocks, in order, echo-ready
        assert stop["raw_content"][0] == {"type": "text", "text": "Checking. "}
        assert stop["raw_content"][1]["type"] == "tool_use"
        assert stop["raw_content"][1]["input"] == {"symbols": ["BZ=F"]}

    def test_parallel_tool_calls(self):
        fold = AnthropicStreamFold()
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "a", "name": "t1"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": "{}"}},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "b", "name": "t2"}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": '{"x": 1}'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            {"type": "message_stop"},
        ]
        out = [item for e in events for item in fold.fold(e)]
        tools = [p for k, p in out if k == "tool_use"]
        assert [t["id"] for t in tools] == ["a", "b"]
        assert tools[1]["input"] == {"x": 1}

    def test_malformed_tool_json_yields_empty_input(self):
        fold = AnthropicStreamFold()
        events = [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "tool_use", "id": "a", "name": "t"}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "input_json_delta", "partial_json": '{"broken'}},
            {"type": "content_block_stop", "index": 0},
        ]
        out = [item for e in events for item in fold.fold(e)]
        assert out[-1] == ("tool_use", {"id": "a", "name": "t", "input": {}})


class TestOpenAIToolGuard:
    @pytest.mark.asyncio
    async def test_openai_complete_rejects_tools(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        from llm.providers import OpenAIProvider
        provider = OpenAIProvider()
        req = LLMRequest(messages=[], system="", model="gpt-4o",
                         tools=[{"name": "t", "input_schema": {}}])
        with pytest.raises(ToolsUnsupportedError):
            await provider.complete(req)

    @pytest.mark.asyncio
    async def test_openai_stream_rejects_tools(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        from llm.providers import OpenAIProvider
        provider = OpenAIProvider()
        req = LLMRequest(messages=[], system="", model="gpt-4o",
                         tools=[{"name": "t", "input_schema": {}}])
        with pytest.raises(ToolsUnsupportedError):
            async for _ in provider.stream(req):
                pass


class TestModelResolution:
    """The 5-series contract: no Haiku on the wire, no rejected parameters.

    These guard a defect that a green suite cannot see. The request body is
    what the API validates, and every other test in this file mocks it away.
    """

    def _body(self, **kw):
        from llm.providers import AnthropicProvider
        provider = AnthropicProvider.__new__(AnthropicProvider)  # no API key needed
        req = LLMRequest(messages=[{"role": "user", "content": "x"}],
                         system="s", model=kw.pop("model", "claude-sonnet-5"), **kw)
        return provider._request_body(req)

    def test_every_mapping_lands_on_the_five_series(self):
        """A legacy key rewritten to its own target is a silent no-op — the
        lookup misses and the stored ID goes to the wire unchanged."""
        from llm.providers import AnthropicProvider
        for key, target in AnthropicProvider.MODELS.items():
            assert target in (AnthropicProvider.SONNET, AnthropicProvider.OPUS), (
                f"{key} resolves to {target}, which is not a current tier"
            )

    def test_haiku_ids_still_resolve_and_land_on_sonnet(self):
        """Haiku is retired by owner decision. The keys must SURVIVE — delete
        them and a stored row falls through to a live Haiku endpoint."""
        from llm.providers import AnthropicProvider
        haiku_keys = [k for k in AnthropicProvider.MODELS if "haiku" in k]
        assert haiku_keys, "legacy Haiku keys were removed; stored rows now reach Haiku"
        for key in haiku_keys:
            assert AnthropicProvider.MODELS[key] == AnthropicProvider.SONNET

    def test_no_haiku_id_can_reach_the_wire(self):
        assert "haiku" not in self._body(model="claude-haiku-4-5-20251001")["model"]

    def test_temperature_is_never_sent(self):
        """Non-default sampling parameters are a 400 on the 5-series. Callers
        still pass temperature=; it must not reach the body."""
        body = self._body(temperature=0.2)
        assert "temperature" not in body
        assert "top_p" not in body and "top_k" not in body

    def test_thinking_defaults_off_so_tight_budgets_survive(self):
        """max_tokens caps thinking AND output together; a 256-token scoring
        call left adaptive would spend the budget reasoning and return nothing."""
        assert self._body(max_tokens=256)["thinking"] == {"type": "disabled"}

    def test_callers_can_opt_into_adaptive_thinking(self):
        body = self._body(thinking={"type": "adaptive"})
        assert body["thinking"] == {"type": "adaptive"}


class TestAdaptiveOnlyModels:
    """The 5.5 generation refuses thinking.type "disabled" (live API, 2026-10-28:
    'Use "thinking.type.adaptive" and "output_config.effort"'). The body must
    change shape for those ids and for no other."""

    def _body(self, **kw):
        from llm.providers import AnthropicProvider
        provider = AnthropicProvider.__new__(AnthropicProvider)
        req = LLMRequest(messages=[{"role": "user", "content": "x"}],
                         system="s", model=kw.pop("model", "claude-opus-5-5"), **kw)
        return provider._request_body(req)

    def test_opus_5_5_gets_adaptive_thinking_with_medium_effort(self):
        body = self._body(max_tokens=256)
        assert body["model"] == "claude-opus-5-5"
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"] == {"effort": "medium"}
        assert body["max_tokens"] == 2048, "thinking shares the budget; a word-budgeted turn needs a floor"

    def test_effort_is_honoured_and_a_large_budget_kept(self):
        body = self._body(effort="high", max_tokens=6000)
        assert body["output_config"] == {"effort": "high"}
        assert body["max_tokens"] == 6000

    def test_sonnet_5_5_and_fable_are_adaptive_only_too(self):
        from llm.providers import AnthropicProvider
        for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"):
            assert AnthropicProvider.adaptive_only(model), model
            assert self._body(model=model)["thinking"] == {"type": "adaptive"}

    def test_mapped_legacy_ids_keep_thinking_disabled(self):
        """claude-opus-4-6 rolls forward to the pinned tier, which accepts disabled; nothing else changes."""
        body = self._body(model="claude-opus-4-6", max_tokens=256)
        assert body["thinking"] == {"type": "disabled"}
        assert "output_config" not in body
        assert body["max_tokens"] == 256

    def test_explicit_thinking_wins(self):
        body = self._body(thinking={"type": "adaptive"}, effort="low")
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"] == {"effort": "low"}


class TestStreamFoldThinkingBlocks:
    def test_signed_thinking_is_echoed_whole_and_never_shown(self):
        fold = AnthropicStreamFold()
        out = []
        for event in [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "weigh the "}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "evidence"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig123"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "S1 says weekly."}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            {"type": "message_stop"},
        ]:
            out.extend(fold.fold(event))
        texts = [p["text"] for kind, p in out if kind == "text"]
        assert texts == ["S1 says weekly."], "thinking never reaches the visible stream"
        stop = next(p for kind, p in out if kind == "message_stop")
        assert stop["raw_content"] == [
            {"type": "thinking", "thinking": "weigh the evidence", "signature": "sig123"},
            {"type": "text", "text": "S1 says weekly."},
        ]

    def test_unsigned_thinking_is_dropped_not_faked(self):
        fold = AnthropicStreamFold()
        for event in [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "redacted_thinking", "data": "opaque"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_stop"},
        ]:
            fold.fold(event)
        assert fold.raw_content() == [{"type": "redacted_thinking", "data": "opaque"}]
