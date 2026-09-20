"""Product feedback collection: many sources -> normalize -> enrich -> index.

Replaces the YouTube-only ``IngestionService``. The API calls this with just a
product; everything else is preset, because "how many videos" and "comments per
video" stopped being meaningful once YouTube became one source among several.
Steam has no videos, Hacker News has no comments-per-video, and asking the user
to size a YouTube quota is asking them to tune the wrong dial.

Depth presets below trade collection time against corpus size. ``standard`` is
the default and takes roughly a minute; ``deep`` is for an overnight or
pre-demo run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .collect import CollectionResult, collect, collect_plan
from .enrich import enrich_records
from .feedback import from_source_documents
from .feedback_store import FeedbackStore
from .llm_analysis import LLMAnalyzer
from .planner import CollectionPlan, fallback_plan, plan_collection

log = logging.getLogger("product_voice.collect_service")


@dataclass(frozen=True)
class Depth:
    """A collection preset. Replaces per-source knobs in the UI.

    ``max_queries`` matters more than ``limit_per_query`` for wall-clock time:
    every query is a separate round trip per source, so 5 queries across 4
    sources is 20 sequential network passes regardless of how small each one
    is. Quick keeps it to 2.
    """

    name: str
    limit_per_query: int
    max_videos: int
    use_planner: bool
    max_queries: int
    sources: list[str] | None = None


DEPTHS: dict[str, Depth] = {
    # Quick is for "does this product have signal at all" — the two free,
    # fastest sources, two queries each.
    "quick": Depth(
        "quick",
        limit_per_query=60,
        max_videos=2,
        use_planner=False,
        max_queries=2,
        sources=["hackernews", "youtube"],
    ),
    "standard": Depth(
        "standard", limit_per_query=200, max_videos=5, use_planner=True, max_queries=4
    ),
    "deep": Depth(
        "deep", limit_per_query=500, max_videos=8, use_planner=True, max_queries=6
    ),
}
DEFAULT_DEPTH = "standard"


@dataclass
class SourceOutcome:
    source: str
    status: str
    collected: int
    kept: int
    detail: str = ""


@dataclass
class CollectionOutcome:
    """What a run produced. Source-shaped, not video-shaped."""

    product: str
    depth: str
    documents_collected: int
    documents_indexed: int
    documents_rejected: int
    relevant: int
    sources: list[SourceOutcome]
    reject_reasons: dict[str, int]
    plan_reasoning: str = ""
    used_llm_planner: bool = False


class FeedbackCollectionService:
    def __init__(
        self,
        store: FeedbackStore,
        analyzer: LLMAnalyzer | None = None,
        browserbase_targets: list[str] | None = None,
    ) -> None:
        self.store = store
        self.analyzer = analyzer or LLMAnalyzer()
        self.browserbase_targets = browserbase_targets

    def collect_for_product(
        self,
        product_name: str,
        organization_id: str,
        product_id: str,
        depth: str = DEFAULT_DEPTH,
        search_query: str | None = None,
    ) -> CollectionOutcome:
        preset = DEPTHS.get(depth, DEPTHS[DEFAULT_DEPTH])

        plan = self._build_plan(product_name, search_query, preset)
        result = self._run(plan, preset)

        records = from_source_documents(result.documents, organization_id, product_id)
        records = enrich_records(records, product_name, self.analyzer)

        self.store.ensure_index()
        stats = self.store.index_records(records)

        return CollectionOutcome(
            product=product_name,
            depth=preset.name,
            documents_collected=len(result.documents),
            documents_indexed=stats["indexed"],
            documents_rejected=len(result.rejects),
            relevant=sum(1 for r in records if r.relevant),
            sources=[
                SourceOutcome(r.name, r.status, r.collected, r.kept, r.detail)
                for r in result.reports
            ],
            reject_reasons=result.reject_reasons,
            plan_reasoning=plan.reasoning,
            used_llm_planner=plan.used_llm,
        )

    # ------------------------------------------------------------------ plan
    def _build_plan(
        self, product_name: str, search_query: str | None, preset: Depth
    ) -> CollectionPlan:
        if not preset.use_planner:
            plan = fallback_plan(search_query or product_name, preset.max_queries)
            if preset.sources:
                plan.sources = [s for s in plan.sources if s.name in preset.sources]
            return plan
        plan = plan_collection(product_name)
        # Cap what the planner asked for; it does not know the depth budget.
        for source_plan in plan.sources:
            del source_plan.queries[preset.max_queries :]
        # The product's saved query is a user-authored hint; make sure it is
        # actually tried rather than silently replaced by the planner's ideas.
        if search_query:
            for source_plan in plan.sources:
                if search_query not in source_plan.queries:
                    source_plan.queries.insert(0, search_query)
        return plan

    def _run(self, plan: CollectionPlan, preset: Depth) -> CollectionResult:
        return collect_plan(
            plan,
            limit_per_query=preset.limit_per_query,
            browserbase_targets=self.browserbase_targets,
            max_videos=preset.max_videos,
        )
