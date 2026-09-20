"""Balanced retrieval.

Engagement is not comparable across sources — measured on one product,
YouTube's top scores were 8843/8288/7453 while Steam's were 4/3/2 and
Browserbase's were 0. A global sort returned 100/100 YouTube, so the other
sources never reached the UI and the multi-source claim was hollow.
"""
from __future__ import annotations

from product_voice.feedback_store import FeedbackStore


class _FakeES:
    """Minimal stand-in for the aggregation calls _balanced_search makes."""

    def __init__(self, per_source: dict[str, int]) -> None:
        self.per_source = per_source

    def search(self, **kwargs):
        aggs = kwargs.get("aggs") or {}
        buckets = [
            {"key": name, "doc_count": count}
            for name, count in self.per_source.items()
        ]
        if "top" in (aggs.get("sources", {}).get("aggs") or {}):
            size = aggs["sources"]["aggs"]["top"]["top_hits"]["size"]
            for bucket in buckets:
                name = bucket["key"]
                bucket["top"] = {
                    "hits": {
                        "hits": [
                            {"_source": {"source": name, "external_id": f"{name}-{i}"}}
                            for i in range(min(size, self.per_source[name]))
                        ]
                    }
                }
        return {"aggregations": {"sources": {"buckets": buckets}}, "hits": {"hits": []}}


def test_balanced_search_splits_the_quota_across_sources() -> None:
    store = FeedbackStore(_FakeES({"youtube": 800, "steam": 300, "browserbase": 90}), "idx")
    rows = store.search(product_id="p", limit=30)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["source"]] = counts.get(row["source"], 0) + 1

    assert len(rows) == 30
    # no source may monopolize the result the way the global sort did
    assert max(counts.values()) <= 10 + 1
    assert set(counts) == {"youtube", "steam", "browserbase"}


def test_balanced_search_interleaves_so_the_top_rows_are_mixed() -> None:
    store = FeedbackStore(_FakeES({"youtube": 50, "steam": 50, "browserbase": 50}), "idx")
    rows = store.search(product_id="p", limit=9)
    # the first three rows should be one from each source, not three YouTube
    assert len({row["source"] for row in rows[:3]}) == 3


def test_balanced_search_handles_a_single_source() -> None:
    store = FeedbackStore(_FakeES({"youtube": 12}), "idx")
    rows = store.search(product_id="p", limit=10)
    assert len(rows) == 10
    assert {row["source"] for row in rows} == {"youtube"}


def test_balanced_search_on_an_empty_corpus() -> None:
    assert FeedbackStore(_FakeES({}), "idx").search(product_id="p", limit=10) == []
