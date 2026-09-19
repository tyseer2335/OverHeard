"""Turn messy raw comments into structured feedback records.

Three tiers, in priority order:

1. **OpenAI Responses API + strict JSON Schema** (when a key is present) — the
   marquee OpenAI usage. Never asked to compute aggregates, only to classify.
2. **Gold labels** carried by curated fixtures — deterministic demo path.
3. **Heuristic** keyword classifier — last-resort so *something* always works.

The LLM path takes priority over gold only when ``EXTRACT_FORCE_LLM=true`` (so you
can demonstrate live extraction on the curated corpus during judging).
"""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel

from app.config import settings
from app.enrich.openai_client import get_openai
from app.models import AspectSentiment, Enrichment, FeedbackKind, RawItem, Sentiment

log = logging.getLogger("voxmarket.enrich")

_BATCH = 12
_CONCURRENCY = 4

# --------------------------------------------------------------------------- normalize
_NORM = re.compile(r"[^a-z0-9]+")


def normalize_aspect(s: str) -> str:
    s = _NORM.sub("_", (s or "").strip().lower()).strip("_")
    return s or "general"


# suggested controlled vocabulary (LLM is nudged toward these; not enforced)
ASPECT_VOCAB = [
    "pricing", "billing", "onboarding", "performance", "reliability", "sync",
    "ui_ux", "mobile", "ai_features", "integrations", "support", "collaboration",
    "offline", "databases", "search", "templates", "documentation", "features",
]

# --------------------------------------------------------------------------- heuristic
_ASPECT_KEYWORDS: dict[str, list[str]] = {
    "pricing": ["price", "pricing", "cost", "expensive", "seat", "billing", "charge",
                "subscription", "refund", "per-seat", "pay"],
    "onboarding": ["onboard", "learning curve", "get started", "getting started",
                   "new hire", "ramp", "setup", "learn", "hand-hold", "walkthrough"],
    "performance": ["slow", "lag", "laggy", "performance", "sluggish", "load", "speed"],
    "reliability": ["crash", "broken", "reliab", "outage", "unstable", "data loss", "bug"],
    "sync": ["sync", "syncing", "conflict", "conflicting"],
    "ui_ux": ["interface", " ui ", " ux ", "cluttered", "confusing", "design"],
    "mobile": ["mobile", "ios", "android", "phone app", "mobile app"],
    "ai_features": ["ai ", " ai", "hallucinat", "autocomplete", "summar"],
    "integrations": ["integration", "api", "zapier", "webhook", "connect"],
    "support": ["support", "customer service", "response time"],
    "collaboration": ["collaborat", "comment", "mention", "shared", "team"],
    "offline": ["offline"],
    "databases": ["database", "relation", "rollup", "formula"],
    "search": ["search"],
    "templates": ["template"],
}
_NEG = ["hate", "terrible", "awful", "worst", "broken", "slow", "frustrat", "annoying",
        "expensive", "bug", "crash", "disappoint", "painful", "can't", "cant", "difficult",
        "hard", "confusing", "lacking", "missing", "sucks", "unusable", "predatory",
        "absurd", "insane", "robbery", "clunky", "afterthought", "regress"]
_POS = ["love", "great", "amazing", "excellent", "best", "awesome", "fantastic", "smooth",
        "incredible", "worth", "fair", "unmatched", "easy", "intuitive", "cheaper", "pays for"]
_REQ = ["wish", "please", "should add", "would love", "feature request", "give us", "needs a"]


def _score_sentiment(text: str) -> Sentiment:
    t = text.lower()
    pos = sum(t.count(w) for w in _POS)
    neg = sum(t.count(w) for w in _NEG)
    if pos and neg and abs(pos - neg) <= 1:
        return Sentiment.mixed
    if neg > pos:
        return Sentiment.negative
    if pos > neg:
        return Sentiment.positive
    return Sentiment.neutral


def _heuristic(item: RawItem) -> Enrichment:
    text = item.text
    t = text.lower()
    sentiment = _score_sentiment(text)
    aspects_found = [a for a, kws in _ASPECT_KEYWORDS.items() if any(k in t for k in kws)]
    if not aspects_found:
        aspects_found = ["general"]
    if any(r in t for r in _REQ):
        kind = FeedbackKind.feature_request
    elif sentiment == Sentiment.negative:
        kind = FeedbackKind.complaint
    elif sentiment == Sentiment.positive:
        kind = FeedbackKind.praise
    elif text.strip().endswith("?"):
        kind = FeedbackKind.question
    else:
        kind = FeedbackKind.other
    aspects = [
        AspectSentiment(aspect=a, sentiment=sentiment, confidence=0.4,
                        evidence_span=text[:200])
        for a in aspects_found
    ]
    return Enrichment(
        relevant=True, subject_match=True, kind=kind, overall_sentiment=sentiment,
        aspects=aspects, summary=text[:160], evidence_span=text[:200],
    )


def _from_gold(item: RawItem) -> Enrichment:
    gold = item.extra.get("gold") or {}
    try:
        overall = Sentiment(gold.get("sentiment", "neutral"))
    except ValueError:
        overall = Sentiment.neutral
    try:
        kind = FeedbackKind(gold.get("kind", "other"))
    except ValueError:
        kind = FeedbackKind.other
    aspects = []
    for a in gold.get("aspects", []):
        try:
            asent = Sentiment(a.get("sentiment", overall.value))
        except ValueError:
            asent = overall
        aspects.append(
            AspectSentiment(
                aspect=normalize_aspect(a.get("aspect", "general")),
                sentiment=asent, confidence=0.95, evidence_span=item.text[:200],
            )
        )
    return Enrichment(
        relevant=True, subject_match=True, kind=kind, overall_sentiment=overall,
        aspects=aspects, summary=item.text[:160], evidence_span=item.text[:200],
    )


# --------------------------------------------------------------------------- LLM path
class _LLMAspect(BaseModel):
    aspect: str
    sentiment: Sentiment
    evidence_span: str


class _LLMItem(BaseModel):
    index: int
    relevant: bool
    subject_match: bool
    kind: FeedbackKind
    overall_sentiment: Sentiment
    aspects: list[_LLMAspect]
    summary: str
    ambiguous: bool


class _LLMBatch(BaseModel):
    items: list[_LLMItem]


_SYSTEM = (
    "You are a precise market-research annotator. For each user comment about a product, "
    "classify it. Rules: (1) Only extract what the text supports — never invent. "
    "(2) 'aspect' must be a short lowercase snake_case label; prefer this vocabulary when it "
    "fits: {vocab}. (3) 'evidence_span' must be a VERBATIM substring of the comment. "
    "(4) 'subject_match' is false if the comment isn't actually about the product. "
    "(5) Do NOT compute counts or statistics — only per-comment labels."
)


async def _llm_extract_batch(subject: str, batch: list[tuple[int, RawItem]]) -> dict[int, Enrichment]:
    client = get_openai()
    assert client is not None
    payload = [
        {"index": idx, "thread_title": it.thread_title, "text": it.text[:1200]}
        for idx, it in batch
    ]
    system = _SYSTEM.format(vocab=", ".join(ASPECT_VOCAB))
    resp = await client.responses.parse(
        model=settings.openai_model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Product/subject: {subject}\nComments (JSON):\n{payload}"},
        ],
        text_format=_LLMBatch,
    )
    parsed = resp.output_parsed
    out: dict[int, Enrichment] = {}
    if not parsed:
        return out
    for li in parsed.items:
        out[li.index] = Enrichment(
            relevant=li.relevant,
            subject_match=li.subject_match,
            kind=li.kind,
            overall_sentiment=li.overall_sentiment,
            aspects=[
                AspectSentiment(
                    aspect=normalize_aspect(a.aspect),
                    sentiment=a.sentiment,
                    confidence=0.8,
                    evidence_span=a.evidence_span,
                )
                for a in li.aspects
            ],
            summary=li.summary,
            evidence_span=li.aspects[0].evidence_span if li.aspects else li.summary,
            ambiguous=li.ambiguous,
        )
    return out


async def _llm_extract(subject: str, indexed: list[tuple[int, RawItem]]) -> dict[int, Enrichment]:
    batches = [indexed[i : i + _BATCH] for i in range(0, len(indexed), _BATCH)]
    sem = asyncio.Semaphore(_CONCURRENCY)
    merged: dict[int, Enrichment] = {}

    async def run(batch):
        async with sem:
            try:
                return await _llm_extract_batch(subject, batch)
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM extract batch failed (%s) — heuristic fallback", exc)
                return {idx: _heuristic(it) for idx, it in batch}

    for result in await asyncio.gather(*(run(b) for b in batches)):
        merged.update(result)
    return merged


# --------------------------------------------------------------------------- orchestrator
async def enrich_items(items: list[RawItem], subject: str) -> list[Enrichment]:
    results: list[Enrichment | None] = [None] * len(items)
    to_llm: list[tuple[int, RawItem]] = []

    force_llm = settings.extract_force_llm and settings.openai_enabled
    for i, it in enumerate(items):
        if it.extra.get("gold") and not force_llm:
            results[i] = _from_gold(it)
        elif settings.openai_enabled:
            to_llm.append((i, it))
        else:
            results[i] = _heuristic(it)

    if to_llm:
        llm_out = await _llm_extract(subject, to_llm)
        for i, it in to_llm:
            results[i] = llm_out.get(i) or _heuristic(it)

    return [r if r is not None else _heuristic(items[i]) for i, r in enumerate(results)]
