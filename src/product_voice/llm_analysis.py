"""LLM-based feedback analysis — replaces the VADER lexicon.

Why VADER had to go
-------------------
VADER is a 7,506-word dictionary plus five rules. It never reads a sentence; it
adds up word scores. Measured against Steam's ``voted_up`` ground truth on this
project's own corpus it agreed 78% of the time overall but called **55% of
genuinely negative reviews positive**, because sarcasm inverts meaning without
changing vocabulary ("10/10 would crash again", "I love how it deletes my
data"). For a complaint-detection product that is the class that matters, so it
was worse than a coin flip exactly where it counted.

It also could not judge *relevance*. Half the noise in the dashboard was
on-topic-looking text that had nothing to do with the product, and a keyword
heuristic cannot tell "the notion that..." from "Notion is slow".

What this does instead
----------------------
One model call per **batch** of comments (not per comment) returns, for each:
relevance, sentiment, a complaint/praise/question label, issue categories and a
one-line summary. Batching is what makes this affordable — a thousand comments
is tens of calls, not a thousand.

Failure is expected and handled: if the model is unreachable, returns
unparseable JSON, or drops rows, the affected items fall back to a neutral,
relevance-unknown result rather than blocking a collection run.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Sequence

log = logging.getLogger("product_voice.llm_analysis")

DEFAULT_MODEL = "gpt-5.6-sol"
#: Comments per request. This is the real throughput dial, not the worker
#: count: a corpus only produces len/BATCH_SIZE batches, so a large batch
#: starves the pool. Measured on 118 comments with 12 workers —
#: 25/batch: 28.4s (5 batches, 5 workers busy)
#: 10/batch: 13.3s (12 batches, pool saturated), same relevance quality
#:  6/batch: 11.9s but more calls, more cost, slightly worse results
BATCH_SIZE = int(os.getenv("LLM_ANALYSIS_BATCH", "10"))
MAX_CHARS = 1200  # per comment; long reviews are truncated, not dropped
#: Batches in flight. Each is one API call, so this is the main throughput
#: dial: analysis is latency-bound, not CPU-bound. Raise it if collection
#: feels slow and your OpenAI rate limit allows; lower it on 429s.
MAX_WORKERS = int(os.getenv("LLM_ANALYSIS_WORKERS", "12"))

ISSUE_CATEGORIES = (
    "performance",
    "reliability",
    "usability",
    "pricing",
    "support",
    "features",
    "integrations",
    "authentication",
    "design",
    "documentation",
    "audio_video",
    "notifications",
    "privacy",
)

SYSTEM_PROMPT = """You analyze customer feedback about a specific product.

For EVERY numbered item you receive, return one object with these fields:

- "id": the item's number, unchanged.
- "relevant": true only if the text is genuinely about THE PRODUCT NAMED BELOW.
  Be strict. false for: generic chatter, other products, the product name used
  as an ordinary English word (e.g. "the notion that..." is NOT the app
  Notion), spam, self-promotion, and comments about the video/article itself
  rather than the product ("first!", "great video", "who's watching in 2026").
- "sentiment": "positive" | "negative" | "neutral" — the author's feeling
  ABOUT THE PRODUCT. Judge intent, not vocabulary: sarcasm like "10/10 would
  crash again" or "I love how it deletes my data" is NEGATIVE. Praise phrased
  bluntly ("this thing is sick") is POSITIVE.
- "score": -1.0 to 1.0, matching the sentiment.
- "kind": "complaint" | "praise" | "feature_request" | "question" | "other".
- "issues": array of categories from this list ONLY, [] if none apply:
  performance, reliability, usability, pricing, support, features,
  integrations, authentication, design, documentation, audio_video,
  notifications, privacy.
  Only include a category the author actually raises. Do not tag "audio_video"
  because the word "video" appears; tag it only for a complaint or comment
  about audio or video functionality of the product itself.
- "summary": at most 12 words, the specific point being made. "" if irrelevant.

Return STRICT JSON only, no markdown fence, no commentary:
{"items": [{"id": 1, "relevant": true, "sentiment": "negative", "score": -0.6,
"kind": "complaint", "issues": ["performance"], "summary": "..."}]}

Return exactly one object per input item, in any order, with matching ids."""


@dataclass
class AnalysisResult:
    relevant: bool | None = None
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    kind: str = "other"
    issue_categories: list[str] = field(default_factory=list)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "is_complaint": self.kind == "complaint",
            "issue_categories": self.issue_categories,
            "relevant": self.relevant,
            "summary": self.summary,
        }


#: Used when the model cannot be reached or drops an item. relevant=None means
#: "unknown", which the store treats as visible — losing a real complaint is
#: worse than showing a questionable row.
UNKNOWN = AnalysisResult()


class LLMAnalyzer:
    """Batched LLM analysis with a safe degradation path."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        batch_size: int = BATCH_SIZE,
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.batch_size = batch_size
        self.max_workers = max_workers

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------ api
    def analyze_many(self, texts: Sequence[str], product: str) -> list[AnalysisResult]:
        """Analyze every text. Always returns one result per input."""
        if not texts:
            return []
        if not self.available():
            log.warning("LLM analyzer unavailable — returning unknown results")
            return [AnalysisResult() for _ in texts]

        batches = [
            list(range(i, min(i + self.batch_size, len(texts))))
            for i in range(0, len(texts), self.batch_size)
        ]
        results: list[AnalysisResult] = [AnalysisResult() for _ in texts]

        def run(indices: list[int]) -> tuple[list[int], dict[int, AnalysisResult]]:
            payload = [(n + 1, texts[idx]) for n, idx in enumerate(indices)]
            return indices, self._analyze_batch(payload, product)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for indices, parsed in pool.map(run, batches):
                for n, idx in enumerate(indices, start=1):
                    if n in parsed:
                        results[idx] = parsed[n]

        analyzed = sum(1 for r in results if r.relevant is not None)
        log.info("llm analyzed %d/%d comments", analyzed, len(texts))
        return results

    # -------------------------------------------------------------- internals
    def _analyze_batch(
        self, payload: list[tuple[int, str]], product: str
    ) -> dict[int, AnalysisResult]:
        from openai import OpenAI

        numbered = "\n\n".join(
            f"[{n}] {text.strip()[:MAX_CHARS]}" for n, text in payload
        )
        user = f"PRODUCT: {product}\n\nITEMS:\n\n{numbered}"

        try:
            client = OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
            data = _extract_json(response.choices[0].message.content or "")
        except Exception as exc:  # noqa: BLE001 - analysis must not kill a run
            log.warning("llm batch failed (%s) — items fall back to unknown", exc)
            return {}

        out: dict[int, AnalysisResult] = {}
        for item in data.get("items", []):
            try:
                item_id = int(item["id"])
            except (KeyError, TypeError, ValueError):
                continue
            out[item_id] = _coerce(item)
        return out


def _coerce(item: dict[str, Any]) -> AnalysisResult:
    """Trust nothing the model returns; clamp everything into range."""
    sentiment = str(item.get("sentiment", "neutral")).strip().casefold()
    if sentiment not in ("positive", "negative", "neutral"):
        sentiment = "neutral"

    try:
        score = float(item.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(-1.0, min(1.0, score))

    kind = str(item.get("kind", "other")).strip().casefold()
    if kind not in ("complaint", "praise", "feature_request", "question", "other"):
        kind = "other"

    raw_issues = item.get("issues") or []
    issues = [
        str(i).strip().casefold()
        for i in raw_issues
        if str(i).strip().casefold() in ISSUE_CATEGORIES
    ]

    relevant = item.get("relevant")
    if not isinstance(relevant, bool):
        relevant = None

    return AnalysisResult(
        relevant=relevant,
        sentiment=sentiment,
        sentiment_score=score,
        kind=kind,
        issue_categories=list(dict.fromkeys(issues)),
        summary=str(item.get("summary", ""))[:160],
    )


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    return json.loads(raw[start : end + 1])
