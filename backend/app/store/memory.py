"""In-memory EvidenceStore — the graceful-degrade fallback.

Not as fast or as clever as Elasticsearch, but it implements the same contract:
lexical scoring, optional embedding cosine, RRF hybrid fusion, and Python-side
aggregations. This is what keeps the demo alive if ES is unreachable.

Filter semantics for ``search`` (shared with the ES store):
* aspect + sentiment  -> docs whose ``aspect_sentiments`` contains "aspect:sentiment"
* aspect only         -> docs mentioning that aspect
* sentiment only      -> docs whose overall_sentiment matches
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Iterable, Optional

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
from app.store.base import (
    EvidenceStore,
    build_themes,
    concentration_verdict,
    evidence_from_doc,
    rrf_fuse,
)

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryEvidenceStore(EvidenceStore):
    kind = "memory"

    def __init__(self) -> None:
        self._jobs: dict[str, ResearchJob] = {}
        self._docs: dict[str, list[dict]] = defaultdict(list)  # research_id -> docs
        self._tickets: dict[str, Ticket] = {}

    async def ready(self) -> bool:
        return True

    async def ensure_setup(self) -> None:
        return None

    # jobs -----------------------------------------------------------------
    async def save_job(self, job: ResearchJob) -> None:
        self._jobs[job.research_id] = job.model_copy(deep=True)

    async def get_job(self, research_id: str) -> Optional[ResearchJob]:
        job = self._jobs.get(research_id)
        return job.model_copy(deep=True) if job else None

    # documents ------------------------------------------------------------
    async def index_docs(self, docs: list[FeedbackDoc]) -> int:
        for d in docs:
            self._docs[d.research_id].append(d.model_dump())
        return len(docs)

    async def delete_research(self, research_id: str) -> None:
        self._docs.pop(research_id, None)

    def _corpus(self, research_id: str) -> list[dict]:
        return [d for d in self._docs.get(research_id, []) if d.get("relevant", True)]

    # retrieval ------------------------------------------------------------
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
    ) -> list[EvidenceItem]:
        excluded = set(excluded_threads)
        pool = [
            d
            for d in self._corpus(research_id)
            if d.get("thread_id") not in excluded
            and _passes_filters(d, aspect, sentiment, kind)
        ]
        if not pool:
            return []

        # lexical ranking (BM25-lite tf-idf)
        lexical_ids: list[str] = []
        if text:
            lexical_ids = _lexical_rank(pool, text)

        # semantic ranking (cosine)
        semantic_ids: list[str] = []
        if query_embedding:
            scored = [
                (d["id"], _cosine(query_embedding, d.get("embedding") or []))
                for d in pool
                if d.get("embedding")
            ]
            scored.sort(key=lambda kv: kv[1], reverse=True)
            semantic_ids = [i for i, s in scored if s > 0]

        by_id = {d["id"]: d for d in pool}
        if lexical_ids and semantic_ids:
            fused = rrf_fuse([lexical_ids, semantic_ids])
        elif lexical_ids:
            fused = {i: 1.0 / (60 + r) for r, i in enumerate(lexical_ids, 1)}
        elif semantic_ids:
            fused = {i: 1.0 / (60 + r) for r, i in enumerate(semantic_ids, 1)}
        else:
            # no query -> just return the pool (most recent-ish / first) ranked neutrally
            fused = {d["id"]: 0.0 for d in pool}

        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [evidence_from_doc(by_id[i], s) for i, s in ordered]

    # aggregations ---------------------------------------------------------
    async def themes(
        self, research_id: str, *, excluded_threads: Iterable[str] = (), top_n: int = 8
    ) -> list[Theme]:
        excluded = set(excluded_threads)
        aspect_sent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        aspect_thread: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for d in self._corpus(research_id):
            if d.get("thread_id") in excluded:
                continue
            for pair in d.get("aspect_sentiments", []):
                if ":" not in pair:
                    continue
                aspect, sent = pair.split(":", 1)
                aspect_sent[aspect][sent] += 1
                aspect_thread[aspect][d.get("thread_id", "")] += 1
        return build_themes(aspect_sent, aspect_thread, top_n=top_n)

    async def counts(
        self, research_id: str, *, excluded_threads: Iterable[str] = ()
    ) -> Counts:
        excluded = set(excluded_threads)
        sb = SentimentBreakdown()
        kinds: dict[str, int] = defaultdict(int)
        threads: set[str] = set()
        total = 0
        for d in self._corpus(research_id):
            if d.get("thread_id") in excluded:
                continue
            total += 1
            threads.add(d.get("thread_id", ""))
            s = d.get("overall_sentiment", "neutral")
            setattr(sb, s, getattr(sb, s, 0) + 1) if hasattr(sb, s) else None
            kinds[d.get("kind", "other")] += 1
        return Counts(total=total, by_sentiment=sb, by_kind=dict(kinds), thread_count=len(threads))

    async def thread_concentration(
        self, research_id: str, aspect: Optional[str], *, excluded_threads: Iterable[str] = ()
    ) -> ThreadConcentration:
        excluded = set(excluded_threads)
        thread_docs: dict[str, int] = defaultdict(int)
        thread_titles: dict[str, str] = {}
        total = 0
        for d in self._corpus(research_id):
            tid = d.get("thread_id", "")
            if tid in excluded:
                continue
            if aspect and aspect not in (d.get("aspect_keys") or []):
                continue
            total += 1
            thread_docs[tid] += 1
            thread_titles.setdefault(tid, d.get("thread_title", ""))
        if not thread_docs:
            return ThreadConcentration(aspect=aspect, verdict="mixed")
        top_id, top_docs = max(thread_docs.items(), key=lambda kv: kv[1])
        share = top_docs / total if total else 0.0
        return ThreadConcentration(
            aspect=aspect,
            total_docs=total,
            thread_count=len(thread_docs),
            top_thread_id=top_id,
            top_thread_title=thread_titles.get(top_id, ""),
            top_thread_docs=top_docs,
            top_thread_share=round(share, 3),
            verdict=concentration_verdict(share, len(thread_docs)),
        )

    async def thread_title(self, research_id: str, thread_id: str) -> str:
        for d in self._docs.get(research_id, []):
            if d.get("thread_id") == thread_id:
                return d.get("thread_title", "")
        return ""

    # tickets --------------------------------------------------------------
    async def save_ticket(self, ticket: Ticket) -> None:
        self._tickets[ticket.ticket_id] = ticket.model_copy(deep=True)

    async def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        t = self._tickets.get(ticket_id)
        return t.model_copy(deep=True) if t else None


# --------------------------------------------------------------------------- helpers
def _passes_filters(
    d: dict,
    aspect: Optional[str],
    sentiment: Optional[Sentiment],
    kind: Optional[FeedbackKind],
) -> bool:
    if not d.get("subject_match", True):
        return False
    if kind and d.get("kind") != kind.value:
        return False
    if aspect and sentiment:
        return f"{aspect}:{sentiment.value}" in (d.get("aspect_sentiments") or [])
    if aspect:
        return aspect in (d.get("aspect_keys") or [])
    if sentiment:
        return d.get("overall_sentiment") == sentiment.value
    return True


def _lexical_rank(pool: list[dict], query: str) -> list[str]:
    q_terms = _tokens(query)
    if not q_terms:
        return []
    n = len(pool)
    df: dict[str, int] = defaultdict(int)
    doc_terms: list[tuple[str, list[str]]] = []
    for d in pool:
        toks = _tokens(f"{d.get('text','')} {d.get('thread_title','')} {d.get('summary','')}")
        doc_terms.append((d["id"], toks))
        for t in set(toks):
            df[t] += 1
    scores: list[tuple[str, float]] = []
    for doc_id, toks in doc_terms:
        if not toks:
            continue
        tf: dict[str, int] = defaultdict(int)
        for t in toks:
            tf[t] += 1
        score = 0.0
        for qt in q_terms:
            if qt in tf:
                idf = math.log(1 + n / (1 + df[qt]))
                score += (tf[qt] / (tf[qt] + 1.5)) * idf  # simple BM25-ish saturation
        if score > 0:
            scores.append((doc_id, score))
    scores.sort(key=lambda kv: kv[1], reverse=True)
    return [i for i, _ in scores]
