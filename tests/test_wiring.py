"""Wiring tests.

These exist because a real 500 shipped: `collect_service` still built a VADER
`CommentAnalyzer` and handed it to `enrich_records`, which by then expected an
`LLMAnalyzer`. Every unit test passed — nothing asserted that the pieces fit
together, so the break only surfaced when a user clicked the button.
"""
from __future__ import annotations

import inspect

from product_voice.collect_service import DEPTHS, FeedbackCollectionService
from product_voice.enrich import enrich_records
from product_voice.feedback import from_source_documents
from product_voice.llm_analysis import AnalysisResult, LLMAnalyzer
from product_voice.sources.base import SourceDocument


class _StubLLM:
    """Stands in for LLMAnalyzer without any network access."""

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def analyze_many(self, texts, product):
        self.calls += 1
        return [AnalysisResult(relevant=True, sentiment="negative", kind="complaint") for _ in texts]


def _doc(i: int = 1) -> SourceDocument:
    return SourceDocument(
        id=f"hackernews_{i}",
        source="hackernews",
        product="Widget",
        text="The app crashes every morning and support never replies.",
    )


def test_service_default_analyzer_satisfies_the_enrich_contract() -> None:
    """The analyzer the service builds must expose what enrich_records calls."""
    service = FeedbackCollectionService(store=None)  # type: ignore[arg-type]

    assert isinstance(service.analyzer, LLMAnalyzer)
    for method in ("available", "analyze_many"):
        assert callable(getattr(service.analyzer, method, None)), (
            f"service analyzer is missing {method}() that enrich_records calls"
        )


def test_enrich_accepts_what_the_service_holds() -> None:
    service = FeedbackCollectionService(store=None, analyzer=_StubLLM())  # type: ignore[arg-type]
    records = from_source_documents([_doc()], "org", "prod")

    enrich_records(records, "Widget", service.analyzer)

    assert records[0].relevant is True
    assert records[0].is_complaint is True


def test_every_depth_preset_is_complete() -> None:
    """A preset missing a field fails only at collection time otherwise."""
    for name, depth in DEPTHS.items():
        assert depth.max_queries >= 1, name
        assert depth.limit_per_query >= 1, name
        assert depth.max_videos >= 1, name
        assert isinstance(depth.use_planner, bool), name


def test_collect_for_product_signature_matches_the_api_call() -> None:
    """api.collect_feedback calls this with exactly these keywords."""
    params = inspect.signature(
        FeedbackCollectionService.collect_for_product
    ).parameters
    for expected in ("product_name", "organization_id", "product_id", "depth", "search_query"):
        assert expected in params, f"api.py passes {expected}= but the service dropped it"
