"""YouTube adapter — wraps the existing YouTubeClient, does not replace it.

``youtube.py`` already handles pagination, comment threads, replies and the
commentsDisabled case correctly. This only normalizes its output into
``SourceDocument`` so YouTube sits alongside the other sources.
"""
from __future__ import annotations

import logging
import re
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

        # YouTube search is fuzzy: searching "Product review" returns videos
        # about hair removal. Pulling hundreds of comments from an unrelated
        # video poisons the corpus far worse than missing one relevant video,
        # so require the title to actually name the product before spending
        # quota on its comments.
        matching = [v for v in videos if _title_matches(v.title, product)]
        if matching:
            videos = matching
        else:
            log.warning(
                "no video title matched %r — keeping top %d unscreened",
                product,
                len(videos),
            )

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


def _title_matches(title: str, product: str) -> bool:
    """Does this video's title actually name the product?

    Requires every distinctive token of the product name to appear, so
    "iPhone 18" does not match a video titled "iPhone 17 Review".

    Short numeric tokens are kept deliberately: a version number is often the
    only thing separating this product from the previous one, and dropping it
    as "too short" silently collects the wrong generation. They are matched on
    a word boundary so "18" does not match "2018".
    """
    lowered = (title or "").casefold()
    tokens = [
        t for t in re.split(r"\W+", product.casefold()) if len(t) > 2 or t.isdigit()
    ]
    if not tokens:
        return True
    for token in tokens:
        if token.isdigit():
            if not re.search(rf"(?<!\d){re.escape(token)}(?!\d)", lowered):
                return False
        elif token not in lowered:
            return False
    return True
