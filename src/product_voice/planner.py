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

DEFAULT_PLANNER_MODEL = "gpt-5.6-sol"

SYSTEM_PROMPT = """You plan data collection for a product-opinion research agent.

Your queries decide what evidence the whole system sees. A vague query returns
tutorials, sponsored reviews and unrelated chatter; a precise one returns people
describing actual experience with the product.

Sources:
- hackernews: technical/developer discussion. Strong for dev tools, infra,
  software and hardware enthusiasts. Weak for mainstream consumer goods.
- youtube: comments under review videos. Broad consumer coverage. Note the
  comments are only as relevant as the video, so the query must describe a
  video that is ABOUT this product.
- browserbase: general web search + page fetch. Review sites, forums, blogs and
  aggregators that quote Reddit. Works for anything.
- steam: Steam user reviews. ONLY for video games. Huge volume when it applies.
  Never select it for non-games.
- lemmy: federated Reddit-like community comments. Modest volume, skews
  technical and privacy-minded.

Choosing sources:
- Pick only sources that plausibly contain opinions about THIS product.
- Fewer, better-targeted sources beat casting wide. Two strong sources are
  better than five that each return noise.

Writing queries — this is the part that matters:
- Each query must target a DIFFERENT angle: overall verdict, specific
  complaints, a named competitor comparison, reliability/bugs, price/value.
- Aim at people REPORTING EXPERIENCE, not at marketing. Prefer wording that
  attracts honest accounts ("problems", "after 6 months", "worth it",
  "switched away", "regret") over bare product names.
- If the product name is also an ordinary English word (Notion, Arc, Nothing,
  Craft), every query MUST carry a disambiguating word so results are about the
  product, not the word.
- Include the product's own distinctive terms (model number, version, maker)
  so results are about THIS product and not its predecessor.

QUERY LENGTH IS PER-SOURCE, and getting it wrong destroys the result set:
- hackernews, lemmy, steam use KEYWORD AND-matching: every extra word shrinks
  results hard. "Notion productivity tool opinions" returns 7 hits where
  "Notion app" returns 33,000. Use 1-3 words, varying one qualifier:
  "Notion app", "Notion pricing", "Notion slow".
- youtube and browserbase handle natural language: use full phrases like
  "Notion vs Obsidian honest comparison after a year".

Return STRICT JSON only, no markdown fence:
{"reasoning": "one sentence on why these sources",
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
    model: str = DEFAULT_PLANNER_MODEL,
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
            # No temperature: gpt-5.x rejects any value but the default, and
            # passing one fails the whole call with a 400.
            response_format={"type": "json_object"},
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
