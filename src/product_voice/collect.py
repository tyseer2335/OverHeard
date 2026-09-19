"""Multi-source collection with dedupe and a rejects log.

Deliberately independent of Elasticsearch and Supabase: collection has to be
runnable and debuggable before any storage exists. ``collect()`` returns
everything in memory and the CLI writes JSONL.

The rejects log is not incidental — it is the record of what the raw feed
actually looked like before filtering, which is the evidence that the pipeline
does real cleaning rather than just summarizing a tidy input.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .sources.base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.collect")

MIN_TEXT_LEN = 25
#: Boilerplate that shows up in scraped pages and adds no opinion signal.
JUNK_MARKERS = (
    "subscribe to our newsletter",
    "accept all cookies",
    "sign in to continue",
    "log in to continue",
    "enable javascript",
    "your browser is not supported",
    "[deleted]",
    "[removed]",
)


@dataclass
class Rejection:
    reason: str
    source: str
    text: str
    id: str = ""


@dataclass
class SourceReport:
    """Per-source outcome, so a partial run is still legible."""

    name: str
    status: str  # "ok" | "skipped" | "failed"
    collected: int = 0
    kept: int = 0
    detail: str = ""


@dataclass
class CollectionResult:
    product: str
    query: str
    documents: list[SourceDocument] = field(default_factory=list)
    rejects: list[Rejection] = field(default_factory=list)
    reports: list[SourceReport] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def by_source(self) -> dict[str, int]:
        return dict(Counter(doc.source for doc in self.documents))

    @property
    def reject_reasons(self) -> dict[str, int]:
        return dict(Counter(r.reason for r in self.rejects))

    def summary(self) -> str:
        lines = [
            f"product         : {self.product}",
            f"query           : {self.query}",
            f"kept            : {len(self.documents)}",
            f"rejected        : {len(self.rejects)}",
            "",
            "per source:",
        ]
        for report in self.reports:
            mark = {"ok": "+", "skipped": "-", "failed": "!"}.get(report.status, "?")
            line = f"  [{mark}] {report.name:<12} {report.status:<8}"
            if report.status == "ok":
                line += f" collected={report.collected} kept={report.kept}"
            if report.detail:
                line += f"  ({report.detail})"
            lines.append(line)
        if self.rejects:
            lines.append("")
            lines.append("rejects by reason:")
            for reason, count in sorted(
                self.reject_reasons.items(), key=lambda kv: -kv[1]
            ):
                lines.append(f"  {reason:<22} {count}")
        return "\n".join(lines)


def _is_junk(text: str) -> str | None:
    """Return a rejection reason, or None if the text looks like a real opinion."""
    stripped = text.strip()
    lowered = stripped.casefold()
    # Specific reasons are checked before the generic length rule: a bare URL is
    # usually under the length floor too, and "link_only" is the honest label.
    # The rejects log is demo evidence, so the reason has to be the real one.
    if stripped.startswith("http") and len(stripped.split()) < 5:
        return "link_only"
    if any(marker in lowered for marker in JUNK_MARKERS):
        return "boilerplate"
    if len(stripped) < MIN_TEXT_LEN:
        return "too_short"
    return None


def collect(
    sources: list[SourceAdapter],
    product: str,
    query: str = "",
    limit_per_source: int = 100,
) -> CollectionResult:
    """Run every adapter, normalize, dedupe and filter into one corpus."""
    effective_query = query or product
    result = CollectionResult(product=product, query=effective_query)

    seen_ids: set[str] = set()
    seen_text: set[str] = set()

    for adapter in sources:
        ok, reason = adapter.available()
        if not ok:
            log.info("source %s unavailable: %s", adapter.name, reason)
            result.reports.append(
                SourceReport(adapter.name, "skipped", detail=reason)
            )
            continue

        try:
            docs = list(adapter.collect(product, effective_query, limit_per_source))
        except SourceError as exc:
            log.warning("source %s failed: %s", adapter.name, exc)
            result.reports.append(SourceReport(adapter.name, "failed", detail=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - never let one source kill the run
            log.exception("source %s crashed", adapter.name)
            result.reports.append(
                SourceReport(adapter.name, "failed", detail=f"{type(exc).__name__}: {exc}")
            )
            continue

        kept = 0
        for doc in docs:
            if doc.id in seen_ids:
                result.rejects.append(
                    Rejection("duplicate_id", doc.source, doc.text[:200], doc.id)
                )
                continue
            reason_junk = _is_junk(doc.text)
            if reason_junk:
                result.rejects.append(
                    Rejection(reason_junk, doc.source, doc.text[:200], doc.id)
                )
                continue
            # Cross-source text dedupe: the same opinion quoted on two platforms.
            key = doc.dedupe_key
            if key in seen_text:
                result.rejects.append(
                    Rejection("duplicate_text", doc.source, doc.text[:200], doc.id)
                )
                continue

            seen_ids.add(doc.id)
            seen_text.add(key)
            result.documents.append(doc)
            kept += 1

        result.reports.append(
            SourceReport(adapter.name, "ok", collected=len(docs), kept=kept)
        )
        log.info("source %s: collected=%d kept=%d", adapter.name, len(docs), kept)

    return result


def collect_plan(
    plan,
    limit_per_query: int = 200,
    *,
    browserbase_targets: list[str] | None = None,
    max_videos: int = 5,
    use_proxies: bool = False,
) -> CollectionResult:
    """Execute a :class:`~product_voice.planner.CollectionPlan`.

    Runs every (source, query) pair and merges the results through one shared
    dedupe pass. This is where volume comes from: N queries against a source
    reach far more of its corpus than one query can, and the different phrasings
    surface different complaint vocabulary.
    """
    from .sources import build_sources

    result = CollectionResult(product=plan.product, query=f"{len(plan.sources)} sources")
    seen_ids: set[str] = set()
    seen_text: set[str] = set()

    for source_plan in plan.sources:
        adapters = build_sources(
            [source_plan.name],
            browserbase_targets=browserbase_targets,
            max_videos=max_videos,
            use_proxies=use_proxies,
        )
        if not adapters:
            result.reports.append(
                SourceReport(source_plan.name, "skipped", detail="unknown source")
            )
            continue
        adapter = adapters[0]

        ok, reason = adapter.available()
        if not ok:
            result.reports.append(SourceReport(adapter.name, "skipped", detail=reason))
            continue

        collected = kept = 0
        failures: list[str] = []

        for query in source_plan.queries:
            try:
                docs = list(adapter.collect(plan.product, query, limit_per_query))
            except SourceError as exc:
                failures.append(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001
                log.exception("source %s crashed on %r", adapter.name, query)
                failures.append(f"{type(exc).__name__}: {exc}")
                continue

            collected += len(docs)
            for doc in docs:
                if doc.id in seen_ids:
                    result.rejects.append(
                        Rejection("duplicate_id", doc.source, doc.text[:200], doc.id)
                    )
                    continue
                junk = _is_junk(doc.text)
                if junk:
                    result.rejects.append(
                        Rejection(junk, doc.source, doc.text[:200], doc.id)
                    )
                    continue
                key = doc.dedupe_key
                if key in seen_text:
                    result.rejects.append(
                        Rejection("duplicate_text", doc.source, doc.text[:200], doc.id)
                    )
                    continue
                seen_ids.add(doc.id)
                seen_text.add(key)
                result.documents.append(doc)
                kept += 1

        if collected == 0 and failures:
            result.reports.append(
                SourceReport(adapter.name, "failed", detail=failures[0])
            )
        else:
            detail = f"{len(source_plan.queries)} queries"
            if failures:
                detail += f", {len(failures)} query failures"
            result.reports.append(
                SourceReport(adapter.name, "ok", collected=collected, kept=kept, detail=detail)
            )
        log.info("%s: collected=%d kept=%d", adapter.name, collected, kept)

    return result
