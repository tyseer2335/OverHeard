"""Ephemeral in-process UI state.

The ElevenLabs webhook tools and the browser frontend hit the same backend
process, so a little in-memory state is the simplest way to let the voice
conversation drive the on-screen dashboard: the agent starts research / issues a
challenge, we stash the result here, and the polling frontend renders it.

Nothing here is durable — that's fine, it's live-demo view state, not evidence.
"""
from __future__ import annotations

from app.models import ChallengeResult, TicketDraft

# most recently created research (so the UI can auto-focus what voice started)
latest_research_id: str | None = None

# research_id -> last challenge / ticket draft, for the UI panels
_challenges: dict[str, ChallengeResult] = {}
_ticket_drafts: dict[str, TicketDraft] = {}


def set_latest_research(research_id: str) -> None:
    global latest_research_id
    latest_research_id = research_id


def get_latest_research() -> str | None:
    return latest_research_id


def set_challenge(research_id: str, result: ChallengeResult) -> None:
    _challenges[research_id] = result


def get_challenge(research_id: str) -> ChallengeResult | None:
    return _challenges.get(research_id)


def clear_challenge(research_id: str) -> None:
    _challenges.pop(research_id, None)


def set_ticket_draft(research_id: str, draft: TicketDraft) -> None:
    _ticket_drafts[research_id] = draft


def get_ticket_draft(research_id: str) -> TicketDraft | None:
    return _ticket_drafts.get(research_id)
