"""Hacker News adapter -- uses the Algolia HN Search API.

No auth, no keys, no rate-limit pain. Just HTTP GET.
Docs: https://hn.algolia.com/api

    pip install requests
"""

import requests

from schema import Item, iso

BASE = "https://hn.algolia.com/api/v1/search"


def search_hn(query, product, limit=50):
    """Search HN stories + comments for `query`. Returns list[Item].

    Algolia returns both stories and comments when you don't restrict tags.
    We pull comments (tags=comment) since that's where opinions live, plus
    stories for context.
    """
    items = []

    for tag in ("comment", "story"):
        resp = requests.get(BASE, params={
            "query": query,
            "tags": tag,
            "hitsPerPage": limit,
        }, timeout=15)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])

        for h in hits:
            text = h.get("comment_text") or h.get("story_text") or h.get("title") or ""
            text = text.strip()
            if not text:
                continue
            oid = h.get("objectID")
            items.append(Item(
                id=f"hn_{oid}",
                source="hn",
                text=text,
                author=h.get("author") or "unknown",
                timestamp=iso(h.get("created_at_i", 0)),
                score=int(h.get("points") or 0),
                url=f"https://news.ycombinator.com/item?id={oid}",
                product=product,
            ))

    return items
