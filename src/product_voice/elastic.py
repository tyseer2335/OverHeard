from collections.abc import Iterable
from hashlib import sha256
from typing import Any

from elasticsearch import Elasticsearch, helpers

from .models import EnrichedComment


INDEX_SETTINGS: dict[str, Any] = {
    "settings": {
        "analysis": {
            "analyzer": {
                "comment_english": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                }
            }
        },
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "id": {"type": "keyword"},
            "product": {"type": "keyword"},
            "search_query": {"type": "keyword"},
            "video_id": {"type": "keyword"},
            "video_title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "channel_id": {"type": "keyword"},
            "channel_title": {"type": "keyword"},
            "video_published_at": {"type": "date"},
            "parent_id": {"type": "keyword"},
            "author": {"type": "keyword", "ignore_above": 256},
            "text": {"type": "text", "analyzer": "comment_english"},
            "like_count": {"type": "integer"},
            "reply_count": {"type": "integer"},
            "published_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "sentiment": {"type": "keyword"},
            "sentiment_score": {"type": "float"},
            "is_complaint": {"type": "boolean"},
            "issue_categories": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        },
    },
}


class CommentStore:
    def __init__(self, client: Elasticsearch, index: str) -> None:
        self.client = client
        self.index = index

    def ensure_index(self) -> None:
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, **INDEX_SETTINGS)

    def index_comments(self, comments: Iterable[EnrichedComment]) -> int:
        actions = (
            {
                "_op_type": "index",
                "_index": self.index,
                # The same video can be discovered for multiple products. Preserve
                # each product association while keeping same-product reruns idempotent.
                "_id": sha256(
                    f"{comment.product.casefold()}\0{comment.id}".encode("utf-8")
                ).hexdigest(),
                "_source": comment.model_dump(mode="json"),
            }
            for comment in comments
        )
        success, _ = helpers.bulk(self.client, actions, raise_on_error=True)
        return success

    def analytics(self, product: str) -> dict[str, Any]:
        response = self.client.search(
            index=self.index,
            size=0,
            query={"term": {"product": product}},
            aggs={
                "sentiment": {"terms": {"field": "sentiment", "size": 3}},
                "issues": {"terms": {"field": "issue_categories", "size": 20}},
                "videos": {
                    "terms": {"field": "video_id", "size": 10},
                    "aggs": {
                        "title": {"top_hits": {"size": 1, "_source": ["video_title"]}},
                        "avg_sentiment": {"avg": {"field": "sentiment_score"}},
                    },
                },
                "over_time": {
                    "date_histogram": {
                        "field": "published_at",
                        "calendar_interval": "month",
                        "min_doc_count": 1,
                    }
                },
                "complaint_rate": {"filter": {"term": {"is_complaint": True}}},
                "avg_sentiment": {"avg": {"field": "sentiment_score"}},
                "avg_likes": {"avg": {"field": "like_count"}},
            },
        )
        total = response["hits"]["total"]["value"]
        aggs = response["aggregations"]
        complaints = aggs["complaint_rate"]["doc_count"]
        return {
            "product": product,
            "total_comments": total,
            "complaint_count": complaints,
            "complaint_rate": round(complaints / total, 4) if total else 0,
            "average_sentiment": aggs["avg_sentiment"]["value"],
            "average_likes": aggs["avg_likes"]["value"],
            "sentiment": self._buckets(aggs["sentiment"]["buckets"]),
            "issues": self._buckets(aggs["issues"]["buckets"]),
            "timeline": [
                {"month": bucket["key_as_string"], "count": bucket["doc_count"]}
                for bucket in aggs["over_time"]["buckets"]
            ],
            "videos": [
                {
                    "video_id": bucket["key"],
                    "title": bucket["title"]["hits"]["hits"][0]["_source"]["video_title"],
                    "comment_count": bucket["doc_count"],
                    "average_sentiment": bucket["avg_sentiment"]["value"],
                }
                for bucket in aggs["videos"]["buckets"]
            ],
        }

    def search_comments(
        self, product: str, query: str | None, complaints_only: bool, limit: int
    ) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = [{"term": {"product": product}}]
        if complaints_only:
            filters.append({"term": {"is_complaint": True}})
        must = [{"match": {"text": query}}] if query else []
        response = self.client.search(
            index=self.index,
            size=limit,
            query={"bool": {"filter": filters, "must": must}},
            sort=[{"like_count": "desc"}, {"published_at": "desc"}],
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    @staticmethod
    def _buckets(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"name": item["key"], "count": item["doc_count"]} for item in buckets]


def create_elastic_client(
    api_key: str, cloud_id: str | None, url: str | None
) -> Elasticsearch:
    if cloud_id:
        return Elasticsearch(cloud_id=cloud_id, api_key=api_key)
    return Elasticsearch(hosts=[url], api_key=api_key)  # type: ignore[list-item]
