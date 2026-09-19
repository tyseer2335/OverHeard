"""Inspect a collected JSONL corpus from the terminal.

    python -m product_voice.inspect_cli data/notion.jsonl
    python -m product_voice.inspect_cli data/notion.jsonl --source browserbase
    python -m product_voice.inspect_cli data/notion.jsonl --complaints --samples 10
    python -m product_voice.inspect_cli data/notion.jsonl --rejects

Reading raw JSONL to judge collection quality is miserable; this prints the
breakdown that actually matters (who supplied what, how negative it is, what
people complain about) plus readable samples with citations.
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from collections import Counter
from pathlib import Path


def _force_utf8_stdout() -> None:
    """Windows consoles default to cp1252 and die on scraped text.

    Collected comments are full of emoji and smart quotes, so printing them
    raises UnicodeEncodeError on a stock Windows terminal. Replace rather than
    crash — this is an inspection tool, not a data path.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - older/odd streams
        pass


def _load(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"no such file: {path}")
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _bar(count: int, total: int, width: int = 28) -> str:
    filled = round(width * count / total) if total else 0
    return "#" * filled + "." * (width - filled)


def _table(title: str, counter: Counter, total: int, limit: int = 12) -> None:
    if not counter:
        return
    print(f"\n{title}")
    for name, count in counter.most_common(limit):
        pct = 100 * count / total if total else 0
        print(f"  {str(name)[:34]:<34} {count:>5}  {_bar(count, total)} {pct:5.1f}%")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="product-voice-inspect",
        description="Summarize and sample a collected JSONL corpus.",
    )
    parser.add_argument("path", type=Path, help="JSONL file from collect_cli")
    parser.add_argument("--source", help="Only show this source")
    parser.add_argument("--samples", type=int, default=5, help="Sample rows to print")
    parser.add_argument("--chars", type=int, default=400, help="Chars per sample")
    parser.add_argument("--complaints", action="store_true", help="Sample negative text only")
    parser.add_argument("--rejects", action="store_true", help="Inspect the .rejects.jsonl instead")
    args = parser.parse_args(argv)
    _force_utf8_stdout()

    path = args.path
    if args.rejects and not path.name.endswith(".rejects.jsonl"):
        path = path.with_name(f"{path.stem}.rejects.jsonl")

    rows = _load(path)
    if not rows:
        print(f"{path} is empty — nothing collected.")
        return 1

    # ---- rejects view -----------------------------------------------------
    if args.rejects:
        print(f"REJECTS  {path}\ntotal: {len(rows)}")
        _table("by reason", Counter(r.get("reason") for r in rows), len(rows))
        _table("by source", Counter(r.get("source") for r in rows), len(rows))
        print("\nsamples:")
        for row in rows[: args.samples]:
            print(f"\n  [{row.get('reason')}] {row.get('source')}  {row.get('id','')}")
            print(textwrap.indent(textwrap.fill(str(row.get("text",""))[:200], 76), "    "))
        return 0

    # ---- corpus view ------------------------------------------------------
    if args.source:
        rows = [r for r in rows if r.get("source") == args.source]
        if not rows:
            print(f"no rows with source={args.source!r}")
            return 1

    total = len(rows)
    print(f"CORPUS   {path}")
    print(f"product  {rows[0].get('product','?')}")
    print(f"total    {total}")

    lengths = [len(r.get("text", "")) for r in rows]
    print(f"text len min/avg/max: {min(lengths)}/{sum(lengths)//total}/{max(lengths)}")
    dated = [r for r in rows if r.get("created_at")]
    if dated:
        stamps = sorted(r["created_at"][:10] for r in dated)
        print(f"dated    {len(dated)}/{total}   {stamps[0]} -> {stamps[-1]}")

    uniq_text = len({" ".join(r.get("text", "").split()).casefold() for r in rows})
    if uniq_text != total:
        print(f"WARNING  {total - uniq_text} duplicate texts survived dedupe")

    _table("by source", Counter(r.get("source") for r in rows), total)
    # container_id is a channel ID for YouTube (UCxxxx), which is unreadable;
    # prefer the human-facing title when the source provides one.
    _table(
        "by source location",
        Counter(r.get("container_title") or r.get("container_id") for r in rows),
        total,
    )
    platforms = Counter(
        r.get("extra", {}).get("platform") for r in rows if r.get("extra", {}).get("platform")
    )
    _table("by platform (browserbase)", platforms, sum(platforms.values()))

    # ---- samples ----------------------------------------------------------
    sample_rows = rows
    if args.complaints:
        negative = ("crash", "bug", "broken", "slow", "hate", "terrible", "awful",
                    "problem", "issue", "expensive", "disappoint", "worst", "annoying")
        sample_rows = [
            r for r in rows if any(w in r.get("text", "").casefold() for w in negative)
        ]
        print(f"\ncomplaint-ish rows: {len(sample_rows)}/{total}")

    print(f"\n{'-' * 78}\nSAMPLES\n{'-' * 78}")
    # Spread samples across the corpus instead of taking the first N, which
    # would all come from whichever source ran first.
    step = max(1, len(sample_rows) // max(1, args.samples))
    for row in sample_rows[::step][: args.samples]:
        head = f"[{row.get('source')}] {row.get('author','?')}"
        meta = f"score={row.get('score',0)}  {str(row.get('created_at') or '')[:10]}"
        print(f"\n{head}   {meta}")
        if row.get("thread_title"):
            print(f"  ~ {str(row['thread_title'])[:70]}")
        print(textwrap.indent(textwrap.fill(row.get("text", "")[: args.chars], 74), "  "))
        print(f"  cite: {row.get('url','')[:100]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
