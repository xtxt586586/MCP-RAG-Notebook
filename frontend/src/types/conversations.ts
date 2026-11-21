import type { CitationSource } from './chat'

export interface ConversationSummary {
  id: string
  knowledge_base_id: string | null
  title: string
  model_name: string | null
  created_at: string
  updated_at: string
  message_count: number
  archived_at: string | null
}

export interface ConversationMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | string
  content: string
  citations: CitationSource[]
  metadata: Record<string, unknown>
  created_at: string
}

export interface ConversationDetail {
  conversation: ConversationSummary
  messages: ConversationMessage[]
}
