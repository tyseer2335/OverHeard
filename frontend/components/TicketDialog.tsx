"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { TicketDraft } from "@/lib/types";

export default function TicketDialog({ draft, onDismiss }: { draft: TicketDraft; onDismiss: () => void }) {
  const [creating, setCreating] = useState(false);
  const [ticketId, setTicketId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function approve() {
    setCreating(true);
    setError(null);
    try {
      const t = await api.createTicket(draft);
      setTicketId(t.ticket_id);
    } catch (e: any) {
      setError(e?.message || "Failed to create ticket");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onDismiss}>
      <div
        className="card max-h-[85vh] w-full max-w-lg overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🎫</span>
          <h3 className="font-semibold">
            {ticketId ? "Investigation ticket created" : "Proposed investigation ticket"}
          </h3>
          <button onClick={onDismiss} className="ml-auto text-slate-500 hover:text-slate-300">
            ✕
          </button>
        </div>

        {ticketId ? (
          <div className="mt-4 rounded-xl bg-emerald-500/10 p-4 text-emerald-200">
            <div className="text-sm">Created</div>
            <div className="font-mono text-lg">{ticketId}</div>
            <div className="mt-1 text-sm text-slate-300">{draft.title}</div>
          </div>
        ) : (
          <>
            <h4 className="mt-4 text-base font-medium">{draft.title}</h4>
            <Field label="Issue" value={draft.issue} />
            <Field label="Uncertainty" value={draft.uncertainty} accent="amber" />
            <Field label="Suggested experiment" value={draft.suggested_experiment} accent="indigo" />

            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-panel2 p-3">
                <div className="text-lg font-semibold text-rose-300">{draft.evidence.length}</div>
                <div className="text-[11px] uppercase text-slate-500">evidence</div>
              </div>
              <div className="rounded-lg bg-panel2 p-3">
                <div className="text-lg font-semibold text-emerald-300">{draft.counterevidence.length}</div>
                <div className="text-[11px] uppercase text-slate-500">counterevidence</div>
              </div>
            </div>

            {draft.supporting_sources.length > 0 && (
              <div className="mt-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Sources</div>
                <div className="mt-1 space-y-1">
                  {draft.supporting_sources.slice(0, 5).map((s) => (
                    <a
                      key={s}
                      href={s}
                      target="_blank"
                      rel="noreferrer"
                      className="block truncate text-xs text-indigo-400 hover:text-indigo-300"
                    >
                      {s}
                    </a>
                  ))}
                </div>
              </div>
            )}

            {error && <div className="mt-3 text-sm text-rose-400">{error}</div>}

            <div className="mt-5 flex gap-2">
              <button
                onClick={approve}
                disabled={creating}
                className="flex-1 rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-400 disabled:opacity-50"
              >
                {creating ? "Creating…" : "Approve & create"}
              </button>
              <button
                onClick={onDismiss}
                className="rounded-xl bg-slate-700 px-4 py-2.5 text-sm font-medium hover:bg-slate-600"
              >
                Dismiss
              </button>
            </div>
            <p className="mt-2 text-center text-[11px] text-slate-500">
              Requires explicit approval — nothing is created until you click.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, accent }: { label: string; value: string; accent?: "amber" | "indigo" }) {
  const color = accent === "amber" ? "text-amber-300" : accent === "indigo" ? "text-indigo-300" : "text-slate-400";
  return (
    <div className="mt-3">
      <div className={`text-xs uppercase tracking-wide ${color}`}>{label}</div>
      <p className="mt-1 text-sm leading-relaxed text-slate-200">{value}</p>
    </div>
  );
}
