export type ReviewItem = {
  review_id: string
  note_id: string
  title: string
  content_preview: string
  review_count: number
  last_reviewed_at: string | null
  interval_days: number
}

export type ReviewQuestion = {
  question: string
  choices: string[]
  answer: string
}

export type TodayReviewsResponse = {
  reviews: ReviewItem[]
  total_count: number
}

export type ReviewDoneResponse = {
  success: boolean
  message: string
  review_count?: number
  interval_days?: number
  next_review_at?: string
}

export type ReviewStats = {
  total_notes: number
  tracked_notes: number
  reviewed_notes: number
  due_count: number
  total_review_count: number
  recent_reviewed_notes: number
  recent_review_count: number
  last_reviewed_at: string | null
  next_review_at: string | null
}

export type ReviewHistoryItem = {
  event_id: string
  note_id: string
  title: string
  review_count: number
  interval_days: number
  reviewed_at: string
}

export type ReviewHistoryResponse = {
  events: ReviewHistoryItem[]
  daily_counts: ReviewTrendItem[]
  days: number
  total_count: number
}

export type ReviewTrendItem = {
  date: string
  count: number
}
