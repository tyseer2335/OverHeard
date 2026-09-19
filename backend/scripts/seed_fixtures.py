"""Seed the evidence store with the fixture corpus and print an analysis.

Doubles as an end-to-end smoke test of the whole pipeline (collect -> clean ->
enrich -> index -> aggregate -> challenge) with zero external keys.

    uv run python -m scripts.seed_fixtures
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app import runtime
from app.analysis.evidence import build_packet, run_challenge
from app.jobs.worker import run_research
from app.models import ChallengeRequest, ResearchJob, ResearchRequest, ResearchStatus
from app.store import get_store, init_store

SEED_ID = "res_seed_notion"


async def main() -> None:
    store = await init_store()
    print(f"→ store: {store.kind}\n")

    request = ResearchRequest(
        subject="Notion",
        question="What are customers frustrated about?",
        sources=["fixtures"],
        max_threads=30,
    )
    now = datetime.now(timezone.utc)
    job = ResearchJob(
        research_id=SEED_ID,
        status=ResearchStatus.QUEUED,
        subject=request.subject,
        question=request.question,
        sources_requested=request.sources,
        created_at=now,
        updated_at=now,
    )
    await store.save_job(job)
    runtime.set_latest_research(SEED_ID)

    await run_research(job, request)
    job = await store.get_job(SEED_ID)
    assert job is not None

    print(f"status: {job.status.value}  docs: {job.document_count}  threads: {job.thread_count}")
    print(f"headline: {job.headline}\n")

    packet = await build_packet(job)
    print("THEMES (ranked):")
    for t in packet.themes:
        print(
            f"  {t.key:<14} n={t.doc_count:<3} "
            f"neg={t.sentiment.negative} pos={t.sentiment.positive} mix={t.sentiment.mixed}  "
            f"threads={t.thread_count}  top_thread_share={t.top_thread_share}"
        )

    print("\nCHALLENGE: 'pricing is the top complaint'")
    ch = await run_challenge(job, ChallengeRequest(claim="pricing is the top complaint"))
    print(f"  verdict: {ch.concentration.verdict}  "
          f"top_thread_share: {ch.concentration.top_thread_share}")
    print(f"  counterevidence: {len(ch.counterevidence)}  supporting: {len(ch.supporting)}")
    print(f"  assessment: {ch.assessment}")

    print(f"\n✓ seeded as research_id={SEED_ID} (store={store.kind})")
    if store.kind == "memory":
        print("  NOTE: memory store is per-process — start ES (docker compose up -d "
              "elasticsearch) to seed data the running server can read.")


if __name__ == "__main__":
    asyncio.run(main())
