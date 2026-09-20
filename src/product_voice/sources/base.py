"""Source-agnostic collection contract.

The original pipeline was YouTube-shaped end to end: ``Comment`` carries a
``video_id``, ``EnrichedComment`` demands a channel, and ``IngestResult``
counts videos. Nothing that isn't a video could be represented.

``SourceDocument`` is the neutral shape every adapter returns instead, so a
YouTube comment, a Hacker News reply and a Browserbase-scraped forum post all
arrive downstream looking the same. It is deliberately a superset: generic
fields for the things every source has (text, author, url, score, time) plus
``extra`` for whatever is specific to one source.

Naming maps onto the old model like this::

    video_id     -> thread_id        (the container the comment lives in)
    video_title  -> thread_title
    channel_id   -> container_id     (who published the container)
    like_count   -> score            (generic engagement signal)
"""
from __future__ import annotations

import abc
import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Iterable

from pydantic import BaseModel, Field


_WS = re.compile(r"\s+")


class SourceDocument(BaseModel):
    """One opinion/comment/post, normalized across every source."""

    # identity
    id: str                       # globally unique, always "<source>_<native id>"
    source: str                   # "youtube" | "hackernews" | "browserbase" | ...
    product: str                  # product this was collected for
    search_query: str = ""        # query that surfaced it (provenance for the demo)

    # content
    text: str
    author: str = "unknown"
    url: str = ""

    # signal
    score: int = 0                # likes / upvotes / points
    reply_count: int = 0
    created_at: datetime | None = None

    # structure
    parent_id: str | None = None
    thread_id: str = ""           # video id, HN story id, page url...
    thread_title: str = ""
    container_id: str = ""        # channel id, subreddit, domain...
    container_title: str = ""

    # provenance / escape hatch for source-specific fields
    extra: dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def dedupe_key(self) -> str:
        """Hash of normalized text — catches the same opinion reposted anywhere.

        Cross-source duplicates are real: the same review gets quoted on HN and
        scraped off a web page. Keying on text (not id) is what lets the clean
        layer collapse them.
        """
        normalized = _WS.sub(" ", self.text or "").strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SourceError(RuntimeError):
    """Adapter failed in a way the caller should record but survive."""


class SourceAdapter(abc.ABC):
    """Every source implements this so the collector treats them uniformly."""

    name: str = "base"
    #: False when the source needs credentials/deps that may be absent.
    requires_credentials: bool = False

    def available(self) -> tuple[bool, str]:
        """Whether this adapter can run. Returns (ok, reason_if_not).

        Returning a reason rather than just a bool means the CLI can tell you
        *why* a source sat out, which is the difference between a useful run
        report and a silent empty result.
        """
        return True, ""

    @abc.abstractmethod
    def collect(
        self, product: str, query: str, limit: int
    ) -> Iterable[SourceDocument]:
        """Collect up to ``limit`` documents. Raise SourceError on hard failure."""
        raise NotImplementedError
