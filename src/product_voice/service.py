from datetime import UTC, datetime

from .analysis import CommentAnalyzer
from .elastic import CommentStore
from .models import EnrichedComment, IngestRequest, IngestResult
from .youtube import CommentsDisabledError, YouTubeClient


class IngestionService:
    def __init__(
        self, youtube: YouTubeClient, store: CommentStore, analyzer: CommentAnalyzer
    ) -> None:
        self.youtube = youtube
        self.store = store
        self.analyzer = analyzer

    def ingest(self, request: IngestRequest) -> IngestResult:
        query = request.query or f"{request.product} review problems"
        videos = self.youtube.search_videos(query, request.max_videos)
        self.store.ensure_index()
        indexed = 0
        processed = 0
        skipped: list[dict[str, str]] = []

        for video in videos:
            try:
                comments = self.youtube.iter_comments(
                    video.id,
                    request.max_comments_per_video,
                    include_replies=request.include_replies,
                )
                enriched = (
                    EnrichedComment(
                        **comment.model_dump(),
                        product=request.product,
                        search_query=query,
                        video_title=video.title,
                        channel_id=video.channel_id,
                        channel_title=video.channel_title,
                        video_published_at=video.published_at,
                        **self.analyzer.analyze(comment.text),
                        ingested_at=datetime.now(UTC),
                    )
                    for comment in comments
                )
                indexed += self.store.index_comments(enriched)
                processed += 1
            except CommentsDisabledError as exc:
                skipped.append({"video_id": video.id, "reason": str(exc)})

        return IngestResult(
            product=request.product,
            query=query,
            videos_found=len(videos),
            videos_processed=processed,
            comments_indexed=indexed,
            videos_skipped=skipped,
        )

