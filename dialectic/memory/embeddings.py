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


class VoyageEmbeddings(EmbeddingProvider):
    """
    ARCHITECTURE: Voyage AI embeddings, model and width read from env.

    WHY config rather than constants: the pgvector column is a fixed width
    (VECTOR(1536) today) and Voyage models are not 1536 by default, so the
    model name and its dimension have to move together with a schema change.
    Pinning either in code here would let them drift apart silently.

    TRADEOFF: a wrong dimension is not a crash, it is a corrupted recall lane
    -- pgvector rejects the insert, but a lane that never writes looks exactly
    like a lane with nothing to find. _check_dim fails loudly instead.
    """

    def __init__(self):
        self.api_key = os.environ.get("VOYAGE_API_KEY")
        if not self.api_key:
            raise EnvironmentError("FATAL: export VOYAGE_API_KEY")
        self.MODEL = os.environ.get("VOYAGE_MODEL", "")
        if not self.MODEL:
            raise EnvironmentError("FATAL: export VOYAGE_MODEL")
        self.DIMENSIONS = int(os.environ.get("VOYAGE_EMBED_DIM", "0"))
        if not self.DIMENSIONS:
            raise EnvironmentError("FATAL: export VOYAGE_EMBED_DIM")
        self.client = httpx.AsyncClient(timeout=30.0)

    def _check_dim(self, vector: list[float]) -> list[float]:
        """A width mismatch means the column and the model disagree. Say so
        here, where the model is named, not three layers down in a failed
        INSERT that reads as 'recall found nothing'."""
        if len(vector) != self.DIMENSIONS:
            raise ValueError(
                f"{self.MODEL} returned {len(vector)} dims, but "
                f"VOYAGE_EMBED_DIM says {self.DIMENSIONS}. The pgvector column "
                "must match the model; re-check the migration before writing."
            )
        return vector

    async def embed(self, text: str) -> EmbeddingResult:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        response = await self.client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.MODEL, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        total = (data.get("usage") or {}).get("total_tokens", 0)
        return [
            EmbeddingResult(
                vector=self._check_dim(item["embedding"]),
                model=self.MODEL,
                tokens=total // max(1, len(texts)),
            )
            for item in data["data"]
        ]


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
    """Get appropriate embedding provider based on available credentials.

    Voyage wins when it is configured, because switching embedding model is
    NOT a drop-in: OpenAI and Voyage vectors live in different spaces, so a
    cosine score between them is noise, not a weak match. Every stored vector
    has to be regenerated on the same model that will query it -- until that
    backfill has run, the dense lane is comparing apples to a different fruit
    and returning confident nonsense into the LLM's context.
    """
    if os.environ.get("VOYAGE_API_KEY"):
        return VoyageEmbeddings()
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAIEmbeddings()
    # Fallback to mock for development
    logger.warning("No OPENAI_API_KEY found, using mock embeddings")
    return MockEmbeddings()
