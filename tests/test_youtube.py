import httpx
import respx

from product_voice.youtube import YouTubeClient


@respx.mock
def test_search_videos_parses_response() -> None:
    respx.get("https://www.googleapis.com/youtube/v3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": {"videoId": "abc"},
                        "snippet": {
                            "title": "Honest review",
                            "channelId": "channel-1",
                            "channelTitle": "Reviewer",
                            "publishedAt": "2025-01-01T00:00:00Z",
                        },
                    }
                ]
            },
        )
    )
    videos = YouTubeClient("test-key").search_videos("product review", 1)
    assert videos[0].id == "abc"
    assert videos[0].title == "Honest review"

