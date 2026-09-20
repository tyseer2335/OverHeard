"""Browser-based social adapters (X / Twitter and Instagram) via Browserbase + Stagehand.

These sources have NO clean API and actively fight scraping, so we drive a real
cloud browser and let an AI agent (Stagehand) navigate by intent and extract
comments. The design rule you asked for: ATTEMPT, and if we hit a login wall or
anything blocks us, return [] with a clear log instead of crashing the pipeline.

Setup:
    pip install stagehand browserbase
    Set env vars:
        BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID
        MODEL_API_KEY (OpenAI key Stagehand uses to navigate)

Notes:
    - This is SLOW (seconds per page) compared to Reddit/HN APIs. Run it ahead of
      the demo and cache results into your corpus; don't depend on it live.
    - X and IG hide most content behind auth. Without a logged-in session you'll
      often hit a wall -- that's expected and handled (returns []).
"""

import os
from schema import Item, now_iso

# Pydantic schema Stagehand extracts into. Keeping it flat and simple.
try:
    from pydantic import BaseModel

    class _Comment(BaseModel):
        text: str
        author: str = "unknown"
        url: str = ""

    class _Comments(BaseModel):
        comments: list[_Comment] = []
except Exception:  # pydantic not installed yet
    _Comments = None


def _looks_like_login_wall(page_text: str) -> bool:
    """Cheap heuristic: did we get bounced to a sign-in gate?"""
    if not page_text:
        return True
    t = page_text.lower()
    hits = ("log in", "sign in", "create account", "phone, email, or username",
            "log into instagram", "see photos and videos from")
    # if the page is basically just a login prompt, bail
    return any(h in t for h in hits) and len(t) < 1500


def _scrape(url, product, source_name, extract_instruction, max_items=40):
    """Shared driver: open a Browserbase browser, navigate, let Stagehand extract.

    Returns list[Item]. Any failure -> [] (logged). Never raises.
    """
    if _Comments is None:
        print(f"[{source_name}] pydantic not installed -- skipping")
        return []

    try:
        from stagehand import Stagehand
    except Exception as e:
        print(f"[{source_name}] stagehand not installed ({e}) -- skipping")
        return []

    if not os.environ.get("BROWSERBASE_API_KEY"):
        print(f"[{source_name}] no BROWSERBASE_API_KEY -- skipping")
        return []

    sh = None
    try:
        sh = Stagehand(
            env="BROWSERBASE",
            api_key=os.environ["BROWSERBASE_API_KEY"],
            project_id=os.environ.get("BROWSERBASE_PROJECT_ID"),
            model_name="gpt-4o",
            model_api_key=os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        )
        sh.init()
        page = sh.page

        page.goto(url, wait_until="domcontentloaded")
        sh.page.wait_for_timeout(3000)  # let content settle

        # login-wall check before we waste an LLM extract call
        try:
            body_text = page.evaluate("() => document.body.innerText") or ""
        except Exception:
            body_text = ""
        if _looks_like_login_wall(body_text):
            print(f"[{source_name}] hit a login wall -- skipping gracefully")
            return []

        result = page.extract(extract_instruction, schema=_Comments)

        raw = getattr(result, "comments", None) or []
        items = []
        for i, c in enumerate(raw[:max_items]):
            text = (c.text or "").strip()
            if not text:
                continue
            items.append(Item(
                id=f"{source_name}_{abs(hash(text)) % (10**12)}",
                source=source_name,          # "x" or "instagram"
                text=text,
                author=(c.author or "unknown"),
                timestamp=now_iso(),         # these rarely expose reliable timestamps
                score=0,                      # no reliable score signal here
                url=(c.url or url),
                product=product,
            ))
        print(f"[{source_name}] extracted {len(items)} items from {url}")
        return items

    except Exception as e:
        print(f"[{source_name}] FAILED ({e}) -- skipping gracefully")
        return []
    finally:
        if sh is not None:
            try:
                sh.close()
            except Exception:
                pass


def search_x(query, product, max_items=40):
    """Try to pull replies/comments about `query` from X (Twitter)."""
    url = f"https://x.com/search?q={query.replace(' ', '%20')}&f=live"
    instruction = (
        "Extract the individual tweets and replies visible on this page that mention "
        "the product. For each, capture the tweet text, the author's handle, and the "
        "permalink URL if visible."
    )
    return _scrape(url, product, "x", instruction, max_items)


def search_instagram(query, product, max_items=40):
    """Try to pull comments about `query` from Instagram.

    IG has no real search-by-keyword for comments, so this works best if you pass a
    specific post/profile URL as `query`. If `query` isn't a URL we just attempt a
    tag page and will very likely hit a wall (handled).
    """
    if query.startswith("http"):
        url = query
    else:
        tag = query.replace(" ", "").replace("#", "")
        url = f"https://www.instagram.com/explore/tags/{tag}/"
    instruction = (
        "Extract the visible comments on this page. For each comment capture the "
        "comment text and the commenter's username."
    )
    return _scrape(url, product, "instagram", instruction, max_items)
