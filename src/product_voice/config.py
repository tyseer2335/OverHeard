from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    youtube_api_key: str = Field(min_length=1)
    elastic_api_key: str = Field(min_length=1)
    elastic_cloud_id: str | None = None
    elasticsearch_url: str | None = None
    elastic_index: str = "youtube-product-comments"
    #: Shared multi-source feedback index the dashboard reads from.
    feedback_index: str = "product-feedback"
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_tool_secret: str = ""
    supabase_url: str = Field(min_length=1)
    supabase_publishable_key: str = Field(min_length=1)
    supabase_secret_key: str = Field(min_length=1)
    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def require_elastic_location(self) -> "Settings":
        if not self.elastic_cloud_id and not self.elasticsearch_url:
            raise ValueError("Set ELASTIC_CLOUD_ID or ELASTICSEARCH_URL")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def elevenlabs_enabled(self) -> bool:
        return bool(
            self.elevenlabs_api_key
            and self.elevenlabs_agent_id
            and self.elevenlabs_tool_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
