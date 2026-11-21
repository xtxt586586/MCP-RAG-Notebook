import {
  API_BASE_URL,
  apiRequest,
  getAccessToken,
  getCsrfToken,
  refreshAccessToken,
} from './client'

import type {
  AgentChatResponse,
  ChatStreamEvent,
} from '../types/chat'

export interface AgentChatRequest {
  knowledge_base_id: string
  conversation_id?: string | null
  question: string
  require_sources?: boolean
}

export async function agentChat(
  request: AgentChatRequest,
) {
  return apiRequest<AgentChatResponse>(
    '/api/v1/agent/chat',
    {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify(request),
    },
  )
}

export async function knowledgeChat(request: AgentChatRequest) {
  const result = await apiRequest<Omit<AgentChatResponse, 'tool_steps' | 'max_steps_reached'>>('/api/v1/chat', {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify({ ...request, require_sources: true }),
  })
  return { ...result, tool_steps: [], max_steps_reached: false }
}

function getEventText(
  event: ChatStreamEvent,
) {
  const value =
    event.token ??
    event.text ??
    event.content ??
    event.message ??
    event.data

  return typeof value === 'string'
    ? value
    : ''
}

async function streamSse(
  path: string,
  request: AgentChatRequest,
  onEvent: (
    event: ChatStreamEvent,
  ) => void,
  signal?: AbortSignal,
) {
  const makeRequest = (token: string | null) => fetch(
    `${API_BASE_URL}${path}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(getCsrfToken()
          ? { 'X-CSRF-Token': getCsrfToken() as string }
          : {}),
      },
      credentials: 'include',
      body: JSON.stringify(request),
      signal,
    },
  )

  let response = await makeRequest(getAccessToken())
  if (response.status === 401 && await refreshAccessToken()) {
    response = await makeRequest(getAccessToken())
  }

  if (!response.ok) {
    const detail = await response.text()

    throw new Error(
      detail || `请求失败：HTTP ${response.status}`,
    )
  }

  if (!response.body) {
    throw new Error('服务器没有返回流式响应')
  }

  const reader =
    response.body.getReader()

  const decoder = new TextDecoder()
  let buffer = ''

  const emitFrame = (frame: string) => {
    const lines = frame.split(/\r?\n/)
    let eventName = 'message'
    const dataLines: string[] = []

    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line
          .slice(6)
          .trim()
      }

      if (line.startsWith('data:')) {
        dataLines.push(
          line.slice(5).trimStart(),
        )
      }
    }

    if (dataLines.length === 0) {
      return
    }

    const rawData = dataLines.join('\n')

    try {
      const parsed = JSON.parse(rawData)

      // The SSE event name is the transport-level contract. Agent final
      // payloads intentionally carry type="final", but the endpoint emits
      // them as event: done; preserve done so the caller can persist the
      // conversation id.
      const parsedType =
        typeof parsed === 'object' &&
        parsed !== null &&
        typeof parsed.type === 'string'
          ? parsed.type
          : undefined
      const eventType =
        eventName !== 'message'
          ? eventName
          : parsedType ?? 'token'

      onEvent({
        ...(typeof parsed === 'object' &&
        parsed !== null
          ? parsed
          : { data: parsed }),
        type: eventType,
      })
    } catch {
      onEvent({
        type:
          eventName === 'message'
            ? 'token'
            : eventName,
        data: rawData,
        text: rawData,
      })
    }
  }

  while (true) {
    const { value, done } =
      await reader.read()

    if (done) {
      break
    }

    buffer += decoder.decode(
      value,
      { stream: true },
    )

    const frames = buffer.split(
      /\r?\n\r?\n/,
    )

    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      emitFrame(frame)
    }
  }

  if (buffer.trim()) {
    emitFrame(buffer)
  }
}

export function streamAgentChat(
  request: AgentChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
) {
  return streamSse(
    '/api/v1/agent/chat/stream',
    request,
    onEvent,
    signal,
  )
}

export function streamKnowledgeChat(
  request: AgentChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
) {
  return streamSse('/api/v1/chat/stream', { ...request, require_sources: true }, onEvent, signal)
}

export { getEventText }
