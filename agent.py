"""GPT research agent -- the brain that decides what to search.

This is the "agent doing research" (Version B): we hand the OpenAI model a set of
search TOOLS (Reddit, HN, YouTube, and optionally X/Instagram via Browserbase). The
model decides what queries to run, reads compact summaries of what came back, and
decides its next move -- chasing gaps, contradictions, and specific complaints --
until it's gathered enough or hits the iteration cap.

The model never sees the full raw text (that would blow the context window). Every
item a tool returns is accumulated in `corpus` keyed by id (natural dedupe). The
model only sees counts + a few sample snippets so it can steer.

Setup:
    pip install openai
    Set env var: OPENAI_API_KEY
"""

import os
import json

from dotenv import load_dotenv
load_dotenv()  # load OPENAI_API_KEY / BROWSERBASE_* / etc. from .env

from schema import Item
from sources.reddit_source import search_reddit
from sources.hn_source import search_hn
from sources.youtube_source import search_youtube

# Browser sources are optional / slow -- imported lazily only if enabled.


SYSTEM_PROMPT = """You are a research agent gathering PUBLIC opinions about a product \
so a downstream system can analyze what people really think about it.

Your job is to GATHER as much relevant, messy, real-world discussion as possible by \
calling the search tools. Be thorough and cast a wide net:
- Start broad (the product name, "<product> review", "<product> problems").
- Then go specific: chase particular features, complaints, comparisons, and any \
contradictions you notice between sources.
- Vary your queries and, for Reddit, target relevant subreddits.
- Different platforms disagree -- deliberately gather from all of them so the \
downstream system has conflicting sources to reconcile.

You will only see SUMMARIES of what each search returned (counts + a few samples), \
not the full data -- that's fine, it's being saved. Use the summaries to decide what \
to search next. Keep going until you have broad, varied coverage, then stop by \
replying with a short plain-text summary of what you gathered (no tool call)."""


def _tools(use_browser):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_reddit",
                "description": "Search Reddit for posts + comments. Great for candid, threaded opinions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "search terms"},
                        "subreddit": {"type": "string", "description": "optional subreddit to restrict to, e.g. 'apple'. Omit to search all of Reddit."},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_hn",
                "description": "Search Hacker News comments + stories. Skews technical; often disagrees with Reddit.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_youtube",
                "description": "Search YouTube and pull comments from review videos about the product.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        },
    ]
    if use_browser:
        tools.append({
            "type": "function",
            "function": {
                "name": "search_social",
                "description": "Try to scrape X (Twitter) and Instagram via a browser. Slow and may hit a login wall (returns nothing if so). Use sparingly for extra signal.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        })
    return tools


def _run_tool(name, args, product, corpus, use_browser):
    """Execute one tool call, add results to `corpus`, return a COMPACT summary dict."""
    q = args.get("query", product)
    got = []
    try:
        if name == "search_reddit":
            got = search_reddit(q, product=product, subreddit=args.get("subreddit"))
        elif name == "search_hn":
            got = search_hn(q, product=product)
        elif name == "search_youtube":
            got = search_youtube(q, product=product)
        elif name == "search_social" and use_browser:
            from sources.browser_source import search_x, search_instagram
            got = search_x(q, product=product) + search_instagram(q, product=product)
        else:
            return {"error": f"unknown tool {name}"}
    except Exception as e:
        return {"tool": name, "query": q, "error": str(e), "new_items": 0}

    # accumulate with natural dedupe by id
    new_count = 0
    for it in got:
        if it.id not in corpus:
            corpus[it.id] = it
            new_count += 1

    # compact summary for the model: counts + a few short samples
    samples = [ (it.text[:160] + ("..." if len(it.text) > 160 else "")) for it in got[:3] ]
    return {
        "tool": name,
        "query": q,
        "returned": len(got),
        "new_items": new_count,
        "total_corpus": len(corpus),
        "samples": samples,
    }


def run_research_agent(product, use_browser=False, max_iters=16, model="gpt-4o"):
    """Drive the research loop. Returns list[Item] (the accumulated corpus).

    max_iters: hard cap on tool-calling rounds so it can't run forever.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    corpus = {}  # id -> Item
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Product to research: {product}. Gather broadly and deeply."},
    ]
    tools = _tools(use_browser)

    for i in range(max_iters):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice="auto",
        )
        msg = resp.choices[0].message

        # model decided to stop (no tool calls) -> we're done
        if not msg.tool_calls:
            print(f"[agent] done after {i} rounds. Final note: {msg.content}")
            break

        # record the assistant turn (with its tool calls) before answering them
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        # execute every tool call the model asked for
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            summary = _run_tool(tc.function.name, args, product, corpus, use_browser)
            print(f"[agent] round {i}: {tc.function.name}({args}) -> "
                  f"+{summary.get('new_items', 0)} new (total {len(corpus)})")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(summary),
            })
    else:
        print(f"[agent] hit max_iters={max_iters} cap, stopping.")

    return list(corpus.values())
