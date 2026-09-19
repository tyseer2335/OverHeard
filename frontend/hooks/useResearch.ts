"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChallengeResult, EvidencePacket, ResearchJob, TicketDraft } from "@/lib/types";

const POLL_MS = 1500;

export function useResearch() {
  const [researchId, setResearchId] = useState<string | null>(null);
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [evidence, setEvidence] = useState<EvidencePacket | null>(null);
  const [challenge, setChallenge] = useState<ChallengeResult | null>(null);
  const [ticketDraft, setTicketDraft] = useState<TicketDraft | null>(null);
  const inFlight = useRef(false);
  const idRef = useRef<string | null>(null);
  idRef.current = researchId;

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      // follow whatever research the voice agent (or a manual start) kicked off
      try {
        const { research_id } = await api.latest();
        if (research_id && research_id !== idRef.current) {
          setResearchId(research_id);
          idRef.current = research_id;
        }
      } catch {
        /* backend not up yet */
      }
      const id = idRef.current;
      if (!id) return;

      const jobData = await api.getJob(id).catch(() => null);
      if (jobData) setJob(jobData);

      const terminal = jobData && ["READY", "PARTIAL", "FAILED"].includes(jobData.status);
      if (terminal && jobData!.status !== "FAILED") {
        const [ev, ch, dr] = await Promise.all([
          api.getEvidence(id).catch(() => null),
          api.getChallenge(id).catch(() => null),
          api.getTicketDraft(id).catch(() => null),
        ]);
        if (ev) setEvidence(ev);
        setChallenge(ch);
        setTicketDraft(dr);
      }
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  const focus = useCallback((id: string) => {
    setResearchId(id);
    idRef.current = id;
    setJob(null);
    setEvidence(null);
    setChallenge(null);
    setTicketDraft(null);
  }, []);

  return { researchId, job, evidence, challenge, ticketDraft, setChallenge, focus, refresh: poll };
}
