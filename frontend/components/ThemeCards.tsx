"use client";

import type { Theme } from "@/lib/types";

const human = (k: string) => k.replace(/_/g, " ");

export default function ThemeCards({
  themes,
  excluded,
  onExclude,
}: {
  themes: Theme[];
  excluded: string[];
  onExclude: (threadId: string, exclude: boolean) => void;
}) {
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="font-semibold">Themes</h3>
        <span className="text-xs text-slate-500">ranked by volume · sentiment via Elasticsearch aggregations</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {themes.map((t) => {
          const total = t.sentiment.positive + t.sentiment.negative + t.sentiment.mixed + t.sentiment.neutral || 1;
          const concentrated = t.top_thread_share >= 0.5 && t.doc_count > 1;
          const isExcluded = t.top_thread_id ? excluded.includes(t.top_thread_id) : false;
          return (
            <div key={t.key} className="animate-fadeUp rounded-xl border border-line bg-panel2 p-3">
              <div className="flex items-center gap-2">
                <span className="font-medium capitalize">{human(t.key)}</span>
                <span className="text-xs text-slate-500">{t.doc_count} · {t.thread_count} threads</span>
                {concentrated && (
                  <span className="ml-auto rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                    {Math.round(t.top_thread_share * 100)}% one thread
                  </span>
                )}
              </div>
              {/* sentiment bar */}
              <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-line">
                <Bar w={t.sentiment.negative / total} c="bg-rose-500" />
                <Bar w={t.sentiment.mixed / total} c="bg-amber-500" />
                <Bar w={t.sentiment.neutral / total} c="bg-slate-500" />
                <Bar w={t.sentiment.positive / total} c="bg-emerald-500" />
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-400">
                <span className="text-rose-400">▼ {t.sentiment.negative}</span>
                <span className="text-emerald-400">▲ {t.sentiment.positive}</span>
                {t.sentiment.mixed > 0 && <span className="text-amber-400">◆ {t.sentiment.mixed}</span>}
                {concentrated && t.top_thread_id && (
                  <button
                    onClick={() => onExclude(t.top_thread_id!, !isExcluded)}
                    className={`ml-auto rounded-md px-2 py-0.5 text-[11px] font-medium transition ${
                      isExcluded
                        ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                        : "bg-slate-700 text-slate-200 hover:bg-slate-600"
                    }`}
                  >
                    {isExcluded ? "↩ re-include thread" : "⊘ exclude top thread"}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Bar({ w, c }: { w: number; c: string }) {
  if (w <= 0) return null;
  return <div className={c} style={{ width: `${w * 100}%` }} />;
}
