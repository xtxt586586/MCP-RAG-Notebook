import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ACCESS_TOKEN_KEY,
  apiRequest,
  REFRESH_TOKEN_KEY,
} from './client'

describe('apiRequest token refresh', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('refreshes an expired access token and retries the request', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'expired-access-token')
    localStorage.setItem(REFRESH_TOKEN_KEY, 'valid-refresh-token')

    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: '认证凭证无效或已经过期' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: 'renewed-access-token',
          refresh_token: 'renewed-refresh-token',
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'ok' }),
      } as Response)

    await expect(apiRequest<{ status: string }>('/api/v1/auth/me')).resolves.toEqual({ status: 'ok' })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('renewed-access-token')
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('renewed-refresh-token')

    const retriedRequest = fetchMock.mock.calls[2]
    expect(new Headers(retriedRequest[1]?.headers).get('Authorization')).toBe('Bearer renewed-access-token')
  })

  it('refreshes from the HttpOnly cookie without creating localStorage tokens', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ detail: '认证凭证无效或已经过期' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          access_token: 'cookie-renewed-access-token',
          refresh_token: 'cookie-renewed-refresh-token',
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ status: 'ok' }),
      } as Response)

    await expect(apiRequest<{ status: string }>('/api/v1/auth/me')).resolves.toEqual({ status: 'ok' })

    const refreshRequest = fetchMock.mock.calls[1]
    expect(refreshRequest[0]).toContain('/api/v1/auth/refresh')
    expect(refreshRequest[1]?.body).toBe('{}')
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull()
  })

  it('shows a useful message when the backend cannot be reached', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(apiRequest('/api/v1/auth/me')).rejects.toThrow(
      '无法连接后端服务，请确认 Docker 已启动',
    )
  })

  it('formats FastAPI validation details instead of showing object object', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [{
          type: 'string_too_short',
          loc: ['body', 'password'],
          msg: '密码至少需要 8 个字符',
        }],
      }),
    } as Response)

    await expect(apiRequest('/api/v1/auth/register')).rejects.toThrow(
      'body.password：密码至少需要 8 个字符',
    )
  })
})
