"""ElevenLabs credentials and tenant-scoped feedback tools for Ask Vox."""
from __future__ import annotations

import base64
from collections import Counter
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import logging
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


class ChallengeBody(BaseModel):
    claim: str = Field(min_length=1, max_length=500)
    issue: str = Field(default="", max_length=200)


def _example(row: dict) -> dict:
    return {
        "content": row.get("content", "")[:350],
        "source": row.get("source"),
        "url": row.get("url"),
        "sentiment": row.get("sentiment"),
        "issues": row.get("issue_categories", []),
        "published_at": row.get("published_at"),
        "engagement": row.get("engagement", {}),
    }


@router.post("/tools/analyze_product")
def analyze_product(
    store: StoreDep, x_voice_scope: ScopeHeader = None
) -> dict[str, Any]:
    organization_id, product_id = _verified_scope(x_voice_scope)
    data = store.analytics(organization_id=organization_id, product_id=product_id)
    if not data["total"]:
        return {"spoken": "There is no analyzed feedback for this product yet.", **data}
    top = ", ".join(row["name"].replace("_", " ") for row in data["issues"][:3])
    return {
        "spoken": (
            f"I found {data['total']} feedback items across {len(data['by_source'])} sources. "
            f"{data['complaints']} are complaints. The leading issue categories are {top or 'not yet classified'}."
        ),
        **data,
    }


@router.post("/tools/query_feedback")
def query_feedback(
    body: QueryBody, store: StoreDep, x_voice_scope: ScopeHeader = None
) -> dict[str, Any]:
    organization_id, product_id = _verified_scope(x_voice_scope)
    rows = store.search(
        organization_id=organization_id, product_id=product_id,
        query=body.query.strip() or None,
        sources=[body.source.strip().lower()] if body.source.strip() else None,
        limit=8,
    )
    if not rows:
        return {"spoken": "I could not find matching feedback for this product.", "count": 0, "examples": []}
    sources = sorted({row.get("source", "unknown") for row in rows})
    return {
        "spoken": (
            f"I found {len(rows)} examples across {', '.join(sources)}. "
            f"One says: {rows[0].get('content', '')[:200]}"
        ),
        "count": len(rows),
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
    counterexamples = [row for row in rows if row.get("sentiment") == "positive"][:3]
    return {
        "spoken": (
            f"In a sample of {len(rows)} matching items, I found feedback from "
            f"{len(by_source)} sources, including {by_sentiment.get('positive', 0)} positive "
            f"and {by_sentiment.get('negative', 0)} negative items. "
            "This is a sample, not a product-wide count."
        ),
        "claim": body.claim,
        "sample_size": len(rows),
        "by_source": dict(by_source),
        "by_sentiment": dict(by_sentiment),
        "examples": [_example(row) for row in rows[:5]],
        "counterexamples": [_example(row) for row in counterexamples],
    }
