from datetime import UTC, datetime
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Source adapters read credentials from the process environment (they must
# work without Settings, which hard-requires Elastic and Supabase). pydantic
# -settings reads .env for its own fields but never exports it, so load it
# here or every keyed connector silently reports itself unavailable.
from dotenv import load_dotenv

load_dotenv()

from .config import get_settings
from .dependencies import (
    get_collection_service,
    get_feedback_store,
    get_auth_context,
    get_ingestion_service,
    get_store,
    get_supabase,
)
from .collect_service import FeedbackCollectionService
from .elastic import CommentStore
from .feedback_store import FeedbackStore
from .models import (
    SourceOutcomeModel,
    CollectionResultModel,
    AuthContext,
    IngestionJob,
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
from .voice import router as voice_router


log = logging.getLogger("product_voice.api")

app = FastAPI(title="Product Voice API", version="0.2.0")
app.include_router(voice_router)

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
            # Column is still named youtube_query, but it is the generic search
            # query for every source now. Default to the bare product name:
            # keyword sources (Hacker News, Lemmy, Steam) AND-match every term,
            # so a longer default would shrink their results dramatically.
            "youtube_query": request.youtube_query or request.name,
        },
    )
    return Product.model_validate(row)


@app.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    store: Annotated[FeedbackStore, Depends(get_feedback_store)],
) -> Response:
    """Delete a product and every piece of feedback collected for it.

    Feedback goes first: if the Supabase row were removed first and the
    Elasticsearch delete then failed, the documents would be orphaned with no
    product left to identify them by.
    """
    product = _get_product(product_id, auth, supabase)
    deleted = store.delete_product(str(product.organization_id), str(product.id))
    log.info("deleted %d feedback documents for product %s", deleted, product.id)
    supabase.delete("products", auth.access_token, str(product.id))
    return Response(status_code=204)


@app.post("/products/{product_id}/ingestions", response_model=CollectionResultModel)
def collect_feedback(
    product_id: UUID,
    request: ProductIngestRequest,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    service: Annotated[FeedbackCollectionService, Depends(get_collection_service)],
) -> CollectionResultModel:
    """Collect from every available source, enrich, and index.

    One button, no per-source knobs: the caller picks a depth and each
    connector decides what that means for itself.
    """
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
        outcome = service.collect_for_product(
            product_name=product.name,
            organization_id=str(product.organization_id),
            product_id=str(product.id),
            depth=request.depth,
            search_query=product.youtube_query,
        )
        supabase.update(
            "ingestion_jobs",
            auth.access_token,
            job["id"],
            {
                "status": "completed",
                # videos_* are legacy YouTube columns kept for schema
                # compatibility; sources_processed is the meaningful number now.
                "videos_found": len(outcome.sources),
                "videos_processed": sum(1 for s in outcome.sources if s.status == "ok"),
                "comments_indexed": outcome.documents_indexed,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        return CollectionResultModel(
            product=outcome.product,
            depth=outcome.depth,
            documents_collected=outcome.documents_collected,
            documents_indexed=outcome.documents_indexed,
            documents_rejected=outcome.documents_rejected,
            relevant=outcome.relevant,
            sources=[
                SourceOutcomeModel(
                    source=s.source,
                    status=s.status,
                    collected=s.collected,
                    kept=s.kept,
                    detail=s.detail,
                )
                for s in outcome.sources
            ],
            reject_reasons=outcome.reject_reasons,
            plan_reasoning=outcome.plan_reasoning,
            used_llm_planner=outcome.used_llm_planner,
        )
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
    store: Annotated[FeedbackStore, Depends(get_feedback_store)],
    sources: str | None = None,
    language: str | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Analytics over every source, with the per-source breakdown attached."""
    product = _get_product(product_id, auth, supabase)
    return store.analytics(
        organization_id=str(product.organization_id),
        product_id=str(product.id),
        sources=[s.strip() for s in sources.split(",")] if sources else None,
        language=language,
        since=since,
    )


@app.get("/products/{product_id}/comments")
def product_comments(
    product_id: UUID,
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    supabase: Annotated[SupabaseClient, Depends(get_supabase)],
    store: Annotated[FeedbackStore, Depends(get_feedback_store)],
    q: str | None = None,
    complaints_only: bool = False,
    sources: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    product = _get_product(product_id, auth, supabase)
    return store.search(
        organization_id=str(product.organization_id),
        product_id=str(product.id),
        query=q,
        sources=[s.strip() for s in sources.split(",")] if sources else None,
        complaints_only=complaints_only,
        limit=limit,
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
