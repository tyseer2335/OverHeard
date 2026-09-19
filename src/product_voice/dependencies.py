from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .analysis import CommentAnalyzer
from .config import get_settings
from .collect_service import FeedbackCollectionService
from .elastic import CommentStore, create_elastic_client
from .feedback_store import DEFAULT_INDEX, FeedbackStore
from .service import IngestionService
from .models import AuthContext
from .supabase import SupabaseClient, SupabaseError
from .youtube import YouTubeClient


@lru_cache
def get_store() -> CommentStore:
    settings = get_settings()
    client = create_elastic_client(
        settings.elastic_api_key, settings.elastic_cloud_id, settings.elasticsearch_url
    )
    return CommentStore(client, settings.elastic_index)


@lru_cache
def get_ingestion_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        YouTubeClient(settings.youtube_api_key), get_store(), CommentAnalyzer()
    )


@lru_cache
def get_supabase() -> SupabaseClient:
    settings = get_settings()
    return SupabaseClient(
        settings.supabase_url,
        settings.supabase_publishable_key,
        settings.supabase_secret_key,
    )


bearer = HTTPBearer(auto_error=False)


def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> AuthContext:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required")
    try:
        user = supabase.get_user(credentials.credentials)
    except SupabaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AuthContext(user=user, access_token=credentials.credentials)


@lru_cache
def get_feedback_store() -> FeedbackStore:
    """The shared, tenant-aware multi-source index."""
    settings = get_settings()
    client = create_elastic_client(
        settings.elastic_api_key, settings.elastic_cloud_id, settings.elasticsearch_url
    )
    return FeedbackStore(client, settings.feedback_index or DEFAULT_INDEX)


@lru_cache
def get_collection_service() -> FeedbackCollectionService:
    return FeedbackCollectionService(get_feedback_store(), CommentAnalyzer())
