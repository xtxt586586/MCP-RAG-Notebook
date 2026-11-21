import type {
  ReactNode,
} from 'react'

import { useState } from 'react'
import { useLanguage } from '../i18n'

export type NotebookView =
  | 'welcome'
  | 'notes'
  | 'chat'
  | 'sessions'
  | 'review'
  | 'knowledge'
  | 'graph'
  | 'mcp'
  | 'profile'
  | 'settings'
  | 'about'

type NotebookShellProps = {
  activeView: NotebookView
  children: ReactNode
  email?: string
  onNavigate: (
    view: NotebookView,
  ) => void
  onLogout: () => void
}

const primaryItems: Array<{
  key: NotebookView
  labelKey: string
  icon: string
}> = [
  {
    key: 'notes',
    labelKey: 'nav.notes',
    icon: '▤',
  },
  {
    key: 'chat',
    labelKey: 'nav.chat',
    icon: '□',
  },
  {
    key: 'sessions',
    labelKey: 'nav.sessions',
    icon: '◷',
  },
  {
    key: 'review',
    labelKey: 'nav.review',
    icon: '⌂',
  },
  {
    key: 'knowledge',
    labelKey: 'nav.knowledge',
    icon: '▥',
  },
  {
    key: 'graph',
    labelKey: 'nav.graph',
    icon: '⌘',
  },
  {
    key: 'mcp',
    labelKey: 'nav.mcp',
    icon: '⚙',
  },
]

function NotebookShell({
  activeView,
  children,
  email,
  onNavigate,
  onLogout,
}: NotebookShellProps) {
  const [collapsed, setCollapsed] = useState(false)
  const { t } = useLanguage()

  return (
    <div
      className={
        collapsed
          ? 'notebook-shell is-collapsed'
          : 'notebook-shell'
      }
    >
      <aside className="notebook-sidebar">
        <div className="notebook-brand">
          <button
            className="notebook-brand-home"
            type="button"
            aria-label={`${t('nav.brand')} - ${t('nav.home')}`}
            aria-current={activeView === 'welcome' ? 'page' : undefined}
            onClick={() => onNavigate('welcome')}
          >
            {t('nav.brand')}
          </button>

          <button
            className="sidebar-collapse-button"
            type="button"
            aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
            aria-expanded={!collapsed}
            title={collapsed ? t('nav.expand') : t('nav.collapse')}
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? '›' : '‹'}
          </button>
        </div>

        <nav
          className="notebook-primary-nav"
          aria-label={t('nav.aria')}
        >
          {primaryItems.map((item) => (
            <button
              className={
                activeView === item.key
                  ? 'notebook-nav-item active'
                  : 'notebook-nav-item'
              }
              type="button"
              key={item.key}
              aria-current={activeView === item.key ? 'page' : undefined}
              onClick={() =>
                onNavigate(item.key)
              }
            >
              <span
                className="notebook-nav-icon"
                aria-hidden="true"
              >
                {item.icon}
              </span>

              <span>{t(item.labelKey)}</span>
            </button>
          ))}
        </nav>

        <div className="notebook-sidebar-footer">
          <button
            className={activeView === 'profile' ? 'notebook-nav-item active' : 'notebook-nav-item'}
            type="button"
            aria-current={activeView === 'profile' ? 'page' : undefined}
            onClick={() => onNavigate('profile')}
          >
            <span
              className="notebook-nav-icon"
              aria-hidden="true"
            >
              ♙
            </span>

            <span>{t('nav.profile')}</span>
          </button>

          <button
            className={activeView === 'settings' ? 'notebook-nav-item active' : 'notebook-nav-item'}
            type="button"
            aria-current={activeView === 'settings' ? 'page' : undefined}
            onClick={() => onNavigate('settings')}
          >
            <span
              className="notebook-nav-icon"
              aria-hidden="true"
            >
              ⚙
            </span>

            <span>{t('nav.settings')}</span>
          </button>

          <button
            className={activeView === 'about' ? 'notebook-nav-item active' : 'notebook-nav-item'}
            type="button"
            aria-current={activeView === 'about' ? 'page' : undefined}
            onClick={() => onNavigate('about')}
          >
            <span
              className="notebook-nav-icon"
              aria-hidden="true"
            >
              ⓘ
            </span>

            <span>{t('nav.about')}</span>
          </button>

          <button
            className="notebook-nav-item"
            type="button"
            onClick={onLogout}
          >
            <span
              className="notebook-nav-icon"
              aria-hidden="true"
            >
              ↪
            </span>

            <span>{t('nav.logout')}</span>
          </button>

          {email && (
            <span className="notebook-account">
              {email}
            </span>
          )}
        </div>
      </aside>

      <main className="notebook-main">
        {children}
      </main>
    </div>
  )
}

export default NotebookShell
