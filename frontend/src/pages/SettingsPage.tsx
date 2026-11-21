import { useEffect, useState } from 'react'

import '../App.css'
import { apiRequest } from '../api/client'
import NotebookShell, { type NotebookView } from '../components/NotebookShell'
import { useLanguage, type Language } from '../i18n'

type SettingsPageProps = { email?: string; onLogout: () => void; onNavigate: (view: NotebookView) => void }

function SettingsPage({ email, onLogout, onNavigate }: SettingsPageProps) {
  const [theme, setTheme] = useState(() => localStorage.getItem('notebook_theme') ?? 'light')
  const { language, setLanguage, t } = useLanguage()
  const [memoryTurns, setMemoryTurns] = useState(8)
  const [memoryDefault, setMemoryDefault] = useState(8)
  const [memoryLoading, setMemoryLoading] = useState(true)
  const [memorySaving, setMemorySaving] = useState(false)
  const [memoryMessage, setMemoryMessage] = useState('')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('notebook_theme', theme)
  }, [theme])

  useEffect(() => {
    let cancelled = false
    void apiRequest<{ max_turns: number; default_max_turns: number }>('/api/v1/profile/agent-memory')
      .then((result) => {
        if (cancelled) return
        setMemoryTurns(result.max_turns)
        setMemoryDefault(result.default_max_turns)
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setMemoryLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  async function saveMemoryTurns() {
    setMemorySaving(true)
    setMemoryMessage('')
    try {
      const result = await apiRequest<{ max_turns: number; default_max_turns: number }>('/api/v1/profile/agent-memory', {
        method: 'PUT',
        body: JSON.stringify({ max_turns: memoryTurns }),
      })
      setMemoryTurns(result.max_turns)
      setMemoryMessage(t('settings.memorySaved'))
    } catch (error) {
      setMemoryMessage(error instanceof Error ? error.message : t('settings.memorySaveFailed'))
    } finally {
      setMemorySaving(false)
    }
  }

  return (
    <NotebookShell activeView="settings" email={email} onNavigate={onNavigate} onLogout={onLogout}>
      <main className="settings-page">
        <header className="notebook-page-header"><div><p className="eyebrow">{t('settings.eyebrow')}</p><h1>{t('settings.title')}</h1></div></header>
        <section className="notebook-page-content settings-content">
          <section className="settings-card preferences-card"><p className="eyebrow">{t('settings.appearance')}</p><h2>{t('settings.appearanceTitle')}</h2>
            <div className="preference-row"><div><strong>{t('settings.theme')}</strong><p className="muted">{t('settings.themeHint')}</p></div><div className="segmented-control"><button className={theme === 'light' ? 'active' : ''} type="button" onClick={() => setTheme('light')}>{t('settings.light')}</button><button className={theme === 'dark' ? 'active' : ''} type="button" onClick={() => setTheme('dark')}>{t('settings.dark')}</button></div></div>
            <div className="preference-row"><div><strong>{t('settings.language')}</strong><p className="muted">{t('settings.languageHint')}</p></div><select className="preference-select" value={language} onChange={(event) => setLanguage(event.target.value as Language)}><option value="zh-CN">{t('language.zh')}</option><option value="en-US">{t('language.en')}</option></select></div>
          </section>
          <section className="settings-card"><p className="eyebrow">{t('settings.workspace')}</p><h2>{t('settings.workspaceTitle')}</h2><p className="muted">{t('settings.workspaceHint')}</p></section>
          <section className="settings-card"><p className="eyebrow">{t('settings.agent')}</p><h2>{t('settings.agentTitle')}</h2>
            <div className="preference-row"><div><strong>{t('settings.memoryTurns')}</strong><p className="muted">{t('settings.memoryTurnsHint')} {t('settings.defaultValue')} {memoryDefault}</p></div><div className="settings-range-control"><input type="range" min="0" max="20" step="1" value={memoryTurns} onChange={(event) => setMemoryTurns(Number(event.target.value))} disabled={memoryLoading || memorySaving} /><output>{memoryTurns}</output><button className="primary-button" type="button" onClick={() => void saveMemoryTurns()} disabled={memoryLoading || memorySaving}>{memorySaving ? t('settings.saving') : t('settings.save')}</button></div></div>
            {memoryMessage && <p className="muted settings-inline-message">{memoryMessage}</p>}
          </section>
        </section>
      </main>
    </NotebookShell>
  )
}

export default SettingsPage
