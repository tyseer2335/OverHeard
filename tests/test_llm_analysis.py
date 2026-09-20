from product_voice.llm_analysis import LLMAnalyzer, _coerce, _extract_json


def test_extract_json_handles_fence_and_prose() -> None:
    assert _extract_json('```json\n{"items": []}\n```') == {"items": []}
    assert _extract_json('Sure:\n{"items": []}\nDone.') == {"items": []}


def test_coerce_clamps_out_of_range_score() -> None:
    assert _coerce({"score": 9.5}).sentiment_score == 1.0
    assert _coerce({"score": -9.5}).sentiment_score == -1.0
    assert _coerce({"score": "not a number"}).sentiment_score == 0.0


def test_coerce_rejects_invented_labels() -> None:
    # the model must not be able to widen the enum
    assert _coerce({"sentiment": "furious"}).sentiment == "neutral"
    assert _coerce({"kind": "rant"}).kind == "other"


def test_coerce_drops_unknown_issue_categories() -> None:
    result = _coerce({"issues": ["performance", "vibes", "PRICING", "performance"]})
    # unknown dropped, case normalized, duplicates collapsed
    assert result.issue_categories == ["performance", "pricing"]


def test_coerce_treats_non_boolean_relevance_as_unknown() -> None:
    assert _coerce({"relevant": "yes"}).relevant is None
    assert _coerce({"relevant": True}).relevant is True
    assert _coerce({"relevant": False}).relevant is False


def test_analyzer_returns_one_result_per_input_without_a_key() -> None:
    analyzer = LLMAnalyzer(api_key="")
    results = analyzer.analyze_many(["a", "b", "c"], "Widget")
    assert len(results) == 3
    # unknown, not a confident neutral
    assert all(r.relevant is None for r in results)


def test_analyzer_handles_empty_input() -> None:
    assert LLMAnalyzer(api_key="").analyze_many([], "Widget") == []


def test_batch_failure_degrades_instead_of_raising(monkeypatch) -> None:
    analyzer = LLMAnalyzer(api_key="test-key")
    monkeypatch.setattr(analyzer, "available", lambda: True)
    monkeypatch.setattr(
        analyzer, "_analyze_batch", lambda payload, product: {}
    )
    results = analyzer.analyze_many(["one", "two"], "Widget")
    assert len(results) == 2
    assert all(r.relevant is None for r in results)
