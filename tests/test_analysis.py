from product_voice.analysis import CommentAnalyzer


def test_negative_comment_is_categorized() -> None:
    result = CommentAnalyzer().analyze(
        "The app is painfully slow and my microphone keeps failing. Worst meeting app."
    )
    assert result["sentiment"] == "negative"
    assert result["is_complaint"] is True
    assert result["issue_categories"] == ["performance", "reliability", "audio_video"]


def test_positive_comment_is_not_a_complaint() -> None:
    result = CommentAnalyzer().analyze("I love this product, it works really well!")
    assert result["sentiment"] == "positive"
    assert result["is_complaint"] is False


def test_category_terms_only_match_complete_words() -> None:
    result = CommentAnalyzer().analyze("Microsoft Teams is used by my company.")
    assert "audio_video" not in result["issue_categories"]
