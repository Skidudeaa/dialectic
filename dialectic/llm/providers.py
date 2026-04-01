# llm/providers.py — Provider abstraction layer

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Optional
import httpx
import os
import logging

logger = logging.getLogger(__name__)


class ProviderName(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    stop_reason: str
    provider: ProviderName


@dataclass
class LLMRequest:
    messages: list[dict]
    system: str
    model: str
    max_tokens: int = 4096
    temperature: float = 1.0
    stream: bool = False


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


class AnthropicProvider(LLMProvider):
    name = ProviderName.ANTHROPIC

    MODELS = {
        # Current Claude 4.x model IDs
        "claude-sonnet-4-6": "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
        "claude-opus-4-6": "claude-opus-4-6",
        # Legacy aliases kept so existing room rows continue to resolve
        "claude-sonnet-4-20250514": "claude-sonnet-4-6",
        "claude-haiku-4-20250514": "claude-haiku-4-5-20251001",
        "claude-opus-4-5-20251101": "claude-opus-4-6",
    }

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export ANTHROPIC_API_KEY")
        self.base_url = "https://api.anthropic.com/v1"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self.client.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.MODELS.get(request.model, request.model),
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "system": request.system,
                "messages": request.messages,
            }
        )
        response.raise_for_status()
        data = response.json()

        return LLMResponse(
            content=data["content"][0]["text"],
            model=data["model"],
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
            stop_reason=data["stop_reason"],
            provider=self.name,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        import json
        async with self.client.stream(
            "POST",
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.MODELS.get(request.model, request.model),
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "system": request.system,
                "messages": request.messages,
                "stream": True,
            }
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event["type"] == "content_block_delta":
                        yield event["delta"]["text"]


class OpenAIProvider(LLMProvider):
    name = ProviderName.OPENAI

    MODELS = {
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
    }

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export OPENAI_API_KEY")
        self.base_url = "https://api.openai.com/v1"
        self.client = httpx.AsyncClient(timeout=120.0)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        messages = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)

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
        messages = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)

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


def get_provider(name: ProviderName) -> LLMProvider:
    return PROVIDERS[name]()
