# CODEX_LOG.md

Concrete record of where an OpenAI coding agent (Codex) materially helped build
**Voxmarket**. Used for the OpenAI prize narrative. Each entry: what was hard,
what the agent contributed, and the outcome.

> Format: `## <area> — <date>` then What / Contribution / Outcome.

---

## Architecture — 2026-09-19
**What:** Greenfield repo, 36h budget, five sponsor integrations to balance.
**Contribution:** Produced the vertical-slice build order (infra → ES evidence
layer → ingestion+extraction → job worker → ElevenLabs → frontend → verify) and
the "runs offline with fixtures, lights up with keys" strategy so the demo can't
hard-fail on a missing credential.
**Outcome:** Every layer has a graceful-degrade path; the pipeline runs with zero
external keys against local Docker Elasticsearch.

## Elasticsearch hybrid retrieval — 2026-09-19
**What:** Combining BM25 + semantic results reliably across ES versions.
**Contribution:** Chose application-side Reciprocal Rank Fusion (run lexical and
semantic searches separately, fuse by `1/(k+rank)`) instead of depending on a
specific `retriever`/`rrf` server version, plus a `semantic_text` vs
`dense_vector` capability switch.
**Outcome:** Hybrid search works on any ES 8.x, cloud or local. See
`backend/app/es/queries.py`.

## Bug: empty themes / silent field drop — 2026-09-19
**What:** After the first end-to-end run, `themes` came back empty and the whole
challenge/headline flow degraded (aspect resolved to None, "praise pricing most").
**Contribution:** Traced it from the symptom (empty aggregation) back through the
pipeline: `aspect_keys` was populated but `aspect_sentiments` raised KeyError on the
dumped doc → the `FeedbackDoc` model was missing the `aspect_sentiments` field, so
Pydantic silently dropped the kwarg in `_build_docs`. Added the field; themes and the
"pricing is concentrated → onboarding" flip immediately worked against real ES.
**Outcome:** Caught a class of bug (silent extra-kwarg drop) that would have derailed
the demo; verified the fix produces the exact intended aggregation numbers.

## OpenAI structured extraction — 2026-09-19
**What:** Extracting relevance, aspect-based sentiment, kind, and verbatim evidence
spans from messy comments, reliably and in batches.
**Contribution:** Designed the `responses.parse` + Pydantic `text_format` batching
(index-aligned, concurrency-limited) with per-batch heuristic fallback, and the rule
that the LLM never computes statistics — only per-comment labels. Aggregates stay in
Elasticsearch/code. See `backend/app/enrich/extract.py`.
**Outcome:** Clean OpenAI footprint that's demonstrable (`EXTRACT_FORCE_LLM=true`) yet
deterministic for the demo via gold-labeled fixtures.

<!-- Append real debugging/integration wins here as they happen during the build. -->
