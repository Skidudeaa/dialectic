# memory/embeddings.py — Embedding pipeline

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import httpx
import os
import logging

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    vector: list[float]
    model: str
    tokens: int


class EmbeddingProvider(ABC):
    """
    ARCHITECTURE: Pluggable embedding backend.
    WHY: Switch providers without changing memory system.
    """

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        pass


class OpenAIEmbeddings(EmbeddingProvider):
    """
    ARCHITECTURE: OpenAI text-embedding-3-small (1536 dims).
    WHY: Good quality, reasonable cost, pgvector compatible.
    """

    MODEL = "text-embedding-3-small"
    DIMENSIONS = 1536

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export OPENAI_API_KEY")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def embed(self, text: str) -> EmbeddingResult:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        response = await self.client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.MODEL,
                "input": texts,
            }
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data["data"]:
            results.append(EmbeddingResult(
                vector=item["embedding"],
                model=self.MODEL,
                tokens=data["usage"]["total_tokens"] // len(texts),
            ))

        return results


class MockEmbeddings(EmbeddingProvider):
    """
    ARCHITECTURE: Mock embeddings for testing without API keys.
    WHY: Allow development without paid API access.
    """

    DIMENSIONS = 1536

    async def embed(self, text: str) -> EmbeddingResult:
        # Generate deterministic fake embedding based on text hash
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        vector = [float(int(h[i:i+2], 16)) / 255.0 for i in range(0, min(len(h), self.DIMENSIONS * 2), 2)]
        # Pad to full dimensions
        vector.extend([0.0] * (self.DIMENSIONS - len(vector)))
        return EmbeddingResult(
            vector=vector[:self.DIMENSIONS],
            model="mock",
            tokens=len(text.split()),
        )

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        return [await self.embed(t) for t in texts]


def get_embedding_provider() -> EmbeddingProvider:
    """Get appropriate embedding provider based on available credentials."""
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbeddings()
    # Fallback to mock for development
    logger.warning("No OPENAI_API_KEY found, using mock embeddings")
    return MockEmbeddings()
