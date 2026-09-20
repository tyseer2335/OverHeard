import httpx
import respx

from product_voice.collect import collect
from product_voice.sources.base import SourceAdapter, SourceDocument, SourceError
from product_voice.sources.browserbase import (
    _looks_blocked,
    _paragraphs,
    _to_text,
)
from product_voice.sources.hackernews import HackerNewsSource


# --------------------------------------------------------------- hacker news
@respx.mock
def test_hackernews_normalizes_hits() -> None:
    respx.get("https://hn.algolia.com/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "objectID": "123",
                        "comment_text": (
                            "The <i>battery life</i> is great but the app "
                            "crashes constantly &#x27;every day&#x27;."
                        ),
                        "author": "someone",
                        "points": 42,
                        "created_at_i": 1700000000,
                        "story_id": 999,
                        "story_title": "Ask HN: thoughts?",
                    }
                ]
            },
        )
    )
    docs = list(HackerNewsSource().collect("Widget", "Widget", 10))

    assert docs, "expected at least one document"
    doc = docs[0]
    assert doc.id == "hackernews_123"
    assert doc.source == "hackernews"
    assert doc.score == 42
    assert doc.url == "https://news.ycombinator.com/item?id=123"
    # HTML tags stripped and entities decoded
    assert "<i>" not in doc.text
    assert "'every day'" in doc.text
    assert doc.created_at is not None


@respx.mock
def test_hackernews_skips_short_text() -> None:
    respx.get("https://hn.algolia.com/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={"hits": [{"objectID": "1", "comment_text": "+1", "author": "x"}]},
        )
    )
    assert list(HackerNewsSource().collect("Widget", "Widget", 10)) == []


@respx.mock
def test_hackernews_raises_source_error_on_http_failure() -> None:
    respx.get("https://hn.algolia.com/api/v1/search").mock(
        return_value=httpx.Response(500)
    )
    try:
        list(HackerNewsSource().collect("Widget", "Widget", 5))
    except SourceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected SourceError")


# ------------------------------------------------------------ browserbase bits
def test_to_text_strips_markdown_chrome() -> None:
    raw = "# Title\n\n![](data:image/png;base64,AAAA)\n\n[Click here](https://x.com) stays."
    text = _to_text(raw)
    assert "data:image" not in text
    assert "https://x.com" not in text
    assert "Click here stays." in text
    assert "#" not in text


def test_looks_blocked_detects_captcha_behind_http_200() -> None:
    assert _looks_blocked("Prove your humanity\nComplete the challenge below")
    assert _looks_blocked("Please log in to continue")
    assert not _looks_blocked("Notion is slow once your workspace grows large.")


def test_paragraphs_prefers_on_topic_and_caps() -> None:
    on_topic = "Notion gets painfully slow once the workspace grows past a few thousand blocks. " * 2
    off_topic = "This unrelated paragraph is long enough to qualify by length alone but never mentions it. " * 2
    paras = _paragraphs(f"{on_topic}\n\n{off_topic}", "Notion")
    assert len(paras) == 1
    assert "Notion" in paras[0]


def test_paragraphs_skips_nav_rows() -> None:
    nav = "Home | Docs | Pricing | Blog | Careers | Login | Signup | About | Contact"
    assert _paragraphs(nav, "Notion") == []


# --------------------------------------------------------------- collect layer
class _Fake(SourceAdapter):
    def __init__(self, name: str, docs: list[SourceDocument], ok: bool = True) -> None:
        self.name = name
        self._docs = docs
        self._ok = ok

    def available(self) -> tuple[bool, str]:
        return (True, "") if self._ok else (False, "no credentials")

    def collect(self, product: str, query: str, limit: int):
        return self._docs


def _doc(doc_id: str, text: str, source: str = "test") -> SourceDocument:
    return SourceDocument(id=doc_id, source=source, product="Widget", text=text)


LONG = "This product genuinely crashes every single morning without fail."


def test_collect_dedupes_across_sources_by_text() -> None:
    a = _Fake("a", [_doc("a_1", LONG, "a")])
    b = _Fake("b", [_doc("b_1", LONG, "b")])
    result = collect([a, b], "Widget")

    assert len(result.documents) == 1
    assert result.reject_reasons == {"duplicate_text": 1}


def test_collect_filters_junk_and_records_reasons() -> None:
    docs = [
        _doc("1", LONG),
        _doc("2", "short"),
        _doc("3", "Please accept all cookies to continue browsing this website today"),
        _doc("4", "https://example.com"),
    ]
    result = collect([_Fake("s", docs)], "Widget")

    assert len(result.documents) == 1
    reasons = result.reject_reasons
    assert reasons["too_short"] == 1
    assert reasons["boilerplate"] == 1
    assert reasons["link_only"] == 1


def test_collect_reports_skipped_source_without_failing() -> None:
    ok = _Fake("good", [_doc("1", LONG)])
    missing = _Fake("nokeys", [], ok=False)
    result = collect([ok, missing], "Widget")

    statuses = {r.name: r.status for r in result.reports}
    assert statuses == {"good": "ok", "nokeys": "skipped"}
    assert len(result.documents) == 1


def test_collect_survives_a_crashing_source() -> None:
    class Boom(SourceAdapter):
        name = "boom"

        def collect(self, product: str, query: str, limit: int):
            raise RuntimeError("upstream exploded")

    result = collect([Boom(), _Fake("good", [_doc("1", LONG)])], "Widget")

    statuses = {r.name: r.status for r in result.reports}
    assert statuses["boom"] == "failed"
    assert statuses["good"] == "ok"
    assert len(result.documents) == 1
