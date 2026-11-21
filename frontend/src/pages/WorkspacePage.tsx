import {
  useCallback,
  useEffect,
  lazy,
  useRef,
  Suspense,
  useState,
} from 'react'

import type {
  FormEvent,
} from 'react'

import '../App.css'

import {
  API_BASE_URL,
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  apiRequest,
} from '../api/client'

import type {
  AuthMode,
  AuthResponse,
  DocumentChunk,
  DocumentChunksResponse,
  DocumentListResponse,
  DocumentRecord,
  KnowledgeBase,
  User,
} from '../types'

const ChatPage = lazy(() => import('./ChatPage'))
const NotesPage = lazy(() => import('./NotesPage'))
const MCPServersPage = lazy(() => import('./MCPServersPage'))
const SessionsPage = lazy(() => import('./SessionsPage'))
const DailyReviewPage = lazy(() => import('./DailyReviewPage'))
const ProfilePage = lazy(() => import('./ProfilePage'))
const SettingsPage = lazy(() => import('./SettingsPage'))
const AboutPage = lazy(() => import('./AboutPage'))
const KnowledgeGraphPage = lazy(() => import('./KnowledgeGraphPage'))
import { useLanguage } from '../i18n'

import NotebookShell, {
  type NotebookView,
} from '../components/NotebookShell'

const TERMINAL_STATUSES = new Set([
  'READY',
  'PARSE_FAILED',
  'EMBEDDING_FAILED',
  'INDEXING_FAILED',
  'UPLOAD_FAILED',
  'FAILED',
])
const DOCUMENT_POLL_MAX_ATTEMPTS = 180
const DOCUMENT_POLL_INTERVAL_MS = 2000

const PAGE_LOADING = (
  <div className="page-loading" role="status" aria-live="polite">
    页面加载中…
  </div>
)

const SUPPORTED_FILE_ACCEPT = [
  '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
  '.png', '.jpg', '.jpeg', '.bmp', '.webp',
  '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.webm',
  '.mp4', '.mov', '.avi', '.mkv', '.m4v',
].join(',')

const SUPPORTED_FORMATS_LABEL =
  'PDF、TXT、Markdown、DOCX、PPTX、XLSX、PNG、JPG、JPEG、BMP、WEBP、MP3、WAV、M4A、AAC、FLAC、OGG、WEBM、MP4、MOV、AVI、MKV、M4V'

function getFileIcon(fileName: string) {
  const extension = fileName.slice(fileName.lastIndexOf('.')).toLowerCase()

  if (extension === '.pdf') return { label: 'PDF', tone: 'pdf' }
  if (extension === '.docx') return { label: 'DOC', tone: 'doc' }
  if (extension === '.pptx') return { label: 'PPT', tone: 'ppt' }
  if (extension === '.xlsx') return { label: 'XLS', tone: 'xls' }
  if (extension === '.md') return { label: 'MD', tone: 'md' }
  if (extension === '.txt') return { label: 'TXT', tone: 'txt' }
  if (['.png', '.jpg', '.jpeg', '.bmp', '.webp'].includes(extension)) {
    return { label: 'IMG', tone: 'image' }
  }
  if (['.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.webm'].includes(extension)) {
    return { label: 'AUD', tone: 'audio' }
  }
  if (['.mp4', '.mov', '.avi', '.mkv', '.m4v'].includes(extension)) {
    return { label: 'VID', tone: 'video' }
  }

  return { label: 'FILE', tone: 'file' }
}

function getStatusLabel(status: string, translate: (key: string) => string) {
  return translate(`workspace.status.${status}`) || status
}

function getProgress(document: DocumentRecord) {
  if (document.status === 'READY') {
    return 100
  }

  return Math.max(
    0,
    Math.min(
      100,
      document.ingestion_task?.progress ?? 0,
    ),
  )
}

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`
  }

  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`
  }

  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value: string | undefined, language: 'zh-CN' | 'en-US', translate: (key: string) => string) {
  if (!value) {
    return translate('workspace.justNow')
  }

  return new Date(value).toLocaleString(
    language,
    {
      dateStyle: 'short',
      timeStyle: 'short',
    },
  )
}

function WorkspacePage() {
  const { language, t } = useLanguage()
  const [token, setToken] = useState(
    () =>
      localStorage.getItem(
        ACCESS_TOKEN_KEY,
      ),
  )
  const [authReady, setAuthReady] = useState(
    () => Boolean(localStorage.getItem(ACCESS_TOKEN_KEY)),
  )

  // ✨ activeView 类型增加 'review'
  const initialUrl = new URL(window.location.href)
  const initialView = initialUrl.searchParams.get('view')
  const validViews = new Set([
    'welcome', 'workspace', 'chat', 'notes', 'sessions', 'review',
    'mcp', 'profile', 'settings', 'about', 'graph',
  ])
  const [
    activeView,
    setActiveView,
  ] = useState<
    'welcome' | 'workspace' | 'chat' | 'notes' | 'sessions' | 'review' | 'mcp' | 'profile' | 'settings' | 'about' | 'graph'
  >(() => initialUrl.searchParams.get('conversation_id')
    ? 'chat'
    : initialView && validViews.has(initialView)
      ? initialView as 'welcome' | 'workspace' | 'chat' | 'notes' | 'sessions' | 'review' | 'mcp' | 'profile' | 'settings' | 'about' | 'graph'
      : 'welcome')

  const [conversationId, setConversationId] = useState<string | null>(
    () => initialUrl.searchParams.get('conversation_id'),
  )

  useEffect(() => {
    const url = new URL(window.location.href)
    if (activeView === 'chat' && conversationId) {
      url.searchParams.set('conversation_id', conversationId)
    } else {
      url.searchParams.delete('conversation_id')
    }
    if (activeView === 'welcome') {
      url.searchParams.delete('view')
    } else {
      url.searchParams.set('view', activeView)
    }
    window.history.replaceState(window.history.state, '', url)
  }, [activeView, conversationId])

  const [user, setUser] =
    useState<User | null>(null)

  const [authMode, setAuthMode] =
    useState<AuthMode>('login')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [
    selectedKnowledgeBaseId,
    setSelectedKnowledgeBaseId,
  ] = useState('')

  const [documents, setDocuments] =
    useState<DocumentRecord[]>([])

  const activeDocumentPolls = useRef(new Map<string, { cancelled: boolean }>())
  const documentListRequestId = useRef(0)
  const documentDetailRequestId = useRef(0)
  const [pausedDocumentPollIds, setPausedDocumentPollIds] = useState<Set<string>>(
    () => new Set(),
  )

  const [selectedFiles, setSelectedFiles] = useState<File[]>([])

  const [uploadProgress, setUploadProgress] = useState('')

  const [busy, setBusy] = useState(false)

  const [retryingDocumentId, setRetryingDocumentId] = useState<string | null>(null)

  const [errorMessage, setErrorMessage] =
    useState('')

  const [successMessage, setSuccessMessage] =
    useState('')

  const [selectedDocument, setSelectedDocument] =
    useState<DocumentRecord | null>(null)

  const documentDetailTriggerRef = useRef<HTMLButtonElement | null>(null)
  const documentDetailCloseButtonRef = useRef<HTMLButtonElement | null>(null)

  const [documentContent, setDocumentContent] =
    useState('')

  const [documentChunks, setDocumentChunks] =
    useState<DocumentChunk[]>([])

  const [sourceChunkIndex, setSourceChunkIndex] = useState<number | null>(null)

  const [documentDetailTab, setDocumentDetailTab] =
    useState<'detail' | 'chunks'>('detail')

  const [documentDetailLoading, setDocumentDetailLoading] =
    useState(false)

  const closeDocumentDetail = useCallback(() => {
    documentDetailRequestId.current += 1
    setSelectedDocument(null)
    setDocumentDetailLoading(false)
    const trigger = documentDetailTriggerRef.current
    window.requestAnimationFrame(() => trigger?.focus())
  }, [])

  useEffect(() => {
    if (!successMessage) {
      return
    }

    const timer = window.setTimeout(() => {
      setSuccessMessage('')
    }, 3600)

    return () => window.clearTimeout(timer)
  }, [successMessage])

  useEffect(() => {
    if (!selectedDocument) return

    const focusFrame = window.requestAnimationFrame(() => {
      documentDetailCloseButtonRef.current?.focus()
    })

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        closeDocumentDetail()
        return
      }

      if (event.key !== 'Tab') return

      const dialog = document.querySelector<HTMLElement>(
        '.document-detail-backdrop [role="dialog"]',
      )
      if (!dialog) return

      const focusableElements = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getClientRects().length > 0)
      if (focusableElements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]
      const activeElement = document.activeElement

      if (event.shiftKey && (activeElement === firstElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && (activeElement === lastElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [closeDocumentDetail, selectedDocument])

  // ✨ 修改导航函数，支持 'review'
  const handleNotebookNavigate = useCallback(
    (view: NotebookView) => {
      if (
      view === 'notes' ||
        view === 'welcome' ||
        view === 'chat' ||
        view === 'sessions' ||
        view === 'review' ||
        view === 'graph' ||
        view === 'mcp' ||
        view === 'profile' ||
        view === 'settings' ||
        view === 'about'
      ) {
        setActiveView(view)
        return
      }

      setActiveView('workspace')
    },
    [],
  )

  const handleApiError = useCallback(
    (error: unknown) => {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : '请求失败，请检查后端服务',
      )
    },
    [],
  )

  const pollDocument = useCallback(
    async (documentId: string, resume = false) => {
      if (activeDocumentPolls.current.has(documentId)) return

      if (resume) {
        setErrorMessage('')
        setPausedDocumentPollIds((current) => {
          const next = new Set(current)
          next.delete(documentId)
          return next
        })
      }

      const poll = { cancelled: false }
      activeDocumentPolls.current.set(documentId, poll)

      try {
        for (let attempt = 0; attempt < DOCUMENT_POLL_MAX_ATTEMPTS; attempt += 1) {
          if (poll.cancelled) return

          try {
            const detail = await apiRequest<DocumentRecord>(
              `/api/v1/documents/${documentId}`,
            )

            if (poll.cancelled) return

            setDocuments((current) =>
              current.map((document) => document.id === documentId ? detail : document),
            )
            setSelectedDocument((current) =>
              current?.id === documentId ? { ...current, ...detail } : current,
            )

            if (TERMINAL_STATUSES.has(detail.status)) {
              setPausedDocumentPollIds((current) => {
                if (!current.has(documentId)) return current
                const next = new Set(current)
                next.delete(documentId)
                return next
              })
              return
            }
          } catch (error) {
            if (!poll.cancelled) {
              setPausedDocumentPollIds((current) => new Set(current).add(documentId))
              handleApiError(error)
            }
            return
          }

          await new Promise((resolve) =>
            window.setTimeout(resolve, DOCUMENT_POLL_INTERVAL_MS),
          )
        }

        if (!poll.cancelled) {
          setPausedDocumentPollIds((current) => new Set(current).add(documentId))
        }
      } finally {
        if (activeDocumentPolls.current.get(documentId) === poll) {
          activeDocumentPolls.current.delete(documentId)
        }
      }
    },
    [handleApiError],
  )

  useEffect(() => () => {
    for (const poll of activeDocumentPolls.current.values()) {
      poll.cancelled = true
    }
    activeDocumentPolls.current.clear()
  }, [])

  const loadDocuments = useCallback(
    async (knowledgeBaseId: string) => {
      const requestId = ++documentListRequestId.current
      if (!knowledgeBaseId) {
        setDocuments([])
        return
      }

      try {
        const response =
          await apiRequest<DocumentListResponse>(
            `/api/v1/documents?knowledge_base_id=${encodeURIComponent(
              knowledgeBaseId,
            )}`,
          )

        if (requestId !== documentListRequestId.current) return

        setDocuments(response.items)

        const terminalDocumentIds = new Set(
          response.items
            .filter((document) => TERMINAL_STATUSES.has(document.status))
            .map((document) => document.id),
        )
        if (terminalDocumentIds.size > 0) {
          setPausedDocumentPollIds((current) => {
            const next = new Set(current)
            for (const documentId of terminalDocumentIds) next.delete(documentId)
            return next
          })
        }

        for (const document of response.items) {
          if (
            !TERMINAL_STATUSES.has(
              document.status,
            ) && !pausedDocumentPollIds.has(document.id)
          ) {
            void pollDocument(document.id)
          }
        }
      } catch (error) {
        if (requestId !== documentListRequestId.current) return
        if (!localStorage.getItem(ACCESS_TOKEN_KEY)) {
          setToken(null)
          setUser(null)
        }
        handleApiError(error)
      }
    },
    [handleApiError, pausedDocumentPollIds, pollDocument],
  )

  const loadWorkspace = useCallback(
    async () => {
      setErrorMessage('')

      try {
        const [
          userData,
          knowledgeBaseData,
        ] = await Promise.all([
          apiRequest<User>(
            '/api/v1/auth/me',
          ),
          apiRequest<KnowledgeBase>(
            '/api/v1/knowledge-bases/current',
          ),
        ])

        setUser(userData)

        if (knowledgeBaseData) {
          setSelectedKnowledgeBaseId(
            (current) =>
              current || knowledgeBaseData.id,
          )
        } else {
          setSelectedKnowledgeBaseId('')
          setDocuments([])
        }
      } catch (error) {
        if (!localStorage.getItem(ACCESS_TOKEN_KEY)) {
          setToken(null)
          setUser(null)
        }
        handleApiError(error)
      }
    },
    [handleApiError],
  )

  useEffect(() => {
    if (localStorage.getItem(ACCESS_TOKEN_KEY)) {
      return
    }

    let cancelled = false

    void apiRequest<User>('/api/v1/auth/me')
      .then((userData) => {
        if (cancelled) return
        setUser(userData)
        // The real credential remains in the HttpOnly cookie. This marker is
        // only used to keep the authenticated application mounted in memory.
        setToken('cookie-session')
      })
      .catch(() => {
        if (!cancelled) {
          setToken(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAuthReady(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!token) {
      return
    }

    const timer = window.setTimeout(() => {
      void loadWorkspace()
      // ✨ 删除 loadMCPServers() 调用
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [
    token,
    loadWorkspace,
    // ✨ 移除 loadMCPServers 依赖
  ])

  useEffect(() => {
    if (
      !token ||
      !selectedKnowledgeBaseId
    ) {
      return
    }

    const timer = window.setTimeout(() => {
      void loadDocuments(
        selectedKnowledgeBaseId,
      )
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [
    token,
    selectedKnowledgeBaseId,
    loadDocuments,
  ])

  async function handleAuthSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (
      !email.trim() ||
      !password.trim()
    ) {
      setErrorMessage(t('auth.required'))
      return
    }

    if (authMode === 'register') {
      if (password.length < 8) {
        setErrorMessage('注册密码至少需要 8 个字符')
        return
      }

      if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
        setErrorMessage('注册密码必须同时包含字母和数字')
        return
      }
    }

    setBusy(true)
    setErrorMessage('')

    try {
      const response =
        await apiRequest<AuthResponse>(
          `/api/v1/auth/${authMode}`,
          {
            method: 'POST',
            body: JSON.stringify({
              email: email.trim(),
              password,
            }),
          },
        )

      setToken('cookie-session')
      setUser(response.user)
      setActiveView('welcome')
      setEmail('')
      setPassword('')
    } catch (error) {
      handleApiError(error)
    } finally {
      setBusy(false)
    }
  }

  function queueFiles(files: File[]) {
    if (files.length === 0) return

    setSelectedFiles((current) => {
      const queued = new Set(
        current.map((file) => `${file.name}:${file.size}:${file.lastModified}`),
      )
      return [
        ...current,
        ...files.filter((file) => {
          const key = `${file.name}:${file.size}:${file.lastModified}`
          if (queued.has(key)) return false
          queued.add(key)
          return true
        }),
      ]
    })
  }

  async function handleUpload() {
    if (selectedFiles.length === 0) {
      setErrorMessage(t('workspace.selectFile'))
      return
    }

    if (!selectedKnowledgeBaseId) {
      setErrorMessage(t('workspace.noDocumentsHint'))
      return
    }

    setBusy(true)
    setErrorMessage('')
    setSuccessMessage('')
    const uploadQueue = [...selectedFiles]
    const uploadedDocuments: DocumentRecord[] = []
    const pollDocumentIds: string[] = []
    let duplicateCount = 0
    let failedFiles: File[] = []
    let uploadError = ''

    try {
      for (const [index, file] of uploadQueue.entries()) {
        setUploadProgress(`${t('workspace.uploading')} ${index + 1}/${uploadQueue.length} · ${file.name}`)
        const formData = new FormData()
        formData.append('knowledge_base_id', selectedKnowledgeBaseId)
        formData.append('file', file)

        try {
          const response = await apiRequest<DocumentRecord>(
            '/api/v1/documents/upload',
            { method: 'POST', body: formData },
          )
          pollDocumentIds.push(response.id)
          if (response.duplicate) {
            duplicateCount += 1
          } else {
            uploadedDocuments.push(response)
          }
        } catch (error) {
          failedFiles = uploadQueue.slice(index)
          uploadError = `${file.name}: ${error instanceof Error ? error.message : t('workspace.uploadFailed')}`
          break
        }
      }

      const uploadedIds = new Set(uploadedDocuments.map((document) => document.id))
      setDocuments((current) => [
        ...uploadedDocuments.reverse(),
        ...current.filter((document) => !uploadedIds.has(document.id)),
      ])
      setSelectedFiles(failedFiles)
      if (uploadedDocuments.length > 0 || duplicateCount > 0) {
        const uploadSummary = [
          uploadedDocuments.length > 0
            ? `${uploadedDocuments.length} ${t('workspace.uploadedCount')}`
            : '',
          duplicateCount > 0
            ? `${duplicateCount} ${t('workspace.duplicatesSkipped')}`
            : '',
        ].filter(Boolean)
        setSuccessMessage(
          uploadSummary.join(' · '),
        )
      }
      if (uploadError) setErrorMessage(uploadError)

      const fileInput = document.querySelector('#document-file-input') as HTMLInputElement | null
      if (fileInput) fileInput.value = ''
      for (const documentId of pollDocumentIds) {
        void pollDocument(documentId)
      }
    } finally {
      setUploadProgress('')
      setBusy(false)
    }
  }

  async function handleViewDocument(documentId: string, chunkIndex?: number) {
    const documentRecord = documents.find(
      (item) => item.id === documentId,
    )

    if (!documentRecord) {
      setErrorMessage('找不到引用的文档，文档可能已被删除。')
      return
    }

    const requestId = ++documentDetailRequestId.current

    setSelectedDocument(documentRecord)
    setDocumentContent('')
    setDocumentChunks([])
    setSourceChunkIndex(chunkIndex ?? null)
    setDocumentDetailTab(chunkIndex == null ? 'detail' : 'chunks')
    setDocumentDetailLoading(true)
    setErrorMessage('')

    try {
      const token = localStorage.getItem(ACCESS_TOKEN_KEY)
      const response = await fetch(
        `${API_BASE_URL}/api/v1/documents/${documentId}/content`,
        { credentials: 'include', headers: token ? { Authorization: `Bearer ${token}` } : undefined },
      )

      if (requestId !== documentDetailRequestId.current) return

      if (!response.ok) {
        throw new Error(`无法打开文档（HTTP ${response.status}）`)
      }

      const contentType = response.headers.get('content-type') ?? ''
      const contentBytes = await response.arrayBuffer()
      if (requestId !== documentDetailRequestId.current) return

      if (
        contentType.includes('text') ||
        contentType.includes('json') ||
        documentRecord.metadata?.parsed_text_object_name
      ) {
        setDocumentContent(
          new TextDecoder('utf-8').decode(contentBytes),
        )
      } else {
        setDocumentContent(
          '该文件已上传，但当前没有可直接展示的文本预览。请在文档处理完成后查看解析内容。',
        )
      }

      try {
        const chunksResponse = await fetch(
          `${API_BASE_URL}/api/v1/documents/${documentId}/chunks`,
          { credentials: 'include', headers: token ? { Authorization: `Bearer ${token}` } : undefined },
        )

        if (requestId === documentDetailRequestId.current && chunksResponse.ok) {
          const chunksPayload =
            await chunksResponse.json() as DocumentChunksResponse
          if (requestId === documentDetailRequestId.current) {
            setDocumentChunks(chunksPayload.items)
          }
        }
      } catch {
        // 文档正文仍可展示时，不阻断详情面板。
      }
    } catch (error) {
      if (requestId === documentDetailRequestId.current) handleApiError(error)
    } finally {
      if (requestId === documentDetailRequestId.current) {
        setDocumentDetailLoading(false)
      }
    }
  }

  async function handleDeleteDocument(documentId: string) {
    const document = documents.find((item) => item.id === documentId)
    if (!document || !window.confirm(`确定删除“${document.file_name}”吗？`)) {
      return
    }

    setBusy(true)
    setErrorMessage('')
    try {
      await apiRequest(`/api/v1/documents/${documentId}`, { method: 'DELETE' })
      const activePoll = activeDocumentPolls.current.get(documentId)
      if (activePoll) activePoll.cancelled = true
      setPausedDocumentPollIds((current) => {
        if (!current.has(documentId)) return current
        const next = new Set(current)
        next.delete(documentId)
        return next
      })
      setDocuments((current) => current.filter((item) => item.id !== documentId))
      setSuccessMessage(t('workspace.documentDeleted'))
    } catch (error) {
      handleApiError(error)
    } finally {
      setBusy(false)
    }
  }

  async function handleRetryDocument(documentId: string) {
    if (retryingDocumentId) return
    setRetryingDocumentId(documentId)
    setErrorMessage('')
    try {
      const response = await apiRequest<DocumentRecord>(
        `/api/v1/documents/${documentId}/retry`,
        { method: 'POST' },
      )
      setDocuments((current) => current.map((item) => item.id === documentId ? response : item))
      void pollDocument(documentId)
      setSuccessMessage(t('workspace.retryStarted'))
    } catch (error) {
      handleApiError(error)
    } finally {
      setRetryingDocumentId(null)
    }
  }

  function logout() {
    void apiRequest('/api/v1/auth/logout', { method: 'POST' }).catch(() => undefined)
    localStorage.removeItem(
      ACCESS_TOKEN_KEY,
    )
    localStorage.removeItem(REFRESH_TOKEN_KEY)

    setToken(null)
    setUser(null)
    setDocuments([])
    setSelectedKnowledgeBaseId('')
    setConversationId(null)
    // ✨ 删除 MCP 相关清理
    setActiveView('welcome')
  }

  if (!authReady) {
    return (
      <main className="auth-page">
        <section className="auth-panel">
          <div className="brand-mark">RAG</div>
          <p className="eyebrow">MCP-RAG-Notebook</p>
          <p>{t('common.loading')}</p>
        </section>
      </main>
    )
  }

  if (!token) {
    return (
      <main className="auth-page">
        <section className="auth-panel">
          <div className="brand-mark">
            RAG
          </div>

          <p className="eyebrow">
            MCP-RAG-Notebook
          </p>

          <h1>
            {authMode === 'login'
              ? t('auth.loginTitle')
              : t('auth.registerTitle')}
          </h1>

          <p className="muted">
            {t('auth.description')}
          </p>

          <form
            className="auth-form"
            onSubmit={handleAuthSubmit}
          >
            <label>
              {t('auth.email')}

              <input
                type="email"
                value={email}
                onChange={(event) =>
                  setEmail(event.target.value)
                }
                placeholder="name@example.com"
                autoComplete="email"
              />
            </label>

            <label>
              {t('auth.password')}

              <input
                type="password"
                value={password}
                onChange={(event) =>
                  setPassword(event.target.value)
                }
                placeholder={t('auth.passwordPlaceholder')}
                autoComplete={
                  authMode === 'login'
                    ? 'current-password'
                    : 'new-password'
                }
              />
            </label>

            <button
              className="primary-button"
              type="submit"
              disabled={busy}
            >
              {busy
                ? t('auth.processing')
                : authMode === 'login'
                  ? t('auth.login')
                  : t('auth.register')}
            </button>
          </form>

          {errorMessage && (
            <p className="message error-message">
              {errorMessage}
            </p>
          )}

          <button
            className="text-button"
            type="button"
            onClick={() => {
              setAuthMode(
                authMode === 'login'
                  ? 'register'
                  : 'login',
              )
              setErrorMessage('')
            }}
          >
            {authMode === 'login'
              ? t('auth.toRegister')
              : t('auth.toLogin')}
          </button>
        </section>
      </main>
    )
  }

  if (activeView === 'welcome') {
    return (
      <NotebookShell
        activeView="welcome"
        email={user?.email}
        onNavigate={handleNotebookNavigate}
        onLogout={logout}
      >
        <main className="welcome-page">
          <header className="notebook-page-header welcome-header">
            <div>
              <p className="eyebrow">{t('welcome.eyebrow')}</p>
              <h1>{language === 'en-US' ? t('welcome.greetingEn') : t('welcome.greeting')}{user?.display_name ? `${language === 'en-US' ? ', ' : '，'}${user.display_name}` : ''}</h1>
              <p className="muted">{t('welcome.description')}</p>
            </div>
            <span className="welcome-date">
              {new Date().toLocaleDateString(language, {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
              })}
            </span>
          </header>

          <section className="welcome-content">
            <div className="welcome-stats" aria-label={t('welcome.overview')}>
              <div className="welcome-stat-card"><span className="welcome-stat-label">{t('welcome.currentDocuments')}</span><strong>{documents.length}</strong><span>{t('welcome.documents')}</span></div>
              <div className="welcome-stat-card"><span className="welcome-stat-label">{t('welcome.entry')}</span><strong>3</strong><span>{t('welcome.workModes')}</span></div>
            </div>

            <section className="welcome-section">
              <div className="welcome-section-heading"><div><p className="eyebrow">{t('welcome.quickStart')}</p><h2>{t('welcome.start')}</h2></div><span className="muted">{t('welcome.chooseEntry')}</span></div>
              <div className="welcome-actions">
                <button className="welcome-action-card" type="button" onClick={() => setActiveView('notes')}><span className="welcome-action-icon">▤</span><span><strong>{t('welcome.notesTitle')}</strong><small>{t('welcome.notesHint')}</small></span><span className="welcome-action-arrow">→</span></button>
                <button className="welcome-action-card" type="button" onClick={() => setActiveView('chat')}><span className="welcome-action-icon">□</span><span><strong>{t('welcome.chatTitle')}</strong><small>{t('welcome.chatHint')}</small></span><span className="welcome-action-arrow">→</span></button>
                <button className="welcome-action-card" type="button" onClick={() => setActiveView('workspace')}><span className="welcome-action-icon">▥</span><span><strong>{t('welcome.documentsTitle')}</strong><small>{t('welcome.documentsHint')}</small></span><span className="welcome-action-arrow">→</span></button>
              </div>
            </section>

            <section className="welcome-tip"><span className="welcome-tip-mark">✦</span><div><strong>{t('welcome.tipTitle')}</strong><p>{t('welcome.tipText')}</p></div><button className="text-button" type="button" onClick={() => setActiveView('review')}>{t('welcome.review')}</button></section>
          </section>
        </main>
      </NotebookShell>
    )
  }

  // ✨ MCP 页面
  if (activeView === 'mcp') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <MCPServersPage
          email={user?.email}
          onNavigate={handleNotebookNavigate}
          onLogout={logout}
        />
      </Suspense>
    )
  }

  if (activeView === 'profile' && user) {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <ProfilePage
          user={user}
          email={user.email}
          onUserChange={setUser}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  if (activeView === 'settings') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <SettingsPage
          email={user?.email}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  if (activeView === 'about') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <AboutPage
          email={user?.email}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  if (activeView === 'chat') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <ChatPage
          email={user?.email}
          conversationId={conversationId}
          onConversationIdChange={setConversationId}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
          onOpenSource={(documentId, chunkIndex) => {
            setActiveView('workspace')
            void handleViewDocument(documentId, chunkIndex)
          }}
        />
      </Suspense>
    )
  }

  if (activeView === 'sessions') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <SessionsPage
          email={user?.email}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
          onOpenConversation={(id) => {
            setConversationId(id)
            setActiveView('chat')
          }}
        />
      </Suspense>
    )
  }

  // ✨ 新增 review 页面判断（放在 notes 之前）
  if (activeView === 'review') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <DailyReviewPage
          email={user?.email}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  if (activeView === 'graph') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <KnowledgeGraphPage
          email={user?.email}
          knowledgeBaseId={selectedKnowledgeBaseId}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  if (activeView === 'notes') {
    return (
      <Suspense fallback={PAGE_LOADING}>
        <NotesPage
          email={user?.email}
          onLogout={logout}
          onNavigate={handleNotebookNavigate}
        />
      </Suspense>
    )
  }

  return (
    <NotebookShell activeView="knowledge" email={user?.email} onNavigate={handleNotebookNavigate} onLogout={logout}>
      <main className="knowledge-page knowledge-library-page">
        <header className="notebook-page-header knowledge-library-header">
          <div><p className="eyebrow">Notebook</p><h1>{t('workspace.title')}</h1></div>
          <span className="count-badge large">{documents.length} {t('workspace.sources')}</span>
        </header>

        <section className="knowledge-library-content">
          {errorMessage && <div className="message error-message">{errorMessage}</div>}
          {successMessage && <div className="message success-message" role="status">{successMessage}</div>}
          <section className="document-upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); queueFiles(Array.from(event.dataTransfer.files)) }}>
            <span className="upload-dropzone-icon">↑</span>
            <strong>{t('workspace.dropzone')}</strong>
            <p className="upload-format-hint" title={SUPPORTED_FORMATS_LABEL}>{t('workspace.supported')} {SUPPORTED_FORMATS_LABEL}</p>
            <input id="document-file-input" className="document-file-input-hidden" type="file" accept={SUPPORTED_FILE_ACCEPT} multiple onChange={(event) => { queueFiles(Array.from(event.currentTarget.files ?? [])); event.currentTarget.value = '' }} />
            <button className="primary-button upload-select-button" type="button" onClick={() => document.getElementById('document-file-input')?.click()} disabled={busy || !selectedKnowledgeBaseId}>{t('workspace.selectFile')}</button>
            {selectedFiles.length > 0 && (
              <div className="upload-selected-files" aria-label={t('workspace.selectedFiles')}>
                {selectedFiles.map((file) => (
                  <div className="upload-selected-file" key={`${file.name}:${file.size}:${file.lastModified}`}>
                    <span title={file.name}>{file.name} · {formatFileSize(file.size)}</span>
                    <button type="button" onClick={() => setSelectedFiles((current) => current.filter((item) => item !== file))} disabled={busy} aria-label={`${t('workspace.removeSelected')} ${file.name}`}>×</button>
                  </div>
                ))}
              </div>
            )}
            {uploadProgress && <span className="upload-progress-status" role="status">{uploadProgress}</span>}
            {selectedFiles.length > 0 && <button className="primary-button upload-submit-button" type="button" onClick={() => void handleUpload()} disabled={busy}>{busy ? t('auth.processing') : `${t('workspace.process')} (${selectedFiles.length})`}</button>}
          </section>

          <section className="knowledge-document-section">
            <div className="knowledge-document-heading"><h2>{t('workspace.documents')} ({documents.length})</h2><button className="text-button" type="button" onClick={() => void loadDocuments(selectedKnowledgeBaseId)} disabled={busy}>{t('mcp.refresh')}</button></div>
            {documents.length === 0 ? (
              <div className="empty-state"><strong>{t('workspace.noDocuments')}</strong><p>{t('workspace.noDocumentsHint')}</p></div>
            ) : (
              <div className="knowledge-document-list">
                {documents.map((document) => {
                  const progress = getProgress(document)
                  const taskStatus = document.ingestion_task?.status ?? document.status
                  const taskError = document.ingestion_task?.error_message
                  const fileIcon = getFileIcon(document.file_name)
                  return (
                    <article className="knowledge-document-card" key={document.id}>
                      <button className="knowledge-document-main" type="button" onClick={(event) => { documentDetailTriggerRef.current = event.currentTarget; void handleViewDocument(document.id) }} title={t('workspace.documentContent')}><span className={`knowledge-document-icon file-icon file-icon-${fileIcon.tone}`} aria-hidden="true">{fileIcon.label}</span><span className="knowledge-document-copy"><strong>{document.file_name}</strong><small>{formatFileSize(document.size_bytes)} · {formatDate(document.created_at, language, t)}</small></span></button>
                      <div className="knowledge-document-progress"><div className="status-line"><span className={`status-dot status-${document.status.toLowerCase()}`} /><span>{getStatusLabel(document.status, t)}</span><strong>{progress}%</strong></div><div className="progress-track"><div className={`progress-bar ${document.status.includes('FAILED') ? 'progress-failed' : ''}`} style={{ width: `${progress}%` }} /></div>{taskStatus !== document.status && <small className="task-status">{t('workspace.status')}：{getStatusLabel(taskStatus, t)}</small>}{taskError && <small className="document-error">{taskError}</small>}</div>
                      <div className="knowledge-document-actions">
                        {pausedDocumentPollIds.has(document.id) && <button className="text-button" type="button" onClick={() => void pollDocument(document.id, true)} aria-label={t('workspace.checkStatus')} title={t('workspace.checkStatus')}>{t('workspace.checkStatus')}</button>}
                        {(document.status.includes('FAILED') || taskStatus === 'FAILED') && <button className="text-button" type="button" onClick={() => void handleRetryDocument(document.id)} disabled={busy || retryingDocumentId !== null} aria-label={t('workspace.retry')} title={t('workspace.retry')}>{retryingDocumentId === document.id ? '…' : t('workspace.retry')}</button>}
                        <button className="document-delete-button" type="button" onClick={() => void handleDeleteDocument(document.id)} disabled={busy || retryingDocumentId !== null} aria-label={`${t('workspace.deleteConfirm')} ${document.file_name}`} title={t('workspace.deleteConfirm')}>⌫</button>
                        {pausedDocumentPollIds.has(document.id) && <small className="document-poll-paused" role="status">{t('workspace.pollingPaused')}</small>}
                      </div>
                    </article>
                  )
                })}
              </div>
            )}
          </section>
        </section>

        {selectedDocument && (
          <div
            className="document-detail-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                closeDocumentDetail()
              }
            }}
          >
            <aside
              className="document-detail-drawer"
              role="dialog"
              aria-modal="true"
              aria-label={t('workspace.detail')}
              tabIndex={-1}
            >
              <header className="document-detail-header">
                <div className="document-detail-title">
                  <span className={`knowledge-document-icon file-icon file-icon-${getFileIcon(selectedDocument.file_name).tone}`} aria-hidden="true">
                    {getFileIcon(selectedDocument.file_name).label}
                  </span>
                  <div>
                    <span className="document-detail-eyebrow">{t('workspace.detail')}</span>
                    <h2>{selectedDocument.file_name}</h2>
                  </div>
                </div>
                <button ref={documentDetailCloseButtonRef} className="document-detail-close" type="button" onClick={closeDocumentDetail} aria-label={t('workspace.close')}>×</button>
              </header>

              <div className="document-detail-tabs" role="tablist" aria-label={t('workspace.views')}>
                <button className={documentDetailTab === 'detail' ? 'active' : ''} type="button" role="tab" aria-selected={documentDetailTab === 'detail'} onClick={() => setDocumentDetailTab('detail')}>{t('workspace.detailTab')}</button>
                <button className={documentDetailTab === 'chunks' ? 'active' : ''} type="button" role="tab" aria-selected={documentDetailTab === 'chunks'} onClick={() => setDocumentDetailTab('chunks')}>{t('workspace.chunksTab')} ({documentChunks.length})</button>
              </div>

              <div className="document-detail-body">
                {documentDetailLoading ? (
                  <div className="document-detail-loading">{t('workspace.reading')}</div>
                ) : documentDetailTab === 'detail' ? (
                  <>
                    <div className="document-detail-meta-grid">
                      <div><span>{t('workspace.fileType')}</span><strong>{selectedDocument.mime_type ?? getFileIcon(selectedDocument.file_name).label}</strong></div>
                      <div><span>{t('workspace.fileSize')}</span><strong>{formatFileSize(selectedDocument.size_bytes)}</strong></div>
                      <div><span>{t('workspace.status')}</span><strong>{getStatusLabel(selectedDocument.status, t)}</strong></div>
                      <div><span>{t('workspace.uploadedAt')}</span><strong>{formatDate(selectedDocument.created_at, language, t)}</strong></div>
                    </div>
                    <section className="document-detail-content-section">
                      <div className="document-detail-section-heading"><h3>{t('workspace.parsedContent')}</h3><span>{documentChunks.length ? `${documentChunks.length} ${t('workspace.chunksTab')}` : t('workspace.textPreview')}</span></div>
                      <pre className="document-detail-content">{documentContent || t('workspace.noContent')}</pre>
                    </section>
                  </>
                ) : (
                  <section className="document-chunks-list">
                    {documentChunks.length === 0 ? (
                      <div className="document-detail-empty">{t('workspace.noChunks')}</div>
                    ) : documentChunks.map((chunk) => (
                      <article className={`document-chunk-card${chunk.chunk_index === sourceChunkIndex ? ' is-cited' : ''}`} key={chunk.id || chunk.chunk_index} ref={(node) => { if (node && chunk.chunk_index === sourceChunkIndex) node.scrollIntoView?.({ block: 'nearest' }) }}>
                        <div className="document-chunk-heading"><strong>#{chunk.chunk_index + 1}</strong><span>{chunk.page_number > 0 ? `${t('workspace.page')} ${chunk.page_number} ${t('workspace.pageSuffix')}` : t('workspace.body')}</span><span>{chunk.source_type}</span></div>
                        <p>{chunk.content}</p>
                      </article>
                    ))}
                  </section>
                )}
              </div>
            </aside>
          </div>
        )}
      </main>
    </NotebookShell>
  )
}

export default WorkspacePage
