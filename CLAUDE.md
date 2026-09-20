# CLAUDE.md — HTN 2026 project context

Context handoff from an earlier session. Read this first.

## What we're building

An AI agent that researches what people really think about a product by gathering
messy, real-world opinions from multiple online sources, reconciling contradictions,
and producing a grounded, cited verdict + actionable output. You can talk to it by
voice and push back on its reasoning.

**One line:** point it at a product, it tells you the honest truth about its online
reception, with receipts, and you can argue with it out loud.

## Why this shape — prize strategy (Hack the North 2026)

Targeting four prizes with ONE build. Every design decision serves these:

- **OpenAI API Prize** — the research agent is a real tool-calling loop (the "engine"),
  not a prompt wrapper. Also judged on how Codex helped build it, so keep a concrete
  Codex story (e.g. Codex built the eval/test harness).
- **Rox: Best AI Agent ($10K)** — the core. Agent must handle messy/unstructured/
  conflicting/noisy multi-source data AND take a meaningful ACTION (not just summarize).
  Must visibly do: dedupe, bot/junk filtering, multi-source contradiction resolution,
  recency weighting, decision under uncertainty. Demo money shot = "mess in, signal out."
- **Elastic: Find the Signal** — Elasticsearch as the agent's context layer. Use HYBRID
  search (BM25 + dense vectors + reranking) — say those exact words. Elastic RETRIEVES,
  the LLM REASONS. Don't conflate them.
- **ElevenLabs (MLH)** — voice interface: talk to the verdict, it defends with citations.

Judging is a LIVE DEMO, not slides. Reliability > ambition. Rehearse a bulletproof demo.

## Architecture / pipeline

```
sources (each returns the SAME Item schema)
      ↓
gather / research agent (GPT tool-calling loop decides what to search)
      ↓
clean + validate  (dedupe, filter junk, tag recency/source) ← Rox layer, NOT built yet
      ↓
index into Elasticsearch (embeddings)                        ← Elastic, NOT built yet
      ↓
agent retrieves via hybrid search + reasons + resolves contradictions
      ↓
output: ranked top issues + drafted action (NOT just a summary) ← Rox "action"
      ↓
ElevenLabs voice: speak the verdict, user pushes back         ← NOT built yet
```

Division of labor to keep straight:
- **Sources / API code** = gather raw data
- **Elastic** = stores + searches the corpus (memory/retrieval)
- **LLM (OpenAI)** = decides what to search, reasons, resolves, decides (the brain)

## DATA SOURCES — read before touching source code (hard-won, don't repeat)

Working / usable:
- **Hacker News** — WORKS. Free Algolia API, no auth. ~58 items/product easily. Reliable.
- **YouTube** — official Data API v3. Needs a free `YOUTUBE_API_KEY` (Google Cloud →
  enable "YouTube Data API v3"). Gives real comments, no login wall. This is the best
  volume source. (The `feature/youtube-comment-ingestion` branch has work on this.)
- **Reviews** — pluggable per product type: Steam (games; public appreviews endpoint,
  thumbs up/down = ground truth), app store / Play store (apps), Amazon (physical).
  Currently a stub in `sources/reviews_source.py`.

PROVEN DEAD ENDS — do NOT waste time retrying these, we already did:
- **Reddit** — blocked every free path. Official API is gated (app creation walled behind
  a moderation-use-case ticket). Public `.json` returns 403 even from a residential/home
  IP. Browserbase (datacenter IP) gets Reddit's "blocked by network security — log in or
  use a developer token" page on both `.json` and old.reddit.com. Residential proxies
  MIGHT fix it but they're PAID on Browserbase (free plan → 402). Not worth it. Code for
  Reddit stays in place and fails gracefully; it lights up only with paid proxies or a
  logged-in session.
- **X (Twitter)** — login wall. No public content without login. Dead.
- **TikTok** — login wall. Dead.
- **Instagram** — only leaks post CAPTIONS on tag pages (not comments), behind a login
  wall for more. Low-value. Not worth building on.
- KEY INSIGHT: X/IG/TikTok are LOGIN walls, not IP blocks — no proxy fixes a login wall.
  Only logged-in accounts would work (ToS violation + ban risk + fragile). Don't.

Bottom line: build on **HN + YouTube + reviews**. That's a genuine multi-source dataset
with real cross-platform disagreement (what Rox wants). Reddit/social are not needed.

## Repo layout (main branch as of last session; feature branches may differ)

```
schema.py            common Item shape ALL sources normalize to (the glue)
agent.py             GPT research agent — tool-calling loop, accumulates deduped corpus
main.py              FastAPI backend (POST /gather, GET /jobs/{id}, /jobs/{id}/raw)
gather.py            CLI gatherer (run sources without the agent/backend)
test_social.py       diagnostic that proved X/IG/TikTok are walled
requirements.txt
.env.example         all keys documented here
sources/
  hn_source.py         WORKS (Algolia API)
  youtube_source.py    YouTube Data API v3 (needs key)
  reviews_source.py    STUB — plug in Steam/appstore/Amazon per product type
  reddit_source.py     scrape .json → Browserbase fallback; both blocked (see above)
  browser_source.py    X/IG via Browserbase/Stagehand (walled; Stagehand is async, sync code needs rework if ever used)
```

Common Item schema (every source MUST return this):
`{ id, source, text, author, timestamp, score, url, product }`
- `id` unique across sources (dedupe), `score` for weighting, `url` for citations,
  `timestamp` for recency, `source` for multi-source logic.

## Environment / setup

`.env` in repo root (loaded via python-dotenv). Required to run:
- `OPENAI_API_KEY` — the agent
- `YOUTUBE_API_KEY` — YouTube source (Google Cloud, free)
- HN needs nothing

Optional / present but not essential:
- `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` — only helps Reddit/social with PAID
  proxies; not needed for the core build
- `REDDIT_USER_AGENT` — for the (blocked) Reddit scraper

Run:
```
pip install -r requirements.txt
uvicorn main:app --reload
# then POST /gather {"product": "..."} and poll /jobs/{id}
```
Quick source test without OpenAI cost: `python gather.py "Sony WH-1000XM5" --queries "..."`

## Status (end of last session)

Done: pipeline scaffolding, HN source working, GPT research agent written, FastAPI
backend written, `.env` with OpenAI + Browserbase keys. Team has pushed
`feature/youtube-comment-ingestion` and `feature/eleven-labs-integration` branches.

NOT done yet (the actual winning work): clean/validate layer (Rox), Elastic hybrid
search, analysis→ranked-issues+action output (Rox action), ElevenLabs voice, and a
rehearsed live demo.

## Next steps (priority order)

1. Finish YouTube ingestion (get the API key in `.env`), merge the youtube branch.
2. Run the full agent end-to-end once to confirm the engine works.
3. Build the clean/validate layer — dedupe, junk/bot filter, recency + source tags,
   and keep a REJECTS LOG (that log is the "mess in" side of the demo).
4. Elastic: index the corpus with embeddings, expose hybrid search (BM25 + vectors +
   rerank) as the agent's `search_corpus` tool.
5. Analysis → action: agent reasons over corpus, resolves contradictions, outputs
   ranked top issues (with severity) + a drafted response. NOT just a summary.
6. ElevenLabs: speak the verdict, let the user push back, it defends with citations.
7. Rehearse the demo: raw garbage on one side, clean cited verdict on the other.

## Conventions / gotchas

- Every new source returns the common Item schema — nothing downstream should care where
  data came from.
- Elastic retrieves; the LLM reasons. Keep them separate (also maps cleanly to prizes).
- Don't over-gather. A few thousand genuinely messy items across sources beats a giant
  crawl. Spend effort on the agent + demo, not corpus size.
- On Windows: use Git Bash (MINGW64) for `&&`; PowerShell rejects it. `.env` must be
  named exactly `.env` (Notepad tends to save `.env.txt`).
