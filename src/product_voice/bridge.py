"""Bridge between the source-agnostic collector and the existing pipeline.

``SourceDocument`` is what adapters emit; ``EnrichedComment`` is what the
Elasticsearch store and the API already speak. This module converts one into
the other and applies the existing ``CommentAnalyzer``, so multi-source data
reaches storage without rewriting the store, the API or the frontend.

Field mapping for non-video sources::

    thread_id      -> video_id          (the container the opinion lives in)
    thread_title   -> video_title
    container_id   -> channel_id
    container_title-> channel_title
    score          -> like_count
    created_at     -> published_at
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from .analysis import CommentAnalyzer
from .models import EnrichedComment
from .sources.base import SourceDocument


def to_enriched_comment(
    doc: SourceDocument,
    analyzer: CommentAnalyzer,
    organization_id: UUID | None = None,
    product_id: UUID | None = None,
) -> EnrichedComment:
    """Convert one collected document into the pipeline's stored shape."""
    # published_at is non-optional downstream; fall back to collection time so a
    # source with no timestamp can still be indexed and recency-sorted.
    published = doc.created_at or doc.collected_at

    return EnrichedComment(
        id=doc.id,
        video_id=doc.thread_id or doc.id,
        parent_id=doc.parent_id,
        author=doc.author,
        text=doc.text,
        like_count=doc.score,
        reply_count=doc.reply_count,
        published_at=published,
        updated_at=published,
        organization_id=organization_id,
        product_id=product_id,
        product=doc.product,
        search_query=doc.search_query,
        source=doc.source,
        url=doc.url,
        video_title=doc.thread_title,
        channel_id=doc.container_id,
        channel_title=doc.container_title,
        video_published_at=doc.created_at,
        **analyzer.analyze(doc.text),
        ingested_at=datetime.now(UTC),
    )


def to_enriched_comments(
    docs: list[SourceDocument],
    analyzer: CommentAnalyzer | None = None,
    organization_id: UUID | None = None,
    product_id: UUID | None = None,
) -> list[EnrichedComment]:
    """Convert a whole collection run."""
    active = analyzer or CommentAnalyzer()
    return [
        to_enriched_comment(doc, active, organization_id, product_id) for doc in docs
    ]
