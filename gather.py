"""Cast the wide net.

Pulls raw data from all sources for a product, dumps it to raw_data.jsonl.
NO cleaning, NO Elastic, NO agent yet -- just gathering. That comes next.

Fast sources (Reddit, HN, reviews) run by default.
Slow browser sources (X, Instagram via Browserbase) only run with --browser,
and they fail gracefully (return nothing) if they hit a login wall.

Usage:
    python gather.py "ProductX" --queries "ProductX battery" "ProductX review"
    python gather.py "ProductX" --browser            # also try X + Instagram
    python gather.py "ProductX" --browser --ig-urls https://instagram.com/p/XXXX
"""

import argparse
import json

from dotenv import load_dotenv
load_dotenv()  # so REDDIT_USER_AGENT / BROWSERBASE_* / keys are available

from sources.reddit_source import search_reddit
from sources.hn_source import search_hn
from sources.reviews_source import search_reviews


def gather(product, queries, subreddits=None, use_browser=False, ig_urls=None):
    """Run every enabled source for every query. Returns a flat list[Item]."""
    all_items = []
    subreddits = subreddits or [None]  # None = search all of Reddit

    for q in queries:
        # Reddit -- once per subreddit (or once against r/all if none given)
        for sub in subreddits:
            try:
                got = search_reddit(q, product=product, subreddit=sub)
                print(f"[reddit] '{q}' sub={sub or 'all'} -> {len(got)} items")
                all_items.extend(got)
            except Exception as e:
                print(f"[reddit] FAILED '{q}' sub={sub}: {e}")

        # HN
        try:
            got = search_hn(q, product=product)
            print(f"[hn] '{q}' -> {len(got)} items")
            all_items.extend(got)
        except Exception as e:
            print(f"[hn] FAILED '{q}': {e}")

        # Reviews (stub for now)
        try:
            got = search_reviews(q, product=product)
            print(f"[reviews] '{q}' -> {len(got)} items")
            all_items.extend(got)
        except Exception as e:
            print(f"[reviews] FAILED '{q}': {e}")

    # Slow browser sources -- opt-in, and they self-skip on any wall/error.
    if use_browser:
        # import lazily so the fast path doesn't need stagehand/browserbase installed
        from sources.browser_source import search_x, search_instagram
        for q in queries:
            all_items.extend(search_x(q, product=product))
        # Instagram works best against specific post/profile URLs
        for target in (ig_urls or queries):
            all_items.extend(search_instagram(target, product=product))

    return all_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("product", help="product name, e.g. 'ProductX'")
    ap.add_argument("--queries", nargs="*", default=None,
                    help="search queries; defaults to just the product name")
    ap.add_argument("--subreddits", nargs="*", default=None,
                    help="subreddits to restrict Reddit search to; default = all")
    ap.add_argument("--browser", action="store_true",
                    help="also try X + Instagram via Browserbase (slow, may wall)")
    ap.add_argument("--ig-urls", nargs="*", default=None,
                    help="specific Instagram post/profile URLs to scrape comments from")
    ap.add_argument("--out", default="raw_data.jsonl")
    args = ap.parse_args()

    queries = args.queries or [args.product]

    items = gather(args.product, queries, args.subreddits,
                   use_browser=args.browser, ig_urls=args.ig_urls)

    # write raw, one JSON object per line (easy to append / stream later)
    with open(args.out, "w") as f:
        for it in items:
            f.write(json.dumps(it.to_dict()) + "\n")

    print(f"\nTOTAL: {len(items)} raw items -> {args.out}")


if __name__ == "__main__":
    main()
