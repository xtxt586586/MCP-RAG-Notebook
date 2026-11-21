import { apiRequest } from './client'
import type {
  ConversationDetail,
  ConversationMessage,
  ConversationSummary,
} from '../types/conversations'

export type ConversationMemory = {
  conversation_id: string
  max_turns: number
  history_turns: number
  messages: ConversationMessage[]
  memory_summary: string | null
  memory_reset_at: string | null
}

export async function listConversations(options: {
  knowledgeBaseId?: string
  query?: string
  limit?: number
  includeArchived?: boolean
} = {}) {
  const params = new URLSearchParams()
  if (options.knowledgeBaseId) params.set('knowledge_base_id', options.knowledgeBaseId)
  if (options.query?.trim()) params.set('query', options.query.trim())
  if (options.limit) params.set('limit', String(options.limit))
  if (options.includeArchived) params.set('include_archived', 'true')
  const suffix = params.toString()
  return apiRequest<{ items: ConversationSummary[]; count: number }>(
    `/api/v1/conversations${suffix ? `?${suffix}` : ''}`,
  )
}

export function getConversation(conversationId: string) {
  return apiRequest<ConversationDetail>(`/api/v1/conversations/${conversationId}`)
}

export function deleteConversation(conversationId: string) {
  return apiRequest<void>(`/api/v1/conversations/${conversationId}`, { method: 'DELETE' })
}

export function updateConversation(
  conversationId: string,
  update: { title?: string; archived?: boolean },
) {
  return apiRequest<ConversationSummary>(
    `/api/v1/conversations/${conversationId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(update),
    },
  )
}

export function getConversationMemory(conversationId: string) {
  return apiRequest<ConversationMemory>(
    `/api/v1/conversations/${conversationId}/memory`,
  )
}

export function clearConversationMemory(conversationId: string) {
  return apiRequest<{ cleared_messages: number; memory_reset: boolean; memory_reset_at: string }>(
    `/api/v1/conversations/${conversationId}/memory`,
    { method: 'DELETE' },
  )
}
