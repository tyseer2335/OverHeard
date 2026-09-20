"""Enrichment applied to normalized records before indexing.

Analysis runs through the LLM (``llm_analysis``), which judges relevance,
sentiment, intent and issue categories by reading each comment. The previous
VADER lexicon is kept only as a degraded fallback for when the model is
unreachable, because a collection run that indexes nothing is worse than one
that indexes rows with weak scores.

The difference that matters is relevance. Keyword rules cannot tell "the notion
that..." from "Notion is slow", and they cannot tell that "great video man keep
it up" is about the video rather than the product. Those two failures were most
of the noise in the dashboard.
"""
from __future__ import annotations

import logging

from .feedback import FeedbackRecord
from .llm_analysis import LLMAnalyzer

log = logging.getLogger("product_voice.enrich")


def enrich_records(
    records: list[FeedbackRecord],
    product_name: str,
    analyzer: LLMAnalyzer | None = None,
) -> list[FeedbackRecord]:
    """Fill sentiment, complaint flags, issue categories and relevance."""
    if not records:
        return records

    active = analyzer or LLMAnalyzer()
    if not active.available():
        log.warning("no LLM available — falling back to lexicon analysis")
        return _fallback_enrich(records, product_name)

    results = active.analyze_many([r.content for r in records], product_name)

    unresolved = []
    for record, result in zip(records, results):
        if result.relevant is None and result.sentiment == "neutral" and not result.summary:
            # The model never returned this row; score it with the lexicon
            # rather than silently marking everything neutral.
            unresolved.append(record)
            continue
        record.sentiment = result.sentiment
        record.sentiment_score = result.sentiment_score
        record.is_complaint = result.kind == "complaint"
        record.issue_categories = result.issue_categories
        record.relevant = result.relevant
        if result.summary:
            record.source_metadata["summary"] = result.summary
        record.source_metadata["kind"] = result.kind

    if unresolved:
        log.warning("%d records unanalyzed by LLM — using lexicon", len(unresolved))
        _fallback_enrich(unresolved, product_name)

    return records


def _fallback_enrich(
    records: list[FeedbackRecord], product_name: str
) -> list[FeedbackRecord]:
    """Lexicon scoring, used only when the LLM cannot be reached.

    Relevance is deliberately left as None here rather than guessed: an
    unknown relevance stays visible downstream, which is the safer error when
    the real classifier is unavailable.
    """
    from .analysis import CommentAnalyzer

    lexicon = CommentAnalyzer()
    for record in records:
        scores = lexicon.analyze(record.content)
        record.sentiment = scores["sentiment"]
        record.sentiment_score = scores["sentiment_score"]
        record.is_complaint = scores["is_complaint"]
        record.issue_categories = scores["issue_categories"]
        record.relevant = None
        record.source_metadata["analysis"] = "lexicon_fallback"
    return records
