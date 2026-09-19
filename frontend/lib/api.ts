import type {
  ChallengeResult,
  ElevenLabsConfig,
  EvidencePacket,
  ResearchJob,
  Ticket,
  TicketDraft,
  VoicesResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  base: BASE,

  elevenLabsConfig: () => j<ElevenLabsConfig>("/api/elevenlabs/config"),

  mintToken: () =>
    j<{ token: string; agent_id: string; connection_type: string }>(
      "/api/elevenlabs/token",
      { method: "POST", body: "{}" }
    ),

  getVoices: () => j<VoicesResponse>("/api/elevenlabs/voices"),

  setVoice: (voice_id: string) =>
    j<{ ok: boolean; voice_id: string }>("/api/elevenlabs/voice", {
      method: "POST",
      body: JSON.stringify({ voice_id }),
    }),

  startResearch: (subject: string, sources: string[] = ["fixtures"]) =>
    j<{ research_id: string; status: string }>("/api/research", {
      method: "POST",
      body: JSON.stringify({ subject, sources }),
    }),

  latest: () => j<{ research_id: string | null }>("/api/research/latest"),

  getJob: (id: string) => j<ResearchJob>(`/api/research/${id}`),

  getEvidence: (id: string) => j<EvidencePacket>(`/api/research/${id}/evidence`),

  // returns null (204) when there is no challenge yet
  getChallenge: async (id: string): Promise<ChallengeResult | null> => {
    const res = await fetch(`${BASE}/api/research/${id}/challenge`, { cache: "no-store" });
    if (res.status === 204 || !res.ok) return null;
    return res.json();
  },

  challenge: (id: string, claim: string) =>
    j<ChallengeResult>(`/api/research/${id}/challenge`, {
      method: "POST",
      body: JSON.stringify({ claim }),
    }),

  exclude: (id: string, thread_id: string, exclude: boolean) =>
    j<EvidencePacket>(`/api/research/${id}/exclude`, {
      method: "POST",
      body: JSON.stringify({ thread_id, exclude }),
    }),

  getTicketDraft: async (id: string): Promise<TicketDraft | null> => {
    const res = await fetch(`${BASE}/api/actions/ticket/draft/${id}`, { cache: "no-store" });
    if (res.status === 204 || !res.ok) return null;
    return res.json();
  },

  draftTicket: (research_id: string, aspect?: string) =>
    j<TicketDraft>("/api/actions/ticket/draft", {
      method: "POST",
      body: JSON.stringify({ research_id, aspect }),
    }),

  createTicket: (draft: TicketDraft) =>
    j<Ticket>("/api/actions/ticket", {
      method: "POST",
      body: JSON.stringify(draft),
    }),
};
