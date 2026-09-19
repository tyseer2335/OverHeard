"use client";

import type { EvidenceItem } from "@/lib/types";

const SENT_COLOR: Record<string, string> = {
  negative: "border-l-rose-500",
  positive: "border-l-emerald-500",
  mixed: "border-l-amber-500",
  neutral: "border-l-slate-500",
};

export function EvidenceList({
  title,
  items,
  hint,
}: {
  title: string;
  items: EvidenceItem[];
  hint?: string;
}) {
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-baseline gap-2">
        <h3 className="font-semibold">{title}</h3>
        {hint && <span className="text-xs text-slate-500">{hint}</span>}
        <span className="ml-auto text-xs text-slate-500">{items.length}</span>
      </div>
      <div className="space-y-2">
        {items.length === 0 && <p className="text-sm text-slate-500">No evidence.</p>}
        {items.map((e) => (
          <EvidenceCard key={e.doc_id} e={e} />
        ))}
      </div>
    </div>
  );
}

export function EvidenceCard({ e }: { e: EvidenceItem }) {
  return (
    <div className={`animate-fadeUp rounded-lg border-l-2 bg-panel2 p-3 ${SENT_COLOR[e.overall_sentiment] || "border-l-slate-500"}`}>
      <p className="text-sm leading-relaxed text-slate-200">“{e.snippet}”</p>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span className="text-slate-400">{e.author || e.source}</span>
        {e.thread_title && <span className="truncate max-w-[220px]">· {e.thread_title}</span>}
        {e.aspects.slice(0, 3).map((a) => (
          <span key={a} className="rounded bg-line px-1.5 py-0.5 capitalize text-slate-300">
            {a.replace(/_/g, " ")}
          </span>
        ))}
        {e.url && (
          <a
            href={e.url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-indigo-400 hover:text-indigo-300"
          >
            source ↗
          </a>
        )}
      </div>
    </div>
  );
}
