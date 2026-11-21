export type AuthMode = 'login' | 'register'

export type User = {
  id: string
  email: string
  is_active: boolean
  display_name?: string | null
  phone?: string | null
  gender?: string | null
  bio?: string | null
  avatar_url?: string | null
  created_at?: string
}

export type AuthResponse = {
  access_token: string
  refresh_token: string
  expires_in: number
  user: User
}

export type KnowledgeBase = {
  id: string
  name: string
  description?: string | null
  created_at?: string
}

export type IngestionTask = {
  id: string
  status: string
  progress: number
  error_message?: string | null
  celery_task_id?: string | null
  updated_at?: string
}

export type DocumentRecord = {
  id: string
  knowledge_base_id: string
  file_name: string
  mime_type?: string | null
  size_bytes: number
  status: string
  content_md5?: string | null
  duplicate?: boolean
  message?: string
  metadata?: Record<string, unknown>
  created_at?: string
  ingestion_task?: IngestionTask | null
}

export type DocumentListResponse = {
  items: DocumentRecord[]
  count: number
  limit: number
  offset: number
}

export type DocumentChunk = {
  id: string
  chunk_index: number
  page_number: number
  content: string
  source_type: string
  start_seconds: number
  end_seconds: number
  metadata?: Record<string, unknown>
}

export type DocumentChunksResponse = {
  document_id: string
  file_name: string
  count: number
  items: DocumentChunk[]
}

export type ApiError = {
  detail?: string
}


export type MCPServer = {
  id: string
  name: string
  transport: string
  command?: string | null
  args: string[]
  url?: string | null
  enabled: boolean
  allowed_tools: string[]
  timeout_seconds: number
  secret_reference?: string | null
}
