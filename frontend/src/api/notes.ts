import {
  API_BASE_URL,
  apiRequest,
  getAccessToken,
  getCsrfToken,
  refreshAccessToken,
} from './client'

import type {
  NoteCreate,
  NoteTemplate,
  NoteResponse,
  NoteUpdate,
} from '../types/notes'

export type WritingAssistAction =
  | 'continue'
  | 'expand'
  | 'summarize'
  | 'polish'

export async function searchNotes(
  knowledgeBaseId: string,
  query?: string,
  limit = 20,
) {
  const params = new URLSearchParams({
    knowledge_base_id: knowledgeBaseId,
    limit: String(limit),
  })

  if (query?.trim()) {
    params.set('query', query.trim())
  }

  return apiRequest<unknown>(
    `/api/v1/notes?${params.toString()}`,
  )
}

export async function getNote(
  noteId: string,
) {
  return apiRequest<NoteResponse>(
    `/api/v1/notes/${noteId}`,
  )
}

export async function createNote(
  request: NoteCreate,
) {
  return apiRequest<NoteResponse>(
    '/api/v1/notes',
    {
      method: 'POST',
      body: JSON.stringify(request),
    },
  )
}

export async function updateNote(
  noteId: string,
  request: NoteUpdate,
) {
  return apiRequest<NoteResponse>(
    `/api/v1/notes/${noteId}`,
    {
      method: 'PUT',
      body: JSON.stringify(request),
    },
  )
}

export function retryNoteIndex(noteId: string) {
  return apiRequest<NoteResponse>(
    `/api/v1/notes/${noteId}/index`,
    { method: 'POST' },
  )
}

export async function deleteNote(
  noteId: string,
) {
  return apiRequest<void>(
    `/api/v1/notes/${noteId}`,
    {
      method: 'DELETE',
    },
  )
}

export function getNoteTemplates() {
  return apiRequest<NoteTemplate[]>('/api/v1/notes/templates')
}

export function createNoteTemplate(
  template: Omit<NoteTemplate, 'id' | 'created_at' | 'updated_at'>,
) {
  return apiRequest<NoteTemplate>('/api/v1/notes/templates', {
    method: 'POST',
    body: JSON.stringify(template),
  })
}

export function deleteNoteTemplate(templateId: string) {
  return apiRequest<void>(
    `/api/v1/notes/templates/${templateId}`,
    {
      method: 'DELETE',
    },
  )
}

export function updateNoteTemplate(
  templateId: string,
  template: Omit<NoteTemplate, 'id' | 'created_at' | 'updated_at'>,
) {
  return apiRequest<NoteTemplate>(
    `/api/v1/notes/templates/${templateId}`,
    {
      method: 'PUT',
      body: JSON.stringify(template),
    },
  )
}

export async function autocompleteNote(
  context: string,
) {
  return apiRequest<{ completion: string }>(
    '/api/v1/notes/autocomplete',
    {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ context }),
    },
  )
}

export async function* assistNoteStream(
  content: string,
  action: WritingAssistAction,
  signal?: AbortSignal,
): AsyncGenerator<string> {
  const makeRequest = (token: string | null) => fetch(
    `${API_BASE_URL}/api/v1/notes/assist/stream`,
    {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token
          ? { Authorization: `Bearer ${token}` }
          : {}),
        ...(getCsrfToken()
          ? { 'X-CSRF-Token': getCsrfToken() as string }
          : {}),
      },
      credentials: 'include',
      body: JSON.stringify({ content, action }),
    },
  )

  let response = await makeRequest(getAccessToken())
  if (response.status === 401 && await refreshAccessToken()) {
    response = await makeRequest(getAccessToken())
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as
      | { detail?: string }
      | null
    throw new Error(
      payload?.detail ?? `写作助手请求失败：HTTP ${response.status}`,
    )
  }

  if (!response.body) {
    throw new Error('写作助手没有返回流式内容')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })

      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data:')) {
          continue
        }

        const payload = line.slice(5).trim()
        if (payload === '[DONE]') {
          return
        }

        const event = JSON.parse(payload) as {
          content?: string
          error?: string
        }

        if (event.error) {
          throw new Error(event.error)
        }

        if (event.content) {
          yield event.content
        }
      }

      if (done) {
        break
      }
    }
  } finally {
    reader.releaseLock()
  }
}
