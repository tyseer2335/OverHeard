"""Source adapter interface.

Every source (fixtures, Reddit, Browserbase, ...) implements the same contract so
the job worker can treat them uniformly and mark them completed/failed
independently — which is what makes the PARTIAL terminal state meaningful.
"""
from __future__ import annotations

import abc
from typing import Awaitable, Callable, Optional

from app.models import RawItem, ResearchRequest

# progress callback: (event_type, payload) — used e.g. to surface a live browser view
EventCb = Optional[Callable[[str, dict], Awaitable[None]]]


class SourceAdapter(abc.ABC):
    name: str = "base"

    def available(self) -> bool:
        """Whether this adapter has what it needs (keys, deps) to run."""
        return True

    @abc.abstractmethod
    async def collect(self, request: ResearchRequest, on_event: EventCb = None) -> list[RawItem]:
        """Collect raw items. Raise on hard failure so the worker records it."""
        raise NotImplementedError
