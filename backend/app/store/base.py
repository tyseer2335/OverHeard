"""EvidenceStore interface + shared, storage-agnostic logic.

The interface is what the job worker, the query/challenge engine, and the
ElevenLabs webhook tools depend on. Two implementations exist: Elasticsearch
(primary) and in-memory (fallback). Everything that is pure computation —
Reciprocal Rank Fusion, assembling ``Theme`` objects from raw counts, turning a
stored document into an ``EvidenceItem`` — lives here so both implementations
stay thin and behave identically.
"""
from __future__ import annotations

import abc
from collections import defaultdict
from typing import Iterable, Optional, Sequence

from app.models import (
    Counts,
    EvidenceItem,
    FeedbackDoc,
    FeedbackKind,
    ResearchJob,
    Sentiment,
    SentimentBreakdown,
    Theme,
    ThreadConcentration,
    Ticket,
)

POLARITY = {Sentiment.positive: 1, Sentiment.negative: -1}


# --------------------------------------------------------------------------- RRF
def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion.

    Each input is an ordered list of document ids (best first). A document's
    fused score is the sum over lists of ``1 / (k + rank)``. This is how we
    combine lexical (BM25) and semantic rankings into one hybrid result without
    having to reconcile their incompatible score scales.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return dict(scores)


# ---------------------------------------------------------------- doc -> evidence
def evidence_from_doc(doc: dict, score: float = 0.0) -> EvidenceItem:
    span = doc.get("evidence_span") or doc.get("summary") or doc.get("text", "")
    snippet = (span or "").strip()
    if len(snippet) > 320:
        snippet = snippet[:317] + "…"
    return EvidenceItem(
        doc_id=doc.get("id") or doc.get("_id") or "",
        source=doc.get("source", ""),
        thread_id=doc.get("thread_id", ""),
        thread_title=doc.get("thread_title", ""),
        url=doc.get("url", ""),
        author=doc.get("author", ""),
        created_at=doc.get("created_at"),
        snippet=snippet,
        overall_sentiment=_as_sentiment(doc.get("overall_sentiment")),
        kind=_as_kind(doc.get("kind")),
        aspects=list(doc.get("aspect_keys", []) or []),
        score=round(float(score), 5),
    )


def _as_sentiment(v) -> Sentiment:
    try:
        return Sentiment(v)
    except (ValueError, TypeError):
        return Sentiment.neutral


def _as_kind(v) -> FeedbackKind:
    try:
        return FeedbackKind(v)
    except (ValueError, TypeError):
        return FeedbackKind.other


# ------------------------------------------------------- themes from raw counts
def build_themes(
    aspect_sentiment_counts: dict[str, dict[str, int]],
    aspect_thread_counts: dict[str, dict[str, int]],
    top_n: int = 8,
) -> list[Theme]:
    """Assemble ranked Theme objects.

    * ``aspect_sentiment_counts``: {aspect: {sentiment: count}}
    * ``aspect_thread_counts``: {aspect: {thread_id: count}}
    """
    themes: list[Theme] = []
    for aspect, sent_counts in aspect_sentiment_counts.items():
        breakdown = SentimentBreakdown(
            positive=sent_counts.get("positive", 0),
            negative=sent_counts.get("negative", 0),
            mixed=sent_counts.get("mixed", 0),
            neutral=sent_counts.get("neutral", 0),
        )
        total = breakdown.total
        if total == 0:
            continue
        net = (breakdown.positive - breakdown.negative) / total
        threads = aspect_thread_counts.get(aspect, {})
        thread_count = len(threads)
        top_thread_id, top_thread_docs = (None, 0)
        if threads:
            top_thread_id, top_thread_docs = max(threads.items(), key=lambda kv: kv[1])
        themes.append(
            Theme(
                key=aspect,
                doc_count=total,
                sentiment=breakdown,
                net_sentiment=round(net, 3),
                thread_count=thread_count,
                top_thread_id=top_thread_id,
                top_thread_share=round(top_thread_docs / total, 3) if total else 0.0,
            )
        )
    # Rank by overall volume (most-discussed themes first) so the theme overview
    # includes both the big complaints and notable praise; ties broken by how
    # negative the theme is. Complaint-specific ordering happens in the evidence
    # cards, which come from dedicated sentiment-filtered searches.
    themes.sort(key=lambda t: (t.doc_count, t.sentiment.negative), reverse=True)
    return themes[:top_n]


def concentration_verdict(top_thread_share: float, thread_count: int) -> str:
    if top_thread_share >= 0.5 or thread_count <= 1:
        return "concentrated"
    if top_thread_share <= 0.25 and thread_count >= 4:
        return "widespread"
    return "mixed"


# ------------------------------------------------------------------- interface
class EvidenceStore(abc.ABC):
    kind: str = "base"

    @abc.abstractmethod
    async def ready(self) -> bool: ...

    @abc.abstractmethod
    async def ensure_setup(self) -> None: ...

    # jobs -----------------------------------------------------------------
    @abc.abstractmethod
    async def save_job(self, job: ResearchJob) -> None: ...

    @abc.abstractmethod
    async def get_job(self, research_id: str) -> Optional[ResearchJob]: ...

    # documents ------------------------------------------------------------
    @abc.abstractmethod
    async def index_docs(self, docs: list[FeedbackDoc]) -> int: ...

    @abc.abstractmethod
    async def delete_research(self, research_id: str) -> None: ...

    # retrieval ------------------------------------------------------------
    @abc.abstractmethod
    async def search(
        self,
        research_id: str,
        *,
        text: Optional[str] = None,
        query_embedding: Optional[list[float]] = None,
        top_k: int = 8,
        aspect: Optional[str] = None,
        sentiment: Optional[Sentiment] = None,
        kind: Optional[FeedbackKind] = None,
        excluded_threads: Iterable[str] = (),
    ) -> list[EvidenceItem]: ...

    # aggregations ---------------------------------------------------------
    @abc.abstractmethod
    async def themes(
        self, research_id: str, *, excluded_threads: Iterable[str] = (), top_n: int = 8
    ) -> list[Theme]: ...

    @abc.abstractmethod
    async def counts(
        self, research_id: str, *, excluded_threads: Iterable[str] = ()
    ) -> Counts: ...

    @abc.abstractmethod
    async def thread_concentration(
        self, research_id: str, aspect: Optional[str], *, excluded_threads: Iterable[str] = ()
    ) -> ThreadConcentration: ...

    @abc.abstractmethod
    async def thread_title(self, research_id: str, thread_id: str) -> str: ...

    # tickets --------------------------------------------------------------
    @abc.abstractmethod
    async def save_ticket(self, ticket: Ticket) -> None: ...

    @abc.abstractmethod
    async def get_ticket(self, ticket_id: str) -> Optional[Ticket]: ...
