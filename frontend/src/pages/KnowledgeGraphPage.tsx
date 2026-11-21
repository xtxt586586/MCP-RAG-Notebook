import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ComponentType, MutableRefObject } from 'react'
import type {
  ForceGraphMethods,
  ForceGraphProps,
  GraphData,
  LinkObject,
  NodeObject,
} from 'react-force-graph-2d'
import NotebookShell, { type NotebookView } from '../components/NotebookShell'
import {
  getGraphRebuildStatus,
  getKnowledgeGraph,
  rebuildKnowledgeGraph,
} from '../api/knowledgeGraph'
import type {
  GraphRebuildJob,
  KnowledgeGraphData,
  KnowledgeGraphEdge,
  KnowledgeGraphNode,
} from '../api/knowledgeGraph'
import { useLanguage } from '../i18n'

type Props = {
  email?: string
  knowledgeBaseId: string
  onLogout: () => void
  onNavigate: (view: NotebookView) => void
}

type GraphNode = KnowledgeGraphNode & { color: string; val: number }
type GraphLink = Omit<KnowledgeGraphEdge, 'source' | 'target'> & {
  source: string | GraphNode
  target: string | GraphNode
}
type GraphNodeObject = NodeObject<GraphNode>
type GraphLinkObject = LinkObject<GraphNode, GraphLink>
type GraphMethods = Pick<ForceGraphMethods<GraphNode, GraphLink>, 'zoomToFit'>
type GraphComponentProps = ForceGraphProps<GraphNode, GraphLink> & {
  ref?: MutableRefObject<GraphMethods | undefined>
}

const ForceGraph2D = lazy(async () => {
  const module = await import('react-force-graph-2d')
  return {
    default: module.default as unknown as ComponentType<GraphComponentProps>,
  }
})
const emptyNodes: KnowledgeGraphNode[] = []
const emptyEdges: KnowledgeGraphEdge[] = []

const nodePalette = ['#2475a8', '#279c91', '#e99a51', '#8064ad', '#d56868']
const edgeColor = '#96a8bc'

function colorForType(type: string) {
  let hash = 0
  for (const character of type) hash = (hash * 31 + character.charCodeAt(0)) | 0
  return nodePalette[Math.abs(hash) % nodePalette.length]
}

function drawNode(node: GraphNodeObject, context: CanvasRenderingContext2D, scale: number) {
  const x = node.x ?? 0
  const y = node.y ?? 0
  const radius = 5.2 * Math.sqrt(node.val ?? 1)

  context.font = `${12 / scale}px Inter, sans-serif`
  context.textAlign = 'center'
  context.textBaseline = 'top'
  context.fillStyle = '#526274'
  context.fillText(node.name, x, y + radius + 3 / scale, 180 / scale)
}

function nodeLabelBounds(node: GraphNodeObject, context: CanvasRenderingContext2D, scale: number) {
  const x = node.x ?? 0
  const y = node.y ?? 0
  const radius = 5.2 * Math.sqrt(node.val ?? 1)
  const width = Math.min(context.measureText(node.name).width, 180 / scale)
  const padding = 8 / scale
  const top = y + radius + 3 / scale
  return {
    left: x - width / 2 - padding,
    right: x + width / 2 + padding,
    top: top - padding,
    bottom: top + 16 / scale + padding,
  }
}

function overlapsLabel(
  candidate: ReturnType<typeof nodeLabelBounds>,
  placed: Array<ReturnType<typeof nodeLabelBounds>>,
) {
  return placed.some((label) =>
    candidate.left < label.right &&
    candidate.right > label.left &&
    candidate.top < label.bottom &&
    candidate.bottom > label.top,
  )
}

function drawLinkLabel(link: GraphLinkObject, context: CanvasRenderingContext2D, scale: number) {
  const source = typeof link.source === 'object' ? link.source : undefined
  const target = typeof link.target === 'object' ? link.target : undefined
  if (source?.x == null || source.y == null || target?.x == null || target.y == null) return

  const x = (source.x + target.x) / 2
  const y = (source.y + target.y) / 2
  const label = String(link.predicate ?? '')
  context.save()
  context.font = `${Math.max(9 / scale, 2.4)}px Inter, sans-serif`
  context.textAlign = 'center'
  context.textBaseline = 'middle'
  const width = context.measureText(label).width
  const height = 12 / scale
  context.fillStyle = 'rgba(255, 255, 255, 0.84)'
  context.fillRect(x - width / 2 - 2 / scale, y - height / 2, width + 4 / scale, height)
  context.fillStyle = '#62758b'
  context.fillText(label, x, y)
  context.restore()
}

export default function KnowledgeGraphPage({
  email,
  knowledgeBaseId,
  onLogout,
  onNavigate,
}: Props) {
  const { t } = useLanguage()
  const [graph, setGraph] = useState<KnowledgeGraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildJob, setRebuildJob] = useState<GraphRebuildJob | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [entityType, setEntityType] = useState('all')
  const [selectedEdge, setSelectedEdge] = useState<KnowledgeGraphEdge | null>(null)
  const [selectedNode, setSelectedNode] = useState<KnowledgeGraphNode | null>(null)
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 })
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const graphRef = useRef<GraphMethods | undefined>(undefined)
  const refresh = useCallback(async () => {
    if (!knowledgeBaseId) return
    setLoading(true)
    setError('')
    try {
      setGraph(await getKnowledgeGraph(knowledgeBaseId))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : t('graph.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [knowledgeBaseId, t])

  useEffect(() => {
    if (!knowledgeBaseId) return
    const storageKey = `graph-rebuild-job:${knowledgeBaseId}`
    const savedJobId = sessionStorage.getItem(storageKey)
    if (!savedJobId) return

    let active = true
    getGraphRebuildStatus(savedJobId)
      .then((job) => {
        if (!active) return
        setRebuildJob(job)
        setRebuilding(job.status === 'pending' || job.status === 'running')
      })
      .catch(() => {
        if (active) sessionStorage.removeItem(storageKey)
      })
    return () => {
      active = false
    }
  }, [knowledgeBaseId])

  useEffect(() => {
    if (!rebuildJob || !['pending', 'running'].includes(rebuildJob.status)) return

    const timer = window.setInterval(() => {
      void getGraphRebuildStatus(rebuildJob.job_id)
        .then((job) => {
          setRebuildJob(job)
          if (job.status === 'completed' || job.status === 'partial' || job.status === 'failed') {
            setRebuilding(false)
            if (job.status === 'completed' || job.status === 'partial') {
              void refresh()
            }
            setNotice(
              job.status === 'completed'
                ? t('graph.completed')
                : job.status === 'partial'
                  ? t('graph.partialFailure')
                  : t('graph.failed'),
            )
          }
        })
        .catch(() => setError(t('graph.statusUnavailable')))
    }, 2500)

    return () => window.clearInterval(timer)
  }, [rebuildJob, refresh, t])

  useEffect(() => {
    let active = true
    getKnowledgeGraph(knowledgeBaseId)
      .then((data) => {
        if (active) setGraph(data)
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(requestError instanceof Error ? requestError.message : t('graph.loadFailed'))
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [knowledgeBaseId, t])

  useEffect(() => {
    const container = canvasRef.current
    if (!container) return
    const resizeObserver = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setCanvasSize({ width: Math.floor(width), height: Math.floor(height) })
    })
    resizeObserver.observe(container)
    return () => resizeObserver.disconnect()
  }, [])

  async function handleRebuild() {
    setRebuilding(true)
    setNotice('')
    setError('')
    try {
      const job = await rebuildKnowledgeGraph(knowledgeBaseId)
      sessionStorage.setItem(`graph-rebuild-job:${knowledgeBaseId}`, job.job_id)
      setRebuildJob(job)
      setRebuilding(job.status === 'pending' || job.status === 'running')
      setNotice(
        `${t('graph.queued')} ${job.queued_notes ?? 0} ${t('graph.noteJobs')}, ${job.queued_documents ?? 0} ${t('graph.documentJobs')}.`,
      )
      if (job.status === 'completed') {
        setNotice(t('graph.completed'))
        void refresh()
      }
    } catch (requestError) {
      setRebuilding(false)
      setError(requestError instanceof Error ? requestError.message : t('graph.rebuildFailed'))
    }
  }

  const nodes = graph?.nodes ?? emptyNodes
  const edges = graph?.edges ?? emptyEdges
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])
  const entityTypes = useMemo(
    () => [...new Set(nodes.map((node) => node.type).filter(Boolean))].sort(),
    [nodes],
  )
  const graphData = useMemo<GraphData<GraphNodeObject, GraphLinkObject>>(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase()
    const matches = (value: string | undefined) =>
      !normalizedQuery || (value ?? '').toLocaleLowerCase().includes(normalizedQuery)
    const matchingEdges = edges.filter((edge) => {
      const source = nodeById.get(edge.source)
      const target = nodeById.get(edge.target)
      const typeMatches = entityType === 'all' || source?.type === entityType || target?.type === entityType
      const queryMatches = [
        edge.predicate,
        edge.evidence,
        edge.evidence_source_title,
        source?.name,
        source?.type,
        target?.name,
        target?.type,
      ].some(matches)
      return typeMatches && queryMatches
    })
    const includedIds = new Set<string>()
    for (const edge of matchingEdges) {
      includedIds.add(edge.source)
      includedIds.add(edge.target)
    }

    const visibleNodes = nodes.filter((node) => {
      const typeMatches = entityType === 'all' || node.type === entityType
      const nodeMatches = [node.name, node.type, node.description].some(matches)
      return includedIds.has(node.id) || (typeMatches && nodeMatches)
    })
    const visibleIds = new Set(visibleNodes.map((node) => node.id))
    const visibleEdges = matchingEdges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target),
    )

    return {
      nodes: visibleNodes.map((node) => ({
        ...node,
        color: colorForType(node.type),
        val: 1.6,
      })),
      links: visibleEdges.map((edge) => ({
        ...edge,
        source: edge.source,
        target: edge.target,
      })),
    }
  }, [edges, entityType, nodeById, nodes, query])

  const selectedNodeEdges = selectedNode
    ? edges.filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
    : []
  const degreeById = useMemo(() => {
    const degree = new Map<string, number>()
    for (const edge of edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
    }
    return degree
  }, [edges])

  function selectEdge(link: LinkObject<GraphNode, GraphLink>) {
    const edge = edges.find((candidate) => candidate.id === link.id)
    if (edge) {
      setSelectedEdge(edge)
      setSelectedNode(null)
    }
  }

  return (
    <NotebookShell
      activeView="graph"
      email={email}
      onNavigate={onNavigate}
      onLogout={onLogout}
    >
      <main className="knowledge-graph-page">
        <header className="notebook-page-header knowledge-graph-page-header">
          <div>
            <p className="eyebrow">{t('graph.eyebrow')}</p>
            <h1>{t('graph.title')}</h1>
          </div>
          <div className="knowledge-graph-summary" aria-label={t('graph.summary')}>
            <span>{t('graph.entities')} <strong>{graph?.count.entities ?? 0}</strong></span>
            <span>{t('graph.relations')} <strong>{graph?.count.relations ?? 0}</strong></span>
          </div>
          <div className="knowledge-graph-actions">
            <button className="primary-button" type="button" onClick={() => void handleRebuild()} disabled={rebuilding || !knowledgeBaseId}>
              {rebuilding ? t('graph.jobRunning') : t('graph.rebuild')}
            </button>
          </div>
        </header>

        <section className="knowledge-graph-workspace">
          {error && <div className="message error-message" role="alert">{error}</div>}
          {notice && <div className="message success-message" role="status">{notice}</div>}

          {rebuildJob && (
            <section className={`knowledge-graph-job is-${rebuildJob.status}`} aria-live="polite">
              <div className="knowledge-graph-job-heading">
                <strong>
                  {{
                    pending: t('graph.jobPending'),
                    running: t('graph.jobRunning'),
                    completed: t('graph.completed'),
                    partial: t('graph.partialFailure'),
                    failed: t('graph.failed'),
                  }[rebuildJob.status]}
                </strong>
                <span>{rebuildJob.completed_count} / {rebuildJob.total_count}</span>
              </div>
              <progress
                max={Math.max(rebuildJob.total_count, 1)}
                value={rebuildJob.completed_count}
                aria-label={t('graph.progress')}
              />
              {rebuildJob.failed_count > 0 && (
                <span className="knowledge-graph-job-failures">
                  {rebuildJob.failed_count} {t('graph.failedItems')}
                </span>
              )}
            </section>
          )}

          <div className="knowledge-graph-canvas" ref={canvasRef}>
            <div className="knowledge-graph-toolbar">
              <label className="knowledge-graph-search">
                <span className="sr-only">{t('graph.searchLabel')}</span>
                <input
                  aria-label={t('graph.searchLabel')}
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t('graph.searchPlaceholder')}
                />
              </label>
              <label className="knowledge-graph-type-filter">
                <span className="sr-only">{t('graph.typeFilter')}</span>
                <select
                  aria-label={t('graph.typeFilter')}
                  value={entityType}
                  onChange={(event) => setEntityType(event.target.value)}
                >
                  <option value="all">{t('graph.allTypes')}</option>
                  {entityTypes.map((type) => <option key={type} value={type}>{type}</option>)}
                </select>
              </label>
              <button className="secondary-button" type="button" onClick={() => void refresh()} disabled={loading}>
                {t('graph.refresh')}
              </button>
            </div>

            {loading ? (
              <p className="knowledge-graph-canvas-message">{t('graph.loading')}</p>
            ) : graphData.nodes.length === 0 ? (
              <div className="knowledge-graph-canvas-message">
                <strong>{query || entityType !== 'all' ? t('graph.noMatches') : t('graph.emptyTitle')}</strong>
                <span>{query || entityType !== 'all' ? t('graph.adjustFilters') : t('graph.emptyHint')}</span>
              </div>
            ) : canvasSize.width > 0 && canvasSize.height > 0 ? (
              <Suspense fallback={<p className="knowledge-graph-canvas-message">{t('graph.loading')}</p>}>
                <ForceGraph2D
                  ref={graphRef}
                  width={canvasSize.width}
                  height={canvasSize.height}
                  graphData={graphData}
                  backgroundColor="#f8f8f6"
                  nodeRelSize={5}
                  nodeLabel={(node) => `${node.name} · ${node.type}`}
                  linkColor={() => edgeColor}
                  linkWidth={1.2}
                  linkLabel={(link) => String(link.predicate ?? '')}
                  linkDirectionalArrowLength={4}
                  linkDirectionalArrowRelPos={1}
                  linkDirectionalArrowColor={() => edgeColor}
                  onRenderFramePost={(context, scale) => {
                    const normalizedQuery = query.trim().toLocaleLowerCase()
                    const closeView = scale >= 2
                    const searched = (node: GraphNodeObject) =>
                      normalizedQuery.length > 0 && node.name.toLocaleLowerCase().includes(normalizedQuery)
                    const rankedNodes = [...graphData.nodes]
                      .filter((node) => {
                        const degree = degreeById.get(String(node.id)) ?? 0
                        return closeView || searched(node) || node.id === selectedNode?.id || degree >= 5 || (scale >= 0.9 && degree >= 2)
                      })
                      .sort((left, right) => {
                        const leftPriority = Number(left.id === selectedNode?.id) * 1000 + Number(searched(left)) * 500
                        const rightPriority = Number(right.id === selectedNode?.id) * 1000 + Number(searched(right)) * 500
                        return rightPriority - leftPriority ||
                          (degreeById.get(String(right.id)) ?? 0) - (degreeById.get(String(left.id)) ?? 0)
                      })

                    context.save()
                    context.font = `${12 / scale}px Inter, sans-serif`
                    const placedLabels: Array<ReturnType<typeof nodeLabelBounds>> = []
                    let labelCount = 0
                    const labelLimit = closeView ? rankedNodes.length : normalizedQuery ? 12 : scale >= 0.9 ? 24 : 10
                    for (const node of rankedNodes) {
                      if (labelCount >= labelLimit) break
                      const bounds = nodeLabelBounds(node, context, scale)
                      if (overlapsLabel(bounds, placedLabels)) continue
                      drawNode(node, context, scale)
                      placedLabels.push(bounds)
                      labelCount += 1
                    }
                    context.restore()

                    if (graphData.links.length <= 40 && scale >= 2) {
                      graphData.links.forEach((link) => drawLinkLabel(link, context, scale))
                    }
                  }}
                  cooldownTime={1600}
                  warmupTicks={24}
                  onEngineStop={() => graphRef.current?.zoomToFit(500, 36)}
                  onNodeClick={(node) => {
                    const selected = nodes.find((item) => item.id === node.id)
                    if (selected) {
                      setSelectedNode(selected)
                      setSelectedEdge(null)
                    }
                  }}
                  onLinkClick={selectEdge}
                  onBackgroundClick={() => {
                    setSelectedNode(null)
                    setSelectedEdge(null)
                  }}
                />
              </Suspense>
            ) : null}
          </div>

          {(selectedEdge || selectedNode) && (
            <section className="knowledge-graph-inspector" aria-live="polite">
              {selectedEdge ? (
                <>
                  <div className="knowledge-graph-inspector-heading">
                    <h2>{t('graph.relationDetails')}</h2>
                    <button type="button" className="secondary-button" onClick={() => setSelectedEdge(null)}>{t('graph.closeDetails')}</button>
                  </div>
                  <p className="knowledge-graph-inspector-triple">
                    <strong>{selectedEdge.source_entity_name}</strong>
                    <span>{selectedEdge.predicate}</span>
                    <strong>{selectedEdge.target_entity_name}</strong>
                  </p>
                  <p>{selectedEdge.evidence || t('graph.noEvidence')}</p>
                  <small>{t('graph.source')}: {selectedEdge.evidence_source_title} ({selectedEdge.source_type === 'note' ? t('nav.notes') : t('nav.knowledge')})</small>
                </>
              ) : selectedNode ? (
                <>
                  <div className="knowledge-graph-inspector-heading">
                    <h2>{selectedNode.name}</h2>
                    <button type="button" className="secondary-button" onClick={() => setSelectedNode(null)}>{t('graph.closeDetails')}</button>
                  </div>
                  <p>{selectedNode.type} · {selectedNode.source_count} {t('graph.sourcesCount')}</p>
                  {selectedNode.description && <p>{selectedNode.description}</p>}
                  <div className="knowledge-graph-related-relations">
                    {selectedNodeEdges.map((edge) => (
                      <button key={edge.id} type="button" onClick={() => setSelectedEdge(edge)}>
                        {edge.source_entity_name} {edge.predicate} {edge.target_entity_name}
                      </button>
                    ))}
                  </div>
                </>
              ) : null}
            </section>
          )}
        </section>
      </main>
    </NotebookShell>
  )
}
