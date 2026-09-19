"use client";

import type { ChallengeResult } from "@/lib/types";
import { EvidenceCard } from "./EvidenceCards";

const VERDICT_STYLE: Record<string, string> = {
  concentrated: "bg-amber-500/15 text-amber-300",
  widespread: "bg-emerald-500/15 text-emerald-300",
  mixed: "bg-slate-500/15 text-slate-300",
};

export default function ChallengePanel({ challenge }: { challenge: ChallengeResult }) {
  const c = challenge.concentration;
  return (
    <div className="animate-fadeUp rounded-2xl border border-amber-500/30 bg-amber-500/[0.06] p-5">
      <div className="flex items-center gap-2">
        <span className="text-lg">⚖️</span>
        <h3 className="font-semibold">Challenge</h3>
        <span className="truncate text-sm text-slate-400">“{challenge.claim}”</span>
        <span className={`ml-auto rounded-full px-2.5 py-1 text-xs font-medium ${VERDICT_STYLE[c.verdict] || VERDICT_STYLE.mixed}`}>
          {c.verdict}
        </span>
      </div>

      <p className="mt-3 rounded-xl bg-panel2 p-3 text-sm leading-relaxed text-slate-100">
        {challenge.assessment}
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Concentration</div>
          <div className="mt-1 rounded-xl bg-panel2 p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="truncate text-slate-300">{c.top_thread_title || "top thread"}</span>
              <span className="font-semibold text-amber-300">{Math.round(c.top_thread_share * 100)}%</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-line">
              <div className="h-full bg-amber-500" style={{ width: `${c.top_thread_share * 100}%` }} />
            </div>
            <div className="mt-1 text-[11px] text-slate-500">
              {c.top_thread_docs} of {c.total_docs} mentions · {c.thread_count} threads
            </div>
          </div>

          {challenge.revised_themes.length > 0 && (
            <>
              <div className="mt-3 text-xs uppercase tracking-wide text-slate-500">
                If the top thread is set aside
              </div>
              <div className="mt-1 space-y-1">
                {challenge.revised_themes
                  .filter((t) => t.sentiment.negative > 0)
                  .slice(0, 3)
                  .map((t, i) => (
                    <div
                      key={t.key}
                      className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-sm ${
                        i === 0 ? "bg-emerald-500/10 text-emerald-200" : "bg-panel2 text-slate-300"
                      }`}
                    >
                      <span className="capitalize">{t.key.replace(/_/g, " ")}</span>
                      <span className="text-xs text-rose-300">▼ {t.sentiment.negative}</span>
                    </div>
                  ))}
              </div>
            </>
          )}
        </div>

        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">
            Counterevidence ({challenge.counterevidence.length})
          </div>
          <div className="mt-1 space-y-2">
            {challenge.counterevidence.length === 0 && (
              <p className="text-sm text-slate-500">No direct counterevidence found.</p>
            )}
            {challenge.counterevidence.slice(0, 3).map((e) => (
              <EvidenceCard key={e.doc_id} e={e} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
