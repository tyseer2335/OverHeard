"""Index mappings + creation.

The feedback index has two flavors of semantic field, chosen at setup time:

* ``ES_USE_SEMANTIC_TEXT=true``  -> a ``semantic_text`` field backed by an
  inference endpoint (Elastic Cloud / event deployment does the embedding).
* otherwise -> a ``dense_vector`` field we populate with OpenAI embeddings.

Either way there is always an analyzed ``text`` field for BM25, so lexical
search (and therefore the whole demo) works even with no embeddings at all.
"""
from __future__ import annotations

import logging

from elasticsearch import AsyncElasticsearch

from app.config import settings

log = logging.getLogger("voxmarket.es")


def feedback_mapping() -> dict:
    props: dict = {
        "research_id": {"type": "keyword"},
        "source": {"type": "keyword"},
        "source_id": {"type": "keyword"},
        "thread_id": {"type": "keyword"},
        "thread_title": {
            "type": "text",
            "fields": {"raw": {"type": "keyword", "ignore_above": 512}},
        },
        "url": {"type": "keyword"},
        "author": {"type": "keyword"},
        "created_at": {"type": "date"},
        "text": {"type": "text", "analyzer": "english"},
        "summary": {"type": "text", "analyzer": "english"},
        "evidence_span": {"type": "text", "analyzer": "english"},
        "relevant": {"type": "boolean"},
        "subject_match": {"type": "boolean"},
        "kind": {"type": "keyword"},
        "overall_sentiment": {"type": "keyword"},
        "aspect_keys": {"type": "keyword"},
        "aspect_sentiments": {"type": "keyword"},
        "ambiguous": {"type": "boolean"},
        "dedupe_hash": {"type": "keyword"},
    }
    if settings.es_use_semantic_text:
        # ES handles embedding + kNN internally via the inference endpoint.
        props["semantic"] = {
            "type": "semantic_text",
            "inference_id": settings.es_inference_id,
        }
    else:
        props["embedding"] = {
            "type": "dense_vector",
            "dims": settings.openai_embed_dims,
            "index": True,
            "similarity": "cosine",
        }
    return {"properties": props}


async def _ensure(es: AsyncElasticsearch, name: str, body: dict) -> None:
    if await es.indices.exists(index=name):
        log.info("index %s already exists", name)
        return
    await es.indices.create(index=name, **body)
    log.info("created index %s", name)


async def ensure_indices(es: AsyncElasticsearch) -> None:
    await _ensure(es, settings.feedback_index, {"mappings": feedback_mapping()})
    await _ensure(
        es,
        settings.jobs_index,
        {
            "mappings": {
                "dynamic": True,
                "properties": {
                    "research_id": {"type": "keyword"},
                    "status": {"type": "keyword"},
                    "subject": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "completed_at": {"type": "date"},
                },
            }
        },
    )
    await _ensure(
        es,
        settings.tickets_index,
        {
            "mappings": {
                "dynamic": True,
                "properties": {
                    "ticket_id": {"type": "keyword"},
                    "research_id": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "status": {"type": "keyword"},
                },
            }
        },
    )
