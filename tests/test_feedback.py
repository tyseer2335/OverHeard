from datetime import UTC, datetime

from product_voice.enrich import enrich_records
from product_voice.feedback import (
    FeedbackRecord,
    from_source_document,
    from_source_documents,
    guess_language,
    hash_author,
)
from product_voice.sources.base import SourceDocument


def _doc(**overrides) -> SourceDocument:
    base = dict(
        id="steam_12345",
        source="steam",
        product="Cyberpunk 2077",
        search_query="Cyberpunk 2077",
        text="The driving physics feel awful and it crashes on my PS5.",
        author="76561198",
        url="https://steamcommunity.com/x",
        score=9,
        reply_count=2,
        created_at=datetime(2026, 2, 3, tzinfo=UTC),
        thread_id="1091500",
        thread_title="Steam reviews",
        container_id="store.steampowered.com",
        container_title="Steam",
        extra={"voted_up": False, "playtime_hours": 42},
    )
    base.update(overrides)
    return SourceDocument(**base)


# ------------------------------------------------------------- normalization
def test_normalizes_to_the_agreed_contract() -> None:
    record = from_source_document(_doc(), "org-1", "prod-1")

    assert record.organization_id == "org-1"
    assert record.product_id == "prod-1"
    assert record.source == "steam"
    # "<source>_<native id>" is unwrapped back to the native id
    assert record.external_id == "12345"
    assert record.content_type == "review"
    assert record.language == "en"
    assert record.published_at == datetime(2026, 2, 3, tzinfo=UTC)
    assert record.engagement.score == 9
    assert record.engagement.replies == 2


def test_ground_truth_survives_normalization() -> None:
    record = from_source_document(_doc(), "org-1", "prod-1")
    assert record.engagement.voted_up is False
    assert record.engagement.playtime_hours == 42


def test_source_specific_extras_land_in_metadata() -> None:
    record = from_source_document(_doc(), "org-1", "prod-1")
    assert record.source_metadata["thread_title"] == "Steam reviews"
    assert record.source_metadata["container_id"] == "store.steampowered.com"
    # promoted fields are not duplicated into metadata
    assert "voted_up" not in record.source_metadata


def test_author_is_hashed_not_stored() -> None:
    record = from_source_document(_doc(), "org-1", "prod-1")
    assert record.author_hash
    assert "76561198" not in record.author_hash


def test_author_hash_is_scoped_per_source() -> None:
    # the same handle on two platforms is not the same person
    assert hash_author("alice", "reddit") != hash_author("alice", "youtube")
    assert hash_author("alice", "reddit") == hash_author("Alice", "reddit")
    assert hash_author("", "reddit") == ""


def test_language_guess_flags_non_english_without_lying() -> None:
    assert guess_language("This product is great") == "en"
    assert guess_language("これは素晴らしい製品です。とても良い。") == "unknown"
    assert guess_language("") == "unknown"


# ---------------------------------------------------- duplicate prevention
def test_document_id_is_stable_for_the_same_item() -> None:
    a = from_source_document(_doc(), "org-1", "prod-1")
    b = from_source_document(_doc(), "org-1", "prod-1")
    assert a.document_id == b.document_id


def test_document_id_is_scoped_per_tenant() -> None:
    a = from_source_document(_doc(), "org-1", "prod-1")
    b = from_source_document(_doc(), "org-2", "prod-1")
    # two organizations watching the same public comment each keep their own row
    assert a.document_id != b.document_id


def test_content_hash_matches_across_sources() -> None:
    text = "It crashes every morning without fail."
    a = FeedbackRecord(source="hackernews", external_id="1", content=text)
    b = FeedbackRecord(source="lemmy", external_id="2", content=f"  {text.upper()} ")
    assert a.content_hash == b.content_hash
    assert a.document_id != b.document_id


def test_batch_conversion() -> None:
    assert len(from_source_documents([_doc(), _doc(id="steam_2")], "o", "p")) == 2


# -------------------------------------------------------------- enrichment
def test_enrichment_uses_the_llm_result() -> None:
    from product_voice.llm_analysis import AnalysisResult

    class _Stub:
        def available(self) -> bool:
            return True

        def analyze_many(self, texts, product):
            return [
                AnalysisResult(
                    relevant=True,
                    sentiment="negative",
                    sentiment_score=-0.8,
                    kind="complaint",
                    issue_categories=["reliability"],
                    summary="crashes on PS5",
                )
                for _ in texts
            ]

    records = from_source_documents([_doc()], "org-1", "prod-1")
    enrich_records(records, "Cyberpunk 2077", _Stub())
    record = records[0]

    assert record.sentiment == "negative"
    assert record.is_complaint is True
    assert record.issue_categories == ["reliability"]
    assert record.relevant is True
    assert record.source_metadata["summary"] == "crashes on PS5"


def test_enrichment_falls_back_to_lexicon_without_an_llm() -> None:
    class _Unavailable:
        def available(self) -> bool:
            return False

        def analyze_many(self, texts, product):  # pragma: no cover
            raise AssertionError("must not be called")

    records = from_source_documents([_doc()], "org-1", "prod-1")
    enrich_records(records, "Cyberpunk 2077", _Unavailable())
    record = records[0]

    assert record.sentiment in {"positive", "negative", "neutral"}
    # relevance is left unknown rather than guessed, so the row stays visible
    assert record.relevant is None
    assert record.source_metadata["analysis"] == "lexicon_fallback"
