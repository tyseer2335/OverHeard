import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


ISSUE_PATTERNS: dict[str, tuple[str, ...]] = {
    "performance": (
        "slow", "lag", "laggy", "freeze", "freezes", "freezing", "cpu", "memory", "battery"
    ),
    "reliability": (
        "bug", "bugs", "broken", "crash", "crashes", "crashed", "crashing",
        "error", "errors", "outage", "disconnect", "disconnected", "fail",
        "fails", "failed", "failing",
    ),
    "usability": ("confusing", "clunky", "hard to", "difficult", "ui", "ux", "interface"),
    "audio_video": ("audio", "camera", "microphone", "mic", "video", "screen share"),
    "notifications": ("notification", "alert", "ping", "badge"),
    "authentication": ("login", "log in", "sign in", "password", "account", "sso"),
    "integrations": ("integration", "sync", "calendar", "outlook", "plugin"),
    "pricing": ("price", "pricing", "expensive", "cost", "subscription", "paywall"),
    "support": ("support", "help desk", "customer service", "documentation"),
}

COMPLAINT_MARKERS = re.compile(
    r"\b(hate|awful|terrible|worst|annoying|frustrat\w*|problem\w*|issue\w*|"
    r"unusable|broken|bug\w*|fail\w*|crash\w*|doesn'?t work|not working)\b",
    re.IGNORECASE,
)


class CommentAnalyzer:
    def __init__(self) -> None:
        self.sentiment_analyzer = SentimentIntensityAnalyzer()

    def analyze(self, text: str) -> dict[str, object]:
        score = round(self.sentiment_analyzer.polarity_scores(text)["compound"], 4)
        sentiment = "negative" if score <= -0.05 else "positive" if score >= 0.05 else "neutral"
        categories = [
            category
            for category, phrases in ISSUE_PATTERNS.items()
            if any(self._contains_phrase(text, phrase) for phrase in phrases)
        ]
        return {
            "sentiment": sentiment,
            "sentiment_score": score,
            "is_complaint": score <= -0.25 or bool(COMPLAINT_MARKERS.search(text)),
            "issue_categories": categories,
        }

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        """Match whole words/phrases so `mic` does not match `Microsoft`."""
        return bool(
            re.search(
                rf"(?<!\w){re.escape(phrase)}(?!\w)",
                text,
                flags=re.IGNORECASE,
            )
        )
