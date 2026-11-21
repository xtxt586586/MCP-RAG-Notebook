import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'

import type {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
} from 'react'

import '../App.css'

import {
  apiRequest,
} from '../api/client'

import {
  agentChat,
  getEventText,
  knowledgeChat,
  streamAgentChat,
  streamKnowledgeChat,
} from '../api/chat'

import {
  createNote,
} from '../api/notes'

import {
  clearConversationMemory,
  getConversation,
  getConversationMemory,
  type ConversationMemory,
} from '../api/conversations'

import NotebookShell, {
  type NotebookView,
} from '../components/NotebookShell'
import { useLanguage } from '../i18n'

import type {
  CitationSource,
  ChatStreamEvent,
  AgentToolStep,
} from '../types/chat'

import type {
  DocumentRecord,
  KnowledgeBase,
} from '../types'

import type {
  ConversationMessage,
} from '../types/conversations'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type ChatPageProps = {
  email?: string
  conversationId?: string | null
  onConversationIdChange?: (conversationId: string | null) => void
  onBack?: () => void
  onLogout?: () => void
  onOpenSource?: (documentId: string, chunkIndex?: number) => void
  onNavigate?: (
    view: NotebookView,
  ) => void
}

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: CitationSource[]
  question?: string
  attachments?: string[]
  toolSteps?: AgentToolStep[]
  error?: boolean
  retryable?: boolean
}

type ChatAttachment = {
  id: string
  file: File
  previewUrl?: string
}

function createClientId() {
  const cryptoApi = globalThis.crypto

  if (typeof cryptoApi?.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }

  if (typeof cryptoApi?.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    cryptoApi.getRandomValues(bytes)
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80

    return Array.from(bytes, (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('').replace(
      /^(.{8})(.{4})(.{4})(.{4})(.{12})$/,
      '$1-$2-$3-$4-$5',
    )
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

const CHAT_FILE_ACCEPT = [
  '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
  '.png', '.jpg', '.jpeg', '.bmp', '.webp',
  '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.webm',
  '.mp4', '.mov', '.avi', '.mkv', '.m4v',
].join(',')

const CHAT_DRAFT_STORAGE_KEY = 'rag_notebook_chat_draft'

function getChatDraftStorageKey(email?: string) {
  return `${CHAT_DRAFT_STORAGE_KEY}:${email?.trim().toLowerCase() || 'anonymous'}`
}

function readChatDraft(storageKey: string) {
  try {
    return localStorage.getItem(storageKey) ?? ''
  } catch {
    return ''
  }
}

function writeChatDraft(storageKey: string, value: string) {
  try {
    if (value.trim()) {
      localStorage.setItem(storageKey, value)
    } else {
      localStorage.removeItem(storageKey)
    }
  } catch {
    // The composer remains usable when browser storage is unavailable.
  }
}

function attachmentKind(file: File) {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('audio/')) return 'audio'
  if (file.type.startsWith('video/')) return 'video'
  return 'document'
}

function sourceLabel(
  source: CitationSource,
) {
  return (
    source.file_name ||
    source.document_id ||
    '知识库来源'
  )
}

function uniqueSources(
  sources: CitationSource[],
) {
  const seen = new Set<string>()

  return sources.filter((source) => {
    const key = String(
      source.document_id ??
        source.file_name ??
        source.citation ??
        JSON.stringify(source),
    )

    if (seen.has(key)) {
      return false
    }

    seen.add(key)
    return true
  })
}

function toolStepKey(step: AgentToolStep) {
  return [
    step.server_name,
    step.tool_name,
    JSON.stringify(step.arguments ?? {}),
  ].join(':')
}

function formatElapsedTime(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function uniqueToolSteps(
  steps: AgentToolStep[],
) {
  const byKey = new Map<string, AgentToolStep>()

  for (const step of steps) {
    const key = toolStepKey(step)
    const previous = byKey.get(key)

    if (!previous) {
      byKey.set(key, step)
      continue
    }

    // A tool_start event can be followed by tool_result for the same call.
    // Merge them while keeping one visible row for an identical invocation.
    byKey.set(key, {
      ...previous,
      ...step,
      step: Math.min(previous.step, step.step),
      result_preview:
        step.result_preview || previous.result_preview,
      is_error: step.is_error || previous.is_error,
    })
  }

  return Array.from(byKey.values()).sort(
    (left, right) => left.step - right.step,
  )
}

function upsertToolStep(
  steps: AgentToolStep[],
  step: AgentToolStep,
) {
  return uniqueToolSteps([...steps, step])
}

function ChatPage({
  email,
  conversationId: requestedConversationId,
  onConversationIdChange,
  onLogout,
  onNavigate,
  onOpenSource,
}: ChatPageProps) {
  const { t } = useLanguage()
  const chatDraftOwner = email?.trim().toLowerCase() || 'anonymous'
  const chatDraftStorageKey = getChatDraftStorageKey(email)
  const chatDraftOwnerRef = useRef(chatDraftOwner)
  const [
    knowledgeBaseId,
    setKnowledgeBaseId,
  ] = useState('')

  const [question, setQuestion] = useState(() =>
    readChatDraft(chatDraftStorageKey),
  )

  const [attachments, setAttachments] =
    useState<ChatAttachment[]>([])

  const [messages, setMessages] =
    useState<ChatMessage[]>([])

  const [restoringConversation, setRestoringConversation] =
    useState(false)

  const [restoreErrorId, setRestoreErrorId] =
    useState<string | null>(null)

  const [conversationId, setConversationId] =
    useState<string | null>(requestedConversationId ?? null)

  const [streaming, setStreaming] =
    useState(true)

  const [knowledgeOnly, setKnowledgeOnly] = useState(false)

  const [loading, setLoading] =
    useState(false)

  const [elapsedSeconds, setElapsedSeconds] =
    useState(0)

  const [errorMessage, setErrorMessage] =
    useState('')

  const [statusMessage, setStatusMessage] =
    useState('')

  const [controller, setController] =
    useState<AbortController | null>(null)

  const [savingNoteId, setSavingNoteId] =
    useState<string | null>(null)

  const [savedNoteIds, setSavedNoteIds] =
    useState<Set<string>>(new Set())

  const [copiedMessageId, setCopiedMessageId] =
    useState<string | null>(null)

  const [memory, setMemory] =
    useState<ConversationMemory | null>(null)

  const [memoryOpen, setMemoryOpen] =
    useState(false)

  const [memoryLoading, setMemoryLoading] =
    useState(false)

  const [attachmentInputKey, setAttachmentInputKey] =
    useState(0)

  const formRef = useRef<HTMLFormElement | null>(null)
  const restoreRequestSequence = useRef(0)
  const createdConversationIds = useRef(new Set<string>())
  const messageListRef = useRef<HTMLElement | null>(null)
  const questionInputRef = useRef<HTMLTextAreaElement | null>(null)
  const copiedResetTimer = useRef<number | null>(null)
  const followLatestMessage = useRef(true)

  function updateConversationId(id: string | null) {
    if (id) {
      createdConversationIds.current.add(id)
    } else {
      createdConversationIds.current.clear()
    }
    setConversationId(id)
    onConversationIdChange?.(id)
  }

  useEffect(() => {
    const input = questionInputRef.current
    if (!input) return

    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`
  }, [question])

  useEffect(() => {
    if (chatDraftOwnerRef.current !== chatDraftOwner) {
      chatDraftOwnerRef.current = chatDraftOwner
      setQuestion(readChatDraft(chatDraftStorageKey))
      return
    }

    const timer = window.setTimeout(() => {
      writeChatDraft(chatDraftStorageKey, question)
    }, 400)

    return () => window.clearTimeout(timer)
  }, [chatDraftOwner, chatDraftStorageKey, question])

  useEffect(() => {
    if (!loading) return

    const interval = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1)
    }, 1000)
    return () => window.clearInterval(interval)
  }, [loading])

  useEffect(() => () => {
    if (copiedResetTimer.current !== null) {
      window.clearTimeout(copiedResetTimer.current)
    }
  }, [])

  useEffect(() => {
    const messageList = messageListRef.current
    if (messageList && followLatestMessage.current) {
      messageList.scrollTop = messageList.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setConversationId(requestedConversationId ?? null)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [requestedConversationId])

  const restoreConversation = useCallback(
    async (id: string) => {
      const requestId = ++restoreRequestSequence.current
      followLatestMessage.current = true
      setRestoringConversation(true)
      setMessages([])
      setMemory(null)
      setMemoryOpen(false)
      setRestoreErrorId(null)
      setErrorMessage('')
      setStatusMessage(t('chat.restoring'))
      try {
        const detail = await getConversation(id)
        if (requestId !== restoreRequestSequence.current) return

        let pendingQuestion: string | undefined
        setMessages(detail.messages.map((message: ConversationMessage) => {
          const isAssistant = message.role === 'assistant'
          if (!isAssistant) pendingQuestion = message.content
          const questionForMessage = isAssistant
            ? pendingQuestion
            : message.content
          if (isAssistant) pendingQuestion = undefined

          return {
            id: message.id,
            role: isAssistant ? 'assistant' : 'user',
            content: message.content,
            sources: uniqueSources(message.citations ?? []),
            question: questionForMessage,
            toolSteps: isAssistant &&
              Array.isArray(message.metadata?.tool_steps)
              ? uniqueToolSteps(
                message.metadata.tool_steps as unknown as AgentToolStep[],
              )
              : undefined,
            error: message.metadata?.status === 'FAILED',
            retryable: message.metadata?.retryable !== false,
          }
        }))
        setKnowledgeBaseId(detail.conversation.knowledge_base_id ?? '')
        setStatusMessage('已恢复会话')
      } catch (error) {
        if (requestId === restoreRequestSequence.current) {
          setErrorMessage(error instanceof Error ? error.message : '无法恢复会话')
          setRestoreErrorId(id)
          setStatusMessage(t('chat.restoreFailed'))
        }
      } finally {
        if (requestId === restoreRequestSequence.current) {
          setRestoringConversation(false)
        }
      }
    },
    [t],
  )

  useEffect(() => {
    if (
      requestedConversationId &&
      createdConversationIds.current.has(requestedConversationId)
    ) {
      return
    }

    if (!requestedConversationId) {
      const timer = window.setTimeout(() => {
        setMessages([])
        setRestoringConversation(false)
        setRestoreErrorId(null)
        setStatusMessage('')
      }, 0)
      return () => {
        window.clearTimeout(timer)
        restoreRequestSequence.current += 1
      }
    }
    const timer = window.setTimeout(() => void restoreConversation(requestedConversationId), 0)
    return () => {
      window.clearTimeout(timer)
      restoreRequestSequence.current += 1
    }
  }, [requestedConversationId, restoreConversation])

  const handleNavigate = useCallback(
    (view: NotebookView) => {
      onNavigate?.(view)
    },
    [onNavigate],
  )

  const handleLogout = useCallback(() => {
    onLogout?.()
  }, [onLogout])

  const loadKnowledgeBases = useCallback(
    async () => {
      try {
        const result =
          await apiRequest<KnowledgeBase>(
            '/api/v1/knowledge-bases/current',
          )

        if (result) {
          setKnowledgeBaseId(
            (current) =>
              current || result.id,
          )
        }
      } catch (error) {
        setErrorMessage(
          error instanceof Error
            ? error.message
            : '无法加载知识库',
        )
      }
    },
    [],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadKnowledgeBases()
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadKnowledgeBases])

  function appendMessage(
    message: ChatMessage,
  ) {
    setMessages((current) => [
      ...current,
      message,
    ])
  }

  function updateLastAssistant(
    updater: (
      message: ChatMessage,
    ) => ChatMessage,
  ) {
    setMessages((current) => {
      const next = [...current]

      for (
        let index = next.length - 1;
        index >= 0;
        index -= 1
      ) {
        if (
          next[index].role === 'assistant'
        ) {
          next[index] = updater(
            next[index],
          )
          break
        }
      }

      return next
    })
  }

  function handleStreamEvent(
    event: ChatStreamEvent,
  ) {
    if (
      event.type === 'conversation' &&
      typeof event.conversation_id === 'string'
    ) {
      updateConversationId(event.conversation_id)
      return
    }

    if (event.type === 'token') {
      updateLastAssistant((message) => ({
        ...message,
        content:
          message.content + getEventText(event),
      }))

      setStatusMessage('正在组织回答……')
      return
    }

    if (event.type === 'tool_start') {
      if (
        typeof event.tool_name === 'string' &&
        typeof event.server_name === 'string'
      ) {
        const step = event as unknown as AgentToolStep
        updateLastAssistant((message) => ({
          ...message,
          toolSteps: upsertToolStep(
            message.toolSteps ?? [],
            step,
          ),
        }))
      }
      setStatusMessage(
        `正在调用工具：${String(
          event.tool_name ??
            event.tool ??
            '外部工具',
        )}`,
      )
      return
    }

    if (event.type === 'tool_result') {
      if (
        typeof event.tool_name === 'string' &&
        typeof event.server_name === 'string'
      ) {
        const step = event as unknown as AgentToolStep
        updateLastAssistant((message) => ({
          ...message,
          toolSteps: upsertToolStep(
            message.toolSteps ?? [],
            step,
          ),
        }))
      }
      setStatusMessage('工具调用完成')
      return
    }

    if (
      event.type === 'sources' ||
      event.type === 'citation'
    ) {
      if (
        event.type === 'sources' &&
        Array.isArray(event.sources)
      ) {
        updateLastAssistant((message) => ({
          ...message,
          sources: uniqueSources(
            event.sources as CitationSource[],
          ),
        }))

        return
      }

      const source =
        (event.source ??
          event.citation) as
          | CitationSource
          | undefined

      if (source) {
        updateLastAssistant((message) => ({
          ...message,
          sources: [
            ...(message.sources ?? []),
            source,
          ],
        }))
      }

      return
    }

    if (event.type === 'error') {
      if (typeof event.conversation_id === 'string') {
        updateConversationId(event.conversation_id)
      }
      updateLastAssistant((message) => ({
        ...message,
        error: true,
        retryable: event.retryable !== false,
        toolSteps: Array.isArray(event.tool_steps)
          ? uniqueToolSteps(event.tool_steps as AgentToolStep[])
          : message.toolSteps,
      }))
      throw new Error(
        getEventText(event) ||
          '流式问答失败',
      )
    }

    if (event.type === 'done') {
      if (Array.isArray(event.tool_steps)) {
        updateLastAssistant((message) => ({
          ...message,
          toolSteps: uniqueToolSteps(
            event.tool_steps as AgentToolStep[],
          ),
        }))
      }
      if (Array.isArray(event.sources)) {
        updateLastAssistant((message) => ({
          ...message,
          sources: uniqueSources(
            event.sources as CitationSource[],
          ),
        }))
      }
      if (typeof event.conversation_id === 'string') {
        updateConversationId(event.conversation_id)
      }
      setStatusMessage('回答完成')
    }
  }

  // ✨ 新增键盘事件处理
  function handleQuestionKeyDown(
    event: KeyboardEvent<HTMLTextAreaElement>,
  ) {
    if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) {
      return
    }

    if (
      event.key === 'Enter' &&
      !event.shiftKey
    ) {
      event.preventDefault()

      if (!loading) {
        event.currentTarget.form?.requestSubmit()
      }
    }
  }

  function handleNewConversation() {
    if (loading) {
      return
    }

    restoreRequestSequence.current += 1
    followLatestMessage.current = true
    setMessages([])
    setRestoringConversation(false)
    setRestoreErrorId(null)
    setQuestion('')
    writeChatDraft(chatDraftStorageKey, '')
    attachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
    })
    setAttachments([])
    updateConversationId(null)
    setErrorMessage('')
    setStatusMessage('新对话已创建')
    setSavedNoteIds(new Set())
    setMemory(null)
    setMemoryOpen(false)
  }

  function handleAttachmentChange(
    event: ChangeEvent<HTMLInputElement>,
  ) {
    const files = Array.from(event.target.files ?? [])

    if (files.length === 0) return

    const remaining = Math.max(0, 5 - attachments.length)
    const next = files.slice(0, remaining).map((file) => ({
      id: createClientId(),
      file,
      previewUrl: file.type.startsWith('image/')
        ? URL.createObjectURL(file)
        : undefined,
    }))

    if (files.length > remaining) {
      setErrorMessage('最多同时添加 5 个附件')
    }

    setAttachments((current) => [...current, ...next])
    setAttachmentInputKey((current) => current + 1)
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const attachment = current.find((item) => item.id === id)
      if (attachment?.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
      return current.filter((item) => item.id !== id)
    })
  }

  async function uploadAttachments(
    currentAttachments: ChatAttachment[],
  ) {
    const uploaded: DocumentRecord[] = []

    for (const [index, attachment] of currentAttachments.entries()) {
      setStatusMessage(
        `正在上传附件 ${index + 1}/${currentAttachments.length}：${attachment.file.name}`,
      )

      const formData = new FormData()
      formData.append('knowledge_base_id', knowledgeBaseId)
      formData.append('file', attachment.file)

      uploaded.push(
        await apiRequest<DocumentRecord>('/api/v1/documents/upload', {
          method: 'POST',
          body: formData,
        }),
      )
    }

    return uploaded
  }

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    const value = question.trim()

    if (!value && attachments.length === 0) {
      setErrorMessage('请输入问题或添加附件')
      return
    }

    if (!knowledgeBaseId) {
      setErrorMessage('默认知识库尚未准备好，请稍后重试')
      return
    }

    const currentAttachments = [...attachments]
    followLatestMessage.current = true
    const attachmentNames = currentAttachments.map(
      (attachment) => attachment.file.name,
    )
    const displayQuestion = value || '请分析我刚上传的附件'

    currentAttachments.forEach((attachment) => {
      if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl)
    })
    setQuestion('')
    writeChatDraft(chatDraftStorageKey, '')
    setAttachments([])
    setErrorMessage('')
    setStatusMessage('正在思考……')
    setElapsedSeconds(0)
    setLoading(true)

    appendMessage({
      id: createClientId(),
      role: 'user',
      content: displayQuestion,
      attachments: attachmentNames,
    })

    appendMessage({
      id: createClientId(),
      role: 'assistant',
      content: '',
      sources: [],
      question: displayQuestion,
    })

    const nextController =
      new AbortController()

    setController(nextController)

    try {
      let uploadedDocuments: DocumentRecord[] = []

      if (currentAttachments.length > 0) {
        uploadedDocuments = await uploadAttachments(
          currentAttachments,
        )
      }

      {
        setStatusMessage(t(knowledgeOnly ? 'chat.searchingKnowledge' : 'chat.decidingKnowledge'))

        const attachmentContext = uploadedDocuments
          .map(
            (document) =>
              `文件名：${document.file_name}，文档 ID：${document.id}`,
          )
          .join('\n')

        const agentQuestion = attachmentContext
          ? `这些文件已经上传到当前知识库，请不要再次调用
ingest_resource 或 upload_resource：

${attachmentContext}

请根据这些资料回答：
${displayQuestion}`
          : displayQuestion

        const agentRequest = {
          knowledge_base_id: knowledgeBaseId,
          conversation_id: conversationId,
          question: agentQuestion,
        }

        if (streaming) {
          await (knowledgeOnly ? streamKnowledgeChat : streamAgentChat)(
            agentRequest,
            handleStreamEvent,
            nextController.signal,
          )
        } else {
          const response = await (knowledgeOnly ? knowledgeChat : agentChat)(agentRequest)

          updateLastAssistant((message) => ({
            ...message,
            content: response.answer,
            sources: uniqueSources(response.sources ?? []),
            toolSteps: uniqueToolSteps(response.tool_steps),
          }))
          updateConversationId(response.conversation_id)
          setStatusMessage('回答完成')
        }
      }
    } catch (error) {
      if (
        error instanceof DOMException &&
        error.name === 'AbortError'
      ) {
        setStatusMessage('已取消')
        updateLastAssistant((message) => ({
          ...message,
          content: message.content || '回答已停止，可点击重试重新生成。',
          error: true,
          retryable: true,
        }))
      } else {
        setStatusMessage('问答失败')
        setErrorMessage(
          error instanceof Error
            ? error.message
            : '问答失败',
        )

        updateLastAssistant((message) => ({
          ...message,
          content:
            message.content ||
            '本次问答失败，请稍后重试。',
          error: true,
          retryable: true,
        }))
      }
    } finally {
      setLoading(false)
      setController(null)
    }
  }

  async function handleViewMemory() {
    if (!conversationId) return

    if (memoryOpen) {
      setMemoryOpen(false)
      return
    }

    setMemoryLoading(true)
    try {
      setMemory(await getConversationMemory(conversationId))
      setMemoryOpen(true)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('chat.memoryLoadFailed'))
    } finally {
      setMemoryLoading(false)
    }
  }

  async function handleClearMemory() {
    if (!conversationId || loading) return
    if (!window.confirm(t('chat.memoryClearConfirm'))) return

    setMemoryLoading(true)
    try {
      await clearConversationMemory(conversationId)
      setMemory({
        conversation_id: conversationId,
        max_turns: memory?.max_turns ?? 0,
        history_turns: 0,
        messages: [],
        memory_summary: null,
        memory_reset_at: new Date().toISOString(),
      })
      setStatusMessage(t('chat.memoryCleared'))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('chat.memoryClearFailed'))
    } finally {
      setMemoryLoading(false)
    }
  }

  function handleRetry(message: ChatMessage) {
    if (
      loading ||
      !message.question ||
      !message.retryable
    ) {
      return
    }

    setErrorMessage('')
    setStatusMessage('正在重试……')
    setQuestion(message.question)
    window.setTimeout(() => {
      formRef.current?.requestSubmit()
    }, 0)
  }

  function handleCancel() {
    controller?.abort()
  }

  function getMessageSourceDocumentId(
    message: ChatMessage,
  ) {
    const documentId =
      message.sources?.find(
        (source) =>
          typeof source.document_id ===
          'string' &&
          source.document_id.length > 0,
      )?.document_id

    return documentId ?? null
  }

  async function handleCopyAnswer(message: ChatMessage) {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopiedMessageId(message.id)
      if (copiedResetTimer.current !== null) {
        window.clearTimeout(copiedResetTimer.current)
      }
      copiedResetTimer.current = window.setTimeout(() => {
        setCopiedMessageId((current) => current === message.id ? null : current)
        copiedResetTimer.current = null
      }, 1600)
    } catch {
      setErrorMessage(t('chat.copyFailed'))
    }
  }

  async function handleSaveAnswerAsNote(
    message: ChatMessage,
  ) {
    if (!knowledgeBaseId) {
      setErrorMessage('默认知识库尚未准备好，请稍后重试')
      return
    }

    if (!message.content.trim()) {
      setErrorMessage('当前回答没有可保存的内容')
      return
    }

    setSavingNoteId(message.id)
    setErrorMessage('')

    try {
      const sourceDocumentId =
        getMessageSourceDocumentId(message)

      const sourceFiles = Array.from(
        new Set(
          (message.sources ?? [])
            .map((source) => source.file_name)
            .filter(
              (fileName): fileName is string =>
                typeof fileName === 'string' &&
                fileName.length > 0,
            ),
        ),
      )

      const title =
        message.question?.slice(0, 80) ||
        'AI 问答记录'

      const note = await createNote({
        knowledge_base_id: knowledgeBaseId,
        title,
        content: message.content,
        source_document_id: sourceDocumentId,
        metadata: {
          category: 'study',
          tags: ['AI 对话', '知识库问答'],
          source_files: sourceFiles,
          saved_from: 'rag_chat',
        },
      })

      setSavedNoteIds((current) => {
        const next = new Set(current)
        next.add(message.id)
        return next
      })

      setStatusMessage(
        `已保存为笔记：${note.title}`,
      )
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '保存笔记失败',
      )
    } finally {
      setSavingNoteId(null)
    }
  }

  return (
    <NotebookShell
      activeView="chat"
      email={email}
      onNavigate={handleNavigate}
      onLogout={handleLogout}
    >
      <main className="chat-page">
        <header className="notebook-page-header chat-page-header">
          <div>
            <p className="eyebrow">{t('chat.eyebrow')}</p>
            <h1>{t('chat.title')}</h1>
          </div>

          <span className="chat-header-status">
            {statusMessage || t('chat.ready')}
            {loading && (
              <span className="chat-elapsed-time" aria-label={`${t('chat.elapsed')}: ${formatElapsedTime(elapsedSeconds)}`}>
                {' '}
                · {formatElapsedTime(elapsedSeconds)}
              </span>
            )}
          </span>

          <button
            className="secondary-button chat-new-conversation-button"
            type="button"
            onClick={handleNewConversation}
            disabled={loading}
          >
            {t('chat.new')}
          </button>

          {conversationId && (
            <div className="chat-memory-actions">
              <button
                className="text-button"
                type="button"
                onClick={() => void handleViewMemory()}
                disabled={loading || memoryLoading}
              >
                {memoryLoading ? t('chat.memoryLoading') : t('chat.memory')}
              </button>
              <button
                className="text-button danger-text"
                type="button"
                onClick={() => void handleClearMemory()}
                disabled={loading || memoryLoading}
              >
                {t('chat.clearMemory')}
              </button>
            </div>
          )}
        </header>

        {memoryOpen && memory && (
          <section className="chat-memory-panel" aria-live="polite">
            <div>
              <strong>{t('chat.memory')}</strong>
              <span>{memory.history_turns}/{memory.max_turns} {t('chat.memoryTurns')}</span>
            </div>
            {memory.messages.length === 0 ? (
              <p className="muted">{t('chat.memoryEmpty')}</p>
            ) : (
              <div className="chat-memory-list">
                {memory.messages.map((item) => (
                  <article key={item.id}>
                    <span>{item.role === 'user' ? t('chat.you') : 'AI'}</span>
                    <p>{item.content}</p>
                  </article>
                ))}
              </div>
            )}
            {memory.memory_summary && (
              <div className="chat-memory-summary">
                <strong>{t('chat.memorySummary')}</strong>
                <p>{memory.memory_summary}</p>
              </div>
            )}
          </section>
        )}

        {errorMessage && (
          <div className="message error-message">
            {errorMessage}
          </div>
        )}

        <section
          className="chat-message-list"
          ref={messageListRef}
          onScroll={(event) => {
            const element = event.currentTarget
            followLatestMessage.current =
              element.scrollHeight - element.scrollTop - element.clientHeight < 72
          }}
        >
          {messages.length === 0 ? (
            <div className="empty-state">
              <strong>
                {restoringConversation
                  ? t('chat.restoring')
                  : restoreErrorId
                    ? t('chat.restoreFailed')
                  : t('chat.emptyTitle')}
              </strong>

              <p>
                {restoringConversation
                  ? t('chat.restoringHint')
                  : restoreErrorId
                    ? t('chat.restoreFailedHint')
                  : t('chat.emptyHint')}
              </p>

              {restoreErrorId && !restoringConversation && (
                <button
                  className="secondary-button chat-restore-retry"
                  type="button"
                  onClick={() => void restoreConversation(restoreErrorId)}
                >
                  {t('chat.retryRestore')}
                </button>
              )}
            </div>
          ) : (
            messages.map((message) => (
              <article
                className={`chat-message ${message.role}`}
                key={message.id}
              >
                <div className="chat-message-role">
                  {message.role === 'user'
                    ? t('chat.you')
                    : 'AI'}
                </div>

                <div
                  className={`chat-message-content ${
                    loading &&
                    message.role === 'assistant' &&
                    !message.content
                      ? 'is-streaming'
                      : ''
                  }`}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content ||
                      (loading && message.role === 'assistant'
                        ? t('chat.thinking')
                        : '')}
                  </ReactMarkdown>

                  {message.attachments && message.attachments.length > 0 && (
                    <div className="chat-message-attachments">
                      {message.attachments.map((name) => (
                        <span key={name} className="chat-message-attachment">
                          <span aria-hidden="true">⌕</span>{name}
                        </span>
                      ))}
                    </div>
                  )}

                  {message.role === 'assistant' &&
                    message.toolSteps &&
                    message.toolSteps.length > 0 && (
                    <details className="chat-tool-steps">
                      <summary>{t('chat.toolsCalled')} {message.toolSteps.length} {t('chat.tools')}</summary>
                      <ul>
                        {uniqueToolSteps(message.toolSteps).map((step) => (
                          <li key={`${step.step}-${step.server_name}-${step.tool_name}`}>
                            <span className={step.is_error ? 'tool-step-failed' : 'tool-step-ok'}>
                              {step.is_error ? t('chat.failed') : t('chat.done')}
                            </span>
                            <span>{step.server_name} · {step.tool_name}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}

                  {message.role === 'assistant' &&
                    message.content.trim() && (
                      <div className="chat-message-actions">
                        <button
                          className="text-button"
                          type="button"
                          onClick={() => void handleCopyAnswer(message)}
                        >
                          {copiedMessageId === message.id
                            ? t('chat.copied')
                            : t('chat.copyAnswer')}
                        </button>
                        {message.error && message.retryable && (
                          <button
                            className="text-button"
                            type="button"
                            onClick={() => handleRetry(message)}
                            disabled={loading}
                          >
                            {t('chat.retry')}
                          </button>
                        )}
                        <button
                          className="text-button"
                          type="button"
                          onClick={() =>
                            void handleSaveAnswerAsNote(
                              message,
                            )
                          }
                          disabled={
                            savingNoteId ===
                              message.id ||
                            savedNoteIds.has(
                              message.id,
                            )
                          }
                        >
                          {savedNoteIds.has(
                            message.id,
                          )
                            ? t('chat.savedNote')
                            : savingNoteId ===
                              message.id
                              ? t('chat.savingNote')
                              : t('chat.saveNote')}
                        </button>
                      </div>
                    )}

                  {message.sources &&
                    message.sources.length > 0 && (
                      <div className="citation-panel">
                        <strong>
                          {t('chat.citations')}
                        </strong>

                        <ul>
                          {message.sources.map(
                            (source, index) => (
                              <li
                                key={`${sourceLabel(
                                  source,
                                )}-${index}`}
                              >
                                {source.document_id && onOpenSource ? (
                                  <button type="button" className="citation-source-link" onClick={() => onOpenSource(source.document_id!, source.chunk_index)}>
                                    {sourceLabel(source)}
                                  </button>
                                ) : <span>{sourceLabel(source)}</span>}

                                {source.page_number && (
                                  <span className="muted">
                                    {' '}
                                    · 第{' '}
                                    {source.page_number}
                                    页
                                  </span>
                                )}

                                {(source.excerpt || source.text ||
                                  source.content) && (
                                  <p className="muted">
                                    {String(
                                      source.excerpt ?? source.text ??
                                        source.content,
                                    )}
                                  </p>
                                )}
                              </li>
                            ),
                          )}
                        </ul>
                      </div>
                    )}
                </div>
              </article>
            ))
          )}
        </section>

        <form
          ref={formRef}
          className="chat-input-panel"
          onSubmit={handleSubmit}
        >
          <div className="chat-composer-options">
            <label className="chat-knowledge-only" title={t('chat.knowledgeOnlyHint')}>
              <input type="checkbox" checked={knowledgeOnly} disabled={loading}
                onChange={(event) => setKnowledgeOnly(event.target.checked)} />
              {t('chat.knowledgeOnly')}
            </label>
          </div>
          <div className="chat-composer-row">
            <label
              className="chat-attachment-button"
              title={t('chat.attachments')}
              aria-label={t('chat.addAttachment')}
            >
              <span aria-hidden="true">＋</span>
              <input
                key={attachmentInputKey}
                type="file"
                accept={CHAT_FILE_ACCEPT}
                multiple
                onChange={handleAttachmentChange}
                disabled={loading || attachments.length >= 5}
              />
            </label>

            <button
              className={`chat-stream-toggle-icon ${
                streaming ? 'is-enabled' : ''
              }`}
              type="button"
              onClick={() => setStreaming((current) => !current)}
              disabled={loading}
              aria-label={t('chat.stream')}
              title={t('chat.stream')}
            >
              <span aria-hidden="true">⌁</span>
            </button>

            <textarea
              ref={questionInputRef}
              value={question}
              onChange={(event) =>
                setQuestion(event.target.value)
              }
              onKeyDown={handleQuestionKeyDown}
              placeholder={t('chat.placeholder')}
              maxLength={2000}
              disabled={loading}
              rows={1}
            />

            <div className="chat-composer-context">
              <span className="chat-knowledge-context">
                {t('chat.currentKnowledge')} · {t(knowledgeOnly ? 'chat.knowledgeOnly' : 'chat.automaticRetrieval')}
              </span>
            </div>

            <div className="chat-input-actions">
              <span className="muted chat-question-count">
                {question.length}/2000
              </span>

              {loading ? (
                <button
                  className="chat-send-button chat-stop-button"
                  type="button"
                  onClick={handleCancel}
                  aria-label={t('chat.stop')}
                  title={t('chat.stop')}
                >
                  <span aria-hidden="true">■</span>
                </button>
              ) : (
                <button
                  className="chat-send-button"
                  type="submit"
                  disabled={
                    !knowledgeBaseId ||
                    (!question.trim() && attachments.length === 0)
                  }
                  aria-label={t('chat.send')}
                  title={t('chat.send')}
                >
                  <span aria-hidden="true">➤</span>
                </button>
              )}
            </div>
          </div>

          {attachments.length > 0 && (
            <div className="chat-attachment-strip" aria-label={t('chat.pendingAttachments')}>
              {attachments.map((attachment) => (
                <div className="chat-attachment-chip" key={attachment.id}>
                  {attachment.previewUrl ? (
                    <img src={attachment.previewUrl} alt="" />
                  ) : (
                    <span className={`chat-attachment-kind is-${attachmentKind(attachment.file)}`} aria-hidden="true">
                      {attachmentKind(attachment.file) === 'audio' ? '♪' : attachmentKind(attachment.file) === 'video' ? '▶' : '▧'}
                    </span>
                  )}
                  <span title={attachment.file.name}>{attachment.file.name}</span>
                  <button
                    type="button"
                    onClick={() => removeAttachment(attachment.id)}
                    aria-label={`${t('chat.removeAttachment')} ${attachment.file.name}`}
                    title={t('chat.removeAttachment')}
                  >×</button>
                </div>
              ))}
            </div>
          )}
        </form>
      </main>
    </NotebookShell>
  )
}

export default ChatPage
