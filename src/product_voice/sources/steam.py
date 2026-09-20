"""Steam reviews adapter — the highest-volume source in the project.

Steam's ``appreviews`` endpoint is public, unauthenticated, cursor-paginated,
and enormous: a popular title has >1.5M English reviews. It also ships
**ground truth** the other sources lack — ``voted_up`` is the author's own
verdict, and ``playtime_forever`` says how much they actually used the product.
That makes it the natural benchmark for whether the analysis layer's inferred
sentiment is any good.

Only applies to games. ``available()`` can't know that, so a product with no
Steam match simply resolves to nothing and the adapter reports zero.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable

import httpx

from .base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.sources.steam")

SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{app_id}"
PER_PAGE = 100
MIN_LEN = 30


class SteamSource(SourceAdapter):
    name = "steam"

    def __init__(
        self,
        app_id: str | None = None,
        client: httpx.Client | None = None,
        review_type: str = "all",
    ) -> None:
        #: Skip the lookup when the caller already knows the app id.
        self.app_id = app_id
        self.review_type = review_type
        self.client = client or httpx.Client(
            timeout=25.0, headers={"User-Agent": "product-voice/0.1"}
        )

    def resolve_app_id(self, product: str) -> str | None:
        """Find the Steam app id for a product name."""
        if self.app_id:
            return self.app_id
        try:
            response = self.client.get(
                SEARCH_URL, params={"term": product, "l": "english", "cc": "US"}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SourceError(f"steam store search failed: {exc}") from exc

        items = response.json().get("items") or []
        if not items:
            log.info("no steam title matches %r", product)
            return None
        log.info("steam matched %r -> %s (%s)", product, items[0]["name"], items[0]["id"])
        return str(items[0]["id"])

    def collect(self, product: str, query: str, limit: int) -> Iterable[SourceDocument]:
        # Resolve on the bare product name, never the planner's qualified query:
        # Steam's storesearch matches titles, so "Cyberpunk 2077" resolves while
        # "Cyberpunk 2077 performance issues" returns nothing at all.
        app_id = self.resolve_app_id(product) or self.resolve_app_id(query)
        if not app_id:
            return []

        docs: list[SourceDocument] = []
        cursor = "*"
        seen_cursors: set[str] = set()

        while len(docs) < limit:
            try:
                response = self.client.get(
                    REVIEWS_URL.format(app_id=app_id),
                    params={
                        "json": 1,
                        "num_per_page": min(PER_PAGE, limit - len(docs)),
                        "filter": "recent",
                        "language": "english",
                        "review_type": self.review_type,
                        "purchase_type": "all",
                        "cursor": cursor,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                if docs:
                    log.warning("steam page failed, keeping %d docs: %s", len(docs), exc)
                    break
                raise SourceError(f"steam reviews failed: {exc}") from exc

            payload = response.json()
            reviews = payload.get("reviews") or []
            if not reviews:
                break

            for review in reviews:
                if len(docs) >= limit:
                    break
                text = (review.get("review") or "").strip()
                if len(text) < MIN_LEN:
                    continue
                author = review.get("author") or {}
                created = review.get("timestamp_created")
                hours = round((author.get("playtime_forever") or 0) / 60)
                docs.append(
                    SourceDocument(
                        id=f"steam_{review.get('recommendationid')}",
                        source=self.name,
                        product=product,
                        search_query=query or product,
                        text=text,
                        author=str(author.get("steamid") or "unknown"),
                        url=(
                            "https://steamcommunity.com/profiles/"
                            f"{author.get('steamid')}/recommended/{app_id}/"
                        ),
                        score=int(review.get("votes_up") or 0),
                        reply_count=int(review.get("comment_count") or 0),
                        created_at=(
                            datetime.fromtimestamp(created, tz=UTC) if created else None
                        ),
                        thread_id=str(app_id),
                        thread_title=f"Steam reviews for app {app_id}",
                        container_id="store.steampowered.com",
                        container_title="Steam",
                        # voted_up is the reviewer's own verdict — ground truth to
                        # score the analysis layer's inferred sentiment against.
                        extra={
                            "voted_up": bool(review.get("voted_up")),
                            "playtime_hours": hours,
                            "early_access": bool(review.get("written_during_early_access")),
                            "steam_purchase": bool(review.get("steam_purchase")),
                        },
                    )
                )

            # Cursors repeat once the feed is exhausted.
            cursor = payload.get("cursor") or ""
            if not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)

        log.info("steam collected %d docs for app %s", len(docs), app_id)
        return docs
