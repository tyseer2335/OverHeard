"""Common schema + normalization for all data sources.

Every adapter returns a list of Item dicts in THIS shape, so everything
downstream (cleaning, Elastic, the agent) treats all sources the same.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Item:
    id: str            # unique across all sources, e.g. "reddit_abc123" -- used for dedupe
    source: str        # "reddit" | "hn" | "reviews"
    text: str          # the actual comment/post/review body
    author: str        # username or "unknown"
    timestamp: str     # ISO 8601 UTC, e.g. "2026-09-01T12:00:00+00:00"
    score: int         # upvotes / likes / helpfulness -- used later for weighting
    url: str           # permalink, for citations
    product: str       # the product this item is about

    def to_dict(self):
        return asdict(self)


def iso(ts_epoch: float) -> str:
    """Turn a unix epoch (Reddit/HN give these) into ISO 8601 UTC."""
    return datetime.fromtimestamp(ts_epoch, tz=timezone.utc).isoformat()


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
