import httpx
import respx

from product_voice.sources.lemmy import LemmySource
from product_voice.sources.steam import SteamSource


@respx.mock
def test_steam_resolves_app_id_and_parses_reviews() -> None:
    respx.get("https://store.steampowered.com/api/storesearch/").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 730, "name": "CS2"}]})
    )
    respx.get("https://store.steampowered.com/appreviews/730").mock(
        return_value=httpx.Response(
            200,
            json={
                "reviews": [
                    {
                        "recommendationid": "abc",
                        "review": "Great game but the anti-cheat is completely broken.",
                        "voted_up": False,
                        "votes_up": 12,
                        "comment_count": 2,
                        "timestamp_created": 1700000000,
                        "author": {"steamid": "76561", "playtime_forever": 600},
                    }
                ],
                "cursor": "next1",
            },
        )
    )
    docs = list(SteamSource().collect("CS2", "CS2", 1))

    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == "steam_abc"
    assert doc.source == "steam"
    assert doc.score == 12
    # ground-truth signal preserved for scoring the analysis layer
    assert doc.extra["voted_up"] is False
    assert doc.extra["playtime_hours"] == 10


@respx.mock
def test_steam_returns_nothing_when_no_title_matches() -> None:
    respx.get("https://store.steampowered.com/api/storesearch/").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    assert list(SteamSource().collect("Sony Headphones", "Sony Headphones", 10)) == []


@respx.mock
def test_lemmy_parses_comments() -> None:
    respx.get("https://lemmy.world/api/v3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "comments": [
                    {
                        "comment": {
                            "id": 5,
                            "content": "It gets really slow once your workspace grows large.",
                            "ap_id": "https://lemmy.world/comment/5",
                            "published": "2026-01-01T00:00:00Z",
                        },
                        "creator": {"name": "someone"},
                        "community": {"name": "technology"},
                        "counts": {"score": 7, "child_count": 1},
                        "post": {"id": 9, "name": "Thoughts on Notion?"},
                    }
                ]
            },
        )
    )
    docs = list(LemmySource(instances=["lemmy.world"]).collect("Notion", "Notion", 5))

    assert len(docs) == 1
    assert docs[0].id == "lemmy_lemmy.world_5"
    assert docs[0].score == 7
    assert docs[0].container_title == "c/technology"


@respx.mock
def test_lemmy_survives_a_dead_instance() -> None:
    respx.get("https://dead.example/api/v3/search").mock(
        return_value=httpx.Response(503)
    )
    respx.get("https://lemmy.world/api/v3/search").mock(
        return_value=httpx.Response(200, json={"comments": []})
    )
    # one instance down must not raise while another answers
    assert list(
        LemmySource(instances=["dead.example", "lemmy.world"]).collect("X", "X", 5)
    ) == []
