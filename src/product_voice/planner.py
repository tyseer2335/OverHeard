"""LLM source planner — the agent decides where to look and what to ask.

Given only a product name, this picks which adapters are worth running and
writes several distinct search queries for each. Two reasons it matters:

1. **Source choice is genuinely product-dependent.** Steam is the best source
   in the project for a game and useless for headphones. Hacker News is rich
   for developer tools and thin for consumer audio. Hardcoding one list wastes
   quota on sources that cannot match.
2. **Query expansion is where the volume comes from.** One query against
   Hacker News tops out near 1000 items; six distinct queries multiply the
   reachable corpus and surface different complaint vocabulary ("crashes",
   "battery", "refund"), which is exactly the messy multi-angle input the
   analysis layer needs.

The plan is advisory. Unavailable sources are dropped by the registry, and a
rule-based fallback runs when no OpenAI key is configured, so collection never
depends on the LLM being reachable.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("product_voice.planner")

KNOWN_SOURCES = ("hackernews", "youtube", "browserbase", "steam", "lemmy")

SYSTEM_PROMPT = """You plan data collection for a product-opinion research agent.

Given a product, choose which sources to collect from and write search queries.

Sources:
- hackernews: technical/developer discussion. Great for dev tools, software,
  hardware enthusiasts. Weak for mainstream consumer goods.
- youtube: video review comments. Broad consumer coverage, good for hardware,
  games, apps.
- browserbase: general web search + fetch. Review sites, forums, blogs, and
  aggregators that quote Reddit. Works for anything.
- steam: Steam user reviews. ONLY for video games. Enormous volume when it
  applies. Do not select it for non-games.
- lemmy: federated Reddit-like community comments. Modest volume, skews
  technical/privacy-minded audiences.

Rules:
- Only select sources that can plausibly contain opinions about this product.
- Write 3-6 queries per selected source, each targeting a DIFFERENT angle:
  general opinion, specific complaints, comparisons, reliability, price.
- If the product name is also a common English word (e.g. "Notion", "Arc"),
  disambiguate every query with context words so results are about the
  product, not the word.
- QUERY LENGTH MATTERS, and differs by source:
  * hackernews, lemmy and steam use KEYWORD AND-matching. Every extra word
    shrinks the result set hard — "Notion productivity tool opinions" returns
    7 hits where "Notion app" returns 33,000. Use 1-3 words MAX for these,
    varying the product term and at most one qualifier
    (e.g. "Notion app", "Notion pricing", "Notion slow").
  * youtube and browserbase handle natural language well. Use fuller phrases
    there (e.g. "Notion vs Obsidian honest comparison").
- Return STRICT JSON only, no markdown fence:
  {"reasoning": "one sentence",
   "sources": [{"name": "hackernews", "queries": ["...", "..."]}]}"""


@dataclass
class SourcePlan:
    name: str
    queries: list[str] = field(default_factory=list)


@dataclass
class CollectionPlan:
    product: str
    sources: list[SourcePlan] = field(default_factory=list)
    reasoning: str = ""
    used_llm: bool = False

    @property
    def source_names(self) -> list[str]:
        return [s.name for s in self.sources]

    def summary(self) -> str:
        lines = [f"plan for {self.product!r} ({'llm' if self.used_llm else 'fallback'})"]
        if self.reasoning:
            lines.append(f"  reasoning: {self.reasoning}")
        for source in self.sources:
            lines.append(f"  {source.name}:")
            for query in source.queries:
                lines.append(f"    - {query}")
        return "\n".join(lines)


def _looks_like_game(product: str) -> bool:
    markers = ("game", "steam", "rpg", "shooter", "simulator", "souls", "craft")
    return any(m in product.casefold() for m in markers)


def fallback_plan(product: str, max_queries: int = 5) -> CollectionPlan:
    """Rule-based plan used when no LLM is available.

    Deliberately broad rather than clever: without a model we cannot tell what
    a product is, so we cast wide and let each adapter return nothing if it
    has no match.
    """
    # Ordered most-to-least valuable so a small max_queries still gets the
    # broad sweep plus the complaint angle, which is what the analysis needs.
    queries = [
        product,
        f"{product} review",
        f"{product} problems",
        f"{product} complaints",
        f"{product} vs alternatives",
    ][:max_queries]
    names = ["hackernews", "youtube", "browserbase", "lemmy"]
    if _looks_like_game(product):
        names.append("steam")
    return CollectionPlan(
        product=product,
        sources=[SourcePlan(name, list(queries)) for name in names],
        reasoning="no LLM available; casting wide across all free sources",
        used_llm=False,
    )


def _extract_json(raw: str) -> dict:
    """Models sometimes wrap JSON in prose or a fence despite instructions."""
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    return json.loads(raw[start : end + 1])


def plan_collection(
    product: str,
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
    allowed: tuple[str, ...] = KNOWN_SOURCES,
) -> CollectionPlan:
    """Ask the LLM which sources and queries to use, falling back on failure."""
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        log.info("no OPENAI_API_KEY — using fallback plan")
        return fallback_plan(product)

    try:
        from openai import OpenAI
    except ImportError:
        log.info("openai package not installed — using fallback plan")
        return fallback_plan(product)

    try:
        client = OpenAI(api_key=key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Product: {product}"},
            ],
            temperature=0.3,
        )
        data = _extract_json(response.choices[0].message.content or "")
    except Exception as exc:  # noqa: BLE001 - planning must never block collection
        log.warning("LLM planning failed (%s) — using fallback", exc)
        return fallback_plan(product)

    sources: list[SourcePlan] = []
    for entry in data.get("sources", []):
        name = str(entry.get("name", "")).strip().casefold()
        if name not in allowed:
            log.warning("planner proposed unknown source %r — dropping", name)
            continue
        queries = [str(q).strip() for q in entry.get("queries", []) if str(q).strip()]
        if queries:
            sources.append(SourcePlan(name, queries))

    if not sources:
        log.warning("planner returned no usable sources — using fallback")
        return fallback_plan(product)

    return CollectionPlan(
        product=product,
        sources=sources,
        reasoning=str(data.get("reasoning", "")),
        used_llm=True,
    )
