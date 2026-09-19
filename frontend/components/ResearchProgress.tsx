"use client";

import type { ResearchJob } from "@/lib/types";

const STEPS = ["QUEUED", "DISCOVERING", "COLLECTING", "CLEANING", "ENRICHING", "INDEXING", "READY"];

export default function ResearchProgress({ job }: { job: ResearchJob }) {
  const terminal = ["READY", "PARTIAL", "FAILED", "CANCELLED"].includes(job.status);
  const currentIdx = job.status === "PARTIAL" ? STEPS.length - 1 : STEPS.indexOf(job.status);
  const failed = job.status === "FAILED";

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">
          {job.subject}
          <span className="ml-2 text-sm font-normal text-slate-400">{job.question}</span>
        </h2>
        <span
          className={`ml-auto rounded-full px-2.5 py-1 text-xs font-medium ${
            failed
              ? "bg-rose-500/15 text-rose-300"
              : terminal
              ? "bg-emerald-500/15 text-emerald-300"
              : "bg-indigo-500/15 text-indigo-300 animate-pulse"
          }`}
        >
          {job.status}
        </span>
      </div>

      {/* stepper */}
      <div className="mt-4 flex items-center gap-1.5">
        {STEPS.map((s, i) => {
          const done = terminal ? true : i < currentIdx;
          const active = !terminal && i === currentIdx;
          return (
            <div key={s} className="flex flex-1 flex-col items-center gap-1">
              <div
                className={`h-1.5 w-full rounded-full ${
                  failed ? "bg-rose-500/40" : done || (terminal && i <= currentIdx) ? "bg-emerald-500" : active ? "bg-indigo-400" : "bg-line"
                }`}
              />
              <span className={`text-[9px] uppercase ${active ? "text-indigo-300" : "text-slate-500"}`}>
                {s.slice(0, 5)}
              </span>
            </div>
          );
        })}
      </div>

      {terminal && !failed && (
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Stat label="Comments" value={job.document_count} />
          <Stat label="Discussions" value={job.thread_count} />
          <Stat label="Sources" value={job.sources_completed.join(", ") || "—"} />
        </div>
      )}

      {job.headline && terminal && !failed && (
        <p className="mt-4 rounded-xl bg-panel2 p-3 text-sm leading-relaxed text-slate-200">
          {job.headline}
        </p>
      )}

      {failed && <p className="mt-3 text-sm text-rose-300">{job.error}</p>}
      {job.sources_failed.length > 0 && !failed && (
        <p className="mt-2 text-xs text-amber-300">Partial: {job.sources_failed.join(", ")} failed.</p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl bg-panel2 p-3">
      <div className="text-xl font-semibold">{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}
