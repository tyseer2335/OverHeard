from product_voice.planner import (
    CollectionPlan,
    SourcePlan,
    _extract_json,
    fallback_plan,
    plan_collection,
)


def test_fallback_plan_used_without_api_key() -> None:
    plan = plan_collection("Sony WH-1000XM5", api_key="")
    assert plan.used_llm is False
    assert "hackernews" in plan.source_names
    assert all(source.queries for source in plan.sources)


def test_fallback_skips_steam_for_non_games() -> None:
    assert "steam" not in fallback_plan("Sony WH-1000XM5").source_names


def test_fallback_includes_steam_for_obvious_games() -> None:
    assert "steam" in fallback_plan("Elden Ring game").source_names


def test_extract_json_handles_markdown_fence() -> None:
    raw = '```json\n{"sources": [{"name": "hackernews", "queries": ["a"]}]}\n```'
    assert _extract_json(raw)["sources"][0]["name"] == "hackernews"


def test_extract_json_handles_surrounding_prose() -> None:
    raw = 'Sure! Here is the plan:\n{"reasoning": "x", "sources": []}\nHope that helps.'
    assert _extract_json(raw)["reasoning"] == "x"


def test_plan_summary_is_readable() -> None:
    plan = CollectionPlan(
        product="Widget",
        sources=[SourcePlan("hackernews", ["Widget app"])],
        reasoning="because",
        used_llm=True,
    )
    text = plan.summary()
    assert "Widget" in text and "hackernews" in text and "Widget app" in text
