"""External actions — the Rox angle: the agent takes a real action on messy data.

Two steps by design: draft first (preview on screen), then create only after
explicit human approval.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app import runtime
from app.analysis import evidence as analysis
from app.deps import load_job
from app.models import ResearchJob, Ticket, TicketDraft

router = APIRouter(prefix="/api/actions", tags=["actions"])


class TicketDraftRequest(BaseModel):
    research_id: str
    aspect: Optional[str] = None


@router.post("/ticket/draft", response_model=TicketDraft)
async def create_ticket_draft(req: TicketDraftRequest) -> TicketDraft:
    job = await load_job(req.research_id)
    draft = await analysis.draft_ticket(job, req.aspect)
    runtime.set_ticket_draft(job.research_id, draft)
    return draft


@router.get("/ticket/draft/{research_id}")
async def get_ticket_draft(research_id: str, response: Response):
    draft = runtime.get_ticket_draft(research_id)
    if draft is None:
        response.status_code = 204
        return None
    return draft


@router.post("/ticket", response_model=Ticket)
async def create_ticket(draft: TicketDraft) -> Ticket:
    """Create the ticket from an (approved) draft."""
    return await analysis.create_ticket(draft)
