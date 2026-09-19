"""Source adapter registry."""
from __future__ import annotations

import logging

from app.ingestion.base import SourceAdapter
from app.ingestion.browserbase import BrowserbaseAdapter
from app.ingestion.fixtures import FixturesAdapter
from app.ingestion.reddit import RedditAdapter

log = logging.getLogger("voxmarket.ingest")

_ADAPTERS: dict[str, SourceAdapter] = {
    a.name: a
    for a in (FixturesAdapter(), RedditAdapter(), BrowserbaseAdapter())
}


def get_adapter(name: str) -> SourceAdapter | None:
    return _ADAPTERS.get(name)


def resolve_sources(names: list[str]) -> list[SourceAdapter]:
    """Map requested source names to available adapters, dropping unavailable ones.

    Always guarantees at least the fixtures adapter so a job can never end up with
    zero sources during a demo.
    """
    resolved: list[SourceAdapter] = []
    for name in names:
        adapter = _ADAPTERS.get(name)
        if adapter is None:
            log.warning("unknown source %r — skipping", name)
            continue
        if not adapter.available():
            log.warning("source %r unavailable (missing keys/deps) — skipping", name)
            continue
        resolved.append(adapter)
    if not resolved:
        log.info("no requested sources available — defaulting to fixtures")
        resolved.append(_ADAPTERS["fixtures"])
    return resolved
