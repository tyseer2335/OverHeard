"""ElevenLabs credentials and tenant-scoped feedback tools for Ask Vox."""
from __future__ import annotations

import base64
import calendar
from collections import Counter
from datetime import UTC, date, datetime, timedelta
import hashlib
import hmac
import logging
import re
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .dependencies import get_auth_context, get_feedback_store, get_supabase
from .feedback_store import FeedbackStore
from .models import AuthContext, Product
from .supabase import SupabaseClient

router = APIRouter(prefix="/voice", tags=["voice"])
log = logging.getLogger("product_voice.voice")
EL_API = "https://api.elevenlabs.io/v1"


@router.get("/config")
def voice_config() -> dict[str, bool]:
    return {"configured": get_settings().elevenlabs_enabled}


def _scope_token(product: Product) -> str:
    expires = int((datetime.now(UTC) + timedelta(hours=2)).timestamp())
    payload = f"{product.organization_id}|{product.id}|{expires}".encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(
        get_settings().elevenlabs_tool_secret.encode(), encoded.encode(), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _verified_scope(token: str | None) -> tuple[str, str]:
    settings = get_settings()
    if not settings.elevenlabs_enabled or not token:
        raise HTTPException(status_code=401, detail="Voice scope required")
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            settings.elevenlabs_tool_secret.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        organization_id, product_id, expires = payload.split("|")
        if int(expires) < int(datetime.now(UTC).timestamp()):
            raise ValueError("Expired")
        return str(UUID(organization_id)), str(UUID(product_id))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid voice scope") from exc


@router.post("/products/{product_id}/signed-url")
def mint_signed_url(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> dict[str, str]:
    settings = get_settings()
    if not settings.elevenlabs_enabled:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured")
    rows = supabase.select("products", auth.access_token, filters={"id": str(product_id)})
    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")
    product = Product.model_validate(rows[0])
    try:
        response = httpx.get(
            f"{EL_API}/convai/conversation/get-signed-url",
            params={"agent_id": settings.elevenlabs_agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to ElevenLabs") from exc
    if response.status_code != 200:
        log.error("ElevenLabs signed URL failed with HTTP %s", response.status_code)
        raise HTTPException(status_code=502, detail="Could not start ElevenLabs session")
    signed_url = response.json().get("signed_url")
    if not isinstance(signed_url, str) or not signed_url.startswith("wss://"):
        raise HTTPException(status_code=502, detail="Invalid ElevenLabs signed URL")
    return {
        "signed_url": signed_url,
        "scope_token": _scope_token(product),
        "product_name": product.name,
    }


@router.get("/voices")
def list_voices(
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.elevenlabs_enabled:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured")
    try:
        response = httpx.get(
            f"{EL_API}/voices",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not load voices") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Could not load voices")
    preferred = ("Eric", "Sarah", "Roger", "Laura", "Charlie", "George")
    rows = response.json().get("voices", [])
    voices = [
        {"voice_id": row["voice_id"], "name": row["name"].split()[0]}
        for name in preferred
        for row in rows
        if row.get("name", "").split()[0] == name and row.get("voice_id")
    ]
    return {"voices": voices[:6]}


StoreDep = Annotated[FeedbackStore, Depends(get_feedback_store)]
ScopeHeader = Annotated[str | None, Header(alias="X-Voice-Scope")]


class QueryBody(BaseModel):
    query: str = Field(default="", max_length=200)
    source: str = Field(default="", max_length=50)
    author_id: str = Field(default="", max_length=50)
    comment_id: str = Field(default="", max_length=200)
    posted_on: str = Field(default="", max_length=40)


class ChallengeBody(BaseModel):
    claim: str = Field(min_length=1, max_length=500)
    issue: str = Field(default="", max_length=200)


def _example(row: dict) -> dict:
    metadata = row.get("source_metadata") or {}
    return {
        "content": row.get("content", "")[:350],
        "source": row.get("source"),
        "comment_id": row.get("external_id"),
        "author_label": f"User {row['author_hash'][:5]}" if row.get("author_hash") else "Anonymous",
        "url": row.get("url"),
        "relevant": row.get("relevant"),
        "content_type": row.get("content_type"),
        "thread_title": metadata.get("thread_title"),
        "sentiment": row.get("sentiment"),
        "issues": row.get("issue_categories", []),
        "published_at": row.get("published_at"),
        "engagement": row.get("engagement", {}),
    }


def _parse_posted_on(value: str) -> tuple[date | None, tuple[int, int] | None]:
    """A full date selects one UTC day; a dashboard label selects all years."""
    if not value.strip():
        return None, None
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip().casefold())
    cleaned = cleaned.replace(",", "")
    try:
        return date.fromisoformat(cleaned), None
    except ValueError:
        pass
    parts = cleaned.split()
    months = {
        alias.casefold(): month
        for month in range(1, 13)
        for alias in (calendar.month_abbr[month], calendar.month_name[month])
    }
    if len(parts) not in (2, 3) or parts[0] not in months:
        raise ValueError("Use a date like Jan 24 or 2026-01-24")
    try:
        month, day = months[parts[0]], int(parts[1])
        year = int(parts[2]) if len(parts) == 3 else 2000
        parsed = date(year, month, day)
    except ValueError as exc:
        raise ValueError("Invalid calendar date") from exc
    return (parsed, None) if len(parts) == 3 else (None, (month, day))


@router.post("/tools/analyze_product")
def analyze_product(
    store: StoreDep, x_voice_scope: ScopeHeader = None
) -> dict[str, Any]:
    organization_id, product_id = _verified_scope(x_voice_scope)
    data = store.analytics(organization_id=organization_id, product_id=product_id)
    coverage = store.relevance_counts(organization_id, product_id)
    if not data["total"]:
        return {"spoken": "There is no indexed feedback for this product yet.", "relevance_counts": coverage, **data}
    top = ", ".join(row["name"].replace("_", " ") for row in data["issues"][:3])
    if not coverage["classified_relevant"]:
        spoken = (
            f"I have {data['total']} indexed items, but none is classified as relevant "
            "to this product yet. I can inspect specific comments, but aggregate "
            "sentiment and issue labels are not reliable product conclusions."
        )
    elif coverage["unreviewed"]:
        spoken = (
            f"I have {data['total']} indexed items, including {coverage['unreviewed']} "
            "without a product relevance classification. Aggregate sentiment and issue "
            "labels may include unrelated comments; inspect specific evidence before "
            "drawing a product conclusion."
        )
    else:
        spoken = (
            f"I found {data['total']} indexed items across {len(data['by_source'])} sources. "
            f"{data['complaints']} are labeled complaints. The leading labeled issue categories "
            f"are {top or 'not yet classified'}."
        )
    return {
        "spoken": spoken,
        "data_quality_note": "Labels are automated and unreviewed rows may be included; inspect comments before product conclusions.",
        "relevance_counts": coverage,
        **data,
    }


@router.post("/tools/query_feedback")
def query_feedback(
    body: QueryBody, store: StoreDep, x_voice_scope: ScopeHeader = None
) -> dict[str, Any]:
    organization_id, product_id = _verified_scope(x_voice_scope)
    author = body.author_id.strip()
    author_match = re.fullmatch(r"(?:user\s+)?([0-9a-f]{5,32})", author, re.I) if author else None
    if author and not author_match:
        return {"spoken": "Use the five-character ID shown after User, such as User 6f77c.", "match_count": 0, "examples": []}
    try:
        posted_date, posted_month_day = _parse_posted_on(body.posted_on)
    except ValueError as exc:
        return {"spoken": str(exc), "match_count": 0, "examples": []}
    filters = {
        "organization_id": organization_id,
        "product_id": product_id,
        "query": body.query.strip() or None,
        "sources": [re.sub(r"[\s_-]+", "", body.source).lower()] if body.source.strip() else None,
        "author_prefix": author_match.group(1).lower() if author_match else None,
        "external_id": body.comment_id.strip() or None,
        "posted_date": posted_date,
        "posted_month_day": posted_month_day,
        # A named author or native ID should remain findable even when an
        # earlier enrichment pass explicitly excluded that row.
        "relevant_only": not bool(author_match or body.comment_id.strip()),
    }
    rows = store.search(**filters, limit=12)
    if not rows:
        return {"spoken": "No indexed comments matched those fields for this product.", "match_count": 0, "examples": []}
    total = store.count_matches(**filters)
    return {
        "spoken": (
            f"{total} indexed items match. Showing {len(rows)} examples. "
            "Check each comment's content for actual product relevance before citing it."
        ),
        "match_count": total,
        "returned_count": len(rows),
        "date_scope": "all years" if posted_month_day else "exact UTC day" if posted_date else None,
        "relevance_note": "Relevance labels are provisional; null means unreviewed.",
        "examples": [_example(row) for row in rows],
    }


@router.post("/tools/challenge_finding")
def challenge_finding(
    body: ChallengeBody, store: StoreDep, x_voice_scope: ScopeHeader = None
) -> dict[str, Any]:
    organization_id, product_id = _verified_scope(x_voice_scope)
    topic = body.issue.strip()
    if not topic:
        return {"spoken": "Which specific topic or issue should I check?", "sample_size": 0}
    rows = store.search(
        organization_id=organization_id, product_id=product_id, query=topic, limit=40,
    )
    if not rows:
        return {"spoken": f"I found no matching feedback about {topic}.", "sample_size": 0}
    by_source = Counter(row.get("source", "unknown") for row in rows)
    by_sentiment = Counter(row.get("sentiment") or "unclassified" for row in rows)
    counterexamples = [
        row for row in rows
        if row.get("sentiment") == "positive" and row.get("relevant") is True
    ][:3]
    return {
        "spoken": (
            f"I found a sample of {len(rows)} indexed matches across {len(by_source)} sources. "
            "Review each comment for product relevance before using it as evidence."
        ),
        "claim": body.claim,
        "sample_size": len(rows),
        "by_source": dict(by_source),
        "by_sentiment": dict(by_sentiment),
        "relevance_note": "Sentiment and relevance labels are provisional; this sample is not a product-wide count.",
        "examples": [_example(row) for row in rows[:5]],
        "counterexamples": [_example(row) for row in counterexamples],
    }
