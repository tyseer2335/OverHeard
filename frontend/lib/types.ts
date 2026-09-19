// Mirrors the backend Pydantic schemas (app/models.py).

export type Sentiment = "positive" | "negative" | "mixed" | "neutral";

export interface SentimentBreakdown {
  positive: number;
  negative: number;
  mixed: number;
  neutral: number;
}

export interface Theme {
  key: string;
  doc_count: number;
  sentiment: SentimentBreakdown;
  net_sentiment: number;
  thread_count: number;
  top_thread_id: string | null;
  top_thread_share: number;
}

export interface EvidenceItem {
  doc_id: string;
  source: string;
  thread_id: string;
  thread_title: string;
  url: string;
  author: string;
  created_at: string | null;
  snippet: string;
  overall_sentiment: Sentiment;
  kind: string;
  aspects: string[];
  score: number;
}

export interface Counts {
  total: number;
  by_sentiment: SentimentBreakdown;
  by_kind: Record<string, number>;
  thread_count: number;
}

export interface EvidencePacket {
  research_id: string;
  evidence_version: number;
  subject: string;
  question: string;
  status: string;
  generated_at: string;
  headline: string;
  themes: Theme[];
  top_negative: EvidenceItem[];
  top_positive: EvidenceItem[];
  counts: Counts;
  sources: string[];
  caveats: string[];
  excluded_thread_ids: string[];
}

export interface StepLog {
  status: string;
  at: string;
  detail: string;
}

export interface ResearchJob {
  research_id: string;
  status: string;
  subject: string;
  question: string;
  sources_requested: string[];
  sources_completed: string[];
  sources_failed: string[];
  document_count: number;
  thread_count: number;
  evidence_version: number;
  excluded_thread_ids: string[];
  headline: string;
  error: string | null;
  progress: StepLog[];
  browser_live_view_url: string | null;
}

export interface ThreadConcentration {
  aspect: string | null;
  total_docs: number;
  thread_count: number;
  top_thread_id: string | null;
  top_thread_title: string;
  top_thread_docs: number;
  top_thread_share: number;
  verdict: string;
}

export interface ChallengeResult {
  research_id: string;
  claim: string;
  assessment: string;
  concentration: ThreadConcentration;
  counterevidence: EvidenceItem[];
  supporting: EvidenceItem[];
  revised_themes: Theme[];
}

export interface TicketDraft {
  research_id: string;
  title: string;
  issue: string;
  evidence: EvidenceItem[];
  supporting_sources: string[];
  counterevidence: EvidenceItem[];
  uncertainty: string;
  suggested_experiment: string;
}

export interface Ticket extends TicketDraft {
  ticket_id: string;
  status: string;
  created_at: string;
  created_by: string;
  approved: boolean;
}

export interface ElevenLabsConfig {
  configured: boolean;
  agent_id: string | null;
  connection_type: string;
}

export interface Voice {
  voice_id: string;
  name: string;
  labels: Record<string, string>;
}

export interface VoicesResponse {
  voices: Voice[];
  current_voice_id: string | null;
}
