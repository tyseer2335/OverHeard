"""Lazy singleton for the async OpenAI client (None when no key configured)."""
from __future__ import annotations

from app.config import settings

_client = None


def get_openai():
    global _client
    if not settings.openai_enabled:
        return None
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client
