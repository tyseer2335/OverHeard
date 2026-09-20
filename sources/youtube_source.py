"""YouTube adapter -- pulls comments via the YouTube Data API v3.

Flow: search for videos about the product, then pull comment threads from each.

Setup:
    pip install google-api-python-client
    Get a key: Google Cloud Console -> enable "YouTube Data API v3" -> create API key
    Set env var: YOUTUBE_API_KEY

Quota note: the API has a daily quota (10,000 units default). search.list costs 100
units per call, commentThreads.list costs 1. So searching is the expensive part --
we cap video count to stay well under quota.
"""

import os
from schema import Item, iso
from datetime import datetime, timezone


def _client():
    from googleapiclient.discovery import build
    return build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"],
                 cache_discovery=False)


def _iso_from_rfc3339(s):
    """YouTube gives RFC3339 like '2026-09-01T12:00:00Z'. Normalize to our ISO."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


def search_youtube(query, product, max_videos=8, comments_per_video=100):
    """Search YouTube for `query`, pull comments from the top videos. Returns list[Item].

    max_videos:         how many videos to pull comments from (each search.list = 100 quota units)
    comments_per_video: max comments per video (paginated, 100 per page)
    """
    yt = _client()
    items = []

    # 1) find videos about the product
    try:
        search = yt.search().list(
            q=query, part="id", type="video", maxResults=min(max_videos, 50),
            relevanceLanguage="en", order="relevance",
        ).execute()
    except Exception as e:
        print(f"[youtube] search failed for '{query}': {e}")
        return items

    video_ids = [it["id"]["videoId"] for it in search.get("items", []) if it["id"].get("videoId")]

    # 2) pull comment threads from each video
    for vid in video_ids:
        pulled = 0
        page_token = None
        while pulled < comments_per_video:
            try:
                resp = yt.commentThreads().list(
                    part="snippet", videoId=vid,
                    maxResults=min(100, comments_per_video - pulled),
                    textFormat="plainText", order="relevance",
                    pageToken=page_token,
                ).execute()
            except Exception as e:
                # comments disabled on a video, etc. -- skip it, don't die
                print(f"[youtube] comments unavailable for video {vid}: {e}")
                break

            for thread in resp.get("items", []):
                sn = thread["snippet"]["topLevelComment"]["snippet"]
                text = (sn.get("textDisplay") or "").strip()
                if not text:
                    continue
                cid = thread["snippet"]["topLevelComment"]["id"]
                items.append(Item(
                    id=f"youtube_{cid}",
                    source="youtube",
                    text=text,
                    author=sn.get("authorDisplayName") or "unknown",
                    timestamp=_iso_from_rfc3339(sn.get("publishedAt", "")),
                    score=int(sn.get("likeCount") or 0),
                    url=f"https://www.youtube.com/watch?v={vid}&lc={cid}",
                    product=product,
                ))
                pulled += 1

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    print(f"[youtube] '{query}' -> {len(items)} comments from {len(video_ids)} videos")
    return items
