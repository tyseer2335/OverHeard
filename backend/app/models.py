"""Domain schemas shared across the backend.

These are the contracts between the ingestion layer, the enrichment (OpenAI)
layer, Elasticsearch, the job worker, and the API/ElevenLabs surface.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- enums
class ResearchStatus(str, Enum):
    QUEUED = "QUEUED"
    DISCOVERING = "DISCOVERING"
    COLLECTING = "COLLECTING"
    CLEANING = "CLEANING"
    ENRICHING = "ENRICHING"
    INDEXING = "INDEXING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {
    ResearchStatus.READY,
    ResearchStatus.PARTIAL,
    ResearchStatus.FAILED,
    ResearchStatus.CANCELLED,
}


class Sentiment(str, Enum):
    positive = "positive"
    negative = "negative"
    mixed = "mixed"
    neutral = "neutral"


class FeedbackKind(str, Enum):
    complaint = "complaint"
    praise = "praise"
    feature_request = "feature_request"
    question = "question"
    other = "other"


# --------------------------------------------------------------------------- request
class DateRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class ResearchRequest(BaseModel):
    subject: str = Field(..., description="Product / company being researched, e.g. 'Notion'")
    question: str = Field(default="What are customers frustrated about?")
    competitors: list[str] = Field(default_factory=list)
    date_range: Optional[DateRange] = None
    sources: list[str] = Field(default_factory=lambda: ["fixtures"])
    max_threads: int = 30


class ResearchCreateResponse(BaseModel):
    research_id: str
    status: ResearchStatus


# --------------------------------------------------------------------------- raw + enriched
class RawItem(BaseModel):
    """A single message/comment as collected from a source, before enrichment."""
    source: str
    source_id: str
    thread_id: str
    thread_title: str = ""
    url: str = ""
    author: str = ""
    text: str
    created_at: Optional[datetime] = None
    score: int = 0
    parent_id: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AspectSentiment(BaseModel):
    """Aspect-based sentiment: how a specific aspect is felt about."""
    aspect: str = Field(..., description="Normalized aspect/theme, e.g. 'pricing', 'onboarding'")
    sentiment: Sentiment
    confidence: float = 0.5
    evidence_span: str = Field(default="", description="Verbatim quote supporting this aspect")


class Enrichment(BaseModel):
    """Structured output of the OpenAI extraction step for one RawItem."""
    relevant: bool = True
    subject_match: bool = True
    kind: FeedbackKind = FeedbackKind.other
    overall_sentiment: Sentiment = Sentiment.neutral
    aspects: list[AspectSentiment] = Field(default_factory=list)
    summary: str = ""
    evidence_span: str = ""
    ambiguous: bool = False


class FeedbackDoc(BaseModel):
    """A fully enriched feedback record — the unit indexed into Elasticsearch."""
    id: str
    research_id: str
    source: str
    source_id: str
    thread_id: str
    thread_title: str = ""
    url: str = ""
    author: str = ""
    created_at: Optional[datetime] = None
    text: str
    dedupe_hash: str = ""
    # enrichment
    relevant: bool = True
    subject_match: bool = True
    kind: FeedbackKind = FeedbackKind.other
    overall_sentiment: Sentiment = Sentiment.neutral
    aspects: list[AspectSentiment] = Field(default_factory=list)
    aspect_keys: list[str] = Field(default_factory=list)  # denormalized for aggregations
    aspect_sentiments: list[str] = Field(default_factory=list)  # "aspect:sentiment" pairs
    summary: str = ""
    evidence_span: str = ""
    ambiguous: bool = False
    # retrieval
    embedding: Optional[list[float]] = None


# --------------------------------------------------------------------------- job state
class StepLog(BaseModel):
    status: ResearchStatus
    at: datetime
    detail: str = ""


class ResearchJob(BaseModel):
    research_id: str
    status: ResearchStatus = ResearchStatus.QUEUED
    subject: str
    question: str = ""
    competitors: list[str] = Field(default_factory=list)
    date_range: Optional[DateRange] = None
    sources_requested: list[str] = Field(default_factory=list)
    sources_completed: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    queries_used: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    document_count: int = 0
    thread_count: int = 0
    evidence_version: int = 0
    excluded_thread_ids: list[str] = Field(default_factory=list)
    headline: str = ""
    error: Optional[str] = None
    progress: list[StepLog] = Field(default_factory=list)
    # non-persistent hint for the UI browser panel (best-effort)
    browser_live_view_url: Optional[str] = None


# --------------------------------------------------------------------------- evidence
class SentimentBreakdown(BaseModel):
    positive: int = 0
    negative: int = 0
    mixed: int = 0
    neutral: int = 0

    @property
    def total(self) -> int:
        return self.positive + self.negative + self.mixed + self.neutral


class Theme(BaseModel):
    key: str
    doc_count: int
    sentiment: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    net_sentiment: float = 0.0  # (-1..1): (pos - neg) / total
    thread_count: int = 0
    top_thread_id: Optional[str] = None
    top_thread_share: float = 0.0  # fraction of this theme's docs in its single biggest thread
    sample_evidence_ids: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    doc_id: str
    source: str
    thread_id: str
    thread_title: str = ""
    url: str = ""
    author: str = ""
    created_at: Optional[datetime] = None
    snippet: str
    overall_sentiment: Sentiment = Sentiment.neutral
    kind: FeedbackKind = FeedbackKind.other
    aspects: list[str] = Field(default_factory=list)
    score: float = 0.0


class Counts(BaseModel):
    total: int = 0
    by_sentiment: SentimentBreakdown = Field(default_factory=SentimentBreakdown)
    by_kind: dict[str, int] = Field(default_factory=dict)
    thread_count: int = 0


class EvidencePacket(BaseModel):
    """Everything the UI renders and the voice agent narrates from."""
    research_id: str
    evidence_version: int
    subject: str
    question: str = ""
    status: ResearchStatus
    generated_at: datetime
    headline: str = ""
    themes: list[Theme] = Field(default_factory=list)
    top_negative: list[EvidenceItem] = Field(default_factory=list)
    top_positive: list[EvidenceItem] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)
    sources: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    excluded_thread_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- query / challenge
class QueryRequest(BaseModel):
    query: str
    top_k: int = 8
    sentiment: Optional[Sentiment] = None
    aspect: Optional[str] = None


class QueryResult(BaseModel):
    research_id: str
    query: str
    answer: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)
    themes: list[Theme] = Field(default_factory=list)
    counts: Counts = Field(default_factory=Counts)


class ChallengeRequest(BaseModel):
    claim: str = Field(..., description="The conclusion to challenge, e.g. 'pricing is the top complaint'")
    aspect: Optional[str] = None


class ThreadConcentration(BaseModel):
    aspect: Optional[str] = None
    total_docs: int = 0
    thread_count: int = 0
    top_thread_id: Optional[str] = None
    top_thread_title: str = ""
    top_thread_docs: int = 0
    top_thread_share: float = 0.0
    verdict: str = ""  # "concentrated" | "widespread" | "mixed"


class ChallengeResult(BaseModel):
    research_id: str
    claim: str
    assessment: str = ""
    concentration: ThreadConcentration = Field(default_factory=ThreadConcentration)
    counterevidence: list[EvidenceItem] = Field(default_factory=list)
    supporting: list[EvidenceItem] = Field(default_factory=list)
    revised_themes: list[Theme] = Field(default_factory=list)


class ExcludeRequest(BaseModel):
    thread_id: str
    exclude: bool = True  # false to re-include


# --------------------------------------------------------------------------- tickets
class TicketDraft(BaseModel):
    research_id: str
    title: str
    issue: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    supporting_sources: list[str] = Field(default_factory=list)
    counterevidence: list[EvidenceItem] = Field(default_factory=list)
    uncertainty: str = ""
    suggested_experiment: str = ""


class Ticket(TicketDraft):
    ticket_id: str
    status: str = "created"
    created_at: datetime
    created_by: str = "voxmarket"
    approved: bool = True
