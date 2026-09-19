"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import HTTPException

from app.models import ResearchJob
from app.store import get_store


async def load_job(research_id: str) -> ResearchJob:
    job = await get_store().get_job(research_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"research {research_id} not found")
    return job
