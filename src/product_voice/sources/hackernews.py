"""Hacker News adapter — Algolia HN Search API.

The most reliable source in the project: no auth, no key, no rate-limit pain,
and HN comments skew technical and blunt, which is exactly the kind of
opinionated text the analysis layer wants.

Algolia caps ``hitsPerPage`` at 100 but exposes ~10 pages, so a query can yield
~1000 items per tag rather than the 100 a single request returns.

Docs: https://hn.algolia.com/api
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Iterable

import httpx

from .base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.sources.hackernews")

BASE_URL = "https://hn.algolia.com/api/v1/search"
_TAG_RE = re.compile(r"<[^>]+>")
MIN_LEN = 30  # skip "+1" / "this" noise
MAX_PAGES = 10  # Algolia's practical ceiling


def _clean(html: str) -> str:
    """Algolia returns comment_text as HTML fragments."""
    text = _TAG_RE.sub(" ", html or "")
    return (
        text.replace("&#x27;", "'")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#x2F;", "/")
        .strip()
    )


class HackerNewsSource(SourceAdapter):
    name = "hackernews"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=20.0)

    def collect(self, product: str, query: str, limit: int) -> Iterable[SourceDocument]:
        docs: list[SourceDocument] = []
        # Comments carry the opinions; stories give context and headline framing.
        for tag in ("comment", "story"):
            if len(docs) >= limit:
                break
            for page in range(MAX_PAGES):
                if len(docs) >= limit:
                    break
                try:
                    response = self.client.get(
                        BASE_URL,
                        params={
                            "query": query,
                            "tags": tag,
                            "hitsPerPage": 100,
                            "page": page,
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    if page:
                        # Already collected something — keep it rather than fail.
                        log.warning("hackernews %s page %d failed: %s", tag, page, exc)
                        break
                    raise SourceError(f"hackernews {tag} search failed: {exc}") from exc

                payload = response.json()
                hits = payload.get("hits", [])
                if not hits:
                    break
                docs.extend(
                    self._parse(hits, product, query, tag, limit - len(docs))
                )
                if page + 1 >= payload.get("nbPages", 1):
                    break

        log.info("hackernews collected %d docs for %r", len(docs), query)
        return docs

    def _parse(
        self, hits: list[dict], product: str, query: str, tag: str, remaining: int
    ) -> list[SourceDocument]:
        docs: list[SourceDocument] = []
        for hit in hits:
            if len(docs) >= remaining:
                break
            text = _clean(
                hit.get("comment_text") or hit.get("story_text") or hit.get("title") or ""
            )
            if len(text) < MIN_LEN:
                continue
            object_id = hit.get("objectID")
            created = hit.get("created_at_i")
            docs.append(
                SourceDocument(
                    id=f"hackernews_{object_id}",
                    source=self.name,
                    product=product,
                    search_query=query,
                    text=text,
                    author=hit.get("author") or "unknown",
                    url=f"https://news.ycombinator.com/item?id={object_id}",
                    score=int(hit.get("points") or 0),
                    reply_count=int(hit.get("num_comments") or 0),
                    created_at=(
                        datetime.fromtimestamp(created, tz=UTC) if created else None
                    ),
                    parent_id=(str(hit["parent_id"]) if hit.get("parent_id") else None),
                    thread_id=str(hit.get("story_id") or object_id),
                    thread_title=hit.get("story_title") or hit.get("title") or "",
                    container_id="news.ycombinator.com",
                    container_title="Hacker News",
                    extra={"tag": tag},
                )
            )
        return docs
