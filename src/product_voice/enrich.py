"""Enrichment applied to normalized records before indexing.

Keeps the existing ``CommentAnalyzer`` (VADER sentiment + keyword issue
categories) and adds **product relevance detection**, which matters more than
it sounds: collection casts wide on purpose, so a corpus for "Notion" contains
rows where "notion" is the English word. Marking those ``relevant=False``
rather than deleting them keeps the rejects visible while stopping them from
polluting sentiment and issue aggregates.

Relevance is **context-aware**, and it has to be. Most real feedback never
repeats the product name — a comment under a Cyberpunk 2077 review saying
"the driving physics feel awful" is obviously on-topic, and a naive
"must mention the product" rule throws away the majority of genuine opinions.
So the container (video title, thread title, review page) counts as evidence
of subject just as much as the text does.
"""
from __future__ import annotations

import re

from .analysis import CommentAnalyzer
from .feedback import FeedbackRecord

#: Sources where every item is collected from a container already known to be
#: about the product (a video found by searching it, a Steam app's own review
#: feed). Absence of the product name here is not evidence of irrelevance.
_CONTEXT_BOUND_SOURCES = {"youtube", "steam"}

#: Words that indicate the product sense rather than the dictionary sense.
_PRODUCT_CONTEXT = (
    "app", "application", "software", "tool", "platform", "product", "device",
    "headphone", "headset", "game", "update", "version", "release", "install",
    "subscription", "pricing", "price", "ui", "ux", "feature", "bug", "crash",
    "workspace", "account", "login", "battery", "firmware", "support",
    "patch", "dlc", "gameplay", "console", "pc", "fps", "review",
)

#: Phrasings where a product name is being used as an ordinary English noun.
_DICTIONARY_SENSE = re.compile(
    r"\b(the|a|an|any|some|this|that|whole|very|no)\s+{term}\b|"
    r"\b{term}\s+(that|of|is\s+that)\b",
)


def _terms(product: str) -> list[str]:
    return [t for t in re.split(r"\W+", product.casefold()) if len(t) > 2]


def _has_word(text: str, word: str) -> bool:
    """Whole-word match.

    Substring matching is a trap here: "app" appears inside "appealing", so
    a plain `in` check marked dictionary-sense prose as product talk.
    """
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def is_relevant(
    text: str,
    product: str,
    source: str = "",
    container_text: str = "",
) -> bool:
    """Whether this row is plausibly about the product.

    ``container_text`` is the thread/video/page title the item came from.
    Conservative by design: wrongly dropping a real complaint is worse than
    keeping some noise.
    """
    if not text or not text.strip():
        return False

    terms = _terms(product)
    if not terms:
        return True

    lowered = text.casefold()
    mentioned = any(term in lowered for term in terms)

    if mentioned:
        # Product-ish vocabulary nearby settles it.
        if any(_has_word(text, word) for word in _PRODUCT_CONTEXT):
            return True
        # Otherwise reject only clear dictionary-sense usage of the name.
        for term in terms:
            if not term.isalpha():
                continue
            pattern = _DICTIONARY_SENSE.pattern.replace("{term}", re.escape(term))
            if re.search(pattern, text, re.IGNORECASE):
                return False
        return True

    # Not mentioned in the text itself — fall back to the container.
    container = (container_text or "").casefold()
    if container and any(term in container for term in terms):
        return True
    # Comments collected from a product-targeted feed are on-topic by
    # construction, even when the container title is missing.
    return source in _CONTEXT_BOUND_SOURCES


def enrich_records(
    records: list[FeedbackRecord],
    product_name: str,
    analyzer: CommentAnalyzer | None = None,
) -> list[FeedbackRecord]:
    """Fill sentiment, complaint flags, issue categories and relevance."""
    active = analyzer or CommentAnalyzer()
    for record in records:
        scores = active.analyze(record.content)
        record.sentiment = scores["sentiment"]
        record.sentiment_score = scores["sentiment_score"]
        record.is_complaint = scores["is_complaint"]
        record.issue_categories = scores["issue_categories"]

        meta = record.source_metadata or {}
        container = " ".join(
            str(meta.get(key, "")) for key in ("thread_title", "container_title")
        )
        record.relevant = is_relevant(
            record.content, product_name, record.source, container
        )
    return records
