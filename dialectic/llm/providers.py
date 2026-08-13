# llm/providers.py — Provider abstraction layer

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional
import httpx
import os
import logging

logger = logging.getLogger(__name__)


class ProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class ToolsUnsupportedError(Exception):
    """Raised when a request carrying tools reaches a provider without tool
    support. The router filters the chain so this should never fire in
    practice — it exists as the loud safety net, not a control path."""


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    provider: ProviderName
    # Tool use (Anthropic only). raw_content is the verbatim content-block
    # list — the agentic loop must echo the assistant turn back exactly
    # (text + tool_use blocks) per the Anthropic tool-use contract.
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_content: list[dict] = field(default_factory=list)


@dataclass
class LLMRequest:
    messages: list[dict]
    system: str
    model: str
    max_tokens: int = 4096
    temperature: float = 1.0
    stream: bool = False
    # Anthropic tool schema dicts, passed verbatim. None = plain text call.
    tools: Optional[list[dict]] = None
    tool_choice: Optional[dict] = None
    # None preserves the pre-5-series behaviour: no thinking. Callers opt in
    # with {"type": "adaptive"} where the extra reasoning is worth the budget.
    thinking: Optional[dict] = None


def _parse_anthropic_message(data: dict, provider: ProviderName) -> LLMResponse:
    """Parse a non-streaming Anthropic response — pure, unit-testable.

    WHY: the old parse was data["content"][0]["text"], which crashes the
    moment the first block isn't text (e.g. a tool_use-first response).
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    blocks = data.get("content") or []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append(ToolCall(
                id=block.get("id", ""),
                name=block.get("name", ""),
                input=block.get("input") or {},
            ))
    return LLMResponse(
        content="".join(text_parts),
        model=data.get("model", ""),
        input_tokens=data.get("usage", {}).get("input_tokens", 0),
        output_tokens=data.get("usage", {}).get("output_tokens", 0),
        stop_reason=data.get("stop_reason") or "",
        provider=provider,
        tool_calls=tool_calls,
        raw_content=blocks,
    )


class AnthropicStreamFold:
    """SSE event fold for the Anthropic stream — pure state machine.

    Feed parsed SSE event dicts to fold(); it returns typed tuples:
      ("text", {"text": str})                        - a text delta
      ("tool_use", {"id", "name", "input"})          - a completed tool call
      ("message_stop", {"stop_reason", "raw_content"}) - end, with the full
        assistant content blocks for the loop to echo back.

    WHY a class, not inline parsing: streaming tool_use arrives as
    content_block_start + N input_json_delta fragments + content_block_stop,
    which needs a JSON buffer per block index. Keeping it pure (no I/O)
    makes every path testable with canned event lists.
    """

    def __init__(self):
        self._blocks: dict[int, dict] = {}
        self._order: list[int] = []
        self._stop_reason: str = ""

    def fold(self, event: dict) -> list[tuple[str, dict]]:
        etype = event.get("type")
        out: list[tuple[str, dict]] = []

        if etype == "content_block_start":
            idx = event.get("index", 0)
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                self._blocks[idx] = {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "json_buf": "",
                }
            else:
                self._blocks[idx] = {"type": "text", "text": ""}
            self._order.append(idx)

        elif etype == "content_block_delta":
            idx = event.get("index", 0)
            delta = event.get("delta") or {}
            blk = self._blocks.setdefault(idx, {"type": "text", "text": ""})
            if delta.get("type") == "input_json_delta":
                blk["json_buf"] = blk.get("json_buf", "") + delta.get("partial_json", "")
            elif "text" in delta:
                blk["text"] = blk.get("text", "") + delta["text"]
                out.append(("text", {"text": delta["text"]}))

        elif etype == "content_block_stop":
            idx = event.get("index", 0)
            blk = self._blocks.get(idx)
            if blk and blk.get("type") == "tool_use":
                import json as _json
                try:
                    blk["input"] = _json.loads(blk.get("json_buf") or "{}")
                except ValueError:
                    blk["input"] = {}
                out.append(("tool_use", {
                    "id": blk["id"], "name": blk["name"], "input": blk["input"],
                }))

        elif etype == "message_delta":
            delta = event.get("delta") or {}
            if delta.get("stop_reason"):
                self._stop_reason = delta["stop_reason"]

        elif etype == "message_stop":
            out.append(("message_stop", {
                "stop_reason": self._stop_reason,
                "raw_content": self.raw_content(),
            }))

        return out

    def raw_content(self) -> list[dict]:
        """Assistant content blocks in arrival order, API-echo shape."""
        blocks = []
        for idx in self._order:
            blk = self._blocks[idx]
            if blk["type"] == "text":
                if blk.get("text"):
                    blocks.append({"type": "text", "text": blk["text"]})
            else:
                blocks.append({
                    "type": "tool_use",
                    "id": blk["id"],
                    "name": blk["name"],
                    "input": blk.get("input", {}),
                })
        return blocks


class LLMProvider(ABC):
    """
    ARCHITECTURE: Thin wrapper over provider APIs.
    WHY: Uniform interface enables provider switching without changing call sites.
    """

    name: ProviderName

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        pass

    async def stream_events(self, request: LLMRequest) -> AsyncIterator[tuple[str, dict]]:
        """Typed streaming: yields ("text"|"tool_use"|"message_stop", payload).

        Default implementation wraps the legacy text-only stream() so
        providers without tool streaming keep working unchanged. Providers
        with real tool support override this.
        """
        if request.tools:
            raise ToolsUnsupportedError(
                f"{self.name.value} provider has no tool streaming support"
            )
        async for token in self.stream(request):
            yield ("text", {"text": token})
        yield ("message_stop", {"stop_reason": "end_turn", "raw_content": []})


class AnthropicProvider(LLMProvider):
    name = ProviderName.ANTHROPIC

    # The live 5-series IDs. There is no `-latest` alias on the Anthropic API:
    # claude-sonnet-latest and claude-opus-latest both 404 (verified against
    # GET /v1/models, which lists only concrete IDs). "Newest" is therefore a
    # pin we update here, in one place, rather than a string the API resolves.
    SONNET = "claude-sonnet-5"
    OPUS = "claude-opus-5"

    MODELS = {
        # Current
        "claude-sonnet-5": SONNET,
        "claude-opus-5": OPUS,
        # Legacy aliases kept so existing room rows continue to resolve. Every
        # one of them rolls FORWARD -- a stored row naming a retired model gets
        # the current tier rather than a 404.
        #
        # These keys are DELIBERATELY the old strings. Do not sweep them with a
        # find/replace over model IDs: rewriting a key to its own target makes
        # the entry a no-op, the lookup misses, and the raw stored ID goes to
        # the wire -- which is how a "retired" model keeps serving traffic.
        "claude-sonnet-4-6": SONNET,
        "claude-sonnet-4-20250514": SONNET,
        "claude-opus-4-6": OPUS,
        "claude-opus-4-5-20251101": OPUS,
        # Haiku is retired from this codebase by owner decision (2026-08-12).
        # The IDs stay mapped so historical rows still resolve -- they land on
        # Sonnet, never on a Haiku endpoint.
        "claude-haiku-4-5-20251001": SONNET,
        "claude-haiku-4-20250514": SONNET,
    }

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export ANTHROPIC_API_KEY")
        self.base_url = "https://api.anthropic.com/v1"
        self.client = httpx.AsyncClient(timeout=120.0)

    def _request_body(self, request: LLMRequest, stream: bool = False) -> dict:
        body = {
            "model": self.MODELS.get(request.model, request.model),
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
            # TWO 5-series contracts, both of which silently break a naive swap:
            #
            # temperature/top_p/top_k are REJECTED with a 400, so the sampling
            # knob never reaches the wire. Callers still pass temperature= and
            # it is still on LLMRequest -- it simply stops being sent. What used
            # to come from temperature=0 has to come from the prompt now.
            #
            # Thinking runs ADAPTIVE unless told otherwise, and max_tokens caps
            # thinking AND output together. Every background call here budgets
            # 256-1024 tokens for a JSON verdict; left adaptive, the model would
            # spend the whole budget reasoning and return nothing parseable.
            # Off is exactly what every caller got before the swap.
            "thinking": request.thinking or {"type": "disabled"},
        }
        if request.tools:
            body["tools"] = request.tools
            if request.tool_choice:
                body["tool_choice"] = request.tool_choice
        if stream:
            body["stream"] = True
        return body

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self.client.post(
            f"{self.base_url}/messages",
            headers=self._headers(),
            json=self._request_body(request),
        )
        response.raise_for_status()
        return _parse_anthropic_message(response.json(), self.name)

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Legacy text-only stream — kept for existing call sites/tests."""
        async for kind, payload in self.stream_events(request):
            if kind == "text":
                yield payload["text"]

    async def stream_events(self, request: LLMRequest) -> AsyncIterator[tuple[str, dict]]:
        import json
        fold = AnthropicStreamFold()
        async with self.client.stream(
            "POST",
            f"{self.base_url}/messages",
            headers=self._headers(),
            json=self._request_body(request, stream=True),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    for item in fold.fold(event):
                        yield item


# WHY this exists: a message carrying an image attachment is a content-BLOCK
# list in Anthropic's shape ({"type":"image","source":{...}}), and OpenAI wants
# image_url with a data: URI — so forwarding it verbatim is a deterministic 400.
# The router would spend three retries and ~7s of backoff discovering that on
# every fallback with a picture in context.
#
# WHY a note rather than a translation: this provider is the AVAILABILITY
# fallback, whose job is to produce a sentence when Anthropic is down. A model
# told plainly that it cannot see the image says so; one handed only the caption
# describes a chart it never looked at. Translating to image_url is a real
# option (gpt-4o has vision) and is deliberately left until the fallback is
# worth that surface — see llm/vision.py.
_UNSEEN_IMAGE_NOTE = "[an image is attached to this message; you cannot see it]"


def flatten_content_blocks(content) -> str:
    """Anthropic content-block list -> one plain string. Strings pass through.

    Unknown block types (tool_use / tool_result) are dropped rather than
    rendered: they are meaningless without the tools parameter this provider
    refuses anyway, and the tool loop rebuilds from the ORIGINAL messages
    before it ever degrades down the chain.
    """
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "image":
            parts.append(_UNSEEN_IMAGE_NOTE)
    return "\n".join(part for part in parts if part)


class OpenAIProvider(LLMProvider):
    name = ProviderName.OPENAI

    MODELS = {
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
    }

    def _messages(self, request: LLMRequest) -> list[dict]:
        """System turn + the conversation, flattened to OpenAI's string form."""
        messages = [{"role": "system", "content": request.system}]
        for msg in request.messages:
            messages.append({
                **msg,
                "content": flatten_content_blocks(msg.get("content")),
            })
        return messages

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.tools:
            # Tools are Anthropic-only by design: mapping schemas to OpenAI
            # function-calling doubles the surface for a fallback path with
            # zero primary users. The router filters the chain; this is the
            # loud safety net. The tool loop degrades to text-only re-route.
            raise ToolsUnsupportedError("OpenAI provider does not accept tools")
        messages = self._messages(request)

        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.MODELS.get(request.model, request.model),
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "messages": messages,
            }
        )
        response.raise_for_status()
        data = response.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data["model"],
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            stop_reason=data["choices"][0]["finish_reason"],
            provider=self.name,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        import json
        if request.tools:
            raise ToolsUnsupportedError("OpenAI provider does not accept tools")
        messages = self._messages(request)

        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.MODELS.get(request.model, request.model),
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "messages": messages,
                "stream": True,
            }
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    event = json.loads(line[6:])
                    delta = event["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]


PROVIDERS: dict[ProviderName, type[LLMProvider]] = {
    ProviderName.ANTHROPIC: AnthropicProvider,
    ProviderName.OPENAI: OpenAIProvider,
}

# WHY: Providers hold an httpx.AsyncClient. Constructing one per call leaked
# an unclosed client (and its connection pool) on every message, because
# orchestrators/routers are rebuilt per WebSocket message. Module-level
# singletons share one client per provider for the process lifetime.
_provider_cache: dict[ProviderName, LLMProvider] = {}


def get_provider(name: ProviderName) -> LLMProvider:
    if name not in _provider_cache:
        _provider_cache[name] = PROVIDERS[name]()
    return _provider_cache[name]
