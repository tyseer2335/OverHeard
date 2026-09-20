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

## Multi-source collection

Collection is source-agnostic and runs **without Elasticsearch or Supabase**, so
the data layer can be developed and demoed before storage exists.

```bash
pip install -e ".[dev,browserbase]"

# all available sources -> JSONL + a rejects log
python -m product_voice.collect_cli "Sony WH-1000XM5"

# pick sources explicitly
python -m product_voice.collect_cli "Notion" --sources hackernews,browserbase \
    --browserbase-targets reddit,reviews --limit 40 --out data/notion.jsonl
```

Sources missing credentials are **skipped and reported**, never fatal:

```
per source:
  [+] hackernews   ok       collected=40 kept=40
  [-] youtube      skipped   (YOUTUBE_API_KEY not set)
  [+] browserbase  ok       collected=40 kept=40
```

### Sources

| Source | Needs | Notes |
|---|---|---|
| `hackernews` | nothing | Algolia API, free, most reliable |
| `youtube` | `YOUTUBE_API_KEY` | wraps the existing `YouTubeClient` |
| `browserbase` | `BROWSERBASE_API_KEY` + `stagehand` | Browserbase Search + Fetch |

Every adapter returns a `SourceDocument`, so nothing downstream cares where a
row came from. `bridge.to_enriched_comments()` converts a run into the
`EnrichedComment` rows the Elastic store and API already use.

### What Browserbase can and cannot reach

Measured 2026-09-19, not assumed:

- **Reddit direct — blocked.** `fetch` returns HTTP 403 without proxies. *With*
  `proxies=True` it returns HTTP 200, but the body is Reddit's "Prove your
  humanity" CAPTCHA. Proxies beat the IP block, then lose to the bot challenge.
- **X / Instagram / TikTok — blocked.** Login walls. No proxy fixes a login
  wall; only a logged-in session would, which is a ToS violation.
- **What works:** Browserbase `search()` surfaces Reddit mirrors, aggregators
  (`whatredditthinks.com`) and review roundups that quote those threads, and
  `fetch()` renders them to markdown. Reddit *opinion* reaches the corpus even
  though reddit.com does not. Walled domains are skipped up front to save quota.

Note `proxies=True` costs quota and requires a paid Developer plan for general
use; it is off by default (`--use-proxies` to enable).

### Ambiguous product names

Product names that are common English words pull in false positives — "Notion"
matches "the notion that...". Measured on 20 Hacker News hits:

| `--query` | ambiguous hits |
|---|---|
| `Notion` | 18 / 20 |
| `Notion.so` | 6 / 20 |
| `Notion app workspace` | 3 / 20 |

Pass a more specific `--query` for names like this.

### Inspecting what you collected

```bash
python -m product_voice.inspect_cli data/notion.jsonl
python -m product_voice.inspect_cli data/notion.jsonl --complaints --samples 10
python -m product_voice.inspect_cli data/notion.jsonl --source browserbase
python -m product_voice.inspect_cli data/notion.jsonl --rejects
```

Prints source/domain breakdowns, date coverage, a duplicate-survivor warning,
and readable samples with citation URLs. Samples are spread across the corpus
rather than taken from the top, so one source can't fill the output.

## Agent-planned collection (high volume)

`--plan` asks the LLM which sources fit the product and to write several
queries per source, then runs every (source, query) pair through one shared
dedupe pass.

```bash
python -m product_voice.collect_cli "Notion" --plan --limit 500
python -m product_voice.collect_cli "Cyberpunk 2077" --plan --limit 500
```

Measured on "Notion": **83 docs → 2,146 docs**. Without an `OPENAI_API_KEY` it
falls back to a rule-based plan, so collection never depends on the LLM.

The planner picks sources by product type — Steam for a game, not for
headphones — and disambiguates names that are common English words, which cut
"notion"-the-word false positives from ~90% to ~7%.

### Query length is per-source, and it matters

Hacker News, Lemmy and Steam use keyword AND-matching, so every extra word
shrinks the result set hard:

| query | HN matches |
|---|---|
| `Notion` | 345,412 |
| `Notion app` | 33,507 |
| `Notion productivity tool opinions` | **7** |

The planner is instructed to keep queries to 1-3 words for those sources and
use natural language only for YouTube and Browserbase. Fixing this alone took
Hacker News from 79 to 1,393 documents on one run.

## Source reference

| Source | Needs | Volume | Notes |
|---|---|---|---|
| `hackernews` | nothing | ~1000/query | 10 pages x 100, free |
| `youtube` | `YOUTUBE_API_KEY` | high | videos x comments |
| `browserbase` | `BROWSERBASE_API_KEY` | moderate | review sites, Reddit aggregators |
| `steam` | nothing | **enormous** | games only; 1.5M reviews on a big title |
| `lemmy` | nothing | low | federated Reddit-alike, real user voice |

Steam also carries **ground truth** — `voted_up` is the reviewer's own verdict
and `playtime_hours` is real usage, so it can score whether the analysis
layer's inferred sentiment is actually right.

### Platforms that cannot be collected

Re-verified 2026-09-19, including through Browserbase residential proxies:

| Platform | Result |
|---|---|
| Reddit direct | 403; with proxies HTTP 200 but a "Prove your humanity" CAPTCHA |
| X / Twitter | syndication endpoint 429 **even through proxies**; oembed 404 |
| Instagram | embed returns HTTP 200 but contains no caption text |
| Bluesky | public search now 403 |

These are login/bot walls, not IP blocks, so proxies do not help. Reddit
opinion still reaches the corpus indirectly through aggregators that quote it.

## Normalized feedback + Elasticsearch

Every connector normalizes into one `FeedbackRecord` shape, indexed into a
single **tenant-aware** index (`product-feedback`) filtered on
`organization_id` / `product_id` / `source` — never one index per product.

```
organization_id  product_id  source     external_id  content   content_type
published_at     author_hash engagement language     url       source_metadata
ingested_at
```

Plus enrichment filled before indexing: `sentiment`, `sentiment_score`,
`is_complaint`, `issue_categories`, `relevant`.

```bash
# collect -> normalize -> enrich -> index
python -m product_voice.index_cli "Notion" --plan --org acme --product-id notion

# index a corpus collected earlier
python -m product_voice.index_cli "Notion" --from-jsonl data/notion.jsonl \
    --org acme --product-id notion

python -m product_voice.index_cli "Notion" --analytics   --org acme --product-id notion
python -m product_voice.index_cli "Notion" --duplicates  --org acme --product-id notion
python -m product_voice.index_cli "Notion" --delete      --org acme --product-id notion
```

### Design decisions

**Duplicate prevention is structural.** `_id` is a deterministic hash of
(org, product, source, external_id), so re-ingesting overwrites instead of
duplicating and a connector can replay a checkpoint safely. Verified: indexing
the same 2,146 documents twice leaves 2,146 documents.

**Tenancy is enforced by the id too**, so two organizations watching the same
public comment each keep their own row. Verified: the same corpus under two
orgs yields 2,146 each, 4,292 total.

**`author_hash` is salted and source-scoped.** Enough to count distinct voices
and spot one person posting fifty times; the username is never stored. The
same handle on two platforms does not collapse into one identity.

**Analytics never pool sources blindly.** Every aggregate returns `by_source`
beside the total, because sources are not comparable:

```
BY SOURCE (totals above pool these — the mix matters)
  source          count   share  complaint%  sentiment  authors
  hackernews       1393   64.9%       45.2%      0.390     1181
  youtube           623   29.0%        8.5%      0.497      616
  browserbase       130    6.1%       24.6%      0.339        25
```

A 45% complaint rate on Hacker News against 8.5% on YouTube is audience bias,
not a change in the product. The pooled 33.3% describes the source mix as much
as the product, which is why the breakdown always ships with it.

### Sentiment is measurably weak on negatives

Steam carries ground truth (`voted_up` is the reviewer's own verdict), so the
analysis layer can be scored rather than trusted:

| reviewer said | n | inferred positive | inferred negative |
|---|---|---|---|
| thumbs up | 278 | 82% | 8% |
| **thumbs down** | 22 | **55%** | 32% |

78.3% agreement overall, but VADER calls the majority of genuinely negative
reviews positive — sarcasm ("10/10 would crash again") defeats it. Replacing
VADER with an LLM classifier on the complaint path is the highest-value
analytics fix, and Steam is how you prove it worked.


## Analysis: LLM, not lexicon

Sentiment, relevance, intent and issue categories all come from a single model
(`gpt-5.6-sol`) reading each comment, batched 25 at a time. VADER remains only
as a degraded fallback for when the model is unreachable.

### Why VADER was replaced

VADER is a 7,506-word dictionary plus five rules — it never reads a sentence,
it adds up word scores. Measured against Steam's `voted_up` ground truth it
agreed 78% overall but called **55% of genuinely negative reviews positive**,
because sarcasm inverts meaning without changing vocabulary:

| text | VADER | LLM |
|---|---|---|
| "I love how it deletes my data" | positive | **negative** |
| "Great, another update that broke everything" | positive | **negative** |
| "this thing is sick, best purchase all year" | negative | **positive** |
| "great video man keep it up" | positive | **irrelevant** |

That last row is the important one. VADER could not judge *relevance* at all,
and neither could keyword rules — they cannot tell "the notion that..." from
"Notion is slow", or a comment about the video from a comment about the
product. That was most of the noise in the dashboard.

### What it caught that nothing else could

Collecting "Notion" from YouTube returns comments about a **song** called
Notion by The Rare Occasions. The analyzer marked all 113 irrelevant —
correctly. Re-running with "Notion app" produced 24 relevant rows with
summaries like *"Creating task pages feels harder than completing the tasks"*.

### Cost and failure behaviour

One call per batch of 25, not per comment — roughly 5 comments/second. Every
failure path degrades instead of blocking: an unreachable model, unparseable
JSON, or a dropped row falls back to lexicon scoring with `relevant = null`,
which stays visible downstream. Losing a real complaint is worse than showing a
questionable row.

Note `gpt-5.x` rejects any `temperature` but the default; passing one fails the
call with a 400.
