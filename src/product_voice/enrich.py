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

#: Sources whose container is *verified* to be the product, so a comment that
#: never names it is still on-topic.
#:
#: Steam qualifies: the app id is resolved by exact title lookup, so the review
#: feed is unambiguously that product's. YouTube does NOT — its search is
#: fuzzy, and trusting it blanket-marked comments about hair removal as
#: relevant feedback for a product. YouTube now earns relevance per row by
#: matching the video title instead.
_CONTEXT_BOUND_SOURCES = {"steam"}

#: Characters that end a sentence, so a capital after one proves nothing.
_SENTENCE_END = ".!?\n"

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


def _mentions_near_context(text: str, term: str, window: int = 140) -> bool:
    """Is the product term used *near* product vocabulary?

    Checking the whole document is far too weak: a long political post that
    happens to contain "notion" and, elsewhere, the word "price" would pass.
    Only text close to the mention is evidence about what the mention means.
    """
    lowered = text.casefold()
    for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", lowered):
        start = max(0, match.start() - window)
        chunk = text[start : match.end() + window]
        if any(_has_word(chunk, word) for word in _PRODUCT_CONTEXT):
            return True
    return False


def _appears_as_proper_noun(text: str, term: str) -> bool:
    """Product names are capitalized; the common noun usually is not.

    "Notion is slow" vs "the notion that" — casing separates the two cheaply
    and reliably. Sentence-initial position is ignored, since every word is
    capitalized there regardless of sense.
    """
    for match in re.finditer(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
        if not match.group(0)[:1].isupper():
            continue
        prefix = text[: match.start()].rstrip()
        if prefix and prefix[-1] not in _SENTENCE_END:
            return True  # capitalized mid-sentence -> proper noun
    return False


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
    mentioned = [t for t in terms if t in lowered]

    if mentioned:
        for term in mentioned:
            # A multi-word or non-dictionary name is evidence on its own.
            if len(terms) > 1 or not term.isalpha():
                return True
            if _mentions_near_context(text, term):
                return True
            if _appears_as_proper_noun(text, term):
                return True
        return False

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
