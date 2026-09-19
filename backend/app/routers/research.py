"""Research REST API — consumed by the frontend dashboard (and usable directly).

The voice agent drives the same underlying operations through the ElevenLabs
webhook router; these HTTP routes are what the browser polls to render live
state and what a keyless/manual demo uses.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app import runtime
from app.analysis import evidence as analysis
from app.deps import load_job
from app.jobs.worker import start_research
from app.models import (
    ChallengeRequest,
    ChallengeResult,
    EvidencePacket,
    ExcludeRequest,
    QueryRequest,
    QueryResult,
    ResearchCreateResponse,
    ResearchJob,
    ResearchRequest,
)

router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("", response_model=ResearchCreateResponse)
async def create_research(request: ResearchRequest) -> ResearchCreateResponse:
    job = await start_research(request)
    return ResearchCreateResponse(research_id=job.research_id, status=job.status)


@router.get("/latest")
async def latest_research() -> dict:
    """The most recently started research (so the UI can follow the voice)."""
    return {"research_id": runtime.get_latest_research()}


@router.get("/{research_id}", response_model=ResearchJob)
async def get_research(job: ResearchJob = Depends(load_job)) -> ResearchJob:
    return job


@router.get("/{research_id}/evidence", response_model=EvidencePacket)
async def get_evidence(job: ResearchJob = Depends(load_job)) -> EvidencePacket:
    return await analysis.build_packet(job)


@router.post("/{research_id}/query", response_model=QueryResult)
async def query_research(req: QueryRequest, job: ResearchJob = Depends(load_job)) -> QueryResult:
    return await analysis.run_query(job, req)


@router.post("/{research_id}/challenge", response_model=ChallengeResult)
async def challenge_research(
    req: ChallengeRequest, job: ResearchJob = Depends(load_job)
) -> ChallengeResult:
    result = await analysis.run_challenge(job, req)
    runtime.set_challenge(job.research_id, result)
    return result


@router.get("/{research_id}/challenge")
async def get_latest_challenge(research_id: str, response: Response):
    result = runtime.get_challenge(research_id)
    if result is None:
        response.status_code = 204
        return None
    return result


@router.post("/{research_id}/exclude", response_model=EvidencePacket)
async def exclude_thread(req: ExcludeRequest, job: ResearchJob = Depends(load_job)) -> EvidencePacket:
    job = await analysis.set_thread_excluded(job, req.thread_id, req.exclude)
    return await analysis.build_packet(job)
