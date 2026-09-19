# Product Voice

A multi-tenant product-feedback service that finds YouTube product-review videos,
collects their comments, enriches them with lightweight sentiment and issue
categories, and stores them in Elasticsearch for search and analytics. Supabase
provides user authentication, organizations, products, RLS, and ingestion history.

## What it does

1. Searches YouTube for a product query (default: `<product> review problems`).
2. Fetches top-level comments, optionally including replies.
3. Adds sentiment, a complaint flag, and issue categories.
4. Bulk-indexes documents using a product/comment composite ID, so reruns are
   idempotent without losing a comment found for more than one product.
5. Exposes product analytics and searchable complaint examples through FastAPI.

The enrichment is a transparent MVP heuristic. Original text is retained so it can
later be reprocessed with Elastic inference, embeddings, or a custom classifier.

## Setup

You need Python 3.11+, a YouTube Data API v3 key, and Elasticsearch.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env`: set the YouTube, Elasticsearch, and Supabase values shown in
`.env.example`. For Elastic Cloud, set `ELASTIC_CLOUD_ID`; for another deployment,
set `ELASTICSEARCH_URL`. Never commit `.env`; Git ignores it.

### Initialize Supabase

Open the Supabase SQL Editor for your project and run the complete contents of:

```text
supabase/migrations/202609190001_initial_tenant_schema.sql
```

The migration creates organizations, memberships, products, ingestion jobs, and
their Row Level Security policies. Create at least one user through Supabase Auth,
then use that user's access token as `Authorization: Bearer <token>` when calling
the API. The Supabase secret key must remain server-side.

## Run it

The CLI remains available for development and non-tenant imports:

```powershell
product-voice "Microsoft Teams" --max-videos 5 --max-comments 200
```

API:

```powershell
uvicorn product_voice.api:app --reload
```

### React dashboard

The React/TypeScript frontend lives in `frontend/` and uses Supabase Auth, Recharts,
and the authenticated FastAPI endpoints. The repository includes a project-local
Node.js toolchain, so no system-wide Node installation is required.

From the repository root:

```powershell
.\scripts\dev.ps1
```

This starts FastAPI on `http://127.0.0.1:8000` and the dashboard on
`http://localhost:3000`. Stop the script with Ctrl+C. For email-confirmation links,
set the Supabase Auth **Site URL** to `http://localhost:3000`.

To validate a production frontend build:

```powershell
$node = Resolve-Path .\.tools\node-v*-win-x64
$env:Path = "$node;$env:Path"
Set-Location frontend
npm run lint
npm run build
```

Open `http://127.0.0.1:8000/docs` for raw API documentation. Except for `/health`
and `/config/public`, API routes require a Supabase user access token through the
Swagger **Authorize** button.

## Endpoints

- `GET /me` — validate the current Supabase user.
- `GET/POST /organizations` — list or create organizations.
- `GET/POST /organizations/{organization_id}/products` — manage tracked products.
- `POST /products/{product_id}/ingestions` — ingest comments for an authorized product.
- `GET /products/{product_id}/ingestions` — ingestion history.
- `GET /products/{product_id}/analytics` — tenant-filtered product analytics.
- `GET /products/{product_id}/comments` — tenant-filtered comment search.
- `GET /health` — service health.

## Important notes

- YouTube `search.list` costs 100 quota units per call; `commentThreads.list` costs
  1 unit. Start with a small video limit.
- Replies are off by default because fetching all replies takes additional calls.
- Videos with disabled comments are reported and skipped.
- Public comments may contain personal data. Define retention and deletion rules
  before production use, and follow the YouTube API Services Terms.

## Test

```powershell
pytest
```
