// Thin fetch wrapper for the Django REST API.
// Session cookies carry authentication; unsafe methods send Django's CSRF token.

// Fired when the server answers 401 to a normal request: the session ended
// (logout elsewhere, idle timeout, account suspended). AuthProvider listens.
export const UNAUTHORIZED_EVENT = 'auth:unauthorized'

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, message: string, data: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

function getCookie(name: string): string | undefined {
  return document.cookie
    .split('; ')
    .find((row) => row.startsWith(`${name}=`))
    ?.split('=')[1]
}

const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS']

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  if (!SAFE_METHODS.includes(method)) {
    const csrfToken = getCookie('csrftoken')
    if (csrfToken) headers.set('X-CSRFToken', csrfToken)
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',
  })

  const data = response.status === 204 ? null : await response.json().catch(() => null)

  if (response.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!response.ok) {
    const detail = (data as { detail?: string } | null)?.detail
    throw new ApiError(response.status, detail ?? `Request failed (${response.status})`, data)
  }
  return data as T
}

export interface HealthStatus {
  status: 'ok' | 'degraded'
  database: 'ok' | 'unavailable'
  database_engine: string
  currency: string
}

export const getHealth = () => apiRequest<HealthStatus>('/health/')

// --- Authentication ---

export interface Role {
  code: string
  name: string
}

export interface CurrentUser {
  id: number
  full_name: string
  email: string
  phone: string
  employee_id: string
  role: Role | null
  permissions: string[]
  account_status: 'ACTIVE' | 'SUSPENDED' | 'DEACTIVATED'
  mfa_enabled: boolean
  last_login: string | null
  created_at: string
}

export type LoginResponse = { mfa_required: true } | { mfa_required: false; user: CurrentUser }

export interface MfaSetup {
  secret: string
  otpauth_uri: string
}

const post = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const authApi = {
  csrf: () => apiRequest<{ detail: string }>('/auth/csrf/'),
  me: () => apiRequest<CurrentUser>('/auth/me/'),
  login: (email: string, password: string) => post<LoginResponse>('/auth/login/', { email, password }),
  verifyMfa: (code: string) => post<{ user: CurrentUser }>('/auth/mfa/verify/', { code }),
  logout: () => post<null>('/auth/logout/'),
  changePassword: (current_password: string, new_password: string) =>
    post<{ detail: string }>('/auth/change-password/', { current_password, new_password }),
  setupMfa: () => post<MfaSetup>('/auth/mfa/setup/'),
  confirmMfa: (code: string) => post<CurrentUser>('/auth/mfa/confirm/', { code }),
  disableMfa: (password: string, code: string) => post<CurrentUser>('/auth/mfa/disable/', { password, code }),
}

// First error message from a DRF error body: `detail`, or the first field error.
export function errorMessage(err: unknown, fallback = 'Something went wrong. Please try again.'): string {
  if (!(err instanceof ApiError)) return fallback
  const data = err.data as Record<string, unknown> | null
  if (data && typeof data.detail === 'string') return data.detail
  if (data) {
    for (const value of Object.values(data)) {
      if (Array.isArray(value) && typeof value[0] === 'string') return value[0]
      if (typeof value === 'string') return value
    }
  }
  return err.message || fallback
}
