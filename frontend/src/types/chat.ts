export interface CitationSource {
  citation?: string
  document_id?: string
  chunk_id?: string
  file_name?: string
  chunk_index?: number
  page_number?: number
  source_type?: 'document' | 'note'
  source_id?: string
  title?: string
  content?: string
  text?: string
  excerpt?: string
  score?: number
  [key: string]: unknown
}

export interface AgentToolStep {
  step: number
  server_name: string
  tool_name: string
  arguments: Record<string, unknown>
  is_error: boolean
  result_preview: string
}

export interface AgentChatResponse {
  conversation_id: string
  query: string
  answer: string
  tool_steps: AgentToolStep[]
  retrieval_mode?: string
  route_score?: number
  retrieval_query?: string
  sources?: CitationSource[]
  history_turns?: number
  max_steps_reached: boolean
}

export type ChatStreamEvent = {
  type:
    | 'token'
    | 'tool_start'
    | 'tool_result'
    | 'citation'
    | 'done'
    | 'error'
    | string
  [key: string]: unknown
}
