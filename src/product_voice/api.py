from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .dependencies import get_auth_context, get_ingestion_service, get_store, get_supabase
from .elastic import CommentStore
from .models import (
    AuthContext,
    IngestionJob,
    IngestRequest,
    IngestResult,
    Organization,
    OrganizationCreate,
    Product,
    ProductCreate,
    ProductIngestRequest,
)
from .service import IngestionService
from .supabase import SupabaseClient, SupabaseError
from .youtube import YouTubeAPIError


app = FastAPI(title="Product Voice API", version="0.2.0")

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


@app.exception_handler(SupabaseError)
async def supabase_error_handler(_request: Any, exc: SupabaseError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config/public")
def public_config() -> dict[str, str]:
    settings = get_settings()
    return {
        "supabase_url": settings.supabase_url,
        "supabase_publishable_key": settings.supabase_publishable_key,
    }


@app.get("/me")
def me(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> dict[str, Any]:
    return auth.user.model_dump(mode="json")


@app.get("/organizations", response_model=list[Organization])
def list_organizations(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> list[Organization]:
    rows = supabase.select("organizations", auth.access_token, order="created_at.asc")
    return [Organization.model_validate(row) for row in rows]


@app.post("/organizations", response_model=Organization, status_code=201)
def create_organization(
    request: OrganizationCreate,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> Organization:
    organization_id = supabase.rpc(
        "create_organization", auth.access_token, {"p_name": request.name}
    )
    rows = supabase.select(
        "organizations", auth.access_token, filters={"id": str(organization_id)}
    )
    if not rows:
        raise HTTPException(status_code=502, detail="Organization creation was not visible")
    return Organization.model_validate(rows[0])


@app.get("/organizations/{organization_id}/products", response_model=list[Product])
def list_products(
    organization_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> list[Product]:
    rows = supabase.select(
        "products",
        auth.access_token,
        filters={"organization_id": str(organization_id)},
        order="created_at.asc",
    )
    return [Product.model_validate(row) for row in rows]


@app.post(
    "/organizations/{organization_id}/products",
    response_model=Product,
    status_code=201,
)
def create_product(
    organization_id: UUID,
    request: ProductCreate,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> Product:
    row = supabase.insert(
        "products",
        auth.access_token,
        {
            "organization_id": str(organization_id),
            "name": request.name,
            "youtube_query": request.youtube_query or f"{request.name} review problems",
        },
    )
    return Product.model_validate(row)


@app.post("/products/{product_id}/ingestions", response_model=IngestResult)
def ingest_product(
    product_id: UUID,
    request: ProductIngestRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    service: Annotated[IngestionService, Depends(get_ingestion_service)],
) -> IngestResult:
    product = _get_product(product_id, auth, supabase)
    job = supabase.insert(
        "ingestion_jobs",
        auth.access_token,
        {
            "organization_id": str(product.organization_id),
            "product_id": str(product.id),
            "requested_by": str(auth.user.id),
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    try:
        result = service.ingest(
            IngestRequest(
                organization_id=product.organization_id,
                product_id=product.id,
                product=product.name,
                query=product.youtube_query,
                max_videos=request.max_videos,
                max_comments_per_video=request.max_comments_per_video,
                include_replies=request.include_replies,
            )
        )
        supabase.update(
            "ingestion_jobs",
            auth.access_token,
            job["id"],
            {
                "status": "completed",
                "videos_found": result.videos_found,
                "videos_processed": result.videos_processed,
                "comments_indexed": result.comments_indexed,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        return result
    except YouTubeAPIError as exc:
        _fail_job(supabase, auth.access_token, job["id"], str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        _fail_job(supabase, auth.access_token, job["id"], str(exc))
        raise


@app.get("/products/{product_id}/ingestions", response_model=list[IngestionJob])
def list_ingestions(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
) -> list[IngestionJob]:
    _get_product(product_id, auth, supabase)
    rows = supabase.select(
        "ingestion_jobs",
        auth.access_token,
        filters={"product_id": str(product_id)},
        order="created_at.desc",
    )
    return [IngestionJob.model_validate(row) for row in rows]


@app.get("/products/{product_id}/analytics")
def product_analytics(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    store: Annotated[CommentStore, Depends(get_store)],
) -> dict[str, Any]:
    product = _get_product(product_id, auth, supabase)
    return store.analytics(product.name, str(product.organization_id), str(product.id))


@app.get("/products/{product_id}/comments")
def product_comments(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    store: Annotated[CommentStore, Depends(get_store)],
    q: str | None = None,
    complaints_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    product = _get_product(product_id, auth, supabase)
    return store.search_comments(
        product.name,
        q,
        complaints_only,
        limit,
        str(product.organization_id),
        str(product.id),
    )


def _get_product(
    product_id: UUID, auth: AuthContext, supabase: SupabaseClient
) -> Product:
    rows = supabase.select(
        "products", auth.access_token, filters={"id": str(product_id)}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Product not found")
    return Product.model_validate(rows[0])


def _fail_job(supabase: SupabaseClient, token: str, job_id: str, error: str) -> None:
    supabase.update(
        "ingestion_jobs",
        token,
        job_id,
        {
            "status": "failed",
            "error": error[:2000],
            "completed_at": datetime.now(UTC).isoformat(),
        },
    )
