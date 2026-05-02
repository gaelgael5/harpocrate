/**
 * Thin fetch wrapper for the Harpocrate backend API.
 *
 * - Adds Authorization header from oidc-client-ts session
 * - Maps HTTP errors to typed ApiError
 * - Base URL: /v1 (proxied by Vite dev server to http://localhost:8000)
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isFirstLogin(): boolean {
    return this.code === 'first_login'
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }

  get isNotFound(): boolean {
    return this.status === 404
  }
}

// Token provider — set by OIDC setup
let _tokenProvider: (() => Promise<string | null>) | null = null

export function setTokenProvider(fn: () => Promise<string | null>): void {
  _tokenProvider = fn
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  if (!_tokenProvider) return {}
  const token = await _tokenProvider()
  if (!token) return {}
  return { Authorization: `Bearer ${token}` }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const authHeaders = await getAuthHeaders()
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...authHeaders,
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`/v1${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 204) {
    return undefined as T
  }

  let json: unknown
  const text = await response.text()
  try {
    json = JSON.parse(text)
  } catch {
    throw new ApiError(response.status, 'parse_error', text)
  }

  if (!response.ok) {
    const errJson = json as Record<string, unknown>
    // FastAPI wrap nos HTTPException(detail={...}) sous { "detail": { error, message } }.
    // On supporte les 3 formes : root {error,message}, root {detail:str}, root {detail:{error,message}}.
    const rootMsg = errJson['message']
    const rootErr = errJson['error']
    const detail = errJson['detail']

    let code: string
    let msg: string
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const d = detail as Record<string, unknown>
      code = (d['error'] as string | undefined) ?? (rootErr as string | undefined) ?? 'error'
      msg =
        (d['message'] as string | undefined) ??
        (rootMsg as string | undefined) ??
        response.statusText
    } else if (typeof detail === 'string') {
      code = (rootErr as string | undefined) ?? 'error'
      msg = detail
    } else {
      code = (rootErr as string | undefined) ?? 'error'
      msg = (rootMsg as string | undefined) ?? response.statusText
    }
    throw new ApiError(response.status, code, msg)
  }

  return json as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown) => request<T>('POST', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  delete: <T>(path: string, body?: unknown) =>
    request<T>('DELETE', path, body),
}
