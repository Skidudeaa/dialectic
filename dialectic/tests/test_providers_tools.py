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
        "model": "claude-sonnet-4-6",
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
