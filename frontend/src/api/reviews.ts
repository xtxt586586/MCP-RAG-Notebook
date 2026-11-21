import { apiRequest } from './client'
import type {
  ReviewDoneResponse,
  ReviewHistoryResponse,
  ReviewQuestion,
  ReviewStats,
  TodayReviewsResponse,
} from '../types/reviews'

export function getReviewStats() {
  return apiRequest<ReviewStats>('/api/v1/reviews/stats')
}

export function getReviewHistory(days = 30) {
  return apiRequest<ReviewHistoryResponse>(
    `/api/v1/reviews/history?days=${days}&limit=100`,
  )
}

export function getTodayReviews() {
  return apiRequest<TodayReviewsResponse>(
    '/api/v1/reviews/today',
  )
}

export function getReviewQuestion(noteId: string) {
  return apiRequest<ReviewQuestion>(
    `/api/v1/reviews/question/${noteId}`,
  )
}

export function markReviewDone(noteId: string) {
  return apiRequest<ReviewDoneResponse>(
    `/api/v1/reviews/done/${noteId}`,
    {
      method: 'POST',
    },
  )
}
