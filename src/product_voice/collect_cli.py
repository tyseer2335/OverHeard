"""CLI for multi-source collection — writes JSONL, needs no Elastic/Supabase.

    python -m product_voice.collect_cli "Sony WH-1000XM5"
    python -m product_voice.collect_cli "Notion" --sources hackernews
    python -m product_voice.collect_cli "Notion" --sources browserbase \
        --browserbase-targets reddit,x --out data/notion.jsonl

Sources that lack credentials are skipped and reported, never fatal, so this
always produces something to look at.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .collect import collect, collect_plan
from .sources import DEFAULT_SOURCES, build_sources


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="product-voice-collect",
        description="Collect product opinions from multiple sources into JSONL.",
    )
    parser.add_argument("product", help="Product name, e.g. 'Sony WH-1000XM5'")
    parser.add_argument("--query", default="", help="Search query (defaults to product)")
    parser.add_argument(
        "--sources",
        type=_csv,
        default=DEFAULT_SOURCES,
        help=f"Comma-separated. Default: {','.join(DEFAULT_SOURCES)}",
    )
    parser.add_argument(
        "--browserbase-targets",
        type=_csv,
        default=None,
        help="Platforms to mine via Google: reddit,x,instagram,tiktok,web",
    )
    parser.add_argument("--limit", type=int, default=100, help="Max items per source")
    parser.add_argument("--max-videos", type=int, default=5, help="YouTube videos to scan")
    parser.add_argument(
        "--use-proxies",
        action="store_true",
        help="Browserbase residential proxies (requires a paid Developer plan)",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSONL output path")
    parser.add_argument("--rejects-out", type=Path, default=None, help="Rejects JSONL path")
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Let the LLM choose sources and write several queries per source "
             "(much higher volume). Falls back to rules without OPENAI_API_KEY.",
    )
    parser.add_argument("--model", default=None, help="Planner model override")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Load .env if python-dotenv is around; keys are optional, not required.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if args.plan:
        from .planner import plan_collection

        plan = plan_collection(args.product, **({'model': args.model} if args.model else {}))
        print(plan.summary())
        print()
        result = collect_plan(
            plan,
            limit_per_query=args.limit,
            browserbase_targets=args.browserbase_targets,
            max_videos=args.max_videos,
            use_proxies=args.use_proxies,
        )
    else:
        sources = build_sources(
            args.sources,
            browserbase_targets=args.browserbase_targets,
            max_videos=args.max_videos,
            use_proxies=args.use_proxies,
        )
        if not sources:
            print("No valid sources requested.", file=sys.stderr)
            return 2

        result = collect(
            sources, args.product, query=args.query, limit_per_source=args.limit
        )

    out = args.out or Path(f"{_slug(args.product)}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for doc in result.documents:
            handle.write(doc.model_dump_json() + "\n")

    rejects_out = args.rejects_out or out.with_name(f"{out.stem}.rejects.jsonl")
    with rejects_out.open("w", encoding="utf-8") as handle:
        for rejection in result.rejects:
            handle.write(
                json.dumps(
                    {
                        "reason": rejection.reason,
                        "source": rejection.source,
                        "id": rejection.id,
                        "text": rejection.text,
                    }
                )
                + "\n"
            )

    print(result.summary())
    print()
    print(f"wrote {len(result.documents)} docs    -> {out}")
    print(f"wrote {len(result.rejects)} rejects -> {rejects_out}")

    # Non-zero only if literally nothing was collected, so CI can catch a
    # total outage while tolerating individual sources being unavailable.
    return 0 if result.documents else 1


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in value.casefold()).strip("-")


if __name__ == "__main__":
    raise SystemExit(main())
