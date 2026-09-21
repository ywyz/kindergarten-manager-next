import { reset } from './auth'
import type { Account, ErrorBody, Me } from './types'

const API_BASE = '/api'

export interface ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string>
}

function makeError(message: string, status: number, body: ErrorBody | null): ApiError {
  const err = new Error(message) as ApiError
  err.status = status
  err.code = body?.error?.code || 'UNKNOWN_ERROR'
  err.fields = body?.error?.fields
  return err
}

function dispatchUnauthorized() {
  reset()
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('auth:required'))
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: 'include',
    headers,
  })

  if (res.status === 204) {
    return undefined as T
  }

  let body: ErrorBody | null = null
  try {
    body = await res.json()
  } catch {
    // non-JSON error
  }

  if (!res.ok) {
    if (res.status === 401) {
      dispatchUnauthorized()
    }
    throw makeError(body?.error?.message || `HTTP ${res.status}`, res.status, body)
  }
  return body as T
}

export async function fetchMe(): Promise<Me> {
  return request<Me>('/auth/me')
}

export async function register(payload: { username: string; password: string }): Promise<{ account: Account; next_action: string }> {
  return request('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
}

export async function login(payload: { username: string; password: string }): Promise<Me> {
  return request('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
}

export async function logout(): Promise<void> {
  return request('/auth/logout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export async function updateProfile(payload: { display_name: string | null; expected_version: number }): Promise<Account> {
  return request('/settings/profile', { method: 'PATCH', body: JSON.stringify(payload) })
}

export async function changePassword(payload: { current_password: string; new_password: string; expected_version: number }): Promise<void> {
  return request('/settings/password', { method: 'POST', body: JSON.stringify(payload) })
}

export interface TeacherList {
  items: Account[]
  total: number
  offset: number
  limit: number
}

export async function listTeachers(params: { offset: number; limit: number; q?: string }): Promise<TeacherList> {
  const query = new URLSearchParams()
  query.set('offset', String(params.offset))
  query.set('limit', String(params.limit))
  if (params.q) query.set('q', params.q)
  return request(`/admin/teachers?${query.toString()}`)
}

export async function resetTeacherPassword(teacherId: string, payload: { new_password: string; expected_version: number }): Promise<{ account: Account; sessions_revoked: boolean }> {
  return request(`/admin/teachers/${teacherId}/password-reset`, { method: 'POST', body: JSON.stringify(payload) })
}
