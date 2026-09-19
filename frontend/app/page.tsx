"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useResearch } from "@/hooks/useResearch";
import ResearchProgress from "@/components/ResearchProgress";
import ThemeCards from "@/components/ThemeCards";
import { EvidenceList } from "@/components/EvidenceCards";
import ChallengePanel from "@/components/ChallengePanel";
import TicketDialog from "@/components/TicketDialog";
import BrowserPreview from "@/components/BrowserPreview";

// The voice SDK touches browser-only APIs — load it client-side only.
const VoicePanel = dynamic(() => import("@/components/VoicePanel"), { ssr: false });

export default function Home() {
  const { researchId, job, evidence, challenge, ticketDraft, setChallenge, focus, refresh } = useResearch();
  const [showTicket, setShowTicket] = useState(false);
  const [claim, setClaim] = useState("");
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    fetch(`${api.base}/health`).then((r) => r.json()).then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    if (ticketDraft) setShowTicket(true);
  }, [ticketDraft]);

  const topAspect = useMemo(() => {
    const t = evidence?.themes.find((x) => x.sentiment.negative > 0);
    return t?.key;
  }, [evidence]);

  const ready = job && ["READY", "PARTIAL"].includes(job.status);

  async function onExclude(threadId: string, exclude: boolean) {
    if (!researchId) return;
    await api.exclude(researchId, threadId, exclude).catch(() => {});
    refresh();
  }

  async function runChallenge(text: string) {
    if (!researchId || !text.trim()) return;
    const res = await api.challenge(researchId, text.trim()).catch(() => null);
    if (res) setChallenge(res);
  }

  async function draftTicket() {
    if (!researchId) return;
    await api.draftTicket(researchId, topAspect).catch(() => {});
    refresh();
    setShowTicket(true);
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">
          Vox<span className="text-indigo-400">market</span>
        </h1>
        <span className="text-sm text-slate-400">voice-driven market intelligence, backed by evidence</span>
        {health && (
          <div className="ml-auto flex flex-wrap gap-1.5 text-[11px]">
            <Badge on={health.integrations?.elasticsearch} off={health.store === "memory"}>
              {health.store === "memory" ? "ES: fallback" : "Elasticsearch"}
            </Badge>
            <Badge on={health.integrations?.elevenlabs}>ElevenLabs</Badge>
            <Badge on={health.integrations?.openai}>OpenAI</Badge>
            <Badge on={health.integrations?.browserbase}>Browserbase</Badge>
          </div>
        )}
      </header>

      <div className="grid gap-5 lg:grid-cols-[380px_1fr]">
        {/* Voice */}
        <div className="lg:sticky lg:top-6 lg:h-[calc(100vh-3rem)]">
          <VoicePanel onFocus={focus} />
        </div>

        {/* Dashboard */}
        <div className="space-y-5">
          {!job && (
            <div className="card flex min-h-[300px] flex-col items-center justify-center p-10 text-center">
              <div className="text-4xl">🎙️</div>
              <h2 className="mt-3 text-lg font-semibold">Start a conversation</h2>
              <p className="mt-1 max-w-md text-sm text-slate-400">
                Ask Vox to research a product — “research what people are saying about Notion lately” —
                and watch the evidence build here in real time. Then challenge its conclusions.
              </p>
            </div>
          )}

          {job && <ResearchProgress job={job} />}
          {job?.browser_live_view_url && <BrowserPreview url={job.browser_live_view_url} />}
          {challenge && <ChallengePanel challenge={challenge} />}

          {ready && evidence && (
            <>
              <ThemeCards
                themes={evidence.themes}
                excluded={evidence.excluded_thread_ids}
                onExclude={onExclude}
              />

              {/* interactive challenge controls (work with or without voice) */}
              <div className="card p-5">
                <div className="mb-2 text-sm font-semibold">Challenge the analysis</div>
                <div className="flex flex-wrap gap-2">
                  {topAspect && (
                    <button
                      onClick={() => runChallenge(`${topAspect} is the top complaint`)}
                      className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
                    >
                      Is “{topAspect.replace(/_/g, " ")}” just one viral thread?
                    </button>
                  )}
                  <button
                    onClick={() => runChallenge(claim || `${topAspect ?? "that"} is the top complaint`)}
                    className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
                  >
                    Find counterevidence
                  </button>
                  <button
                    onClick={draftTicket}
                    className="ml-auto rounded-lg bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-400"
                  >
                    🎫 Draft investigation ticket
                  </button>
                </div>
                <div className="mt-2 flex gap-2">
                  <input
                    value={claim}
                    onChange={(e) => setClaim(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runChallenge(claim)}
                    placeholder="Challenge a specific claim…"
                    className="flex-1 rounded-lg border border-line bg-panel2 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                  />
                  <button
                    onClick={() => runChallenge(claim)}
                    className="rounded-lg bg-slate-700 px-3 py-2 text-sm hover:bg-slate-600"
                  >
                    Challenge
                  </button>
                </div>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <EvidenceList title="Top complaints" hint="negative" items={evidence.top_negative} />
                <EvidenceList title="What they like" hint="positive" items={evidence.top_positive} />
              </div>

              {evidence.caveats.length > 0 && (
                <div className="card border-amber-500/20 p-4">
                  <div className="text-xs uppercase tracking-wide text-amber-300">Caveats</div>
                  <ul className="mt-2 space-y-1 text-sm text-slate-300">
                    {evidence.caveats.map((c, i) => (
                      <li key={i}>• {c}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {showTicket && ticketDraft && (
        <TicketDialog draft={ticketDraft} onDismiss={() => setShowTicket(false)} />
      )}
    </main>
  );
}

function Badge({ on, off, children }: { on?: boolean; off?: boolean; children: React.ReactNode }) {
  const cls = off
    ? "bg-amber-500/15 text-amber-300"
    : on
    ? "bg-emerald-500/15 text-emerald-300"
    : "bg-slate-600/20 text-slate-500";
  return <span className={`rounded-full px-2 py-0.5 ${cls}`}>{children}</span>;
}
