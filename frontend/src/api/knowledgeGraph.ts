import { apiRequest } from './client'

export type KnowledgeGraphNode = {
  id: string
  name: string
  type: string
  description: string
  source_count: number
}

export type KnowledgeGraphEdge = {
  id: string
  source: string
  target: string
  predicate: string
  evidence: string
  source_type: string
  source_id: string
  source_entity_name: string
  target_entity_name: string
  evidence_source_title: string
}

export type KnowledgeGraphData = {
  knowledge_base_id: string
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  count: { entities: number; relations: number }
}

export type GraphRebuildJob = {
  job_id: string
  status: 'pending' | 'running' | 'completed' | 'partial' | 'failed'
  total_count: number
  completed_count: number
  failed_count: number
  queued_notes?: number
  queued_documents?: number
  created_at?: string
  finished_at?: string | null
}

export function getKnowledgeGraph(knowledgeBaseId: string) {
  const params = new URLSearchParams({ knowledge_base_id: knowledgeBaseId })
  return apiRequest<KnowledgeGraphData>(`/api/v1/knowledge-graph?${params}`)
}

export function rebuildKnowledgeGraph(knowledgeBaseId: string) {
  const params = new URLSearchParams({ knowledge_base_id: knowledgeBaseId })
  return apiRequest<GraphRebuildJob>(
    `/api/v1/knowledge-graph/rebuild?${params}`,
    { method: 'POST' },
  )
}

export function getGraphRebuildStatus(jobId: string) {
  return apiRequest<GraphRebuildJob>(`/api/v1/knowledge-graph/rebuild/${jobId}`)
}
