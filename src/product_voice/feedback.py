"""Normalized feedback record — the one shape every connector produces.

Analytics must work identically whether a row came from YouTube, Browserbase,
Steam, Hacker News or Lemmy, so every connector normalizes into
``FeedbackRecord`` before anything downstream sees it.

Two fields carry the weight of the multi-tenant design:

``organization_id`` / ``product_id``
    Every query filters on these. One shared index/data stream, never one
    index per product — per-product indices explode shard counts and make
    cross-product analytics impossible.

``source``
    Kept on every row because sources are **not comparable**. A Steam review
    feed, a YouTube comment section and a Reddit thread have different
    audience and ranking biases, so a raw count pooled across them is
    misleading. Analytics always returns the breakdown beside the total.

``author_hash`` stores a salted digest rather than the username: enough to
count distinct voices and spot one person posting fifty times, without
retaining personal identifiers.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .sources.base import SourceDocument

#: Salt for author hashing. Set AUTHOR_HASH_SALT in production; the default
#: keeps hashes stable across a dev run without pretending to be a secret.
_SALT = os.getenv("AUTHOR_HASH_SALT", "product-voice-dev-salt")

_NON_ASCII = re.compile(r"[^\x00-\x7F]")
_WS = re.compile(r"\s+")

#: How each connector's payload maps onto a content_type.
CONTENT_TYPES = {
    "youtube": "comment",
    "hackernews": "comment",
    "lemmy": "comment",
    "steam": "review",
    "browserbase": "article",
}


def hash_author(author: str | None, source: str) -> str:
    """Salted, source-scoped digest of an author identifier.

    Source-scoped so the same username on two platforms does not collapse into
    one identity, which would be a false claim about who is speaking.
    """
    if not author:
        return ""
    material = f"{_SALT}\0{source}\0{author.strip().casefold()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def guess_language(text: str) -> str:
    """Very cheap language hint.

    Deliberately crude: every connector currently requests English explicitly
    (YouTube ``relevanceLanguage``, Steam ``language=english``), so this exists
    to flag obvious non-English rows rather than to do real detection. Returns
    "en" or "unknown", never a confident wrong answer.
    """
    if not text:
        return "unknown"
    sample = text[:400]
    non_ascii = len(_NON_ASCII.findall(sample))
    if non_ascii > len(sample) * 0.15:
        return "unknown"
    return "en"


class Engagement(BaseModel):
    """Source-relative engagement. Values are NOT comparable across sources."""

    score: int = 0          # upvotes / likes / helpful votes
    replies: int = 0
    # Steam only: the reviewer's own verdict — ground truth for scoring
    # whether inferred sentiment is actually right.
    voted_up: bool | None = None
    playtime_hours: int | None = None


class FeedbackRecord(BaseModel):
    """One piece of feedback, normalized across all connectors."""

    # --- tenancy (every analytics query filters on these) ---
    organization_id: str | None = None
    product_id: str | None = None

    # --- provenance ---
    source: str
    external_id: str                     # the id native to that source
    url: str = ""

    # --- content ---
    content: str
    content_type: str = "comment"        # comment | post | review | article
    language: str = "en"

    # --- signals ---
    published_at: datetime | None = None
    author_hash: str = ""
    engagement: Engagement = Field(default_factory=Engagement)

    # --- enrichment (filled by the analysis layer, optional at ingest) ---
    sentiment: str | None = None
    sentiment_score: float | None = None
    is_complaint: bool | None = None
    issue_categories: list[str] = Field(default_factory=list)
    relevant: bool | None = None

    # --- escape hatch + bookkeeping ---
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def document_id(self) -> str:
        """Deterministic _id — the duplicate-prevention mechanism.

        Re-ingesting the same item overwrites rather than duplicates, so a
        connector can be re-run safely after a crash or a checkpoint replay.
        Scoped by tenant and product because the same public comment can
        legitimately belong to two organizations watching the same product.
        """
        parts = (
            self.organization_id or "-",
            self.product_id or "-",
            self.source,
            self.external_id,
        )
        return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()

    @property
    def content_hash(self) -> str:
        """Digest of normalized text, for cross-source duplicate detection."""
        return hashlib.sha256(
            _WS.sub(" ", self.content).strip().casefold().encode("utf-8")
        ).hexdigest()


def from_source_document(
    doc: SourceDocument,
    organization_id: str | UUID | None = None,
    product_id: str | UUID | None = None,
) -> FeedbackRecord:
    """Convert a collected ``SourceDocument`` into the normalized record."""
    extra = dict(doc.extra or {})

    engagement = Engagement(
        score=doc.score,
        replies=doc.reply_count,
        voted_up=extra.get("voted_up"),
        playtime_hours=extra.get("playtime_hours"),
    )

    # Everything source-specific that isn't a first-class field is preserved
    # here rather than dropped, so a connector can add detail without a
    # mapping change.
    metadata = {
        "thread_id": doc.thread_id,
        "thread_title": doc.thread_title,
        "container_id": doc.container_id,
        "container_title": doc.container_title,
        "search_query": doc.search_query,
        "product_name": doc.product,
        **{k: v for k, v in extra.items() if k not in ("voted_up", "playtime_hours")},
    }

    # Strip empties so source_metadata stays readable in Kibana.
    metadata = {k: v for k, v in metadata.items() if v not in ("", None)}

    return FeedbackRecord(
        organization_id=str(organization_id) if organization_id else None,
        product_id=str(product_id) if product_id else None,
        source=doc.source,
        # doc.id is already "<source>_<native id>"; keep the native part.
        external_id=doc.id.split("_", 1)[-1] if "_" in doc.id else doc.id,
        url=doc.url,
        content=doc.text,
        content_type=CONTENT_TYPES.get(doc.source, "comment"),
        language=guess_language(doc.text),
        published_at=doc.created_at,
        author_hash=hash_author(doc.author, doc.source),
        engagement=engagement,
        source_metadata=metadata,
        ingested_at=doc.collected_at,
    )


def from_source_documents(
    docs: list[SourceDocument],
    organization_id: str | UUID | None = None,
    product_id: str | UUID | None = None,
) -> list[FeedbackRecord]:
    return [from_source_document(d, organization_id, product_id) for d in docs]
