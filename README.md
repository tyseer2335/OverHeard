# Product Voice

An MVP pipeline that finds YouTube product-review videos, collects their comments,
enriches them with lightweight sentiment and issue categories, and stores them in
Elasticsearch for search and analytics.

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

Edit `.env`: set `YOUTUBE_API_KEY` and `ELASTIC_API_KEY`. For Elastic Cloud,
set `ELASTIC_CLOUD_ID`; for another deployment, set `ELASTICSEARCH_URL`.
Never commit `.env`; Git ignores it.

## Run it

CLI:

```powershell
product-voice "Microsoft Teams" --max-videos 5 --max-comments 200
```

API:

```powershell
uvicorn product_voice.api:app --reload
```

Open `http://127.0.0.1:8000/docs`, or call:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ingestions `
  -ContentType application/json `
  -Body '{"product":"Microsoft Teams","max_videos":5,"max_comments_per_video":200}'

Invoke-RestMethod -Uri "http://127.0.0.1:8000/products/Microsoft%20Teams/analytics"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/products/Microsoft%20Teams/comments?complaints_only=true&limit=20"
```

## Endpoints

- `POST /ingestions` — search videos, ingest comments, and return counts.
- `GET /products/{product}/analytics` — sentiment, complaint rate, issue counts,
  monthly volume, and video breakdown.
- `GET /products/{product}/comments` — search and filter stored comments.
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
