"use client";

import React, { useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { api } from "@/lib/api";
import type { ElevenLabsConfig, Voice } from "@/lib/types";

type Turn = { role: "user" | "ai"; text: string; id: number };
type OrbState = "idle" | "listening" | "speaking";

/* ------------------------------------------------------------------ presentational */
function Orb({ state }: { state: OrbState }) {
  const color =
    state === "speaking" ? "bg-indigo-500" : state === "listening" ? "bg-emerald-500" : "bg-slate-600";
  const label =
    state === "speaking" ? "speaking… (mic paused)" : state === "listening" ? "listening…" : "idle";
  return (
    <div className="my-6 flex flex-col items-center justify-center">
      <div className="relative flex h-28 w-28 items-center justify-center">
        {state !== "idle" && (
          <span className={`absolute h-24 w-24 rounded-full ${color} opacity-30 animate-pulseRing`} />
        )}
        <div
          className={`flex h-24 w-24 items-center justify-center rounded-full ${color} shadow-lg transition-all duration-300`}
          style={{ transform: state === "speaking" ? "scale(1.08)" : "scale(1)" }}
        >
          <MicIcon />
        </div>
      </div>
      <div className="mt-3 text-sm text-slate-400">{label}</div>
    </div>
  );
}

/* ------------------------------------------------------- error boundary (voice only) */
class VoiceErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err: unknown) {
    // eslint-disable-next-line no-console
    console.warn("Voice SDK error — falling back to manual mode:", err);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/* -------------------------------------------------- SDK-backed session (needs provider) */
function VoiceSession({
  addTurn,
  setError,
}: {
  addTurn: (role: "user" | "ai", text: string) => void;
  setError: (s: string | null) => void;
}) {
  const [connecting, setConnecting] = useState(false);
  const conversation = useConversation({
    onError: (e: unknown) => setError(typeof e === "string" ? e : (e as any)?.message || "voice error"),
    onMessage: (m: any) => {
      const text: string = m?.message ?? m?.text ?? "";
      const role: "user" | "ai" = m?.source === "user" ? "user" : "ai";
      if (text) addTurn(role, text);
    },
  });

  const status = conversation.status; // 'disconnected' | 'connecting' | 'connected'
  const connected = status === "connected";
  const speaking = conversation.isSpeaking;
  const orbState: OrbState = !connected ? "idle" : speaking ? "speaking" : "listening";

  // No barge-in: mute the mic while the agent speaks so the user's voice can't
  // interrupt it, then unmute the moment it finishes and starts listening.
  useEffect(() => {
    if (!connected) return;
    conversation.setMuted(speaking);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speaking, connected]);

  async function connect() {
    setError(null);
    setConnecting(true);
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const { token } = await api.mintToken();
      await conversation.startSession({ conversationToken: token, connectionType: "webrtc" });
    } catch (e: any) {
      setError(e?.message || "Failed to start voice session");
    } finally {
      setConnecting(false);
    }
  }

  async function disconnect() {
    try {
      await conversation.endSession();
    } catch {
      /* noop */
    }
  }

  // ---- voice selection ----
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceId, setVoiceId] = useState("");
  const [savingVoice, setSavingVoice] = useState(false);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);

  useEffect(() => {
    api
      .getVoices()
      .then((r) => {
        setVoices(r.voices);
        if (r.current_voice_id) setVoiceId(r.current_voice_id);
      })
      .catch(() => {});
  }, []);

  async function changeVoice(id: string) {
    setVoiceId(id);
    setSavingVoice(true);
    setVoiceNote(null);
    try {
      await api.setVoice(id);
      if (connected) {
        await conversation.endSession();
        setVoiceNote("Voice updated — press Start to hear it.");
      } else {
        setVoiceNote("Voice updated.");
      }
    } catch (e: any) {
      setError(e?.message || "Failed to change voice");
    } finally {
      setSavingVoice(false);
    }
  }

  return (
    <>
      <Orb state={orbState} />

      {voices.length > 0 && (
        <div className="mb-2">
          <label className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Voice</label>
          <div className="flex items-center gap-2">
            <select
              value={voiceId}
              disabled={savingVoice}
              onChange={(e) => changeVoice(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-3 py-2 text-sm outline-none focus:border-indigo-400 disabled:opacity-50"
            >
              {voices.map((v) => (
                <option key={v.voice_id} value={v.voice_id}>
                  {v.name}
                  {v.labels?.accent ? ` · ${v.labels.accent}` : ""}
                </option>
              ))}
            </select>
            {savingVoice && <span className="text-[11px] text-slate-500">saving…</span>}
          </div>
          {voiceNote && <div className="mt-1 text-[11px] text-emerald-300">{voiceNote}</div>}
        </div>
      )}

      <button
        onClick={connected ? disconnect : connect}
        disabled={connecting}
        className={`w-full rounded-xl px-4 py-2.5 text-sm font-medium transition ${
          connected ? "bg-rose-500/90 hover:bg-rose-500 text-white" : "bg-indigo-500 hover:bg-indigo-400 text-white"
        } disabled:opacity-50`}
      >
        {connecting ? "Connecting…" : connected ? "End conversation" : "Start voice conversation"}
      </button>
    </>
  );
}

/* -------------------------------------------- fallback (no key / SDK failed / loading) */
function VoiceFallback({ failed }: { failed?: boolean }) {
  return (
    <>
      <Orb state="idle" />
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
        {failed ? (
          <>Voice couldn’t start — continuing in manual mode. Use the box below.</>
        ) : (
          <>
            Voice is off (no ElevenLabs key). Use the box below, or set{" "}
            <code className="text-amber-100">ELEVENLABS_API_KEY</code> +{" "}
            <code className="text-amber-100">ELEVENLABS_AGENT_ID</code> and run the setup script.
          </>
        )}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ panel (no SDK deps) */
export default function VoicePanel({ onFocus }: { onFocus?: (id: string) => void }) {
  const [config, setConfig] = useState<ElevenLabsConfig | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [subject, setSubject] = useState("Notion");
  const seq = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);

  const addTurn = (role: "user" | "ai", text: string) =>
    setTurns((t) => [...t, { role, text, id: seq.current++ }]);

  useEffect(() => {
    api
      .elevenLabsConfig()
      .then(setConfig)
      .catch(() => setConfig({ configured: false, agent_id: null, connection_type: "webrtc" }));
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  async function manualStart() {
    if (!subject.trim()) return;
    try {
      const { research_id } = await api.startResearch(subject.trim());
      onFocus?.(research_id);
      addTurn("user", `Research ${subject}`);
      addTurn("ai", `Starting research on ${subject}…`);
    } catch (e: any) {
      setError(e?.message || "Failed to start research");
    }
  }

  return (
    <div className="card flex h-full flex-col p-5">
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold tracking-tight">Vox</span>
        <span className="text-xs text-slate-400">market-research analyst</span>
        <span
          className={`ml-auto rounded-full px-2 py-0.5 text-[11px] ${
            config?.configured ? "bg-indigo-500/15 text-indigo-300" : "bg-slate-600/20 text-slate-400"
          }`}
        >
          {config == null ? "…" : config.configured ? "voice ready" : "manual"}
        </span>
      </div>

      {/* Voice control area — SDK only mounts when actually configured */}
      {config?.configured ? (
        <VoiceErrorBoundary fallback={<VoiceFallback failed />}>
          <ConversationProvider>
            <VoiceSession addTurn={addTurn} setError={setError} />
          </ConversationProvider>
        </VoiceErrorBoundary>
      ) : (
        <VoiceFallback />
      )}

      {/* Manual starter (always available so the demo never depends on a key) */}
      <div className="mt-3 flex gap-2">
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && manualStart()}
          placeholder="Subject e.g. Notion"
          className="min-w-0 flex-1 rounded-lg border border-line bg-panel2 px-3 py-2 text-sm outline-none focus:border-indigo-400"
        />
        <button
          onClick={manualStart}
          className="rounded-lg bg-slate-700 px-3 py-2 text-sm font-medium hover:bg-slate-600"
        >
          Research
        </button>
      </div>

      {error && <div className="mt-2 text-xs text-rose-400">{error}</div>}

      {/* Transcript */}
      <div className="mt-4 text-xs uppercase tracking-wide text-slate-500">Transcript</div>
      <div ref={scroller} className="mt-2 flex-1 space-y-2 overflow-y-auto pr-1">
        {turns.length === 0 && (
          <p className="text-sm text-slate-500">
            {config?.configured
              ? "Say: “Research what people are saying about Notion lately — what do they dislike?”"
              : "Type a subject above and hit Research to see the pipeline run."}
          </p>
        )}
        {turns.map((t) => (
          <div
            key={t.id}
            className={`animate-fadeUp rounded-lg px-3 py-2 text-sm ${
              t.role === "user" ? "ml-6 bg-indigo-500/15 text-indigo-100" : "mr-6 bg-panel2 text-slate-200"
            }`}
          >
            <span className="mr-1 text-[10px] uppercase text-slate-500">{t.role === "user" ? "you" : "vox"}</span>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
    </svg>
  );
}
