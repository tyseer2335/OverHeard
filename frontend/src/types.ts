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
export interface TimelineBucket { month: string; count: number }
export interface VideoMetric { video_id: string; title: string; comment_count: number; average_sentiment: number | null }

export interface Analytics {
  product: string
  total_comments: number
  complaint_count: number
  complaint_rate: number
  average_sentiment: number | null
  average_likes: number | null
  sentiment: MetricBucket[]
  issues: MetricBucket[]
  timeline: TimelineBucket[]
  videos: VideoMetric[]
}

export interface ProductComment {
  id: string
  text: string
  author: string
  video_id: string
  video_title: string
  like_count: number
  published_at: string
  sentiment: 'positive' | 'neutral' | 'negative'
  sentiment_score: number
  is_complaint: boolean
  issue_categories: string[]
}

export interface IngestResult {
  product: string
  query: string
  videos_found: number
  videos_processed: number
  comments_indexed: number
  videos_skipped: Array<{ video_id: string; reason: string }>
}
