"""Offline fixtures adapter — the reliable demo path.

Reads curated corpora from ``backend/data/fixtures/*.json`` and matches the
research subject against each file's ``subject``/``aliases``. Items carry a
``gold`` enrichment hint so the pipeline produces crisp, deterministic themes
even with no OpenAI key.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.ingestion.base import EventCb, SourceAdapter
from app.models import RawItem, ResearchRequest

log = logging.getLogger("voxmarket.ingest.fixtures")
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"


class FixturesAdapter(SourceAdapter):
    name = "fixtures"

    def available(self) -> bool:
        return FIXTURES_DIR.exists()

    def _load_matching(self, subject: str) -> list[dict]:
        subject_l = subject.strip().lower()
        matches: list[dict] = []
        for path in sorted(FIXTURES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping bad fixture %s: %s", path.name, exc)
                continue
            names = [data.get("subject", "").lower(), *[a.lower() for a in data.get("aliases", [])]]
            if any(subject_l == n or (n and n in subject_l) for n in names if n):
                matches.append(data)
        return matches

    async def collect(self, request: ResearchRequest, on_event: EventCb = None) -> list[RawItem]:
        datasets = self._load_matching(request.subject)
        if not datasets:
            log.info("no fixture matches subject %r", request.subject)
            return []
        items: list[RawItem] = []
        for data in datasets:
            for raw in data.get("items", []):
                created = raw.get("created_at")
                items.append(
                    RawItem(
                        source=self.name,
                        source_id=raw["source_id"],
                        thread_id=raw["thread_id"],
                        thread_title=raw.get("thread_title", ""),
                        url=raw.get("url", ""),
                        author=raw.get("author", ""),
                        text=raw["text"],
                        created_at=datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if created
                        else None,
                        score=raw.get("score", 0),
                        extra={"gold": raw.get("gold")} if raw.get("gold") else {},
                    )
                )
        if on_event:
            await on_event("source_collected", {"source": self.name, "items": len(items)})
        log.info("fixtures collected %d items for %r", len(items), request.subject)
        return items
