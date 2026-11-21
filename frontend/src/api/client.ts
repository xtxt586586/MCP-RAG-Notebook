export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  'http://127.0.0.1:18765'

export const ACCESS_TOKEN_KEY = 'rag_access_token'
export const REFRESH_TOKEN_KEY = 'rag_refresh_token'
const CSRF_TOKEN_COOKIE = 'rag_csrf_token'
const CSRF_TOKEN_HEADER = 'X-CSRF-Token'

let refreshPromise: Promise<string | null> | null = null

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getCsrfToken() {
  if (typeof document === 'undefined') return null

  const cookie = document.cookie
    .split('; ')
    .find((item) => item.startsWith(`${CSRF_TOKEN_COOKIE}=`))

  return cookie
    ? decodeURIComponent(cookie.slice(CSRF_TOKEN_COOKIE.length + 1))
    : null
}

function isUnsafeMethod(method: string | undefined) {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(
    (method ?? 'GET').toUpperCase(),
  )
}

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => formatApiErrorDetail(item))
      .filter(Boolean)
      .join('；')
  }

  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    if (typeof record.msg === 'string') {
      const location = Array.isArray(record.loc)
        ? record.loc.filter((item): item is string | number => (
          typeof item === 'string' || typeof item === 'number'
        )).join('.')
        : ''

      return location ? `${location}：${record.msg}` : record.msg
    }

    return Object.entries(record)
      .map(([key, value]) => {
        const formatted = formatApiErrorDetail(value)
        return formatted ? `${key}：${formatted}` : ''
      })
      .filter(Boolean)
      .join('；')
  }

  return ''
}

export async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)

  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(getCsrfToken()
          ? { [CSRF_TOKEN_HEADER]: getCsrfToken() as string }
          : {}),
      },
      // New sessions use the HttpOnly refresh cookie. Keep accepting the
      // legacy localStorage token for users who have not signed in again yet.
      body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Refresh Token 无效或已经过期')
        }

        const payload = await response.json() as {
          access_token: string
          refresh_token: string
        }
        if (refreshToken) {
          localStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token)
          localStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token)
        }
        return payload.access_token
      })
      .catch(() => {
        localStorage.removeItem(ACCESS_TOKEN_KEY)
        localStorage.removeItem(REFRESH_TOKEN_KEY)
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

async function requestApi<T>(
  path: string,
  options: RequestInit = {},
  allowRefresh = true,
): Promise<T> {
  const token = getAccessToken()
  const headers = new Headers(options.headers)

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const csrfToken = getCsrfToken()
  if (csrfToken && isUnsafeMethod(options.method)) {
    headers.set(CSRF_TOKEN_HEADER, csrfToken)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: options.credentials ?? 'include',
      headers,
    })
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        `无法连接后端服务，请确认 Docker 已启动（${API_BASE_URL}）`,
        { cause: error },
      )
    }
    throw error
  }

  const payload = await response.json().catch(() => null) as unknown

  if (!response.ok) {
    const canRefresh = response.status === 401
      && allowRefresh
      && !path.includes('/auth/login')
      && !path.includes('/auth/register')
      && !path.includes('/auth/refresh')

    if (canRefresh && await refreshAccessToken()) {
      return requestApi<T>(path, options, false)
    }

    const errorPayload = payload && typeof payload === 'object'
      ? payload as { detail?: unknown }
      : null
    const detail = formatApiErrorDetail(errorPayload?.detail)
    throw new Error(
      detail || `请求失败：HTTP ${response.status}`,
    )
  }

  return payload as T
}

export function apiRequest<T>(path: string, options: RequestInit = {}) {
  return requestApi<T>(path, options)
}
