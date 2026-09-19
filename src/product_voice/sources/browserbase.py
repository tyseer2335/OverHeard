"""Browserbase adapter — native Search + Fetch API.

What actually works (measured, not assumed)
-------------------------------------------
Browserbase's SDK exposes two server-side primitives that need no browser
session and no LLM:

* ``browserbase.search(query)``  -> ranked web results (url, title, author, date)
* ``browserbase.fetch(url)``     -> page content rendered to **markdown**

That combination is the collection path: search the open web for opinions about
a product, fetch the pages, split them into individual opinion paragraphs.

What does not work, and why we don't try
----------------------------------------
* ``reddit.com`` direct — ``fetch`` returns HTTP 403 (block page) without
  proxies. **With** ``proxies=True`` it returns HTTP 200, but the body is
  Reddit's *"Prove your humanity"* CAPTCHA. The proxy beats the IP block and
  then loses to the bot challenge. Measured 2026-09-19.
* ``x.com`` / ``instagram.com`` / ``tiktok.com`` — login walls. No proxy fixes
  a login wall; only a logged-in session would, which is a ToS violation.

So ``BLOCKED_DOMAINS`` are skipped deliberately. Reddit *opinion* still reaches
the corpus, because search surfaces mirrors and aggregators (whatredditthinks,
sentinel mirrors, review roundups) that quote the threads and are freely
fetchable. Note a 200 can still be a block page, hence ``_looks_blocked``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from .base import SourceAdapter, SourceDocument, SourceError

log = logging.getLogger("product_voice.sources.browserbase")

#: Query templates. Kept free of the ``site:`` operator — Browserbase's search
#: returns zero results for it (measured); plain keywords work.
QUERY_TEMPLATES: dict[str, str] = {
    "reddit": "{product} reddit review complaints what users say",
    "forums": "{product} forum thread problems issues users",
    "reviews": "{product} honest review pros and cons complaints",
    "web": "{product} customer reviews complaints",
}

#: Never fetch these — they serve CAPTCHAs or login walls, wasting the quota.
BLOCKED_DOMAINS = (
    "reddit.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "linkedin.com",
)

#: Phrases that mean "this 200 response is actually a wall".
_BLOCK_MARKERS = (
    "prove your humanity",
    "verify you are human",
    "enable javascript and cookies",
    "checking your browser",
    "blocked by network security",
    "log in to continue",
    "sign in to continue",
    "are you a robot",
)

MIN_PARAGRAPH = 80
MAX_PARAGRAPH = 2000
#: Caps exist for corpus diversity, not politeness. Without them a single
#: long listicle supplies the whole run and the "multi-source" claim is hollow.
MAX_PARAGRAPHS_PER_PAGE = 5
MAX_DOCS_PER_DOMAIN = 8

_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MULTI_NL = re.compile(r"\n{3,}")


class BrowserbaseSource(SourceAdapter):
    name = "browserbase"
    requires_credentials = True

    def __init__(
        self,
        api_key: str | None,
        project_id: str | None = None,
        targets: list[str] | None = None,
        results_per_query: int = 6,
        use_proxies: bool = False,
        **_ignored: Any,
    ) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.targets = targets or ["reddit", "reviews"]
        self.results_per_query = results_per_query
        # Only helps on sites that IP-block but don't CAPTCHA; costs quota.
        self.use_proxies = use_proxies

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "BROWSERBASE_API_KEY not set"
        try:
            import stagehand  # noqa: F401
        except ImportError:
            return False, "stagehand not installed (pip install stagehand)"
        return True, ""

    def collect(self, product: str, query: str, limit: int) -> Iterable[SourceDocument]:
        ok, reason = self.available()
        if not ok:
            raise SourceError(reason)
        return _run_sync(self._collect_async(product, query, limit))

    async def _collect_async(
        self, product: str, query: str, limit: int
    ) -> list[SourceDocument]:
        from stagehand.browser import browserbase as bb

        subject = query or product
        docs: list[SourceDocument] = []
        seen_urls: set[str] = set()
        per_domain: dict[str, int] = {}

        for target in self.targets:
            if len(docs) >= limit:
                break
            template = QUERY_TEMPLATES.get(target)
            if not template:
                log.warning("unknown browserbase target %r — skipping", target)
                continue
            search_query = template.format(product=subject)

            try:
                found = await bb.search(
                    api_key=self.api_key,
                    query=search_query,
                    num_results=self.results_per_query,
                )
            except Exception as exc:  # noqa: BLE001 - one target must not kill the run
                log.warning("browserbase search failed for %r: %s", search_query, exc)
                continue

            log.info("search %r -> %d results", search_query, len(found.results))

            for item in found.results:
                if len(docs) >= limit:
                    break
                url = item.url or ""
                domain = _domain(url)
                if not url or url in seen_urls:
                    continue
                if any(blocked in domain for blocked in BLOCKED_DOMAINS):
                    log.info("skipping walled domain %s", domain)
                    continue
                if per_domain.get(domain, 0) >= MAX_DOCS_PER_DOMAIN:
                    log.info("domain %s at cap — skipping for diversity", domain)
                    continue
                seen_urls.add(url)

                try:
                    page = await bb.fetch(
                        api_key=self.api_key,
                        url=url,
                        format="markdown",
                        **({"proxies": True} if self.use_proxies else {}),
                    )
                except Exception as exc:  # noqa: BLE001
                    # 402 means the plan's fetch quota is gone. Every later
                    # fetch will fail the same way, so stop and say so rather
                    # than grinding through the list and reporting a silent
                    # zero that looks like "no opinions found".
                    if "402" in str(exc):
                        raise SourceError(
                            "Browserbase fetch quota exhausted (HTTP 402) — "
                            "the plan's included fetches are used up"
                        ) from exc
                    log.warning("fetch failed for %s: %s", url, exc)
                    continue

                if page.status_code >= 400:
                    log.info("fetch %s -> HTTP %s, skipping", domain, page.status_code)
                    continue
                text = _to_text(page.content or "")
                if _looks_blocked(text):
                    log.info("fetch %s -> block/CAPTCHA page, skipping", domain)
                    continue

                published = _parse_date(item.published_date)
                for i, para in enumerate(_paragraphs(text, subject)):
                    if len(docs) >= limit:
                        break
                    if per_domain.get(domain, 0) >= MAX_DOCS_PER_DOMAIN:
                        break
                    per_domain[domain] = per_domain.get(domain, 0) + 1
                    docs.append(
                        SourceDocument(
                            id=f"browserbase_{_slug(url)}_{i}",
                            source=self.name,
                            product=product,
                            search_query=search_query,
                            text=para,
                            author=item.author or domain or "web",
                            url=url,
                            created_at=published,
                            thread_id=_slug(url),
                            thread_title=item.title or "",
                            container_id=domain,
                            container_title=domain,
                            # `platform` = where the opinion lives;
                            # `source`   = how we collected it.
                            extra={"platform": target, "via": "browserbase_search"},
                        )
                    )
        log.info("browserbase collected %d docs", len(docs))
        return docs


def _to_text(markdown: str) -> str:
    """Strip markdown chrome: base64 images, link targets, heading markers."""
    text = _IMG_RE.sub("", markdown)
    text = _LINK_RE.sub(r"\1", text)
    text = _HEADING_RE.sub("", text)
    return _MULTI_NL.sub("\n\n", text).strip()


def _looks_blocked(text: str) -> bool:
    """A 200 response can still be a CAPTCHA or login wall."""
    lowered = text[:4000].casefold()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _paragraphs(text: str, subject: str) -> list[str]:
    """Split a page into individual opinion-sized chunks.

    Prefers paragraphs that actually mention the product; falls back to any
    substantial prose so a relevant page still contributes something.
    """
    terms = [t for t in re.split(r"\W+", subject.casefold()) if len(t) > 2]
    on_topic: list[str] = []
    generic: list[str] = []

    for block in text.split("\n\n"):
        para = " ".join(block.split())
        if not (MIN_PARAGRAPH <= len(para) <= MAX_PARAGRAPH):
            continue
        # Nav bars and link soup survive as short word-dense lines; skip them.
        if para.count("|") > 3:
            continue
        lowered = para.casefold()
        if terms and any(term in lowered for term in terms):
            on_topic.append(para)
        else:
            generic.append(para)

    chosen = on_topic or generic
    return chosen[:MAX_PARAGRAPHS_PER_PAGE]


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.removeprefix("www.")
    except ValueError:
        return ""


def _slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.casefold())[-60:].strip("-")


def _run_sync(coro):
    """Bridge Browserbase's async API into this codebase's sync collectors."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside a loop (e.g. FastAPI): run in a private loop on a thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
