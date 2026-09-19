"""Elasticsearch EvidenceStore — the primary evidence layer.

This is where the "Elastic isn't storing the answer, it's the evidence layer"
story lives:

* lexical BM25 (``multi_match``) and semantic (kNN over dense_vector, or a
  ``semantic`` query over a ``semantic_text`` field) are run as two separate
  searches and fused with Reciprocal Rank Fusion — robust hybrid retrieval on
  any ES 8.x.
* themes / sentiment / thread concentration come from aggregations, never from
  the LLM.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable, Optional

from app.config import settings
from app.es.client import es_ping, get_es
from app.es.indices import ensure_indices
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

log = logging.getLogger("voxmarket.store.es")
_SRC_EXCLUDE = ["embedding"]


class ElasticEvidenceStore(EvidenceStore):
    kind = "elasticsearch"

    def __init__(self) -> None:
        self.es = get_es()

    async def ready(self) -> bool:
        return await es_ping()

    async def ensure_setup(self) -> None:
        await ensure_indices(self.es)

    # jobs -----------------------------------------------------------------
    async def save_job(self, job: ResearchJob) -> None:
        await self.es.index(
            index=settings.jobs_index,
            id=job.research_id,
            document=job.model_dump(mode="json"),
            refresh=True,
        )

    async def get_job(self, research_id: str) -> Optional[ResearchJob]:
        try:
            resp = await self.es.get(index=settings.jobs_index, id=research_id)
        except Exception:  # noqa: BLE001  (NotFoundError etc.)
            return None
        return ResearchJob.model_validate(resp["_source"])

    # documents ------------------------------------------------------------
    async def index_docs(self, docs: list[FeedbackDoc]) -> int:
        if not docs:
            return 0
        ops: list[dict] = []
        for d in docs:
            body = d.model_dump(mode="json", exclude_none=True)
            emb = body.pop("embedding", None)
            if settings.es_use_semantic_text:
                body["semantic"] = d.text
            elif emb is not None:
                body["embedding"] = emb
            ops.append({"index": {"_index": settings.feedback_index, "_id": d.id}})
            ops.append(body)
        resp = await self.es.bulk(operations=ops, refresh=True)
        if resp.get("errors"):
            n_err = sum(1 for it in resp["items"] if it.get("index", {}).get("error"))
            log.warning("bulk index: %d/%d docs errored", n_err, len(docs))
            first = next((it["index"]["error"] for it in resp["items"]
                          if it.get("index", {}).get("error")), None)
            if first:
                log.warning("first bulk error: %s", first)
        return len(docs)

    async def delete_research(self, research_id: str) -> None:
        await self.es.delete_by_query(
            index=settings.feedback_index,
            query={"term": {"research_id": research_id}},
            refresh=True,
            conflicts="proceed",
        )

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
        filters = self._filters(research_id, aspect, sentiment, kind, excluded_threads)
        fetch = max(top_k * 3, top_k)
        docs: dict[str, dict] = {}
        rankings: list[list[str]] = []

        # --- lexical (BM25) ---
        if text:
            resp = await self.es.search(
                index=settings.feedback_index,
                query={
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": text,
                                    "fields": ["text^2", "thread_title", "summary"],
                                }
                            }
                        ],
                        "filter": filters,
                    }
                },
                size=fetch,
                source_excludes=_SRC_EXCLUDE,
            )
            ids = self._collect(resp, docs)
            if ids:
                rankings.append(ids)

        # --- semantic ---
        sem_resp = None
        if settings.es_use_semantic_text and text:
            sem_resp = await self.es.search(
                index=settings.feedback_index,
                query={
                    "bool": {
                        "must": [{"semantic": {"field": "semantic", "query": text}}],
                        "filter": filters,
                    }
                },
                size=fetch,
                source_excludes=_SRC_EXCLUDE,
            )
        elif query_embedding:
            sem_resp = await self.es.search(
                index=settings.feedback_index,
                knn={
                    "field": "embedding",
                    "query_vector": query_embedding,
                    "k": fetch,
                    "num_candidates": max(100, fetch * 5),
                    "filter": filters,
                },
                size=fetch,
                source_excludes=_SRC_EXCLUDE,
            )
        if sem_resp is not None:
            ids = self._collect(sem_resp, docs)
            if ids:
                rankings.append(ids)

        # --- no query at all: match_all with filters ---
        if not rankings:
            resp = await self.es.search(
                index=settings.feedback_index,
                query={"bool": {"filter": filters}},
                size=top_k,
                source_excludes=_SRC_EXCLUDE,
            )
            ids = self._collect(resp, docs)
            return [evidence_from_doc(docs[i], 0.0) for i in ids[:top_k]]

        # --- fuse ---
        if len(rankings) > 1:
            fused = rrf_fuse(rankings)
        else:
            fused = {i: 1.0 / (60 + r) for r, i in enumerate(rankings[0], 1)}
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
        return [evidence_from_doc(docs[i], s) for i, s in ordered if i in docs]

    # aggregations ---------------------------------------------------------
    async def themes(
        self, research_id: str, *, excluded_threads: Iterable[str] = (), top_n: int = 8
    ) -> list[Theme]:
        filters = self._filters(research_id, None, None, None, excluded_threads)
        filters.append({"exists": {"field": "aspect_keys"}})
        resp = await self.es.search(
            index=settings.feedback_index,
            size=0,
            query={"bool": {"filter": filters}},
            aggs={
                "aspect_sentiments": {"terms": {"field": "aspect_sentiments", "size": 200}},
                "aspects": {
                    "terms": {"field": "aspect_keys", "size": 50},
                    "aggs": {"threads": {"terms": {"field": "thread_id", "size": 100}}},
                },
            },
        )
        aggs = resp["aggregations"]
        aspect_sent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for b in aggs["aspect_sentiments"]["buckets"]:
            key = b["key"]
            if ":" not in key:
                continue
            aspect, sent = key.split(":", 1)
            aspect_sent[aspect][sent] += b["doc_count"]
        aspect_thread: dict[str, dict[str, int]] = defaultdict(dict)
        for b in aggs["aspects"]["buckets"]:
            aspect = b["key"]
            aspect_thread[aspect] = {
                tb["key"]: tb["doc_count"] for tb in b["threads"]["buckets"]
            }
        return build_themes(aspect_sent, aspect_thread, top_n=top_n)

    async def counts(
        self, research_id: str, *, excluded_threads: Iterable[str] = ()
    ) -> Counts:
        filters = self._filters(research_id, None, None, None, excluded_threads)
        resp = await self.es.search(
            index=settings.feedback_index,
            size=0,
            track_total_hits=True,
            query={"bool": {"filter": filters}},
            aggs={
                "sentiment": {"terms": {"field": "overall_sentiment", "size": 10}},
                "kind": {"terms": {"field": "kind", "size": 10}},
                "threads": {"cardinality": {"field": "thread_id"}},
            },
        )
        sb = SentimentBreakdown()
        for b in resp["aggregations"]["sentiment"]["buckets"]:
            if hasattr(sb, b["key"]):
                setattr(sb, b["key"], b["doc_count"])
        kinds = {b["key"]: b["doc_count"] for b in resp["aggregations"]["kind"]["buckets"]}
        total = resp["hits"]["total"]["value"]
        thread_count = resp["aggregations"]["threads"]["value"]
        return Counts(total=total, by_sentiment=sb, by_kind=kinds, thread_count=thread_count)

    async def thread_concentration(
        self, research_id: str, aspect: Optional[str], *, excluded_threads: Iterable[str] = ()
    ) -> ThreadConcentration:
        filters = self._filters(research_id, aspect, None, None, excluded_threads)
        resp = await self.es.search(
            index=settings.feedback_index,
            size=0,
            track_total_hits=True,
            query={"bool": {"filter": filters}},
            aggs={
                "threads": {
                    "terms": {"field": "thread_id", "size": 200},
                    "aggs": {
                        "title": {
                            "top_hits": {"size": 1, "_source": {"includes": ["thread_title"]}}
                        }
                    },
                }
            },
        )
        buckets = resp["aggregations"]["threads"]["buckets"]
        total = resp["hits"]["total"]["value"]
        if not buckets or total == 0:
            return ThreadConcentration(aspect=aspect, verdict="mixed")
        top = buckets[0]  # terms buckets are already sorted by doc_count desc
        title = ""
        hits = top["title"]["hits"]["hits"]
        if hits:
            title = hits[0]["_source"].get("thread_title", "")
        share = top["doc_count"] / total
        return ThreadConcentration(
            aspect=aspect,
            total_docs=total,
            thread_count=len(buckets),
            top_thread_id=top["key"],
            top_thread_title=title,
            top_thread_docs=top["doc_count"],
            top_thread_share=round(share, 3),
            verdict=concentration_verdict(share, len(buckets)),
        )

    async def thread_title(self, research_id: str, thread_id: str) -> str:
        resp = await self.es.search(
            index=settings.feedback_index,
            size=1,
            query={
                "bool": {
                    "filter": [
                        {"term": {"research_id": research_id}},
                        {"term": {"thread_id": thread_id}},
                    ]
                }
            },
            source_includes=["thread_title"],
        )
        hits = resp["hits"]["hits"]
        return hits[0]["_source"].get("thread_title", "") if hits else ""

    # tickets --------------------------------------------------------------
    async def save_ticket(self, ticket: Ticket) -> None:
        await self.es.index(
            index=settings.tickets_index,
            id=ticket.ticket_id,
            document=ticket.model_dump(mode="json"),
            refresh=True,
        )

    async def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        try:
            resp = await self.es.get(index=settings.tickets_index, id=ticket_id)
        except Exception:  # noqa: BLE001
            return None
        return Ticket.model_validate(resp["_source"])

    # helpers --------------------------------------------------------------
    @staticmethod
    def _filters(
        research_id: str,
        aspect: Optional[str],
        sentiment: Optional[Sentiment],
        kind: Optional[FeedbackKind],
        excluded_threads: Iterable[str],
    ) -> list[dict]:
        f: list[dict] = [
            {"term": {"research_id": research_id}},
            {"term": {"subject_match": True}},
        ]
        if aspect and sentiment:
            f.append({"term": {"aspect_sentiments": f"{aspect}:{sentiment.value}"}})
        elif aspect:
            f.append({"term": {"aspect_keys": aspect}})
        elif sentiment:
            f.append({"term": {"overall_sentiment": sentiment.value}})
        if kind:
            f.append({"term": {"kind": kind.value}})
        excluded = list(excluded_threads)
        if excluded:
            f.append({"bool": {"must_not": {"terms": {"thread_id": excluded}}}})
        return f

    @staticmethod
    def _collect(resp, docs: dict[str, dict]) -> list[str]:
        ids: list[str] = []
        for hit in resp["hits"]["hits"]:
            src = dict(hit["_source"])
            src.setdefault("id", hit["_id"])
            docs[hit["_id"]] = src
            ids.append(hit["_id"])
        return ids
