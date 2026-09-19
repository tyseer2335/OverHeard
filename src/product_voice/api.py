from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .dependencies import get_ingestion_service, get_store
from .elastic import CommentStore
from .models import IngestRequest, IngestResult
from .service import IngestionService
from .youtube import YouTubeAPIError


app = FastAPI(title="Product Voice API", version="0.1.0")

try:
    origins = get_settings().cors_origin_list
except Exception:
    origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingestions", response_model=IngestResult)
def create_ingestion(
    request: IngestRequest,
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> IngestResult:
    try:
        return service.ingest(request)
    except YouTubeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/products/{product}/analytics")
def product_analytics(
    product: str, store: Annotated[CommentStore, Depends(get_store)]
) -> dict[str, Any]:
    return store.analytics(product)


@app.get("/products/{product}/comments")
def product_comments(
    product: str,
    store: Annotated[CommentStore, Depends(get_store)],
    q: str | None = None,
    complaints_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return store.search_comments(product, q, complaints_only, limit)

