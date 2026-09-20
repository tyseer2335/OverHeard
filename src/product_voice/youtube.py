from collections.abc import Iterator
from typing import Any

import httpx

from .models import Comment, Video


class YouTubeAPIError(RuntimeError):
    pass


class CommentsDisabledError(YouTubeAPIError):
    pass


class YouTubeClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30.0)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(
            f"{self.BASE_URL}/{path}", params={**params, "key": self.api_key}
        )
        if response.status_code == 403 and path == "commentThreads":
            details = response.json().get("error", {}).get("errors", [])
            if any(item.get("reason") == "commentsDisabled" for item in details):
                raise CommentsDisabledError("Comments are disabled for this video")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise YouTubeAPIError(
                f"YouTube {path} request failed ({response.status_code}): {response.text[:500]}"
            ) from exc
        return response.json()

    def search_videos(self, query: str, limit: int) -> list[Video]:
        videos: list[Video] = []
        page_token: str | None = None
        while len(videos) < limit:
            params: dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "relevance",
                "maxResults": min(50, limit - len(videos)),
                "safeSearch": "moderate",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("search", params)
            for item in data.get("items", []):
                snippet = item["snippet"]
                videos.append(
                    Video(
                        id=item["id"]["videoId"],
                        title=snippet["title"],
                        channel_id=snippet["channelId"],
                        channel_title=snippet["channelTitle"],
                        published_at=snippet["publishedAt"],
                    )
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return videos

    def iter_comments(
        self, video_id: str, limit: int, include_replies: bool = False
    ) -> Iterator[Comment]:
        yielded = 0
        page_token: str | None = None
        while yielded < limit:
            params: dict[str, Any] = {
                "part": "snippet,replies" if include_replies else "snippet",
                "videoId": video_id,
                "maxResults": min(100, limit - yielded),
                "textFormat": "plainText",
                "order": "relevance",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("commentThreads", params)
            for thread in data.get("items", []):
                top = thread["snippet"]["topLevelComment"]
                comment = self._parse_comment(
                    top, reply_count=thread["snippet"].get("totalReplyCount", 0)
                )
                yield comment
                yielded += 1
                if yielded >= limit:
                    return
                if include_replies:
                    for reply in self._iter_replies(comment.id, limit - yielded):
                        yield reply
                        yielded += 1
                        if yielded >= limit:
                            return
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    def _iter_replies(self, parent_id: str, limit: int) -> Iterator[Comment]:
        page_token: str | None = None
        yielded = 0
        while yielded < limit:
            params: dict[str, Any] = {
                "part": "snippet",
                "parentId": parent_id,
                "maxResults": min(100, limit - yielded),
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            data = self._get("comments", params)
            for item in data.get("items", []):
                yield self._parse_comment(item, parent_id=parent_id)
                yielded += 1
            page_token = data.get("nextPageToken")
            if not page_token:
                break

    @staticmethod
    def _parse_comment(
        item: dict[str, Any], parent_id: str | None = None, reply_count: int = 0
    ) -> Comment:
        snippet = item["snippet"]
        return Comment(
            id=item["id"],
            video_id=snippet["videoId"],
            parent_id=parent_id,
            author=snippet.get("authorDisplayName", "Unknown"),
            text=snippet["textDisplay"],
            like_count=snippet.get("likeCount", 0),
            reply_count=reply_count,
            published_at=snippet["publishedAt"],
            updated_at=snippet["updatedAt"],
        )

