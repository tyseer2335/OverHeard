"""Collect -> normalize -> enrich -> index into the shared feedback index.

    # collect and index in one pass
    python -m product_voice.index_cli "Notion" --plan --org acme --product notion

    # index a JSONL file collected earlier
    python -m product_voice.index_cli "Notion" --from-jsonl data/notion.jsonl \
        --org acme --product notion

    # inspect what is in the index
    python -m product_voice.index_cli "Notion" --analytics --org acme --product notion

Org/product are free-form ids here so the data layer can be exercised before
Supabase issues real UUIDs; pass the UUIDs once it does.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def _csv(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def _print_analytics(stats: dict) -> None:
    print(f"total            {stats['total']}")
    print(f"complaints       {stats['complaints']}  ({stats['complaint_rate']:.1%})")
    avg = stats["average_sentiment"]
    print(f"avg sentiment    {avg:.3f}" if avg is not None else "avg sentiment    n/a")
    print(f"distinct authors {stats['distinct_authors']}")

    print("\nBY SOURCE (totals above pool these — the mix matters)")
    header = f"  {'source':<14}{'count':>7}{'share':>8}{'complaint%':>12}{'sentiment':>11}{'authors':>9}"
    print(header)
    for row in stats["by_source"]:
        sentiment = row["average_sentiment"]
        sentiment_text = f"{sentiment:>11.3f}" if sentiment is not None else f"{'n/a':>11}"
        print(
            f"  {row['source']:<14}{row['count']:>7}{row['share']:>8.1%}"
            f"{row['complaint_rate']:>12.1%}{sentiment_text}{row['distinct_authors']:>9}"
        )

    if stats["issues"]:
        print("\ntop issues (all sources)")
        for issue in stats["issues"][:8]:
            print(f"  {issue['name']:<20} {issue['count']}")

    if stats["by_language"]:
        print("\nlanguages:", ", ".join(f"{b['name']}={b['count']}" for b in stats["by_language"]))
    if stats["by_content_type"]:
        print("content types:", ", ".join(f"{b['name']}={b['count']}" for b in stats["by_content_type"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="product-voice-index",
        description="Collect, normalize, enrich and index product feedback.",
    )
    parser.add_argument("product", help="Product name")
    parser.add_argument("--org", default="dev-org", help="organization_id")
    parser.add_argument("--product-id", default=None, help="product_id (defaults to slug)")
    parser.add_argument("--plan", action="store_true", help="LLM-planned collection")
    parser.add_argument("--sources", type=_csv, default=None)
    parser.add_argument("--browserbase-targets", type=_csv, default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--max-videos", type=int, default=5)
    parser.add_argument("--from-jsonl", type=Path, default=None, help="Index an existing file")
    parser.add_argument("--analytics", action="store_true", help="Only print analytics")
    parser.add_argument("--duplicates", action="store_true", help="Show duplicate report")
    parser.add_argument("--delete", action="store_true", help="Delete this product's rows")
    parser.add_argument("--index", default=None, help="Override index name")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except index")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)
    except ImportError:
        pass

    from .feedback import from_source_documents
    from .feedback_store import DEFAULT_INDEX, FeedbackStore, create_client

    product_id = args.product_id or _slug(args.product)
    index = args.index or os.getenv("FEEDBACK_INDEX") or DEFAULT_INDEX

    api_key = os.getenv("ELASTIC_API_KEY")
    if not api_key:
        print("ELASTIC_API_KEY not set", file=sys.stderr)
        return 2
    store = FeedbackStore(
        create_client(api_key, os.getenv("ELASTIC_CLOUD_ID"), os.getenv("ELASTICSEARCH_URL")),
        index,
    )

    # ---- read-only modes -------------------------------------------------
    if args.analytics:
        _print_analytics(store.analytics(args.org, product_id))
        return 0

    if args.duplicates:
        rows = store.duplicate_report(args.org, product_id)
        if not rows:
            print("no duplicate texts found")
            return 0
        print(f"{len(rows)} duplicated texts:")
        for row in rows:
            sources = ", ".join(f"{s['name']}x{s['count']}" for s in row["sources"])
            print(f"\n  x{row['count']}  [{sources}]")
            print(f"    {row['text']}")
        return 0

    if args.delete:
        deleted = store.delete_product(args.org, product_id)
        print(f"deleted {deleted} documents for {args.org}/{product_id}")
        return 0

    # ---- collect ---------------------------------------------------------
    if args.from_jsonl:
        from .sources.base import SourceDocument

        docs = [
            SourceDocument.model_validate_json(line)
            for line in args.from_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(f"loaded {len(docs)} documents from {args.from_jsonl}")
    else:
        from .collect import collect, collect_plan
        from .sources import DEFAULT_SOURCES, build_sources

        if args.plan:
            from .planner import plan_collection

            plan = plan_collection(args.product)
            print(plan.summary())
            print()
            result = collect_plan(
                plan,
                limit_per_query=args.limit,
                browserbase_targets=args.browserbase_targets,
                max_videos=args.max_videos,
            )
        else:
            result = collect(
                build_sources(
                    args.sources or DEFAULT_SOURCES,
                    browserbase_targets=args.browserbase_targets,
                    max_videos=args.max_videos,
                ),
                args.product,
                limit_per_source=args.limit,
            )
        print(result.summary())
        print()
        docs = result.documents

    if not docs:
        print("nothing collected — not indexing")
        return 1

    # ---- normalize + enrich ---------------------------------------------
    records = from_source_documents(docs, args.org, product_id)

    from .enrich import enrich_records

    records = enrich_records(records, args.product)

    relevant = sum(1 for r in records if r.relevant)
    print(f"normalized {len(records)} records "
          f"({relevant} relevant, {len(records) - relevant} off-topic)")

    if args.dry_run:
        print("\n--dry-run: sample record")
        print(json.dumps(records[0].model_dump(mode="json"), indent=2)[:900])
        return 0

    # ---- index -----------------------------------------------------------
    created = store.ensure_index()
    print(f"index {index} ({'created' if created else 'exists'})")
    stats = store.index_records(records)
    print(f"indexed {stats['indexed']}  failed {stats['failed']}")

    print()
    _print_analytics(store.analytics(args.org, product_id))
    return 0


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in value.casefold()).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
