"""Async research-job worker — the state machine.

QUEUED → DISCOVERING → COLLECTING → CLEANING → ENRICHING → INDEXING → READY
Terminal: READY | PARTIAL | FAILED | CANCELLED

Runs in-process as an asyncio task (no Kafka/Celery — a hackathon doesn't need
them). Each source succeeds or fails independently; if some succeed and some
fail the job ends PARTIAL so useful evidence is still available.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone

from app import runtime
from app.config import settings
from app.enrich.embed import embed_texts
from app.enrich.extract import enrich_items
from app.enrich.narrate import narrate_headline
from app.ingestion.registry import resolve_sources
from app.models import (
    Enrichment,
    FeedbackDoc,
    RawItem,
    ResearchJob,
    ResearchRequest,
    ResearchStatus,
    StepLog,
)
from app.store import get_store

log = logging.getLogger("voxmarket.worker")

_TASKS: set[asyncio.Task] = set()
_WS = re.compile(r"\s+")


def now() -> datetime:
    return datetime.now(timezone.utc)


def launch_job(job: ResearchJob, request: ResearchRequest) -> None:
    """Fire-and-forget: schedule the job and keep a ref so it isn't GC'd."""
    task = asyncio.create_task(run_research(job, request))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def start_research(request: ResearchRequest) -> ResearchJob:
    """Create a QUEUED job, persist it, mark it as the latest (for the UI), and
    launch the background worker. Shared by the HTTP API and the voice tool."""
    store = get_store()
    job = ResearchJob(
        research_id=f"res_{uuid.uuid4().hex[:10]}",
        status=ResearchStatus.QUEUED,
        subject=request.subject,
        question=request.question,
        competitors=request.competitors,
        date_range=request.date_range,
        sources_requested=request.sources,
        created_at=now(),
        updated_at=now(),
    )
    await store.save_job(job)
    runtime.set_latest_research(job.research_id)
    launch_job(job, request)
    return job


async def run_research(job: ResearchJob, request: ResearchRequest) -> None:
    store = get_store()

    async def advance(status: ResearchStatus, detail: str = "") -> None:
        job.status = status
        job.updated_at = now()
        job.progress.append(StepLog(status=status, at=job.updated_at, detail=detail))
        await store.save_job(job)
        log.info("[%s] %s %s", job.research_id, status.value, detail)

    async def on_event(kind: str, payload: dict) -> None:
        if kind == "browser_session":
            job.browser_live_view_url = payload.get("live_view_url")
            await store.save_job(job)

    try:
        # ---- DISCOVERING -------------------------------------------------
        await advance(ResearchStatus.DISCOVERING, "resolving sources")
        adapters = resolve_sources(request.sources)
        job.sources_requested = [a.name for a in adapters]
        job.queries_used = [request.subject, request.question]
        await store.save_job(job)

        # ---- COLLECTING --------------------------------------------------
        await advance(ResearchStatus.COLLECTING, f"{len(adapters)} source(s)")
        raw: list[RawItem] = []
        for adapter in adapters:
            try:
                items = await adapter.collect(request, on_event=on_event)
                raw.extend(items)
                job.sources_completed.append(adapter.name)
                await advance(ResearchStatus.COLLECTING, f"{adapter.name}: {len(items)} items")
            except Exception as exc:  # noqa: BLE001
                job.sources_failed.append(adapter.name)
                log.warning("source %s failed: %s", adapter.name, exc)
                await advance(ResearchStatus.COLLECTING, f"{adapter.name} FAILED: {exc}")

        if not raw:
            job.error = "no data collected from any source"
            await advance(ResearchStatus.FAILED, job.error)
            job.completed_at = now()
            await store.save_job(job)
            return

        # ---- CLEANING ----------------------------------------------------
        await advance(ResearchStatus.CLEANING, f"{len(raw)} raw items")
        cleaned = _dedupe(raw)
        await advance(ResearchStatus.CLEANING, f"{len(cleaned)} after dedupe")

        # ---- ENRICHING ---------------------------------------------------
        await advance(ResearchStatus.ENRICHING, "structuring feedback")
        enrichments = await enrich_items(cleaned, request.subject)
        docs = _build_docs(job.research_id, cleaned, enrichments)
        await _maybe_embed(docs)

        # ---- INDEXING ----------------------------------------------------
        await advance(ResearchStatus.INDEXING, f"indexing {len(docs)} docs")
        await store.delete_research(job.research_id)  # idempotent re-runs
        await store.index_docs(docs)

        counts = await store.counts(job.research_id)
        themes = await store.themes(job.research_id, top_n=10)
        job.document_count = counts.total
        job.thread_count = counts.thread_count
        job.evidence_version += 1
        try:
            job.headline = await narrate_headline(request.subject, request.question, themes, counts)
        except Exception as exc:  # noqa: BLE001
            log.warning("headline failed: %s", exc)

        # ---- terminal ----------------------------------------------------
        terminal = (
            ResearchStatus.PARTIAL if job.sources_failed and job.sources_completed
            else ResearchStatus.READY
        )
        job.completed_at = now()
        await advance(terminal, f"{job.document_count} docs / {job.thread_count} threads")

    except Exception as exc:  # noqa: BLE001
        log.exception("research job crashed")
        job.error = str(exc)
        job.completed_at = now()
        await advance(ResearchStatus.FAILED, str(exc))


# --------------------------------------------------------------------------- helpers
def _norm_text(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def _dedupe(items: list[RawItem]) -> list[RawItem]:
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        h = hashlib.sha1(f"{it.thread_id}|{_norm_text(it.text)}".encode()).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        it.extra["dedupe_hash"] = h
        out.append(it)
    return out


def _build_docs(
    research_id: str, items: list[RawItem], enrichments: list[Enrichment]
) -> list[FeedbackDoc]:
    docs: list[FeedbackDoc] = []
    for it, en in zip(items, enrichments):
        aspect_keys = sorted({a.aspect for a in en.aspects})
        aspect_sentiments = sorted({f"{a.aspect}:{a.sentiment.value}" for a in en.aspects})
        docs.append(
            FeedbackDoc(
                id=f"{research_id}:{it.source}:{it.source_id}",
                research_id=research_id,
                source=it.source,
                source_id=it.source_id,
                thread_id=it.thread_id,
                thread_title=it.thread_title,
                url=it.url,
                author=it.author,
                created_at=it.created_at,
                text=it.text,
                dedupe_hash=it.extra.get("dedupe_hash", ""),
                relevant=en.relevant,
                subject_match=en.subject_match,
                kind=en.kind,
                overall_sentiment=en.overall_sentiment,
                aspects=en.aspects,
                aspect_keys=aspect_keys,
                aspect_sentiments=aspect_sentiments,
                summary=en.summary,
                evidence_span=en.evidence_span,
                ambiguous=en.ambiguous,
            )
        )
    return docs


async def _maybe_embed(docs: list[FeedbackDoc]) -> None:
    """Populate embeddings for the dense_vector path. No-op in semantic_text mode
    (ES embeds) or when OpenAI is unconfigured (BM25-only)."""
    if settings.es_use_semantic_text:
        return
    texts = [f"{d.thread_title}. {d.text}" for d in docs]
    vectors = await embed_texts(texts)
    if not vectors:
        return
    for d, v in zip(docs, vectors):
        d.embedding = v
