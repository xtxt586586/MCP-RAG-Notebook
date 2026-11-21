import { useCallback, useEffect, useRef, useState } from 'react'

import '../App.css'
import {
  deleteConversation,
  listConversations,
  updateConversation,
} from '../api/conversations'
import NotebookShell, { type NotebookView } from '../components/NotebookShell'
import { useLanguage } from '../i18n'
import type { ConversationSummary } from '../types/conversations'

type SessionsPageProps = {
  email?: string
  onLogout?: () => void
  onNavigate?: (view: NotebookView) => void
  onOpenConversation?: (conversationId: string) => void
}

function formatDate(value: string, language: 'zh-CN' | 'en-US') {
  return new Date(value).toLocaleString(language, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    second: '2-digit',
  })
}

function SessionsPage({
  email,
  onLogout,
  onNavigate,
  onOpenConversation,
}: SessionsPageProps) {
  const { language, t } = useLanguage()
  const [query, setQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const includeArchivedRef = useRef(false)
  const [sessions, setSessions] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const requestSequence = useRef(0)
  const sessionMutationRef = useRef(new Map<string, 'delete' | 'rename' | 'archive'>())
  const [sessionMutations, setSessionMutations] = useState<Map<string, 'delete' | 'rename' | 'archive'>>(
    () => new Map(),
  )

  function beginSessionMutation(sessionId: string, action: 'delete' | 'rename' | 'archive') {
    if (sessionMutationRef.current.has(sessionId)) return false
    sessionMutationRef.current.set(sessionId, action)
    setSessionMutations(new Map(sessionMutationRef.current))
    return true
  }

  function endSessionMutation(sessionId: string) {
    sessionMutationRef.current.delete(sessionId)
    setSessionMutations(new Map(sessionMutationRef.current))
  }

  function invalidateSessionLoads() {
    requestSequence.current += 1
    setLoading(false)
  }

  const loadSessions = useCallback(async () => {
    const requestId = ++requestSequence.current
    setLoading(true)
    setErrorMessage('')
    try {
      const result = await listConversations({
        query,
        includeArchived,
      })
      if (requestId === requestSequence.current) {
        setSessions(result.items)
      }
    } catch (error) {
      if (requestId === requestSequence.current) {
        setErrorMessage(error instanceof Error ? error.message : t('sessions.loading'))
      }
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false)
      }
    }
  }, [includeArchived, query, t])

  useEffect(() => {
    const timer = window.setTimeout(() => void loadSessions(), 180)
    return () => {
      window.clearTimeout(timer)
      requestSequence.current += 1
    }
  }, [loadSessions])

  async function handleDelete(session: ConversationSummary) {
    if (!window.confirm(`${t('sessions.delete')} “${session.title}”?`)) return
    if (!beginSessionMutation(session.id, 'delete')) return
    try {
      await deleteConversation(session.id)
      invalidateSessionLoads()
      setSessions((current) => current.filter((item) => item.id !== session.id))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('sessions.delete'))
    } finally {
      endSessionMutation(session.id)
    }
  }

  async function handleRename(session: ConversationSummary) {
    const title = window.prompt(t('sessions.renamePrompt'), session.title)
    if (title === null || !title.trim() || title.trim() === session.title) return
    if (!beginSessionMutation(session.id, 'rename')) return

    try {
      const updated = await updateConversation(session.id, { title: title.trim() })
      invalidateSessionLoads()
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('sessions.rename'))
    } finally {
      endSessionMutation(session.id)
    }
  }

  async function handleArchive(session: ConversationSummary) {
    if (!beginSessionMutation(session.id, 'archive')) return
    const archived = !session.archived_at
    try {
      const updated = await updateConversation(session.id, { archived })
      invalidateSessionLoads()
      if (!includeArchivedRef.current && archived) {
        setSessions((current) => current.filter((item) => item.id !== session.id))
      } else {
        setSessions((current) => current.map((item) => item.id === session.id ? updated : item))
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t('sessions.archive'))
    } finally {
      endSessionMutation(session.id)
    }
  }

  return (
    <NotebookShell
      activeView="sessions"
      email={email}
      onNavigate={onNavigate ?? (() => undefined)}
      onLogout={onLogout ?? (() => undefined)}
    >
      <main className="sessions-page">
        <header className="notebook-page-header">
          <div>
            <p className="eyebrow">{t('sessions.eyebrow')}</p>
            <h1>{t('sessions.title')}</h1>
            <p className="page-description">{t('sessions.description')}</p>
          </div>
        </header>

        <section className="sessions-toolbar" aria-label={t('sessions.search')}>
          <input
            className="search-input"
            value={query}
            onChange={(event) => {
              setLoading(true)
              setErrorMessage('')
              setQuery(event.target.value)
            }}
            placeholder={t('sessions.search')}
            aria-label={t('sessions.search')}
          />
          <label className="sessions-archive-toggle">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => {
                includeArchivedRef.current = event.target.checked
                setLoading(true)
                setErrorMessage('')
                setIncludeArchived(event.target.checked)
              }}
            />
            {t('sessions.archived')}
          </label>
          <button
            className="text-button"
            type="button"
            onClick={() => void loadSessions()}
            disabled={loading}
          >
            {t('mcp.refresh')}
          </button>
        </section>

        {errorMessage && <div className="message error-message">{errorMessage}</div>}
        <section className="sessions-list" aria-live="polite">
          {loading ? <div className="empty-state"><p>{t('sessions.loading')}</p></div> : sessions.length === 0 ? (
            <div className="empty-state"><strong>{t('sessions.emptyTitle')}</strong><p>{t('sessions.emptyHint')}</p></div>
          ) : sessions.map((session) => (
            <article className={`session-card${session.archived_at ? ' session-card-archived' : ''}`} key={session.id}>
              <button className="session-card-main" type="button" onClick={() => onOpenConversation?.(session.id)} disabled={sessionMutations.has(session.id)}>
                <span className="session-card-title">{session.title || '新对话'}</span>
                <span className="session-card-meta">{session.message_count} {t('sessions.messages')} · {formatDate(session.updated_at, language)}</span>
              </button>
              <div className="session-card-actions">
                <button className="text-button" type="button" onClick={() => void handleRename(session)} disabled={sessionMutations.has(session.id)}>{sessionMutations.get(session.id) === 'rename' ? t('sessions.saving') : t('sessions.rename')}</button>
                <button className="text-button" type="button" onClick={() => void handleArchive(session)} disabled={sessionMutations.has(session.id)}>{sessionMutations.get(session.id) === 'archive' ? t('sessions.updating') : session.archived_at ? t('sessions.restore') : t('sessions.archive')}</button>
                <button className="text-button danger-text" type="button" onClick={() => void handleDelete(session)} disabled={sessionMutations.has(session.id)}>{sessionMutations.get(session.id) === 'delete' ? t('sessions.deleting') : t('sessions.delete')}</button>
              </div>
            </article>
          ))}
        </section>
      </main>
    </NotebookShell>
  )
}

export default SessionsPage
