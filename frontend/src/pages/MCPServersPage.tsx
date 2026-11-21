import {
  useCallback,
  useEffect,
  useState,
} from 'react'

import '../App.css'

import {
  discoverMCPTools,
  getMCPRegistryMode,
  listMCPServers,
  listStaticMCPServers,
  updateMCPServer,
} from '../api/mcp'

import NotebookShell, {
  type NotebookView,
} from '../components/NotebookShell'
import { useLanguage } from '../i18n'

import type {
  MCPServer,
} from '../types'

type MCPServersPageProps = {
  email?: string
  onLogout: () => void
  onNavigate: (
    view: NotebookView,
  ) => void
}

function MCPServersPage({
  email,
  onLogout,
  onNavigate,
}: MCPServersPageProps) {
  const { t } = useLanguage()
  const [servers, setServers] =
    useState<MCPServer[]>([])

  const [loading, setLoading] =
    useState(false)
  const [dynamicEnabled, setDynamicEnabled] = useState(false)

  const [errorMessage, setErrorMessage] =
    useState('')

  const [expandedServer, setExpandedServer] =
    useState<string | null>(null)

  const [serverTools, setServerTools] =
    useState<Record<string, string[]>>({})

  const loadServers = useCallback(
    async () => {
      setLoading(true)
      setErrorMessage('')

      try {
        const mode = await getMCPRegistryMode()
        setDynamicEnabled(mode.dynamic_enabled)
        if (mode.dynamic_enabled) {
          setServers(await listMCPServers())
        } else {
          const result = await listStaticMCPServers()
          setServers(result.servers.map((server) => ({
            ...server, id: server.name, timeout_seconds: 0,
            allowed_tools: [], args: [],
          })) as MCPServer[])
        }
      } catch (error) {
        setErrorMessage(
          error instanceof Error
            ? error.message
            : t('mcp.emptyHint'),
        )
      } finally {
        setLoading(false)
      }
    },
    [t],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadServers()
    }, 0)

    return () => {
      window.clearTimeout(timer)
    }
  }, [loadServers])

  async function handleEnabledChange(
    server: MCPServer,
    enabled: boolean,
  ) {
    setErrorMessage('')

    try {
      const updated =
        await updateMCPServer(
          server.id,
          { enabled },
        )

      setServers((current) =>
        current.map((item) =>
          item.id === updated.id
            ? updated
            : item,
        ),
      )

      if (!enabled) {
        setExpandedServer((current) =>
          current === server.name
            ? null
            : current,
        )
      }
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : t('mcp.emptyHint'),
      )
    }
  }

  async function handleDiscoverTools(
    server: MCPServer,
  ) {
    setErrorMessage('')

    try {
      const result =
        await discoverMCPTools(server.name)

      setServerTools((current) => ({
        ...current,
        [server.name]: result.tools.map(
          (tool) => tool.name,
        ),
      }))

      setExpandedServer(server.name)
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : t('mcp.noTools'),
      )
    }
  }

  return (
    <NotebookShell
      activeView="mcp"
      email={email}
      onNavigate={onNavigate}
      onLogout={onLogout}
    >
      <main className="knowledge-page">
        <header className="notebook-page-header">
          <div>
            <p className="eyebrow">
              Notebook
            </p>

            <h1>{t('mcp.title')}</h1>
          </div>

          <button
            className="secondary-button"
            type="button"
            onClick={() => void loadServers()}
            disabled={loading}
          >
            {loading ? t('mcp.loading') : t('mcp.refresh')}
          </button>
        </header>

        <section className="notebook-page-content">
          <div className="content-heading">
            <div>
              <p className="eyebrow">
                MCP Gateway
              </p>

              <h2>{t('mcp.management')}</h2>

              <p className="muted">
                {t(dynamicEnabled ? 'mcp.description' : 'mcp.staticDescription')}
              </p>
            </div>

            <span className="count-badge large">
              {servers.length} {t('mcp.services')}
            </span>
          </div>

          {errorMessage && (
            <div className="message error-message">
              {errorMessage}
            </div>
          )}

          {servers.length === 0 &&
            !loading && (
              <div className="empty-state">
                <strong>
                  {t('mcp.emptyTitle')}
                </strong>

                <p>
                  {t('mcp.emptyHint')}
                </p>
              </div>
            )}

          <section className="mcp-panel">
            <div className="mcp-server-list">
              {servers.map((server) => {
                const tools =
                  serverTools[server.name] ?? []

                const expanded =
                  expandedServer ===
                  server.name

                return (
                  <article
                    className="mcp-server-row"
                    key={server.id}
                  >
                    <div className="mcp-server-main">
                      <div>
                        <h3>{server.name}</h3>

                        <p className="muted">
                          {server.transport}
                          {dynamicEnabled && <> {' · '}{t('mcp.timeout')} {server.timeout_seconds}{t('mcp.seconds')}</>}
                        </p>
                      </div>

                      <span
                        className={
                          server.enabled
                            ? 'mcp-status enabled'
                            : 'mcp-status disabled'
                        }
                      >
                        {server.enabled
                          ? t('mcp.enabled')
                          : t('mcp.disabled')}
                      </span>
                    </div>

                    <div className="mcp-server-actions">
                      <label className="switch-control">
                        <input
                          type="checkbox"
                          checked={server.enabled}
                          disabled={!dynamicEnabled}
                          onChange={(event) =>
                            void handleEnabledChange(
                              server,
                              event.target.checked,
                            )
                          }
                        />

                        <span>{t('mcp.enable')}</span>
                      </label>

                      <button
                        className="text-button"
                        type="button"
                        disabled={!server.enabled}
                        onClick={() =>
                          expanded
                            ? setExpandedServer(
                                null,
                              )
                            : void handleDiscoverTools(
                                server,
                              )
                        }
                      >
                        {expanded
                          ? t('mcp.collapseTools')
                          : t('mcp.discoverTools')}
                      </button>
                    </div>

                    {expanded && (
                      <div className="mcp-tool-list">
                        <p className="muted">
                          {t('mcp.discovered')} {tools.length} {t('mcp.tools')}
                        </p>

                        {tools.length === 0 ? (
                          <p className="muted">
                            {t('mcp.noTools')}
                          </p>
                        ) : (
                          <ul>
                            {tools.map((tool) => (
                              <li key={tool}>
                                {tool}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </article>
                )
              })}
            </div>
          </section>
        </section>
      </main>
    </NotebookShell>
  )
}

export default MCPServersPage
