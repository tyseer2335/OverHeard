export interface PublicConfig {
  supabase_url: string
  supabase_publishable_key: string
}

export interface Organization {
  id: string
  name: string
  created_by: string
  created_at: string
}

export interface Product {
  id: string
  organization_id: string
  name: string
  youtube_query: string
  active: boolean
  created_at: string
  updated_at: string
}

export interface MetricBucket { name: string; count: number }
export interface TimelineBucket { month: string; count: number; by_source: MetricBucket[] }

/**
 * Per-source figures. Shown beside every total on purpose: a Steam review feed
 * and a YouTube comment section carry different audience and ranking bias, so
 * a pooled number describes the source mix as much as the product.
 */
export interface SourceBreakdown {
  source: string
  count: number
  share: number
  complaints: number
  complaint_rate: number
  average_sentiment: number | null
  distinct_authors: number
  top_issues: MetricBucket[]
}

export interface Analytics {
  total: number
  complaints: number
  complaint_rate: number
  average_sentiment: number | null
  distinct_authors: number
  by_source: SourceBreakdown[]
  by_content_type: MetricBucket[]
  by_language: MetricBucket[]
  sentiment: MetricBucket[]
  issues: MetricBucket[]
  timeline: TimelineBucket[]
}

/** A normalized feedback row, identical in shape whatever source produced it. */
export interface ProductComment {
  external_id: string
  source: string
  content: string
  content_type: string
  url: string
  author_hash: string
  language: string
  published_at: string | null
  engagement: { score: number; replies: number; voted_up?: boolean | null; playtime_hours?: number | null }
  sentiment: 'positive' | 'neutral' | 'negative' | null
  sentiment_score: number | null
  is_complaint: boolean | null
  issue_categories: string[]
  relevant: boolean | null
  source_metadata: Record<string, unknown>
}

export interface SourceOutcome {
  source: string
  status: 'ok' | 'skipped' | 'failed'
  collected: number
  kept: number
  detail: string
}

export interface IngestResult {
  product: string
  depth: string
  documents_collected: number
  documents_indexed: number
  documents_rejected: number
  relevant: number
  sources: SourceOutcome[]
  reject_reasons: Record<string, number>
  plan_reasoning: string
  used_llm_planner: boolean
}
