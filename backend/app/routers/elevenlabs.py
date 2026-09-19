"""ElevenLabs integration — the conversational control plane.

Two responsibilities:

1. **Mint short-lived voice credentials server-side** (`/api/elevenlabs/token`)
   so the private-agent API key NEVER reaches the browser. The React SDK uses the
   returned WebRTC token to open the voice session.

2. **Webhook tools** (`/api/webhooks/elevenlabs/*`) the agent invokes mid-
   conversation. These are the point of the whole product: the voice conversation
   *controls the research pipeline*, it doesn't read a static dashboard. Each tool
   returns a short ``spoken`` string for the agent plus structured data, and
   stashes UI state in ``runtime`` so the on-screen dashboard follows along.

Every webhook is authenticated with a shared ``X-Tool-Secret`` header (configured
on the agent's tools by ``scripts/setup_elevenlabs_agent.py``).
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app import runtime
from app.analysis import evidence as analysis
from app.config import settings
from app.jobs.worker import start_research
from app.models import (
    ChallengeRequest,
    QueryRequest,
    ResearchJob,
    ResearchRequest,
    ResearchStatus,
    Sentiment,
    TERMINAL_STATUSES,
)
from app.store import get_store

log = logging.getLogger("voxmarket.elevenlabs")

router = APIRouter(tags=["elevenlabs"])
EL_API = "https://api.elevenlabs.io/v1/convai/conversation"


# =============================================================== token / config
class TokenRequest(BaseModel):
    user_id: Optional[str] = None


@router.get("/api/elevenlabs/config")
async def elevenlabs_config() -> dict:
    """Lets the frontend decide whether to show the voice UI."""
    return {
        "configured": settings.elevenlabs_enabled,
        "agent_id": settings.elevenlabs_agent_id or None,
        "connection_type": "webrtc",
    }


@router.post("/api/elevenlabs/token")
async def mint_token(_: TokenRequest | None = None) -> dict:
    """Mint a WebRTC conversation token for the configured private agent."""
    if not settings.elevenlabs_enabled:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured on the server")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{EL_API}/token",
            params={"agent_id": settings.elevenlabs_agent_id},
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
    if resp.status_code != 200:
        log.error("token mint failed %s: %s", resp.status_code, resp.text[:300])
        raise HTTPException(status_code=502, detail="failed to mint ElevenLabs token")
    data = resp.json()
    return {
        "token": data.get("token"),
        "conversation_id": data.get("conversation_id"),
        "agent_id": settings.elevenlabs_agent_id,
        "connection_type": "webrtc",
    }


# =============================================================== voice selection
AGENTS_API = "https://api.elevenlabs.io/v1/convai/agents"


def _el_headers() -> dict:
    return {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}


@router.get("/api/elevenlabs/voices")
async def list_voices() -> dict:
    """Voices available to this account + the agent's current voice (for the dropdown)."""
    if not settings.elevenlabs_enabled:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        vr = await client.get("https://api.elevenlabs.io/v1/voices", headers=_el_headers())
        ar = await client.get(f"{AGENTS_API}/{settings.elevenlabs_agent_id}", headers=_el_headers())
    if vr.status_code != 200:
        raise HTTPException(status_code=502, detail="failed to list voices")
    voices = [
        {"voice_id": v.get("voice_id"), "name": v.get("name"), "labels": v.get("labels", {}) or {}}
        for v in vr.json().get("voices", [])
    ]
    current = None
    if ar.status_code == 200:
        current = ar.json().get("conversation_config", {}).get("tts", {}).get("voice_id")
    return {"voices": voices, "current_voice_id": current}


class VoiceBody(BaseModel):
    voice_id: str


@router.post("/api/elevenlabs/voice")
async def set_voice(body: VoiceBody) -> dict:
    """Change the agent's voice, merging onto its existing TTS settings."""
    if not settings.elevenlabs_enabled:
        raise HTTPException(status_code=503, detail="ElevenLabs is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        ar = await client.get(f"{AGENTS_API}/{settings.elevenlabs_agent_id}", headers=_el_headers())
        if ar.status_code != 200:
            raise HTTPException(status_code=502, detail="failed to read agent")
        tts = dict(ar.json().get("conversation_config", {}).get("tts", {}) or {})
        tts["voice_id"] = body.voice_id
        pr = await client.patch(
            f"{AGENTS_API}/{settings.elevenlabs_agent_id}",
            headers=_el_headers(),
            json={"conversation_config": {"tts": tts}},
        )
    if pr.status_code // 100 != 2:
        log.error("set voice failed %s: %s", pr.status_code, pr.text[:300])
        raise HTTPException(status_code=502, detail="failed to set voice")
    return {"ok": True, "voice_id": body.voice_id}


# ================================================================ webhook tools
def _verify(secret: Optional[str]) -> None:
    expected = settings.elevenlabs_tool_secret
    if expected and secret != expected:
        raise HTTPException(status_code=401, detail="invalid tool secret")


async def _job(research_id: str) -> ResearchJob:
    job = await get_store().get_job(research_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"research {research_id} not found")
    return job


def _parse_sentiment(v: Optional[str]) -> Optional[Sentiment]:
    if not v:
        return None
    try:
        return Sentiment(v.lower())
    except ValueError:
        return None


# ---- start_research ----------------------------------------------------------
class StartResearchBody(BaseModel):
    subject: str
    question: Optional[str] = None
    competitors: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    max_threads: Optional[int] = None


@router.post("/api/webhooks/elevenlabs/start_research")
async def wh_start_research(
    body: StartResearchBody, x_tool_secret: Optional[str] = Header(default=None)
) -> dict:
    _verify(x_tool_secret)
    request = ResearchRequest(
        subject=body.subject,
        question=body.question or "What are customers frustrated about?",
        competitors=body.competitors or [],
        sources=body.sources or ["fixtures"],
        max_threads=body.max_threads or 30,
    )
    job = await start_research(request)
    return {
        "research_id": job.research_id,
        "status": job.status.value,
        "spoken": (
            f"Starting research on {body.subject}. I'm gathering and structuring customer "
            "feedback now — give me a few seconds, then ask me for the status or the findings."
        ),
    }


# ---- get_research_status -----------------------------------------------------
class ResearchIdBody(BaseModel):
    research_id: str


@router.post("/api/webhooks/elevenlabs/get_research_status")
async def wh_status(
    body: ResearchIdBody, x_tool_secret: Optional[str] = Header(default=None)
) -> dict:
    _verify(x_tool_secret)
    job = await _job(body.research_id)
    ready = job.status in TERMINAL_STATUSES
    if ready and job.status in (ResearchStatus.READY, ResearchStatus.PARTIAL):
        spoken = (
            f"Done. I analyzed {job.document_count} comments across {job.thread_count} "
            f"discussions. {job.headline}"
        )
    elif job.status == ResearchStatus.FAILED:
        spoken = f"The research failed: {job.error or 'unknown error'}."
    else:
        spoken = f"Still {job.status.value.lower()} — give me a moment and ask again."
    return {
        "status": job.status.value,
        "ready": ready,
        "document_count": job.document_count,
        "thread_count": job.thread_count,
        "headline": job.headline,
        "spoken": spoken,
    }


# ---- query_feedback ----------------------------------------------------------
class QueryBody(BaseModel):
    research_id: str
    query: str
    aspect: Optional[str] = None
    sentiment: Optional[str] = None


@router.post("/api/webhooks/elevenlabs/query_feedback")
async def wh_query(
    body: QueryBody, x_tool_secret: Optional[str] = Header(default=None)
) -> dict:
    _verify(x_tool_secret)
    job = await _job(body.research_id)
    result = await analysis.run_query(
        job,
        QueryRequest(query=body.query, aspect=body.aspect,
                     sentiment=_parse_sentiment(body.sentiment)),
    )
    return {
        "spoken": result.answer,
        "evidence_count": len(result.evidence),
        "top_themes": [
            {"theme": t.key, "negative": t.sentiment.negative, "positive": t.sentiment.positive,
             "threads": t.thread_count}
            for t in result.themes[:4]
        ],
    }


# ---- challenge_finding -------------------------------------------------------
class ChallengeBody(BaseModel):
    research_id: str
    claim: str
    aspect: Optional[str] = None


@router.post("/api/webhooks/elevenlabs/challenge_finding")
async def wh_challenge(
    body: ChallengeBody, x_tool_secret: Optional[str] = Header(default=None)
) -> dict:
    _verify(x_tool_secret)
    job = await _job(body.research_id)
    result = await analysis.run_challenge(job, ChallengeRequest(claim=body.claim, aspect=body.aspect))
    runtime.set_challenge(job.research_id, result)  # UI renders the counterevidence panel
    new_top = next(
        (t.key for t in result.revised_themes if t.sentiment.negative > 0), None
    )
    return {
        "spoken": result.assessment,
        "verdict": result.concentration.verdict,
        "top_thread_share": result.concentration.top_thread_share,
        "top_thread_id": result.concentration.top_thread_id,
        "counterevidence_count": len(result.counterevidence),
        "revised_top_theme": new_top,
    }


# ---- create_investigation_ticket --------------------------------------------
class TicketBody(BaseModel):
    research_id: str
    aspect: Optional[str] = None
    approve: bool = False


@router.post("/api/webhooks/elevenlabs/create_investigation_ticket")
async def wh_ticket(
    body: TicketBody, x_tool_secret: Optional[str] = Header(default=None)
) -> dict:
    _verify(x_tool_secret)
    job = await _job(body.research_id)
    draft = await analysis.draft_ticket(job, body.aspect)
    runtime.set_ticket_draft(job.research_id, draft)  # UI shows the preview

    if not body.approve:
        return {
            "needs_approval": True,
            "spoken": (
                f"Here's the ticket I'd create: \"{draft.title}\". {draft.issue} "
                f"It cites {len(draft.evidence)} pieces of evidence and "
                f"{len(draft.counterevidence)} counterpoints. Shall I create it?"
            ),
            "ticket_preview": {
                "title": draft.title,
                "issue": draft.issue,
                "uncertainty": draft.uncertainty,
                "suggested_experiment": draft.suggested_experiment,
                "evidence_count": len(draft.evidence),
                "counterevidence_count": len(draft.counterevidence),
            },
        }

    ticket = await analysis.create_ticket(draft)
    return {
        "created": True,
        "ticket_id": ticket.ticket_id,
        "spoken": f"Created the investigation ticket {ticket.ticket_id}: {ticket.title}.",
    }
