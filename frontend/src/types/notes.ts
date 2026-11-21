export interface NoteCreate {
  knowledge_base_id: string
  title: string
  content?: string
  source_document_id?: string | null
  metadata?: Record<string, unknown>
}

export interface NoteUpdate {
  title?: string
  content?: string
  source_document_id?: string | null
  metadata?: Record<string, unknown>
}

export interface NoteResponse {
  id: string
  user_id: string
  knowledge_base_id: string | null
  source_document_id: string | null
  title: string
  content: string
  vector_index_status: 'unknown' | 'pending' | 'indexing' | 'ready' | 'failed' | 'skipped'
  vector_index_error: string | null
  metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface NoteTemplate {
  id: string
  name: string
  title: string
  content: string
  category: string
  tags: string
  created_at?: string
  updated_at?: string
}
