# llm/router.py — Retry + fallback chain

from dataclasses import dataclass
from typing import Optional
import asyncio
import hashlib
import logging

from .providers import (
    LLMProvider, LLMRequest, LLMResponse,
    ProviderName, get_provider
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]


@dataclass
class RoutingResult:
    """
    ARCHITECTURE: Captures full routing trace for observability.
    WHY: Debug failed requests, understand fallback patterns.
    """
    response: Optional[LLMResponse]
    success: bool
    attempts: list[dict]
    prompt_hash: str


class ModelRouter:
    """
    ARCHITECTURE: Cascading fallback with retry per provider.
    WHY: Maximize availability without manual intervention.
    TRADEOFF: Latency on failure vs reliability.
    """

    def __init__(
        self,
        primary_provider: ProviderName,
        fallback_provider: ProviderName,
        primary_model: str,
        fallback_model: str,
    ):
        self.chain = [
            (primary_provider, primary_model),
            (fallback_provider, self._map_model(primary_model, fallback_provider)),
            (primary_provider, fallback_model),
        ]
        self._providers: dict[ProviderName, LLMProvider] = {}

    def _get_provider(self, name: ProviderName) -> LLMProvider:
        if name not in self._providers:
            self._providers[name] = get_provider(name)
        return self._providers[name]

    def _map_model(self, model: str, target_provider: ProviderName) -> str:
        """Map model name across providers."""
        mapping = {
            "claude-sonnet-4-20250514": "gpt-4o",
            "claude-haiku-4-20250514": "gpt-4o-mini",
            "claude-opus-4-5-20251101": "gpt-4o",
        }
        if target_provider == ProviderName.OPENAI:
            return mapping.get(model, "gpt-4o")
        return model

    def _hash_prompt(self, request: LLMRequest) -> str:
        """Deterministic hash for tracing."""
        content = f"{request.system}|{request.messages}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def route(self, request: LLMRequest) -> RoutingResult:
        """Execute request through fallback chain."""
        prompt_hash = self._hash_prompt(request)
        attempts = []

        for provider_name, model in self.chain:
            provider = self._get_provider(provider_name)

            for retry in range(MAX_RETRIES):
                attempt = {
                    "provider": provider_name.value,
                    "model": model,
                    "retry": retry,
                    "error": None,
                    "latency_ms": 0,
                }

                try:
                    import time
                    start = time.monotonic()

                    routed_request = LLMRequest(
                        messages=request.messages,
                        system=request.system,
                        model=model,
                        max_tokens=request.max_tokens,
                        temperature=request.temperature,
                    )

                    response = await provider.complete(routed_request)

                    attempt["latency_ms"] = int((time.monotonic() - start) * 1000)
                    attempts.append(attempt)

                    logger.info(
                        f"LLM success: {provider_name.value}/{model} "
                        f"in {attempt['latency_ms']}ms, hash={prompt_hash}"
                    )

                    return RoutingResult(
                        response=response,
                        success=True,
                        attempts=attempts,
                        prompt_hash=prompt_hash,
                    )

                except Exception as e:
                    attempt["error"] = str(e)
                    attempts.append(attempt)

                    logger.warning(
                        f"LLM attempt failed: {provider_name.value}/{model} "
                        f"retry={retry}, error={e}"
                    )

                    if retry < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAYS[retry])

        logger.error(f"LLM routing failed after {len(attempts)} attempts, hash={prompt_hash}")

        return RoutingResult(
            response=None,
            success=False,
            attempts=attempts,
            prompt_hash=prompt_hash,
        )
