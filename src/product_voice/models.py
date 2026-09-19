from datetime import datetime

from pydantic import BaseModel, Field


class Video(BaseModel):
    id: str
    title: str
    channel_id: str
    channel_title: str
    published_at: datetime


class Comment(BaseModel):
    id: str
    video_id: str
    parent_id: str | None = None
    author: str
    text: str
    like_count: int = 0
    reply_count: int = 0
    published_at: datetime
    updated_at: datetime


class EnrichedComment(Comment):
    product: str
    search_query: str
    video_title: str
    channel_id: str
    channel_title: str
    video_published_at: datetime
    sentiment: str
    sentiment_score: float
    is_complaint: bool
    issue_categories: list[str]
    ingested_at: datetime


class IngestRequest(BaseModel):
    product: str = Field(min_length=1, max_length=100, examples=["Microsoft Teams"])
    query: str | None = Field(default=None, max_length=200)
    max_videos: int = Field(default=5, ge=1, le=50)
    max_comments_per_video: int = Field(default=200, ge=1, le=1000)
    include_replies: bool = False


class IngestResult(BaseModel):
    product: str
    query: str
    videos_found: int
    videos_processed: int
    comments_indexed: int
    videos_skipped: list[dict[str, str]]

