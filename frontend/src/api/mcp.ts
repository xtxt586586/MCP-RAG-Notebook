import { apiRequest } from './client'
import type { MCPServer } from '../types'

export async function getMCPRegistryMode() {
  return apiRequest<{ dynamic_enabled: boolean }>('/api/v1/mcp/registry/mode')
}

export async function listStaticMCPServers() {
  return apiRequest<{ servers: Array<{ name: string; enabled: boolean; transport: string }> }>('/api/v1/mcp/servers')
}

export async function listMCPServers() {
  return apiRequest<MCPServer[]>(
    '/api/v1/mcp/registry/servers',
  )
}

export async function updateMCPServer(
  serverId: string,
  data: Partial<Pick<
    MCPServer,
    'enabled' | 'allowed_tools' | 'timeout_seconds'
  >>,
) {
  return apiRequest<MCPServer>(
    `/api/v1/mcp/registry/servers/${serverId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(data),
    },
  )
}

export async function discoverMCPTools(
  serverName: string,
) {
  return apiRequest<{
    server_name: string
    count: number
    tools: Array<{
      name: string
      description?: string | null
      inputSchema?: Record<string, unknown>
    }>
  }>(
    `/api/v1/mcp/servers/${encodeURIComponent(serverName)}/tools`,
  )
}
