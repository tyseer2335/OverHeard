"""Async Elasticsearch client factory.

Supports both a local Docker node (ELASTICSEARCH_URL) and Elastic Cloud / the
event deployment (ELASTIC_CLOUD_ID + ELASTIC_API_KEY).
"""
from __future__ import annotations

import logging

from elasticsearch import AsyncElasticsearch

from app.config import settings

log = logging.getLogger("voxmarket.es")

_client: AsyncElasticsearch | None = None


def get_es() -> AsyncElasticsearch:
    global _client
    if _client is None:
        if settings.elastic_cloud_id and settings.elastic_api_key:
            log.info("Connecting to Elastic Cloud (cloud_id)")
            _client = AsyncElasticsearch(
                cloud_id=settings.elastic_cloud_id,
                api_key=settings.elastic_api_key,
                request_timeout=60,
            )
        elif settings.elastic_api_key:
            # URL + API key: Elastic Cloud / Serverless endpoint
            log.info("Connecting to Elastic (url + api_key) at %s", settings.elasticsearch_url)
            _client = AsyncElasticsearch(
                hosts=[settings.elasticsearch_url],
                api_key=settings.elastic_api_key,
                request_timeout=60,
            )
        else:
            log.info("Connecting to Elasticsearch at %s", settings.elasticsearch_url)
            _client = AsyncElasticsearch(
                hosts=[settings.elasticsearch_url],
                request_timeout=60,
            )
    return _client


async def es_ping() -> bool:
    """Best-effort connectivity check; never raises."""
    try:
        return await get_es().ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("Elasticsearch ping failed: %s", exc)
        return False


async def close_es() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
