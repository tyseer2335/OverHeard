"""Evidence & analysis engine.

Everything the API/voice tools call to reason over the indexed corpus:
* build the EvidencePacket the UI renders and the agent narrates from
* answer follow-up queries (hybrid retrieval)
* challenge a conclusion (thread-concentration + real counterevidence, recompute)
* exclude/include a thread and recompute
* draft an investigation ticket

Statistics come from Elasticsearch aggregations; the LLM only ever phrases.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.config import settings
from app.enrich.embed import embed_query
from app.enrich.extract import normalize_aspect
from app.enrich.narrate import draft_ticket_fields
from app.models import (
    ChallengeRequest,
    ChallengeResult,
    Counts,
    EvidenceItem,
    EvidencePacket,
    FeedbackKind,
    QueryRequest,
    QueryResult,
    ResearchJob,
    Sentiment,
    Theme,
    ThreadConcentration,
    Ticket,
    TicketDraft,
)
from app.store import get_store

log = logging.getLogger("voxmarket.analysis")
_WORD = re.compile(r"[a-z0-9]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _query_embedding(text: Optional[str]) -> Optional[list[float]]:
    # In semantic_text mode ES does the embedding, so we pass text only.
    if not text or settings.es_use_semantic_text:
        return None
    return await embed_query(text)


async def hybrid_search(
    research_id: str,
    text: Optional[str],
    *,
    top_k: int = 8,
    aspect: Optional[str] = None,
    sentiment: Optional[Sentiment] = None,
    kind: Optional[FeedbackKind] = None,
    excluded_threads: Iterable[str] = (),
) -> list[EvidenceItem]:
    store = get_store()
    emb = await _query_embedding(text)
    return await store.search(
        research_id,
        text=text,
        query_embedding=emb,
        top_k=top_k,
        aspect=aspect,
        sentiment=sentiment,
        kind=kind,
        excluded_threads=excluded_threads,
    )


# --------------------------------------------------------------------------- packet
async def build_packet(job: ResearchJob) -> EvidencePacket:
    store = get_store()
    excluded = job.excluded_thread_ids
    themes = await store.themes(job.research_id, excluded_threads=excluded, top_n=10)
    counts = await store.counts(job.research_id, excluded_threads=excluded)
    top_negative = await hybrid_search(
        job.research_id,
        f"{job.subject} problems complaints issues frustrations",
        sentiment=Sentiment.negative, top_k=6, excluded_threads=excluded,
    )
    top_positive = await hybrid_search(
        job.research_id,
        f"{job.subject} what users like praise love",
        sentiment=Sentiment.positive, top_k=6, excluded_threads=excluded,
    )
    caveats = await _caveats(job, themes)
    return EvidencePacket(
        research_id=job.research_id,
        evidence_version=job.evidence_version,
        subject=job.subject,
        question=job.question,
        status=job.status,
        generated_at=_now(),
        headline=job.headline or _fallback_headline(job.subject, themes, counts),
        themes=themes,
        top_negative=top_negative,
        top_positive=top_positive,
        counts=counts,
        sources=job.sources_completed,
        caveats=caveats,
        excluded_thread_ids=list(excluded),
    )


def _fallback_headline(subject: str, themes: list[Theme], counts: Counts) -> str:
    top = next((t for t in themes if t.sentiment.negative > 0), None)
    if not top:
        return f"{counts.total} comments analyzed across {counts.thread_count} discussions about {subject}."
    return (
        f"Top complaint about {subject}: {top.key.replace('_', ' ')} "
        f"({top.sentiment.negative} mentions in {top.thread_count} threads)."
    )


async def _caveats(job: ResearchJob, themes: list[Theme]) -> list[str]:
    caveats: list[str] = []
    if job.sources_failed:
        caveats.append(
            f"Partial data: source(s) {', '.join(job.sources_failed)} failed to collect."
        )
    top = next((t for t in themes if t.sentiment.negative > 0), None)
    if top and top.top_thread_share >= 0.5:
        caveats.append(
            f"'{top.key.replace('_', ' ')}' is concentrated — "
            f"{round(top.top_thread_share * 100)}% of its mentions come from a single thread. "
            "Ask me to challenge it."
        )
    if job.excluded_thread_ids:
        caveats.append(f"{len(job.excluded_thread_ids)} thread(s) currently excluded from the analysis.")
    return caveats


# --------------------------------------------------------------------------- query
async def run_query(job: ResearchJob, req: QueryRequest) -> QueryResult:
    store = get_store()
    evidence = await hybrid_search(
        job.research_id, req.query, top_k=req.top_k, aspect=req.aspect,
        sentiment=req.sentiment, excluded_threads=job.excluded_thread_ids,
    )
    themes = await store.themes(job.research_id, excluded_threads=job.excluded_thread_ids)
    counts = await store.counts(job.research_id, excluded_threads=job.excluded_thread_ids)
    answer = _spoken_query_answer(req.query, evidence, themes)
    return QueryResult(
        research_id=job.research_id, query=req.query, answer=answer,
        evidence=evidence, themes=themes, counts=counts,
    )


def _spoken_query_answer(query: str, evidence: list[EvidenceItem], themes: list[Theme]) -> str:
    if not evidence:
        return "I couldn't find evidence for that in the collected feedback."
    aspects = [a for e in evidence for a in e.aspects]
    top_aspect = max(set(aspects), key=aspects.count).replace("_", " ") if aspects else "several themes"
    neg = sum(1 for e in evidence if e.overall_sentiment == Sentiment.negative)
    pos = sum(1 for e in evidence if e.overall_sentiment == Sentiment.positive)
    quote = evidence[0].snippet
    return (
        f"I found {len(evidence)} relevant comments, mostly about {top_aspect} "
        f"({neg} negative, {pos} positive). For example: \"{quote}\""
    )


# --------------------------------------------------------------------------- challenge
async def run_challenge(job: ResearchJob, req: ChallengeRequest) -> ChallengeResult:
    store = get_store()
    excluded = job.excluded_thread_ids
    aspect = req.aspect or await _infer_aspect(job, req.claim)

    concentration = await store.thread_concentration(
        job.research_id, aspect, excluded_threads=excluded
    )
    # Assume the claim is a *negative* conclusion about `aspect` (the common case).
    # Counterevidence = independent positive statements about that same aspect.
    counterevidence = await hybrid_search(
        job.research_id, req.claim, aspect=aspect, sentiment=Sentiment.positive,
        top_k=6, excluded_threads=excluded,
    )
    supporting = await hybrid_search(
        job.research_id, req.claim, aspect=aspect, sentiment=Sentiment.negative,
        top_k=6, excluded_threads=excluded,
    )
    # Recompute themes as if the dominant thread were removed — this is the
    # "isolate the viral thread and see what's left" move.
    revised_excluded = list(excluded)
    if concentration.top_thread_id and concentration.verdict == "concentrated":
        revised_excluded.append(concentration.top_thread_id)
    revised_themes = await store.themes(job.research_id, excluded_threads=revised_excluded)

    assessment = _spoken_challenge(aspect, concentration, counterevidence, revised_themes)
    return ChallengeResult(
        research_id=job.research_id, claim=req.claim, assessment=assessment,
        concentration=concentration, counterevidence=counterevidence,
        supporting=supporting, revised_themes=revised_themes,
    )


async def _infer_aspect(job: ResearchJob, claim: str) -> Optional[str]:
    store = get_store()
    themes = await store.themes(job.research_id, excluded_threads=job.excluded_thread_ids, top_n=20)
    claim_tokens = set(_WORD.findall(claim.lower()))
    # direct token/label overlap first
    for t in themes:
        label_tokens = set(t.key.lower().split("_"))
        if label_tokens & claim_tokens or normalize_aspect(t.key) in claim.lower():
            return t.key
    # otherwise the biggest negative theme is the thing worth challenging
    neg = [t for t in themes if t.sentiment.negative > 0]
    return neg[0].key if neg else (themes[0].key if themes else None)


def _spoken_challenge(
    aspect: Optional[str],
    conc: ThreadConcentration,
    counter: list[EvidenceItem],
    revised_themes: list[Theme],
) -> str:
    label = (aspect or "that theme").replace("_", " ")
    if conc.total_docs == 0:
        return f"I don't have enough evidence about {label} to evaluate that."
    share_pct = round(conc.top_thread_share * 100)
    lead = (
        f"The {label} concern is {conc.verdict}: its biggest single thread "
        f"(\"{conc.top_thread_title}\") accounts for {share_pct}% of the "
        f"{conc.total_docs} mentions across {conc.thread_count} threads."
    )
    tail = ""
    if conc.verdict == "concentrated" and revised_themes:
        new_top = next((t for t in revised_themes if t.sentiment.negative > 0), None)
        if new_top and normalize_aspect(new_top.key) != aspect:
            tail = (
                f" If I set that thread aside, {new_top.key.replace('_', ' ')} becomes the "
                f"more consistent complaint across independent discussions."
            )
    counter_note = (
        f" I also found {len(counter)} comments that push back on it." if counter else ""
    )
    return lead + tail + counter_note


# --------------------------------------------------------------------------- exclude
async def set_thread_excluded(job: ResearchJob, thread_id: str, exclude: bool) -> ResearchJob:
    store = get_store()
    excluded = set(job.excluded_thread_ids)
    if exclude:
        excluded.add(thread_id)
    else:
        excluded.discard(thread_id)
    job.excluded_thread_ids = sorted(excluded)
    job.evidence_version += 1
    job.updated_at = _now()
    await store.save_job(job)
    return job


# --------------------------------------------------------------------------- ticket
async def draft_ticket(job: ResearchJob, aspect: Optional[str] = None) -> TicketDraft:
    store = get_store()
    excluded = job.excluded_thread_ids
    if not aspect:
        themes = await store.themes(job.research_id, excluded_threads=excluded)
        top = next((t for t in themes if t.sentiment.negative > 0), None)
        aspect = top.key if top else (themes[0].key if themes else "general")
    aspect = normalize_aspect(aspect)

    evidence = await hybrid_search(
        job.research_id, f"{job.subject} {aspect} problem", aspect=aspect,
        sentiment=Sentiment.negative, top_k=6, excluded_threads=excluded,
    )
    counter = await hybrid_search(
        job.research_id, f"{job.subject} {aspect}", aspect=aspect,
        sentiment=Sentiment.positive, top_k=4, excluded_threads=excluded,
    )
    concentration = await store.thread_concentration(
        job.research_id, aspect, excluded_threads=excluded
    )
    fields = await draft_ticket_fields(job.subject, aspect, evidence, counter, concentration)
    sources = list(dict.fromkeys(e.url for e in evidence if e.url))
    return TicketDraft(
        research_id=job.research_id,
        title=f"Investigate {aspect.replace('_', ' ')} feedback for {job.subject}",
        issue=fields.issue,
        evidence=evidence,
        supporting_sources=sources,
        counterevidence=counter,
        uncertainty=fields.uncertainty,
        suggested_experiment=fields.suggested_experiment,
    )


async def create_ticket(draft: TicketDraft) -> Ticket:
    store = get_store()
    ticket = Ticket(
        **draft.model_dump(),
        ticket_id=f"tkt_{uuid.uuid4().hex[:10]}",
        status="created",
        created_at=_now(),
        approved=True,
    )
    await store.save_ticket(ticket)
    return ticket
