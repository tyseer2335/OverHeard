"""Reddit adapter -- scrape via .json, fall back to a REAL browser (Browserbase).

Reddit blocks plain HTTP scraping (403 on .json, even from a home IP) and gates the
official API. So the reliable path is a real Chrome driven by Browserbase, which
loads reddit like any browser does. We parse old.reddit.com's HTML directly, so no
LLM/Stagehand needed for Reddit -- deterministic and cheap.

  1. PRIMARY: Reddit public .json (fast, free). Usually 403s now, but kept as a
     cheap first try in case it works from a given IP.
  2. FALLBACK: Browserbase + Playwright. Loads old.reddit.com search in a real
     browser, pulls post titles, then visits the top posts and scrapes comments.

Setup for the fallback:
    pip install browserbase playwright
    (no `playwright install` needed -- the browser runs remotely on Browserbase)
    Set env: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID

Note: scraping public Reddit is against Reddit's ToS strictly speaking. Fine for a
non-commercial hackathon reading public opinions; don't build a business on it.
"""

import os
import time
import requests

from schema import Item, iso, now_iso

# For SCRAPING .json, a real browser User-Agent does better than a bot UA.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.reddit.com/",
}


# ---------------------------------------------------------------------------
# PRIMARY: public .json
# ---------------------------------------------------------------------------

def _post_to_item(d, product):
    return Item(
        id=f"reddit_{d.get('id')}",
        source="reddit",
        text=((d.get("title") or "") + "\n" + (d.get("selftext") or "")).strip(),
        author=d.get("author") or "unknown",
        timestamp=iso(d.get("created_utc", 0)),
        score=int(d.get("score") or 0),
        url="https://reddit.com" + (d.get("permalink") or ""),
        product=product,
    )


def _comment_to_item(d, product):
    return Item(
        id=f"reddit_{d.get('id')}",
        source="reddit",
        text=(d.get("body") or "").strip(),
        author=d.get("author") or "unknown",
        timestamp=iso(d.get("created_utc", 0)),
        score=int(d.get("score") or 0),
        url="https://reddit.com" + (d.get("permalink") or ""),
        product=product,
    )


def _walk_comments(node, product, out, cap):
    if len(out) >= cap:
        return
    for ch in (node or {}).get("data", {}).get("children", []):
        if ch.get("kind") != "t1":
            continue
        d = ch.get("data", {})
        if d.get("body"):
            out.append(_comment_to_item(d, product))
            if len(out) >= cap:
                return
        replies = d.get("replies")
        if isinstance(replies, dict):
            _walk_comments(replies, product, out, cap)


def _search_via_json(query, product, subreddit=None, limit=50, comment_posts=8, comments_per_post=15):
    """Primary path. Returns list[Item], or None if blocked (so we fall back)."""
    if subreddit:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "restrict_sr": 1, "limit": limit, "sort": "relevance", "raw_json": 1}
    else:
        url = "https://www.reddit.com/search.json"
        params = {"q": query, "limit": limit, "type": "link", "raw_json": 1}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code in (403, 429):
            print(f"[reddit] .json blocked ({r.status_code}) -- using browser fallback")
            return None
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[reddit] .json failed ({e}) -- using browser fallback")
        return None

    posts = [c["data"] for c in data.get("data", {}).get("children", []) if c.get("kind") == "t3"]
    items = [_post_to_item(p, product) for p in posts]
    for p in posts[:comment_posts]:
        permalink = p.get("permalink")
        if not permalink:
            continue
        try:
            cr = requests.get(f"https://www.reddit.com{permalink}.json",
                              params={"raw_json": 1, "limit": comments_per_post},
                              headers=HEADERS, timeout=15)
            if cr.status_code in (403, 429):
                break
            cr.raise_for_status()
            listing = cr.json()
            if len(listing) > 1:
                _walk_comments(listing[1], product, items, cap=len(items) + comments_per_post)
            time.sleep(0.7)
        except Exception as e:
            print(f"[reddit] comment fetch failed for {permalink}: {e}")
    print(f"[reddit] .json '{query}' (sub={subreddit or 'all'}) -> {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# FALLBACK: Browserbase + Playwright, parsing old.reddit.com HTML
# ---------------------------------------------------------------------------

def _bb_session(bb, project_id):
    """Create a Browserbase session, preferring residential proxies (Reddit blocks
    datacenter IPs). Falls back to no-proxy if proxies aren't available on the plan."""
    kwargs = {}
    if project_id:
        kwargs["project_id"] = project_id
    try:
        return bb.sessions.create(proxies=True, **kwargs)
    except Exception as e:
        print(f"[reddit] proxies unavailable ({e}) -- retrying without proxies")
        return bb.sessions.create(**kwargs)


def _browser_get_json(page, url, timeout=45000):
    """Navigate to a Reddit .json URL in the real browser and parse the JSON body."""
    import json as _json
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_timeout(700)
    body = page.evaluate("() => document.body.innerText") or ""
    return _json.loads(body)  # raises if Reddit returned an HTML block/login page


def _search_via_browser(query, product, subreddit=None, visit_posts=5, comments_per_post=12):
    """Fetch Reddit through a REAL browser (Browserbase). Tries .json-in-browser first
    (structured, reliable), falls back to parsing old.reddit HTML, prints diagnostics."""
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    if not api_key:
        print("[reddit] browser fallback unavailable: BROWSERBASE_API_KEY not set "
              "(check your .env is in this folder and not named .env.txt)")
        return []
    try:
        from playwright.sync_api import sync_playwright
        from browserbase import Browserbase
    except Exception as e:
        print(f"[reddit] browser fallback unavailable: {e} (pip install browserbase playwright)")
        return []

    q = query.replace(" ", "+")
    if subreddit:
        json_url = (f"https://www.reddit.com/r/{subreddit}/search.json"
                    f"?q={q}&restrict_sr=1&sort=relevance&raw_json=1&limit=50")
        html_url = f"https://old.reddit.com/r/{subreddit}/search?q={q}&restrict_sr=1&sort=relevance"
    else:
        json_url = f"https://www.reddit.com/search.json?q={q}&type=link&raw_json=1&limit=50"
        html_url = f"https://old.reddit.com/search?q={q}&sort=relevance"

    bb = Browserbase(api_key=api_key)
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID")

    items = []
    browser = None
    try:
        with sync_playwright() as pw:
            session = _bb_session(bb, project_id)
            browser = pw.chromium.connect_over_cdp(session.connect_url)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # --- attempt 1: fetch .json THROUGH the browser (best case) ---
            try:
                data = _browser_get_json(page, json_url)
                posts = [c["data"] for c in data.get("data", {}).get("children", [])
                         if c.get("kind") == "t3"]
                for p in posts:
                    items.append(_post_to_item(p, product))
                print(f"[reddit] browser+json got {len(posts)} posts")
                for p in posts[:visit_posts]:
                    permalink = p.get("permalink")
                    if not permalink:
                        continue
                    try:
                        listing = _browser_get_json(
                            page, f"https://www.reddit.com{permalink}.json?raw_json=1&limit={comments_per_post}")
                        if isinstance(listing, list) and len(listing) > 1:
                            _walk_comments(listing[1], product, items, cap=len(items) + comments_per_post)
                    except Exception as e:
                        print(f"[reddit] browser comment fetch failed {permalink}: {e}")
            except Exception as e:
                print(f"[reddit] browser+json failed ({e}); trying HTML parse")
                # diagnostics: what did Reddit actually serve?
                try:
                    title = page.title()
                    snippet = (page.evaluate("() => document.body.innerText") or "")[:220]
                    print(f"[reddit] DIAG title={title!r}")
                    print(f"[reddit] DIAG body[:220]={snippet!r}")
                except Exception:
                    pass

            # --- attempt 2: parse old.reddit HTML ---
            if not items:
                page.goto(html_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(1500)
                results = page.query_selector_all("div.search-result-link")
                print(f"[reddit] html fallback: found {len(results)} search-result-link nodes")
                for res in results[:15]:
                    title_el = res.query_selector("a.search-title")
                    if title_el:
                        t = title_el.inner_text().strip()
                        href = title_el.get_attribute("href")
                        if t:
                            items.append(Item(
                                id=f"reddit_post_{abs(hash(href or t)) % (10**12)}",
                                source="reddit", text=t, author="unknown",
                                timestamp=now_iso(), score=0,
                                url=href or html_url, product=product,
                            ))
                if not results:
                    try:
                        print(f"[reddit] DIAG html title={page.title()!r}")
                    except Exception:
                        pass

            print(f"[reddit] browser '{query}' (sub={subreddit or 'all'}) -> {len(items)} items")
    except Exception as e:
        print(f"[reddit] browser fallback FAILED ({e})")
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    return items


# ---------------------------------------------------------------------------

def search_reddit(query, product, subreddit=None, limit=50, comments_per_post=15):
    """Search Reddit. Tries .json first, falls back to a real browser via Browserbase.

    Signature unchanged so the agent/gatherer don't care how it works underneath.
    """
    items = _search_via_json(query, product, subreddit=subreddit,
                             limit=limit, comments_per_post=comments_per_post)
    if items:
        return items
    return _search_via_browser(query, product, subreddit=subreddit)
