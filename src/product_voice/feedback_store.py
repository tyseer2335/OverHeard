"""Tenant-aware Elasticsearch store for normalized feedback.

One shared index for every organization, product and source, filtered on
``organization_id`` / ``product_id`` / ``source`` — not one index per product.
Per-product indices multiply shards, make cross-product analytics impossible,
and turn every new product into an ops task.

Design notes
------------
**Duplicate prevention** is structural, not a post-pass: ``_id`` is a
deterministic hash of (org, product, source, external_id), so re-ingesting an
item overwrites it. Connectors can safely replay from a checkpoint.

**Analytics never pool sources blindly.** Every aggregate returns a
``by_source`` breakdown beside the total, because a Steam review feed and a
YouTube comment section carry different audience and ranking bias — a single
pooled number reads as precision the data doesn't have.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Sequence

from elasticsearch import Elasticsearch, helpers

from .feedback import FeedbackRecord

log = logging.getLogger("product_voice.feedback_store")

DEFAULT_INDEX = "product-feedback"

FEEDBACK_MAPPING: dict[str, Any] = {
    "settings": {
        "analysis": {
            "analyzer": {
                "feedback_english": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        # Strict: a connector that invents a field should fail loudly at
        # ingest rather than silently create an unqueryable mapping.
        "dynamic": "strict",
        "properties": {
            "organization_id": {"type": "keyword"},
            "product_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "external_id": {"type": "keyword"},
            "url": {"type": "keyword", "ignore_above": 2048},
            "content": {"type": "text", "analyzer": "feedback_english"},
            "content_type": {"type": "keyword"},
            "language": {"type": "keyword"},
            "published_at": {"type": "date"},
            "author_hash": {"type": "keyword"},
            "engagement": {
                "properties": {
                    "score": {"type": "integer"},
                    "replies": {"type": "integer"},
                    "voted_up": {"type": "boolean"},
                    "playtime_hours": {"type": "integer"},
                }
            },
            "sentiment": {"type": "keyword"},
            "sentiment_score": {"type": "float"},
            "is_complaint": {"type": "boolean"},
            "issue_categories": {"type": "keyword"},
            "relevant": {"type": "boolean"},
            "content_hash": {"type": "keyword"},
            # Source-specific extras. Not indexed as searchable fields — they
            # vary per connector and would pollute a strict mapping.
            "source_metadata": {"type": "object", "enabled": False},
            "ingested_at": {"type": "date"},
        },
    },
}


class FeedbackStore:
    def __init__(self, client: Elasticsearch, index: str = DEFAULT_INDEX) -> None:
        self.client = client
        self.index = index

    # ------------------------------------------------------------ lifecycle
    def ensure_index(self) -> bool:
        """Create the index if absent; additively patch it if present."""
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, **FEEDBACK_MAPPING)
            log.info("created index %s", self.index)
            return True
        # Additive only — existing fields are never redefined.
        self.client.indices.put_mapping(
            index=self.index,
            properties=FEEDBACK_MAPPING["mappings"]["properties"],
        )
        return False

    # -------------------------------------------------------------- writing
    def index_records(
        self,
        records: Iterable[FeedbackRecord],
        chunk_size: int = 500,
        max_retries: int = 3,
    ) -> dict[str, int]:
        """Bulk-index with retry. Returns {indexed, failed}.

        Uses deterministic ids, so a retry or a replayed checkpoint updates
        the existing document instead of creating a second copy.
        """
        actions = []
        for record in records:
            body = record.model_dump(mode="json")
            body["content_hash"] = record.content_hash
            actions.append(
                {
                    "_op_type": "index",
                    "_index": self.index,
                    "_id": record.document_id,
                    "_source": body,
                }
            )
        if not actions:
            return {"indexed": 0, "failed": 0}

        indexed = failed = 0
        attempt = 0
        pending = actions
        while pending and attempt <= max_retries:
            if attempt:
                # Exponential backoff: 429s from a busy cluster are transient.
                delay = 2 ** attempt
                log.warning("retry %d for %d docs after %ss", attempt, len(pending), delay)
                time.sleep(delay)
            ok, errors = helpers.bulk(
                self.client,
                pending,
                chunk_size=chunk_size,
                raise_on_error=False,
                stats_only=False,
            )
            indexed += ok
            retryable = []
            for err in errors or []:
                info = err.get("index", {}) if isinstance(err, dict) else {}
                status = info.get("status", 0)
                if status in (429, 503):
                    doc_id = info.get("_id")
                    match = next((a for a in pending if a["_id"] == doc_id), None)
                    if match:
                        retryable.append(match)
                        continue
                failed += 1
                log.warning("permanent index failure: %s", str(info.get("error"))[:200])
            pending = retryable
            attempt += 1

        failed += len(pending)
        self.client.indices.refresh(index=self.index)
        log.info("indexed=%d failed=%d into %s", indexed, failed, self.index)
        return {"indexed": indexed, "failed": failed}

    def delete_product(self, organization_id: str, product_id: str) -> int:
        """Delete everything for one product — GDPR/reset path."""
        response = self.client.delete_by_query(
            index=self.index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"organization_id": organization_id}},
                        {"term": {"product_id": product_id}},
                    ]
                }
            },
            refresh=True,
        )
        return int(response.get("deleted", 0))

    # -------------------------------------------------------------- reading
    def _tenant_filter(
        self,
        organization_id: str | None,
        product_id: str | None,
        sources: Sequence[str] | None = None,
        language: str | None = None,
        since: str | None = None,
        relevant_only: bool = True,
    ) -> list[dict]:
        filters: list[dict] = []
        if relevant_only:
            # Collection casts wide on purpose, so an off-topic row is expected
            # rather than exceptional. Excluding relevant=false keeps it out of
            # the numbers while leaving it indexed and auditable.
            # must_not (rather than term relevant=true) so rows indexed before
            # enrichment existed, where relevant is null, still count.
            filters.append({"bool": {"must_not": {"term": {"relevant": False}}}})
        if organization_id:
            filters.append({"term": {"organization_id": organization_id}})
        if product_id:
            filters.append({"term": {"product_id": product_id}})
        if sources:
            filters.append({"terms": {"source": list(sources)}})
        if language:
            filters.append({"term": {"language": language}})
        if since:
            filters.append({"range": {"published_at": {"gte": since}}})
        return filters

    def search(
        self,
        organization_id: str | None = None,
        product_id: str | None = None,
        query: str | None = None,
        sources: Sequence[str] | None = None,
        complaints_only: bool = False,
        language: str | None = None,
        since: str | None = None,
        limit: int = 20,
        relevant_only: bool = True,
    ) -> list[dict]:
        filters = self._tenant_filter(
            organization_id, product_id, sources, language, since, relevant_only
        )
        if complaints_only:
            filters.append({"term": {"is_complaint": True}})
        must = [{"match": {"content": query}}] if query else []
        response = self.client.search(
            index=self.index,
            size=limit,
            query={"bool": {"filter": filters, "must": must}},
            sort=(
                ["_score"]
                if query
                else [{"engagement.score": "desc"}, {"published_at": "desc"}]
            ),
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def analytics(
        self,
        organization_id: str | None = None,
        product_id: str | None = None,
        sources: Sequence[str] | None = None,
        language: str | None = None,
        since: str | None = None,
        relevant_only: bool = True,
    ) -> dict[str, Any]:
        """Totals **plus** a per-source breakdown of each one.

        The breakdown is not optional decoration. Pooling a Steam review feed
        with a YouTube comment section produces a number whose meaning depends
        entirely on the mix, so the caller always gets both.
        """
        filters = self._tenant_filter(
            organization_id, product_id, sources, language, since, relevant_only
        )

        per_source_aggs = {
            "complaints": {"filter": {"term": {"is_complaint": True}}},
            "avg_sentiment": {"avg": {"field": "sentiment_score"}},
            "issues": {"terms": {"field": "issue_categories", "size": 10}},
            "authors": {"cardinality": {"field": "author_hash"}},
        }

        response = self.client.search(
            index=self.index,
            size=0,
            query={"bool": {"filter": filters}} if filters else {"match_all": {}},
            aggs={
                "by_source": {
                    "terms": {"field": "source", "size": 20},
                    "aggs": per_source_aggs,
                },
                "by_content_type": {"terms": {"field": "content_type", "size": 10}},
                "by_language": {"terms": {"field": "language", "size": 10}},
                "issues": {"terms": {"field": "issue_categories", "size": 20}},
                "sentiment": {"terms": {"field": "sentiment", "size": 5}},
                "complaints": {"filter": {"term": {"is_complaint": True}}},
                "avg_sentiment": {"avg": {"field": "sentiment_score"}},
                "authors": {"cardinality": {"field": "author_hash"}},
                "over_time": {
                    "date_histogram": {
                        "field": "published_at",
                        "calendar_interval": "month",
                        "min_doc_count": 1,
                    },
                    "aggs": {"by_source": {"terms": {"field": "source", "size": 10}}},
                },
            },
        )

        total = response["hits"]["total"]["value"]
        aggs = response["aggregations"]

        by_source = []
        for bucket in aggs["by_source"]["buckets"]:
            count = bucket["doc_count"]
            complaints = bucket["complaints"]["doc_count"]
            by_source.append(
                {
                    "source": bucket["key"],
                    "count": count,
                    "share": round(count / total, 4) if total else 0,
                    "complaints": complaints,
                    "complaint_rate": round(complaints / count, 4) if count else 0,
                    "average_sentiment": bucket["avg_sentiment"]["value"],
                    "distinct_authors": bucket["authors"]["value"],
                    "top_issues": [
                        {"name": b["key"], "count": b["doc_count"]}
                        for b in bucket["issues"]["buckets"]
                    ],
                }
            )

        complaints_total = aggs["complaints"]["doc_count"]
        return {
            "total": total,
            "complaints": complaints_total,
            "complaint_rate": round(complaints_total / total, 4) if total else 0,
            "average_sentiment": aggs["avg_sentiment"]["value"],
            "distinct_authors": aggs["authors"]["value"],
            # Always beside the totals — see docstring.
            "by_source": by_source,
            "by_content_type": _buckets(aggs["by_content_type"]),
            "by_language": _buckets(aggs["by_language"]),
            "sentiment": _buckets(aggs["sentiment"]),
            "issues": _buckets(aggs["issues"]),
            "timeline": [
                {
                    "month": b["key_as_string"],
                    "count": b["doc_count"],
                    "by_source": _buckets(b["by_source"]),
                }
                for b in aggs["over_time"]["buckets"]
            ],
        }

    def duplicate_report(
        self, organization_id: str | None = None, product_id: str | None = None
    ) -> list[dict]:
        """Texts appearing more than once, possibly across different sources."""
        filters = self._tenant_filter(organization_id, product_id)
        response = self.client.search(
            index=self.index,
            size=0,
            query={"bool": {"filter": filters}} if filters else {"match_all": {}},
            aggs={
                "dupes": {
                    "terms": {
                        "field": "content_hash",
                        "size": 20,
                        "min_doc_count": 2,
                        "order": {"_count": "desc"},
                    },
                    "aggs": {
                        "sources": {"terms": {"field": "source", "size": 5}},
                        "sample": {"top_hits": {"size": 1, "_source": ["content", "url"]}},
                    },
                }
            },
        )
        out = []
        for bucket in response["aggregations"]["dupes"]["buckets"]:
            hit = bucket["sample"]["hits"]["hits"][0]["_source"]
            out.append(
                {
                    "count": bucket["doc_count"],
                    "sources": _buckets(bucket["sources"]),
                    "text": hit.get("content", "")[:160],
                    "url": hit.get("url", ""),
                }
            )
        return out


def _buckets(agg: dict) -> list[dict]:
    return [{"name": b["key"], "count": b["doc_count"]} for b in agg["buckets"]]


def create_client(
    api_key: str, cloud_id: str | None = None, url: str | None = None
) -> Elasticsearch:
    if cloud_id:
        return Elasticsearch(cloud_id=cloud_id, api_key=api_key)
    return Elasticsearch(hosts=[url], api_key=api_key)  # type: ignore[list-item]
