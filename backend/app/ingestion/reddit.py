"""Reddit adapter using the public read-only JSON endpoints.

Best-effort: Reddit rate-limits/blocks unauthenticated traffic, so this can
fail — that's fine, the worker records it and the job goes PARTIAL while other
sources still produce evidence. Bounded by ``max_threads`` and a per-thread
comment cap so we stay polite.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.ingestion.base import EventCb, SourceAdapter
from app.models import RawItem, ResearchRequest

log = logging.getLogger("voxmarket.ingest.reddit")

UA = "voxmarket-research/0.1 (HackTheNorth demo; contact: demo@voxmarket.local)"
COMMENTS_PER_THREAD = 12
MIN_LEN = 40  # skip trivially short comments


class RedditAdapter(SourceAdapter):
    name = "reddit"

    async def collect(self, request: ResearchRequest, on_event: EventCb = None) -> list[RawItem]:
        query = request.subject
        items: list[RawItem] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": UA}, timeout=20, follow_redirects=True
        ) as client:
            search = await client.get(
                "https://www.reddit.com/search.json",
                params={"q": query, "sort": "relevance", "t": "year",
                        "limit": min(request.max_threads, 25), "type": "link"},
            )
            search.raise_for_status()
            children = search.json().get("data", {}).get("children", [])
            log.info("reddit search returned %d threads for %r", len(children), query)

            for child in children:
                post = child.get("data", {})
                permalink = post.get("permalink")
                if not permalink:
                    continue
                thread_id = f"reddit_{post.get('id')}"
                title = post.get("title", "")
                url = f"https://www.reddit.com{permalink}"
                # the post's selftext is itself a data point
                if post.get("selftext") and len(post["selftext"]) >= MIN_LEN:
                    items.append(self._mk(post, thread_id, title, url, post["selftext"]))
                # then top comments
                try:
                    items.extend(await self._comments(client, permalink, thread_id, title))
                except Exception as exc:  # noqa: BLE001
                    log.warning("reddit comments failed for %s: %s", permalink, exc)
                if on_event:
                    await on_event("source_progress", {"source": self.name, "items": len(items)})
                await asyncio.sleep(0.6)  # be polite / avoid throttling

        if not items:
            raise RuntimeError("reddit returned no usable items")
        log.info("reddit collected %d items", len(items))
        return items

    async def _comments(self, client, permalink, thread_id, title) -> list[RawItem]:
        resp = await client.get(
            f"https://www.reddit.com{permalink}.json",
            params={"limit": COMMENTS_PER_THREAD, "sort": "top", "depth": 1},
        )
        resp.raise_for_status()
        payload = resp.json()
        out: list[RawItem] = []
        if len(payload) < 2:
            return out
        for c in payload[1].get("data", {}).get("children", []):
            d = c.get("data", {})
            body = d.get("body")
            if not body or len(body) < MIN_LEN or body in ("[deleted]", "[removed]"):
                continue
            url = f"https://www.reddit.com{permalink}{d.get('id','')}"
            out.append(self._mk(d, thread_id, title, url, body))
            if len(out) >= COMMENTS_PER_THREAD:
                break
        return out

    @staticmethod
    def _mk(d: dict, thread_id: str, title: str, url: str, text: str) -> RawItem:
        created = d.get("created_utc")
        return RawItem(
            source="reddit",
            source_id=f"reddit_{d.get('id')}",
            thread_id=thread_id,
            thread_title=title,
            url=url,
            author=f"u/{d.get('author', 'unknown')}",
            text=text,
            created_at=datetime.fromtimestamp(created, tz=timezone.utc) if created else None,
            score=int(d.get("score", 0) or 0),
        )
