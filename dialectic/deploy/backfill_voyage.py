#!/usr/bin/env python3
"""Regenerate every memory embedding on the configured Voyage model.

Run AFTER migrations/016_voyage_embeddings.sql and after the backend restart
that puts the Voyage provider in the running process.

WHY it drives get_embedding_provider() instead of calling Voyage directly: a
hand-rolled client is a different subject than the app. It would embed with its
own model string, its own dimension, and its own batching, and prove nothing
about what the running service writes. Going through the real provider means
the vectors this writes are the vectors recall will later compare against --
and the provider's own _check_dim guard runs on every row.

Idempotent: only rows with a NULL embedding are touched, so an interrupted run
resumes by being run again.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402
from memory.embeddings import get_embedding_provider  # noqa: E402

BATCH = 32


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL", "postgresql://root@localhost/dialectic")
    provider = get_embedding_provider()
    name = type(provider).__name__
    model = getattr(provider, "MODEL", "?")
    dims = getattr(provider, "DIMENSIONS", "?")

    # Refuse to write mock or wrong-provider vectors into the live table -- a
    # silent mock backfill looks exactly like a successful one until recall
    # starts returning noise.
    if name != "VoyageEmbeddings":
        print(f"ABORT: provider is {name} (model {model}); expected VoyageEmbeddings.")
        print("       Set VOYAGE_API_KEY / VOYAGE_MODEL / VOYAGE_EMBED_DIM first.")
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        col_dims = await conn.fetchval(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid='memories'::regclass AND attname='embedding'"
        )
        if col_dims != dims:
            print(f"ABORT: column is vector({col_dims}) but {model} emits {dims}.")
            print("       Apply migrations/016_voyage_embeddings.sql first.")
            return 2

        rows = await conn.fetch(
            "SELECT id, key, content FROM memories "
            "WHERE embedding IS NULL AND content IS NOT NULL ORDER BY created_at"
        )
        total = len(rows)
        print(f"{name} / {model} / {dims} dims -- {total} memories to embed")
        if not total:
            return 0

        done = 0
        for i in range(0, total, BATCH):
            chunk = rows[i:i + BATCH]
            texts = [f"{r['key'] or ''} {r['content']}".strip() for r in chunk]
            results = await provider.embed_batch(texts)
            for row, res in zip(chunk, results):
                await conn.execute(
                    "UPDATE memories SET embedding = $1::vector WHERE id = $2",
                    "[" + ",".join(str(x) for x in res.vector) + "]", row["id"],
                )
            done += len(chunk)
            print(f"  {done}/{total}")

        remaining = await conn.fetchval(
            "SELECT count(*) FROM memories WHERE embedding IS NULL AND content IS NOT NULL"
        )
        print(f"done: {done} embedded, {remaining} still NULL")
        return 0 if remaining == 0 else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
