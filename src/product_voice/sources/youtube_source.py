"""YouTube adapter — wraps the existing YouTubeClient, does not replace it.

``youtube.py`` already handles pagination, comment threads, replies and the
commentsDisabled case correctly. This only normalizes its output into
``SourceDocument`` so YouTube sits alongside the other sources.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ..youtube import CommentsDisabledError, YouTubeAPIError, YouTubeClient
from .base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.sources.youtube")


class YouTubeSource(SourceAdapter):
    name = "youtube"
    requires_credentials = True

    def __init__(self, api_key: str | None, max_videos: int = 5) -> None:
        self.api_key = api_key
        self.max_videos = max_videos

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "YOUTUBE_API_KEY not set"
        return True, ""

    def collect(self, product: str, query: str, limit: int) -> Iterable[SourceDocument]:
        ok, reason = self.available()
        if not ok:
            raise SourceError(reason)

        client = YouTubeClient(self.api_key or "")
        try:
            videos = client.search_videos(query, self.max_videos)
        except YouTubeAPIError as exc:
            raise SourceError(str(exc)) from exc

        if not videos:
            return []

        docs: list[SourceDocument] = []
        # Spread the budget across videos so one chatty video can't eat the run.
        per_video = max(1, limit // max(1, len(videos)))

        for video in videos:
            if len(docs) >= limit:
                break
            try:
                for comment in client.iter_comments(video.id, per_video):
                    docs.append(
                        SourceDocument(
                            id=f"youtube_{comment.id}",
                            source=self.name,
                            product=product,
                            search_query=query,
                            text=comment.text,
                            author=comment.author,
                            url=f"https://www.youtube.com/watch?v={video.id}&lc={comment.id}",
                            score=comment.like_count,
                            reply_count=comment.reply_count,
                            created_at=comment.published_at,
                            parent_id=comment.parent_id,
                            thread_id=video.id,
                            thread_title=video.title,
                            container_id=video.channel_id,
                            container_title=video.channel_title,
                            extra={"video_published_at": video.published_at.isoformat()},
                        )
                    )
                    if len(docs) >= limit:
                        break
            except CommentsDisabledError:
                log.info("comments disabled for video %s — skipping", video.id)
            except YouTubeAPIError as exc:
                # One bad video shouldn't kill the whole collection run.
                log.warning("youtube video %s failed: %s", video.id, exc)

        return docs
