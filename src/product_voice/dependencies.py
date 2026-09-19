from functools import lru_cache

from .analysis import CommentAnalyzer
from .config import get_settings
from .elastic import CommentStore, create_elastic_client
from .service import IngestionService
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

