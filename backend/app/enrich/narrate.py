"""Natural-language narration used OFF the voice hot-path (job completion, tickets).

The live voice loop keeps latency low by returning deterministic ``spoken_summary``
strings from the webhook tools and letting the ElevenLabs agent phrase them. These
richer narrations (headline, ticket prose) use the OpenAI Responses API when a key
is present, with a deterministic template fallback otherwise. They are grounded in
numbers/evidence we pass in — the model never computes statistics.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import settings
from app.enrich.openai_client import get_openai
from app.models import Counts, EvidenceItem, Theme, ThreadConcentration

log = logging.getLogger("voxmarket.narrate")


async def narrate_headline(subject: str, question: str, themes: list[Theme], counts: Counts) -> str:
    top_neg = max(themes, key=lambda t: t.sentiment.negative, default=None)
    if top_neg and top_neg.sentiment.negative == 0:
        top_neg = None
    top_pos = max(
        (t for t in themes if t.sentiment.positive > t.sentiment.negative),
        key=lambda t: t.sentiment.positive, default=None,
    )
    fallback = _headline_template(subject, themes, counts, top_neg, top_pos)
    client = get_openai()
    if client is None:
        return fallback
    facts = {
        "subject": subject,
        "question": question,
        "total_documents": counts.total,
        "thread_count": counts.thread_count,
        "themes": [
            {"theme": t.key, "mentions": t.doc_count, "negative": t.sentiment.negative,
             "positive": t.sentiment.positive, "threads": t.thread_count}
            for t in themes[:6]
        ],
    }
    try:
        resp = await client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content":
                 "You are a market-research analyst. Write ONE tight sentence (max 40 words) "
                 "summarizing the findings for a busy executive. Use ONLY the numbers provided; "
                 "do not invent figures."},
                {"role": "user", "content": f"Facts (JSON): {facts}"},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or fallback
    except Exception as exc:  # noqa: BLE001
        log.warning("headline narration failed (%s)", exc)
        return fallback


def _headline_template(subject, themes, counts, top_neg, top_pos) -> str:
    parts = [f"Across {counts.total} comments in {counts.thread_count} discussions about {subject},"]
    if top_neg:
        parts.append(
            f"the leading complaint is {top_neg.key.replace('_', ' ')} "
            f"({top_neg.sentiment.negative} mentions across {top_neg.thread_count} threads)."
        )
    if top_pos and top_pos.sentiment.positive > 0:
        parts.append(f"Users praise {top_pos.key.replace('_', ' ')} most.")
    return " ".join(parts)


class _TicketFields(BaseModel):
    issue: str
    uncertainty: str
    suggested_experiment: str


async def draft_ticket_fields(
    subject: str,
    theme_key: str,
    evidence: list[EvidenceItem],
    counterevidence: list[EvidenceItem],
    concentration: ThreadConcentration,
) -> _TicketFields:
    fallback = _TicketFields(
        issue=(
            f"Recurring negative feedback about {theme_key.replace('_', ' ')} in {subject}. "
            f"Seen across {concentration.thread_count} independent discussions "
            f"({concentration.total_docs} comments)."
        ),
        uncertainty=(
            f"Signal is {concentration.verdict}; the largest single thread accounts for "
            f"{round(concentration.top_thread_share * 100)}% of mentions. "
            f"{len(counterevidence)} comments push back on this."
        ),
        suggested_experiment=(
            f"Interview 5 users who raised {theme_key.replace('_', ' ')} and instrument the "
            "relevant flow to confirm the pattern before committing roadmap changes."
        ),
    )
    client = get_openai()
    if client is None:
        return fallback
    ctx = {
        "subject": subject,
        "theme": theme_key,
        "concentration": concentration.model_dump(),
        "evidence": [e.snippet for e in evidence[:6]],
        "counterevidence": [e.snippet for e in counterevidence[:4]],
    }
    try:
        resp = await client.responses.parse(
            model=settings.openai_model,
            input=[
                {"role": "system", "content":
                 "You draft a crisp product investigation ticket from provided evidence. "
                 "Be specific and grounded ONLY in the given snippets and numbers. "
                 "'issue' states the problem; 'uncertainty' honestly notes how concentrated/"
                 "contested the signal is; 'suggested_experiment' proposes one concrete next step."},
                {"role": "user", "content": f"Context (JSON): {ctx}"},
            ],
            text_format=_TicketFields,
        )
        return resp.output_parsed or fallback
    except Exception as exc:  # noqa: BLE001
        log.warning("ticket narration failed (%s)", exc)
        return fallback
