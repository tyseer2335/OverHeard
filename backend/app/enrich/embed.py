"""OpenAI embeddings for the dense_vector retrieval path.

Returns None when no key is configured — the store then falls back to BM25-only,
so semantic search simply degrades rather than breaking. (In ES semantic_text
mode, embeddings happen inside Elasticsearch and these functions aren't used.)
"""
from __future__ import annotations

import logging

from app.config import settings
from app.enrich.openai_client import get_openai

log = logging.getLogger("voxmarket.embed")
_EMBED_BATCH = 128


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    client = get_openai()
    if client is None or not texts:
        return None
    out: list[list[float]] = []
    try:
        for i in range(0, len(texts), _EMBED_BATCH):
            chunk = [t[:8000] or " " for t in texts[i : i + _EMBED_BATCH]]
            resp = await client.embeddings.create(
                model=settings.openai_embed_model, input=chunk
            )
            out.extend(d.embedding for d in resp.data)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding failed (%s) — continuing without vectors", exc)
        return None


async def embed_query(text: str) -> list[float] | None:
    res = await embed_texts([text])
    return res[0] if res else None
