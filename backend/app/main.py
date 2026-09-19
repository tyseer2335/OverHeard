"""FastAPI application assembly."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import actions, elevenlabs, research
from app.store import get_store, init_store


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _maybe_sentry() -> None:
    if not settings.sentry_enabled:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=1.0,
                        environment=settings.app_env)
        logging.getLogger("voxmarket").info("Sentry initialized")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("voxmarket").warning("Sentry init skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    _maybe_sentry()
    store = await init_store()
    logging.getLogger("voxmarket").info("Evidence store: %s", store.kind)
    yield
    try:
        from app.es.client import close_es

        await close_es()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="Voxmarket API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)
app.include_router(actions.router)
app.include_router(elevenlabs.router)


@app.get("/health")
async def health() -> dict:
    store = get_store()
    return {
        "ok": True,
        "store": store.kind,
        "store_ready": await store.ready(),
        "integrations": {
            "elasticsearch": settings.es_enabled,
            "openai": settings.openai_enabled,
            "elevenlabs": settings.elevenlabs_enabled,
            "browserbase": settings.browserbase_enabled,
            "sentry": settings.sentry_enabled,
            "semantic_text": settings.es_use_semantic_text,
        },
    }


@app.get("/")
async def root() -> dict:
    return {"service": "voxmarket", "docs": "/docs", "health": "/health"}
