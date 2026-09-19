from datetime import datetime
from typing import Any
from uuid import UUID

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
    organization_id: UUID | None = None
    product_id: UUID | None = None
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
    organization_id: UUID | None = None
    product_id: UUID | None = None
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


class AuthenticatedUser(BaseModel):
    id: UUID
    email: str | None = None


class AuthContext(BaseModel):
    user: AuthenticatedUser
    access_token: str


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Organization(BaseModel):
    id: UUID
    name: str
    created_by: UUID
    created_at: datetime


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    youtube_query: str | None = Field(default=None, max_length=200)


class Product(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    youtube_query: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ProductIngestRequest(BaseModel):
    max_videos: int = Field(default=5, ge=1, le=50)
    max_comments_per_video: int = Field(default=200, ge=1, le=1000)
    include_replies: bool = False


class IngestionJob(BaseModel):
    id: UUID
    organization_id: UUID
    product_id: UUID
    requested_by: UUID
    status: str
    videos_found: int = 0
    videos_processed: int = 0
    comments_indexed: int = 0
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


JsonObject = dict[str, Any]
