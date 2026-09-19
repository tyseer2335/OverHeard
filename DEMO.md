# Voxmarket — Demo Runbook

Target: a **60–90 second** live demo where the **voice conversation controls the
research pipeline** and the screen fills with evidence, then the analyst is
**challenged** and the conclusion visibly changes.

---

## 0. One-time setup

```bash
# Elasticsearch (primary evidence layer)
docker compose up -d elasticsearch      # wait for green: curl localhost:9200/_cluster/health

# Backend
cd backend && uv sync
cp ../.env.example ../.env               # works offline as-is
uv run python -m scripts.seed_fixtures   # index the Notion corpus (also a full smoke test)

# Frontend
cd ../frontend && npm install && cp .env.local.example .env.local
```

## 1. Run it (3 terminals)

```bash
# T1 — Elasticsearch already running via docker
# T2 — backend
cd backend && uv run uvicorn app.main:app --reload --port 8000
# T3 — frontend
cd frontend && npm run dev      # http://localhost:3000
```

Open **http://localhost:3000**. The header badges show which integrations are live.

---

## 2. Turn on the voice (ElevenLabs)

The demo works **without voice** (see §4), but the voice is the wow. To enable it:

1. Expose the backend so ElevenLabs can reach the webhook tools:
   ```bash
   ngrok http 8000        # copy the https URL
   ```
2. In `.env` set:
   ```
   ELEVENLABS_API_KEY=sk_...
   PUBLIC_BASE_URL=https://<your-ngrok>.ngrok.app
   ELEVENLABS_TOOL_SECRET=<openssl rand -hex 32>
   ```
3. Provision the agent + tools:
   ```bash
   cd backend && uv run python -m scripts.setup_elevenlabs_agent
   ```
   It prints an `agent_id` (or, if the API schema differs for your account,
   writes `backend/elevenlabs_agent.json` to paste into the dashboard — the tool
   URLs/headers/body-schemas are correct either way).
4. Put the id in `.env`: `ELEVENLABS_AGENT_ID=agent_...`, restart the backend.
5. Reload the page → the badge flips to **ElevenLabs**, and **Start voice
   conversation** appears. Voice creds are minted server-side (`/api/elevenlabs/token`);
   the API key never touches the browser.

> Tip: also set `OPENAI_API_KEY` to switch extraction to the Responses API + strict
> JSON Schema and enable true semantic (embedding) search. For the event Elastic
> deployment, set `ELASTIC_CLOUD_ID`/`ELASTIC_API_KEY` and `ES_USE_SEMANTIC_TEXT=true`.

---

## 3. The 60–90s voice script

| You say | What happens | On screen |
|---|---|---|
| "Research what people are saying about **Notion** lately — what do they dislike?" | Agent calls **start_research**, then polls **get_research_status**. | Progress stepper runs QUEUED→…→READY; comment/thread counts appear. |
| "What are customers complaining about most?" | Agent calls **query_feedback**. | Theme cards render; **pricing** leads with a ⚠️ "83% one thread" badge. |
| "Is that actually widespread, or mostly one viral thread?" | Agent calls **challenge_finding**. | **Challenge panel** appears: verdict *concentrated*, 83% concentration bar, counterevidence cards, and "set that thread aside → **onboarding**". |
| "Set that thread aside." *(or click ⊘ on the pricing card)* | `exclude` recomputes. | Themes reorder — **onboarding** becomes #1 (evidence_version bumps). |
| "Find evidence against your conclusion." | **challenge_finding** retrieves real positive/pushback comments. | Counterevidence cards (e.g. "pricing is fair for what you get"). |
| "Create a product investigation ticket about onboarding." | **create_investigation_ticket** returns a *draft*. | Ticket modal: issue, evidence, counterevidence, uncertainty, next experiment. |
| "Approve it." | Human-approved → ticket created. | Modal shows the created `tkt_…` id. |

The key line for judges: **"Elastic isn't storing the answer — it's the evidence
layer that lets the agent reason over hundreds of individual opinions, and change
its mind when challenged."**

## 4. No-key / fallback demo (bulletproof)

Everything above is reproducible from the UI without any keys:
- Type **Notion** in the voice panel's box → **Research**.
- Use **"Is 'pricing' just one viral thread?"** and **"Find counterevidence"** buttons.
- Click **⊘ exclude top thread** on the pricing card to trigger the recompute.
- Click **🎫 Draft investigation ticket** → **Approve & create**.

If Elasticsearch is down, the backend automatically falls back to an in-memory
store (badge shows *ES: fallback*) so the pipeline still runs.

> Note: `seed_fixtures` leaves `res_seed_notion` with no exclusions. If you were
> testing and a thread is excluded, click **↩ re-include** or just start a fresh
> research to reset the narrative.

---

## 5. Prize talking points

- **Elasticsearch (primary):** BM25 + semantic fused with **RRF**, theme/sentiment
  **aggregations**, thread-concentration analysis, and dedicated **counterevidence**
  retrieval. Not a KV store — the reasoning substrate.
- **ElevenLabs (primary):** Agents with 5 **server webhook tools** that *drive* the
  pipeline; WebRTC; server-minted tokens; shared-secret auth on every tool call.
- **OpenAI (strong):** Responses API + **strict JSON Schema** turns messy comments
  into structured records; never computes aggregates (ES does). See `CODEX_LOG.md`.
- **Browserbase (strong):** bounded Stagehand collection with a live-view panel.
- **Rox (stretch):** the agent takes a real, human-approved **action** (the ticket)
  on genuinely messy, contested data.
- **Sentry (optional):** set `SENTRY_DSN` to trace jobs/OpenAI/ES/Browserbase.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Badge says *ES: fallback* | `docker compose up -d elasticsearch`; wait for green; restart backend. |
| Voice button missing | `ELEVENLABS_API_KEY` + `ELEVENLABS_AGENT_ID` unset, or restart needed. |
| Agent tools 401 | `ELEVENLABS_TOOL_SECRET` in `.env` must match the `X-Tool-Secret` header on the agent's tools (re-run the setup script after changing it). |
| Agent can't reach tools | `PUBLIC_BASE_URL` must be the public tunnel URL, not localhost. |
| Empty dashboard | Start a research (voice or the box); the UI follows `/api/research/latest`. |
