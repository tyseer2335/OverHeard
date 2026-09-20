"""Lemmy adapter — the Reddit-shaped source that is actually reachable.

Lemmy is a federated Reddit alternative with a public, unauthenticated read
API. It gives the thing Reddit would have given us: threaded community
comments with scores, from people talking to each other rather than writing
review articles. Volume is far lower than Reddit's, but it is real user voice
and it costs nothing.

Queries several instances because federation means each one indexes a
different slice, and any single instance may be down.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import httpx

from .base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.sources.lemmy")

DEFAULT_INSTANCES = ("lemmy.world", "lemmy.ml", "sh.itjust.works")
MIN_LEN = 40


class LemmySource(SourceAdapter):
    name = "lemmy"

    def __init__(
        self,
        instances: list[str] | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.instances = instances or list(DEFAULT_INSTANCES)
        self.client = client or httpx.Client(
            timeout=25.0, headers={"User-Agent": "product-voice/0.1"}
        )

    def collect(self, product: str, query: str, limit: int) -> Iterable[SourceDocument]:
        subject = query or product
        docs: list[SourceDocument] = []
        errors: list[str] = []
        responded = 0
        per_instance = max(1, limit // max(1, len(self.instances)))

        for instance in self.instances:
            if len(docs) >= limit:
                break
            for kind in ("Comments", "Posts"):
                if len(docs) >= limit:
                    break
                try:
                    response = self.client.get(
                        f"https://{instance}/api/v3/search",
                        params={
                            "q": subject,
                            "type_": kind,
                            "sort": "TopAll",
                            "limit": min(50, per_instance),
                        },
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    # Instances go down routinely; that's why we query several.
                    errors.append(f"{instance}/{kind}: {exc}")
                    log.warning("lemmy %s %s failed: %s", instance, kind, exc)
                    continue

                responded += 1
                payload = response.json()
                rows = payload.get("comments" if kind == "Comments" else "posts") or []
                docs.extend(
                    self._parse(rows, kind, instance, product, subject, limit - len(docs))
                )

        # Only a total outage is an error. A healthy instance that simply has
        # nothing to say about this product is a valid empty result.
        if responded == 0 and errors:
            raise SourceError("all lemmy instances failed: " + "; ".join(errors[:3]))
        log.info("lemmy collected %d docs for %r", len(docs), subject)
        return docs

    def _parse(
        self,
        rows: list[dict],
        kind: str,
        instance: str,
        product: str,
        query: str,
        remaining: int,
    ) -> list[SourceDocument]:
        docs: list[SourceDocument] = []
        for row in rows:
            if len(docs) >= remaining:
                break
            if kind == "Comments":
                body = (row.get("comment") or {}).get("content") or ""
                native_id = (row.get("comment") or {}).get("id")
                url = (row.get("comment") or {}).get("ap_id") or ""
                published = (row.get("comment") or {}).get("published")
            else:
                post = row.get("post") or {}
                body = post.get("body") or post.get("name") or ""
                native_id = post.get("id")
                url = post.get("ap_id") or ""
                published = post.get("published")

            text = body.strip()
            if len(text) < MIN_LEN:
                continue

            community = (row.get("community") or {}).get("name", "")
            counts = row.get("counts") or {}
            docs.append(
                SourceDocument(
                    id=f"lemmy_{instance}_{native_id}",
                    source=self.name,
                    product=product,
                    search_query=query,
                    text=text,
                    author=(row.get("creator") or {}).get("name") or "unknown",
                    url=url,
                    score=int(counts.get("score") or 0),
                    reply_count=int(counts.get("child_count") or 0),
                    created_at=_parse_dt(published),
                    thread_id=str((row.get("post") or {}).get("id") or native_id),
                    thread_title=(row.get("post") or {}).get("name") or "",
                    container_id=f"{instance}/c/{community}" if community else instance,
                    container_title=f"c/{community}" if community else instance,
                    extra={"instance": instance, "kind": kind.lower()},
                )
            )
        return docs


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
