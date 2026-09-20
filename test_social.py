"""Quick diagnostic: can Browserbase load X / Instagram / TikTok at all?

Hits a public search/tag page on each platform through a real Browserbase browser
and prints what comes back (title + a snippet of visible text + whether it looks
blocked or login-walled). No parsing, just: what does each site actually serve us?

Run:
    python test_social.py "Sony WH-1000XM5"
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

PRODUCT = sys.argv[1] if len(sys.argv) > 1 else "Sony WH-1000XM5"
Q = PRODUCT.replace(" ", "%20")
TAG = PRODUCT.replace(" ", "").lower()

TARGETS = {
    "X (Twitter)": f"https://x.com/search?q={Q}&f=live",
    "Instagram":   f"https://www.instagram.com/explore/tags/{TAG}/",
    "TikTok":      f"https://www.tiktok.com/search?q={Q}",
}

BLOCK_HINTS = ("log in", "sign in", "blocked", "network security",
               "something went wrong", "verify", "captcha", "enable javascript",
               "create account", "help center")


def looks_blocked(text):
    t = (text or "").lower()
    return any(h in t for h in BLOCK_HINTS)


def main():
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    if not api_key:
        print("No BROWSERBASE_API_KEY in .env -- can't test.")
        return
    from playwright.sync_api import sync_playwright
    from browserbase import Browserbase

    bb = Browserbase(api_key=api_key)
    project_id = os.environ.get("BROWSERBASE_PROJECT_ID")

    for name, url in TARGETS.items():
        print("\n" + "=" * 60)
        print(f"{name}: {url}")
        browser = None
        try:
            with sync_playwright() as pw:
                kwargs = {"project_id": project_id} if project_id else {}
                # try proxies if the plan has them; fall back if not
                try:
                    session = bb.sessions.create(proxies=True, **kwargs)
                    print("  (using proxies)")
                except Exception:
                    session = bb.sessions.create(**kwargs)
                    print("  (no proxies -- datacenter IP)")

                browser = pw.chromium.connect_over_cdp(session.connect_url)
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4000)  # let JS render

                title = ""
                body = ""
                try:
                    title = page.title()
                    body = (page.evaluate("() => document.body.innerText") or "")
                except Exception as e:
                    print(f"  read failed: {e}")

                print(f"  title : {title!r}")
                print(f"  text  : {body[:300]!r}")
                print(f"  chars : {len(body)}")
                print(f"  VERDICT: {'BLOCKED / login wall' if looks_blocked(body) or len(body) < 200 else 'content visible?? worth a closer look'}")
        except Exception as e:
            print(f"  ERROR: {e}")
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
