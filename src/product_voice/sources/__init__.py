"""Pluggable data sources.

Adapters are built from the environment rather than ``config.Settings`` on
purpose: ``Settings`` hard-requires Elastic and Supabase credentials, and data
collection must stay runnable when those aren't configured yet.
"""
from __future__ import annotations

import os

from .base import SourceAdapter, SourceDocument, SourceError
from .browserbase import BrowserbaseSource
from .hackernews import HackerNewsSource
from .lemmy import LemmySource
from .steam import SteamSource
from .youtube_source import YouTubeSource

__all__ = [
    "SourceAdapter",
    "SourceDocument",
    "SourceError",
    "BrowserbaseSource",
    "HackerNewsSource",
    "LemmySource",
    "SteamSource",
    "YouTubeSource",
    "build_sources",
    "DEFAULT_SOURCES",
    "ALL_SOURCES",
]

DEFAULT_SOURCES = ["hackernews", "youtube", "browserbase", "lemmy"]
#: Steam is excluded from the default set because it only matches games;
#: the planner selects it when the product warrants it.
ALL_SOURCES = ["hackernews", "youtube", "browserbase", "lemmy", "steam"]


def build_sources(
    names: list[str] | None = None,
    *,
    browserbase_targets: list[str] | None = None,
    max_videos: int = 5,
    use_proxies: bool = False,
) -> list[SourceAdapter]:
    """Instantiate the requested adapters, reading credentials from env.

    Unknown names are skipped with a warning rather than raising, so a typo in
    ``--sources`` can't abort a collection run mid-demo.
    """
    requested = names or DEFAULT_SOURCES
    built: list[SourceAdapter] = []

    for name in requested:
        key = name.strip().casefold()
        if key == "hackernews":
            built.append(HackerNewsSource())
        elif key == "youtube":
            built.append(
                YouTubeSource(os.getenv("YOUTUBE_API_KEY"), max_videos=max_videos)
            )
        elif key == "lemmy":
            built.append(LemmySource())
        elif key == "steam":
            built.append(SteamSource())
        elif key == "browserbase":
            built.append(
                BrowserbaseSource(
                    api_key=os.getenv("BROWSERBASE_API_KEY"),
                    project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
                    targets=browserbase_targets,
                    use_proxies=use_proxies,
                )
            )
        else:
            import logging

            logging.getLogger("product_voice.sources").warning(
                "unknown source %r — skipping", name
            )
    return built
