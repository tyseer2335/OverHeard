"""Application configuration.

All external integrations are optional. The corresponding `*_enabled` properties
let the rest of the app degrade gracefully when a credential is missing, which is
what keeps the offline/fixture demo working.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_file resolves relative to the CWD; we run from backend/, so ../.env
    # (repo root) is the primary location, with a local backend/.env override.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: str = "dev"
    port: int = 8000
    cors_origins: str = "http://localhost:3000"
    public_base_url: str = "http://localhost:8000"

    # --- Elasticsearch ---
    elasticsearch_url: str = "http://localhost:9200"
    elastic_cloud_id: str = ""
    elastic_api_key: str = ""
    es_index_prefix: str = "voxmarket"
    es_use_semantic_text: bool = False
    es_inference_id: str = ".elser-2-elasticsearch"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    openai_embed_model: str = "text-embedding-3-small"
    openai_embed_dims: int = 1536
    # When true, run LLM extraction even on fixture items that carry gold labels
    # (useful to *show* OpenAI extraction on the curated corpus during judging).
    extract_force_llm: bool = False

    # --- ElevenLabs ---
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_tool_secret: str = "dev-tool-secret-change-me"
    # Optional: set an ElevenLabs voice_id to change Vox's voice (setup script applies it).
    elevenlabs_voice_id: str = ""

    # --- Browserbase ---
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    # --- Sentry ---
    sentry_dsn: str = ""

    # ------------------------------------------------------------------ helpers
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def es_enabled(self) -> bool:
        return bool(self.elastic_cloud_id or self.elasticsearch_url)

    @property
    def es_cloud(self) -> bool:
        return bool(self.elastic_cloud_id and self.elastic_api_key)

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def elevenlabs_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key and self.elevenlabs_agent_id)

    @property
    def browserbase_enabled(self) -> bool:
        return bool(self.browserbase_api_key and self.browserbase_project_id)

    @property
    def sentry_enabled(self) -> bool:
        return bool(self.sentry_dsn)

    # index names
    @property
    def feedback_index(self) -> str:
        return f"{self.es_index_prefix}-feedback"

    @property
    def jobs_index(self) -> str:
        return f"{self.es_index_prefix}-jobs"

    @property
    def tickets_index(self) -> str:
        return f"{self.es_index_prefix}-tickets"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
