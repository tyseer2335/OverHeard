"""Provision (or print) the ElevenLabs agent for Voxmarket.

Builds the full agent config — system prompt + the five webhook tools wired to
this backend's ``PUBLIC_BASE_URL`` with the ``X-Tool-Secret`` header — then:

  * writes it to ``backend/elevenlabs_agent.json`` (paste-able into the dashboard),
  * and, if ``ELEVENLABS_API_KEY`` is set, attempts to create the agent via the
    API and prints the resulting ``agent_id`` to drop into ``.env``.

    uv run python -m scripts.setup_elevenlabs_agent

NOTE: the ElevenLabs agent-config schema shifts between versions. If the API call
is rejected, use the generated JSON to configure the agent in the dashboard — the
tool URLs, headers, and body schemas are what matter and are correct regardless.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.config import settings

OUT = Path(__file__).resolve().parents[1] / "elevenlabs_agent.json"
CREATE_URL = "https://api.elevenlabs.io/v1/convai/agents/create"

SYSTEM_PROMPT = """\
# Personality

You are Vox, a sharp, evidence-driven market-research analyst. You are curious, direct, and \
intellectually honest — you would rather say "the data doesn't support that" than flatter the \
user. You think in terms of evidence, sample sizes, and competing explanations, and you are \
genuinely interested in what customers actually feel. Confident but never overconfident: you \
change your mind when the evidence changes.

# Environment

You are speaking with a business leader over a live voice connection, paired with an on-screen \
dashboard that fills with the evidence behind everything you say — themes, sentiment, quotes, \
sources, and counterevidence. You do not read the dashboard aloud; you narrate the story and \
let the screen carry the detail. You operate a research backend through tools that collect \
messy public customer feedback, index it into Elasticsearch, and let you query it, challenge \
it, and act on it.

# Tone

- Conversational and brief — 1 to 3 sentences per turn. Voice is not a report.
- Lead with the finding, then offer to go deeper: "Pricing is the loudest complaint right now — want me to break it down?"
- Signal work in progress naturally: "Give me a few seconds to pull that together…"
- Ground every claim in the numbers the tools return; cite one vivid example, not ten, and point to the screen for the rest: "The full breakdown is on your screen."
- Be honest about the strength of evidence: "That's really just one viral thread," or "This shows up across a dozen independent discussions."
- When challenged, engage the challenge head-on and report what actually changes.
- Close cleanly: "Want me to dig into anything else, or should I file this?"

# Goal

Help the user investigate what customers think and reach conclusions they can trust. Core loop:

1. When the user asks you to research a product or company, call `start_research` with the \
subject (and their question if they gave one). Remember the `research_id` it returns — you MUST \
pass it to every later tool call in this conversation.
2. Tell them you have started, then call `get_research_status`. Do not report any findings until \
it is ready; if it is not, say so briefly and check again in a moment.
3. Answer questions with `query_feedback`. Report the leading themes, whether they are positive \
or negative, and one concrete example. Keep it short — the detail is on screen.
4. When the user pushes back — "is that widespread or just one thread?", "challenge that", "find \
evidence against your conclusion" — call `challenge_finding` with their claim. Honestly report \
how concentrated the signal is, what the counterevidence says, and whether setting aside a \
dominant thread changes the top complaint.
5. If the user asks to file or investigate an issue, call `create_investigation_ticket`. It \
returns a draft first — read back the proposed ticket and its evidence, ask for approval, and \
only call it again with `approve` set to true once they clearly say yes.

Confirm each action you take, and ask what they would like to explore next before ending.

# Guardrails

- Never invent statistics, quotes, themes, or trends. Every number and example must come from a tool result. If a tool has not run or returned nothing, say so.
- Do not summarize findings before `get_research_status` reports the research is ready.
- Do not manufacture a counterargument yourself — use `challenge_finding` to retrieve real counterevidence.
- Represent uncertainty honestly: if a finding is concentrated in one thread or is contested, say that plainly rather than overstating it.
- Never create a ticket or take any external action without explicit user approval in the same conversation.
- Keep it about the evidence — no speculation about individuals, and no advice beyond what the feedback supports.
"""

FIRST_MESSAGE = (
    "Hi, I'm Vox, your market-research analyst. Give me a product or company and what you want "
    'to know — like, "research what people are saying about Notion lately, and what they\'re '
    'frustrated about."'
)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "webhook",
        "name": name,
        "description": description,
        "response_timeout_secs": 30,
        "api_schema": {
            "url": f"{settings.public_base_url}/api/webhooks/elevenlabs/{name}",
            "method": "POST",
            "request_headers": {
                "Content-Type": "application/json",
                "X-Tool-Secret": settings.elevenlabs_tool_secret,
                # bypass ngrok's free-tier browser-warning interstitial (harmless elsewhere)
                "ngrok-skip-browser-warning": "true",
            },
            "request_body_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def build_tools() -> list[dict]:
    return [
        _tool(
            "start_research",
            "Begin researching customer feedback about a product or company. Returns a "
            "research_id to use in all subsequent tool calls.",
            {
                "subject": {"type": "string", "description": "Product or company to research, e.g. 'Notion'"},
                "question": {"type": "string", "description": "The user's specific question, if any"},
                "sources": {
                    "type": "array",
                    "description": "Data sources to collect from. Default ['fixtures'].",
                    "items": {
                        "type": "string",
                        "description": "A source name such as 'fixtures' or 'reddit'",
                    },
                },
            },
            ["subject"],
        ),
        _tool(
            "get_research_status",
            "Check whether a research job has finished collecting and analyzing feedback.",
            {"research_id": {"type": "string", "description": "The research_id from start_research"}},
            ["research_id"],
        ),
        _tool(
            "query_feedback",
            "Ask a question over the analyzed feedback (themes, sentiment, examples).",
            {
                "research_id": {"type": "string", "description": "The research_id from start_research"},
                "query": {"type": "string", "description": "The natural-language question to answer"},
                "aspect": {"type": "string", "description": "Optional theme filter, e.g. 'pricing'"},
                "sentiment": {"type": "string", "description": "Optional: positive|negative|mixed|neutral"},
            },
            ["research_id", "query"],
        ),
        _tool(
            "challenge_finding",
            "Stress-test a conclusion: check if it's concentrated in one thread, retrieve "
            "real counterevidence, and recompute excluding a dominant thread.",
            {
                "research_id": {"type": "string", "description": "The research_id from start_research"},
                "claim": {"type": "string", "description": "The conclusion to challenge, e.g. 'pricing is the top complaint'"},
                "aspect": {"type": "string", "description": "Optional theme the claim is about, e.g. 'pricing'"},
            },
            ["research_id", "claim"],
        ),
        _tool(
            "create_investigation_ticket",
            "Draft (and, once approved, create) a product investigation ticket with evidence, "
            "counterevidence, uncertainty, and a suggested next experiment. Call without "
            "approve to preview; call with approve=true only after the user confirms.",
            {
                "research_id": {"type": "string", "description": "The research_id from start_research"},
                "aspect": {"type": "string", "description": "Optional theme to file about, e.g. 'onboarding'"},
                "approve": {"type": "boolean", "description": "true only after the user explicitly approves"},
            },
            ["research_id"],
        ),
    ]


def build_agent_config() -> dict:
    return {
        "name": "Voxmarket Analyst",
        "conversation_config": {
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "en",
                "prompt": {
                    "prompt": SYSTEM_PROMPT,
                    "llm": "gpt-4o",
                    "temperature": 0.3,
                    "tools": build_tools(),
                },
            }
        },
    }


AGENTS_URL = "https://api.elevenlabs.io/v1/convai/agents"


def _warn_if_localhost() -> None:
    if "localhost" in settings.public_base_url or "127.0.0.1" in settings.public_base_url:
        print("  ⚠ PUBLIC_BASE_URL is localhost — ElevenLabs CANNOT reach your webhook tools.")
        print("    Run `ngrok http 8000`, set PUBLIC_BASE_URL to that https URL, and rerun.")


def update_existing_agent(agent_id: str) -> None:
    """PATCH an existing agent: swap in the Vox prompt/first message and add our 5
    webhook tools, preserving any built-in system tools (end_call, etc.)."""
    headers = {"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"}
    print(f"\n→ fetching existing agent {agent_id}…")
    cur = httpx.get(f"{AGENTS_URL}/{agent_id}", headers=headers, timeout=30)
    if cur.status_code // 100 != 2:
        print(f"✗ could not fetch agent ({cur.status_code}): {cur.text[:300]}")
        return
    cc = cur.json().get("conversation_config", {})
    prompt = cc.get("agent", {}).get("prompt", {}) or {}
    existing = prompt.get("tools", []) or []
    system_tools = [t for t in existing if isinstance(t, dict) and t.get("type") == "system"]
    llm = prompt.get("llm")

    cc_body: dict = {
        "agent": {
            "first_message": FIRST_MESSAGE,
            # don't let the greeting get barged over
            "disable_first_message_interruptions": True,
            "prompt": {
                "prompt": SYSTEM_PROMPT,
                "tools": system_tools + build_tools(),
                **({"llm": llm} if llm else {}),
            },
        }
    }
    # Optionally swap the voice, merging onto the existing tts settings.
    if settings.elevenlabs_voice_id:
        tts = dict(cc.get("tts", {}) or {})
        tts["voice_id"] = settings.elevenlabs_voice_id
        cc_body["tts"] = tts
        print(f"  setting voice_id = {settings.elevenlabs_voice_id}")

    body = {"conversation_config": cc_body}
    print("→ updating agent (Vox prompt + first message + 5 webhook tools)…")
    resp = httpx.patch(f"{AGENTS_URL}/{agent_id}", headers=headers, json=body, timeout=30)
    if resp.status_code // 100 == 2:
        tools = (
            resp.json().get("conversation_config", {}).get("agent", {}).get("prompt", {}).get("tools", [])
        )
        print(f"\n✓ updated agent {agent_id}")
        print(f"  tools now: {[t.get('name') for t in tools]}")
        print(f"  webhook base: {settings.public_base_url}")
        _warn_if_localhost()
    else:
        print(f"\n✗ update failed ({resp.status_code}): {resp.text[:600]}")
        print("  Schema may differ for your account version — set tools in the dashboard using")
        print("  elevenlabs_agent.json (URLs/headers/body-schemas are correct).")


def main() -> None:
    config = build_agent_config()
    OUT.write_text(json.dumps(config, indent=2))
    print(f"→ wrote agent config to {OUT}")
    print(f"  webhook base: {settings.public_base_url}")
    print(f"  tool secret : {settings.elevenlabs_tool_secret}")

    if not settings.elevenlabs_api_key:
        print("\nELEVENLABS_API_KEY not set — skipping API calls.")
        print("Paste elevenlabs_agent.json into the ElevenLabs dashboard, or set the key and rerun.")
        return

    # Update in place if we already have an agent; otherwise create a new one.
    if settings.elevenlabs_agent_id:
        update_existing_agent(settings.elevenlabs_agent_id)
        return

    print("\n→ creating agent via ElevenLabs API…")
    resp = httpx.post(
        CREATE_URL,
        headers={"xi-api-key": settings.elevenlabs_api_key, "Content-Type": "application/json"},
        json=config,
        timeout=30,
    )
    if resp.status_code // 100 == 2:
        agent_id = resp.json().get("agent_id")
        print(f"\n✓ created agent_id = {agent_id}")
        print("  Add to .env:  ELEVENLABS_AGENT_ID=" + str(agent_id))
        _warn_if_localhost()
    else:
        print(f"\n✗ API create failed ({resp.status_code}): {resp.text[:500]}")
        print("  The schema may differ for your account version — configure the agent in the")
        print("  dashboard using elevenlabs_agent.json (tool URLs/headers/schemas are correct).")


if __name__ == "__main__":
    main()
