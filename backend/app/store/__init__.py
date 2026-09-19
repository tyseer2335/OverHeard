"""Evidence store selection.

Prefers real Elasticsearch (the primary prize + the demo story). Falls back to a
pure-Python in-memory store if ES can't be reached, so a flaky venue network or a
cold Docker daemon can't hard-fail the demo.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.store.base import EvidenceStore
from app.store.memory import MemoryEvidenceStore

log = logging.getLogger("voxmarket.store")

_store: EvidenceStore | None = None


async def init_store() -> EvidenceStore:
    """Pick and set up the store. Call once at startup."""
    global _store
    if _store is not None:
        return _store

    if settings.es_enabled:
        try:
            from app.es.client import close_es, es_ping
            from app.store.elastic import ElasticEvidenceStore

            if await es_ping():
                store = ElasticEvidenceStore()
                await store.ensure_setup()
                _store = store
                log.info("Using ElasticEvidenceStore")
                return _store
            log.warning("Elasticsearch unreachable — falling back to in-memory store")
            await close_es()  # don't leak the aiohttp session
        except Exception as exc:  # noqa: BLE001
            log.warning("Elasticsearch init failed (%s) — using in-memory store", exc)
            try:
                from app.es.client import close_es

                await close_es()
            except Exception:  # noqa: BLE001
                pass

    _store = MemoryEvidenceStore()
    await _store.ensure_setup()
    log.info("Using MemoryEvidenceStore (fallback)")
    return _store


def get_store() -> EvidenceStore:
    if _store is None:
        raise RuntimeError("store not initialized — call init_store() at startup")
    return _store


def set_store(store: EvidenceStore) -> None:
    """Test/seed hook."""
    global _store
    _store = store
