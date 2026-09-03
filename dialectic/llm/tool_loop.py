# llm/tool_loop.py — the agentic loop: model asks, we fetch, model answers

import asyncio
import logging
import time
from dataclasses import dataclass, field, replace
from typing import AsyncIterator, Optional

from .providers import LLMRequest, ToolCall
from .router import RoutingResult
from .tools import ToolRegistry, serialize_tool_result

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 5
DEFAULT_LOOP_BUDGET_S = 60.0

# WHY this wording: the model is a participant in a live conversation, not a
# batch job. A failed check must not become silence or a retry storm — it must
# become an honest sentence in the room. Saying "do not retry" matters: the
# same tool failing twice in one turn burns the budget the answer needs.
_FAILURE_TEMPLATE = (
    "The {name} check failed: {reason}. That tool is unavailable for the rest "
    "of this turn — do not call it again. Answer from the conversation and say "
    "plainly that you could not check the live value."
)

_DEGRADED_SYSTEM_NOTE = (
    "\n\n[LIVE DATA ALREADY FETCHED THIS TURN]\n{blob}\n"
    "The tool channel has since failed. Use what is above, answer from the "
    "conversation for anything else, and do not imply you checked more."
)


@dataclass
class ToolLoopResult:
    """
    ARCHITECTURE: Everything the caller needs after one turn of the loop —
    the final routing result to persist, plus what the model did to get there.
    WHY tool_trace: the room needs to be able to ask "where did that number
    come from", and a failed check that the model then talked around is only
    visible here.
    """
    routing: RoutingResult
    tool_trace: list[dict] = field(default_factory=list)
    iterations: int = 0
    degraded: bool = False


class ToolLoop:
    """
    ARCHITECTURE: Anthropic tool-use loop — route, execute requested tools,
    echo results back as a user turn, repeat until the model emits text.
    WHY here rather than in the orchestrator: the loop is the only thing that
    knows a turn can take several round trips, and the only place that can
    guarantee the turn still ends in a sentence when a tool (or the whole
    Anthropic chain) is down.
    TRADEOFF: bounded by iterations AND a wall-clock budget, so a model that
    keeps asking for one more check gets cut off with tool_choice=none rather
    than holding the room open indefinitely.
    """

    def __init__(
        self,
        router,
        registry: ToolRegistry,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        loop_budget_s: float = DEFAULT_LOOP_BUDGET_S,
    ):
        self.router = router
        self.registry = registry
        self.max_iterations = max(1, max_iterations)
        self.loop_budget_s = loop_budget_s

    # ── non-streaming ────────────────────────────────────────────────

    async def run(self, request: LLMRequest) -> ToolLoopResult:
        schemas = self.registry.schemas()
        if not schemas:
            # No tools for this room — one plain call, no loop.
            return ToolLoopResult(
                routing=await self.router.route(request), iterations=1
            )

        messages = list(request.messages)
        trace: list[dict] = []
        gathered: list[tuple[str, str]] = []
        deadline = time.monotonic() + self.loop_budget_s
        result: Optional[RoutingResult] = None
        iterations = 0

        for i in range(self.max_iterations):
            iterations = i + 1
            attempt = replace(
                request,
                messages=messages,
                tools=schemas,
                tool_choice=self._tool_choice(i, deadline),
            )
            result = await self.router.route(attempt)

            if not result.success:
                # The Anthropic-only chain is exhausted. Strip tools and go
                # back through the FULL chain (OpenAI included) so the room
                # gets an answer — silence is the worse failure.
                degraded_result = await self.router.route(
                    self._text_only_request(request, gathered)
                )
                return ToolLoopResult(degraded_result, trace, iterations, True)

            response = result.response
            if response is None or response.stop_reason != "tool_use" or not response.tool_calls:
                return ToolLoopResult(result, trace, iterations, False)

            # The assistant turn must be echoed back VERBATIM (text + tool_use
            # blocks) — the API pairs tool_result to tool_use by id.
            messages = messages + [
                {"role": "assistant", "content": response.raw_content}
            ]
            blocks = []
            for call in response.tool_calls:
                block, entry, content = await self._execute(call)
                trace.append(entry)
                blocks.append(block)
                if entry["ok"] and content:
                    gathered.append((call.name, content))
            messages.append({"role": "user", "content": blocks})

        # Fell out of the loop still asking for tools (tool_choice=none should
        # make this unreachable) — hand back the last real result regardless.
        return ToolLoopResult(result, trace, iterations, False)

    # ── streaming ────────────────────────────────────────────────────

    async def run_streaming(
        self, request: LLMRequest
    ) -> AsyncIterator[tuple[str, dict]]:
        """Yields ("token"|"tool_start"|"tool_result"|"loop_done", payload).

        Text is yielded as it arrives across EVERY iteration: the "let me
        check the tape" before a tool call and the answer after it are one
        message in the room, not two.
        """
        schemas = self.registry.schemas()
        labels = self.registry.labels()
        messages = list(request.messages)
        trace: list[dict] = []
        gathered: list[tuple[str, str]] = []
        text_parts: list[str] = []
        deadline = time.monotonic() + self.loop_budget_s
        emitted_any = False
        degraded = False
        iterations = 0

        for i in range(self.max_iterations):
            iterations = i + 1
            attempt = replace(
                request,
                messages=messages,
                stream=True,
                tools=schemas or None,
                tool_choice=self._tool_choice(i, deadline) if schemas else None,
            )

            pending: list[ToolCall] = []
            stop_reason = ""
            raw_content: list[dict] = []

            try:
                async for kind, payload in self.router.stream_events(attempt):
                    if kind == "text":
                        emitted_any = True
                        text_parts.append(payload["text"])
                        yield ("token", {"token": payload["text"]})
                    elif kind == "tool_use":
                        pending.append(ToolCall(
                            id=payload.get("id", ""),
                            name=payload.get("name", ""),
                            input=payload.get("input") or {},
                        ))
                    elif kind == "message_stop":
                        stop_reason = payload.get("stop_reason") or ""
                        raw_content = payload.get("raw_content") or []
            except Exception:
                # Router invariant: once a token has reached the client,
                # restarting would splice two different answers together, so
                # the failure propagates. Before the first token nothing has
                # been shown, so one text-only retry is safe and honest.
                if emitted_any:
                    raise
                logger.warning("Tool stream failed before first token — degrading to text-only")
                degraded = True
                async for token in self._degraded_stream(request, gathered):
                    text_parts.append(token)
                    yield ("token", {"token": token})
                break

            if stop_reason != "tool_use" or not pending:
                break

            messages = messages + [{"role": "assistant", "content": raw_content}]
            blocks = []
            for call in pending:
                yield ("tool_start", {
                    "name": call.name,
                    "label": labels.get(call.name, "checking"),
                    "input": call.input,
                })
                block, entry, content = await self._execute(call)
                trace.append(entry)
                blocks.append(block)
                if entry["ok"] and content:
                    gathered.append((call.name, content))
                yield ("tool_result", {
                    "name": call.name,
                    "ok": entry["ok"],
                    "latency_ms": entry["latency_ms"],
                })
            messages.append({"role": "user", "content": blocks})

        yield ("loop_done", {
            "tool_trace": trace,
            "iterations": iterations,
            "degraded": degraded,
            # The whole turn's text, already accumulated — the caller persists
            # ONE message and should not have to re-join the token stream.
            "text": "".join(text_parts),
        })

    # ── internals ────────────────────────────────────────────────────

    def _tool_choice(self, index: int, deadline: float) -> dict:
        """auto until the last permitted iteration, then none.

        WHY force none rather than just stopping: a loop that ends on a
        tool_use response has no text to show the room. Handing the model a
        turn where calling a tool is impossible is what guarantees a sentence.
        """
        out_of_budget = time.monotonic() >= deadline
        if out_of_budget or index >= self.max_iterations - 1:
            return {"type": "none"}
        return {"type": "auto"}

    def _degraded_system(self, system: str, gathered: list[tuple[str, str]]) -> str:
        if not gathered:
            return system
        blob = "\n".join(f"{name}: {content}" for name, content in gathered)
        return system + _DEGRADED_SYSTEM_NOTE.format(blob=blob)

    def _text_only_request(
        self, request: LLMRequest, gathered: list[tuple[str, str]]
    ) -> LLMRequest:
        """The original conversation, no tools, with any data already fetched
        folded into the system prompt.

        WHY not just resend the loop's messages: they contain tool_use /
        tool_result blocks, which are invalid without a tools parameter and
        cannot be represented at all by the OpenAI fallback. Rebuilding from
        the original messages keeps the degraded call valid on every provider
        in the chain, and the system-prompt fold means the checks that DID
        succeed are not thrown away.
        """
        return replace(
            request,
            messages=list(request.messages),
            system=self._degraded_system(request.system, gathered),
            tools=None,
            tool_choice=None,
        )

    async def _degraded_stream(
        self, request: LLMRequest, gathered: list[tuple[str, str]]
    ):
        text_only = replace(
            self._text_only_request(request, gathered), stream=True
        )
        async for kind, payload in self.router.stream_events(text_only):
            if kind == "text":
                yield payload["text"]

    async def _execute(self, call: ToolCall) -> tuple[dict, dict, Optional[str]]:
        """Run one tool call. Returns (tool_result block, trace entry, content).

        NEVER raises: every failure — unknown name, timeout, backend error,
        a bug in an executor — comes back as an is_error tool_result telling
        the model what happened. An exception here would kill the turn.
        """
        started = time.monotonic()
        entry: dict = {
            "name": call.name,
            "input": call.input,
            "ok": False,
            "latency_ms": 0,
        }

        tool = self.registry.get(call.name)
        if tool is None:
            entry["error"] = f"unknown tool: {call.name}"
            logger.warning("Model requested unknown tool %r", call.name)
            return (
                self._error_block(call, f"'{call.name}' is not one of your tools"),
                entry,
                None,
            )

        reason: Optional[str] = None
        raw = None
        try:
            raw = await asyncio.wait_for(
                tool.execute(call.input or {}), timeout=tool.timeout_s
            )
        except asyncio.TimeoutError:
            reason = f"timed out after {tool.timeout_s:g}s"
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"

        entry["latency_ms"] = int((time.monotonic() - started) * 1000)

        if reason is not None:
            entry["error"] = reason
            logger.warning("Tool %s failed: %s", call.name, reason)
            return self._error_block(call, reason), entry, None

        content = serialize_tool_result(raw)
        entry["ok"] = True
        # The working surface's write-path fix (2026-09-02): a tool that
        # touched objects names them as {entity, id, label} refs, and the
        # trace keeps them so the message can carry what it used. Ids were
        # dropped at write before this; every shape over the conversation
        # was empty for that one reason.
        if isinstance(raw, dict) and isinstance(raw.get("refs"), list):
            entry["refs"] = [r for r in raw["refs"] if isinstance(r, dict)][:12]
        if isinstance(raw, dict) and isinstance(raw.get("provenance"), dict):
            entry["provenance"] = raw["provenance"]
        return (
            {"type": "tool_result", "tool_use_id": call.id, "content": content},
            entry,
            content,
        )

    def _error_block(self, call: ToolCall, reason: str) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": call.id,
            "content": _FAILURE_TEMPLATE.format(name=call.name, reason=reason),
            "is_error": True,
        }
