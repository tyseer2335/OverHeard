from datetime import UTC, datetime

from product_voice.analysis import CommentAnalyzer
from product_voice.bridge import to_enriched_comment, to_enriched_comments
from product_voice.sources.base import SourceDocument


def _doc(**overrides) -> SourceDocument:
    base = dict(
        id="hackernews_1",
        source="hackernews",
        product="Widget",
        search_query="Widget review",
        text="The app crashes constantly and the battery drains in an hour.",
        author="someone",
        url="https://news.ycombinator.com/item?id=1",
        score=17,
        reply_count=3,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        thread_id="story-99",
        thread_title="Ask HN: thoughts?",
        container_id="news.ycombinator.com",
        container_title="Hacker News",
    )
    base.update(overrides)
    return SourceDocument(**base)


def test_bridge_maps_generic_fields_onto_pipeline_shape() -> None:
    enriched = to_enriched_comment(_doc(), CommentAnalyzer())

    assert enriched.source == "hackernews"
    assert enriched.url == "https://news.ycombinator.com/item?id=1"
    # generic -> youtube-shaped field mapping
    assert enriched.video_id == "story-99"
    assert enriched.video_title == "Ask HN: thoughts?"
    assert enriched.channel_id == "news.ycombinator.com"
    assert enriched.like_count == 17
    assert enriched.published_at == datetime(2026, 1, 2, tzinfo=UTC)


def test_bridge_applies_analyzer() -> None:
    enriched = to_enriched_comment(_doc(), CommentAnalyzer())

    assert enriched.is_complaint is True
    assert enriched.sentiment in {"negative", "neutral", "positive"}
    assert "reliability" in enriched.issue_categories


def test_bridge_falls_back_when_source_has_no_timestamp() -> None:
    doc = _doc(created_at=None)
    enriched = to_enriched_comment(doc, CommentAnalyzer())

    # must still be indexable / recency-sortable
    assert enriched.published_at == doc.collected_at
    assert enriched.video_published_at is None


def test_bridge_handles_a_source_with_no_container() -> None:
    doc = _doc(
        id="browserbase_x", source="browserbase", thread_id="", container_id=""
    )
    enriched = to_enriched_comment(doc, CommentAnalyzer())

    # video_id is required downstream, so it falls back to the doc id
    assert enriched.video_id == "browserbase_x"
    assert enriched.channel_id == ""


def test_bridge_converts_a_batch() -> None:
    docs = [_doc(), _doc(id="hackernews_2")]
    assert len(to_enriched_comments(docs)) == 2
