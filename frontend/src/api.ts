import { reset } from './auth'
import type {
  Account,
  Calendar,
  ClassContext,
  ClassDetail,
  ClassInfo,
  ConfigurationChange,
  DailyPlan,
  DailyPlanCreateIn,
  DailyPlanPatchIn,
  ErrorBody,
  Me,
  SchoolSettings,
  TeacherListItem,
  Term,
} from './types'

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
  items: TeacherListItem[]
  total: number
  offset: number
  limit: number
}

export async function listTeachers(params: {
  offset: number
  limit: number
  q?: string
  assignment_status?: 'assigned' | 'pending_assignment'
}): Promise<TeacherList> {
  const query = new URLSearchParams()
  query.set('offset', String(params.offset))
  query.set('limit', String(params.limit))
  if (params.q) query.set('q', params.q)
  if (params.assignment_status) query.set('assignment_status', params.assignment_status)
  return request(`/admin/teachers?${query.toString()}`)
}

export async function assignTeacher(teacherId: string, payload: {
  class_id: string
  expected_version: number
  expected_class_version: number
}): Promise<{ account: Account; class_id: string; assignment_status: 'assigned' }> {
  return request(`/admin/teachers/${teacherId}/assignment`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// --- School settings / classes -------------------------------------------

export async function getSchoolSettings(): Promise<SchoolSettings> {
  return request('/admin/school-settings')
}

export async function listClasses(params: { offset: number; limit: number }): Promise<{
  items: ClassInfo[]
  total: number
  offset: number
  limit: number
}> {
  const query = new URLSearchParams()
  query.set('offset', String(params.offset))
  query.set('limit', String(params.limit))
  return request(`/admin/classes?${query.toString()}`)
}

export async function getClass(classId: string): Promise<ClassDetail> {
  return request(`/admin/classes/${classId}`)
}

// --- Configuration change preview / apply --------------------------------

export async function createPreview(payload: Record<string, unknown>): Promise<ConfigurationChange> {
  return request('/admin/configuration-changes/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getConfigurationChange(changeId: string): Promise<ConfigurationChange> {
  return request(`/admin/configuration-changes/${changeId}`)
}

export async function applyConfigurationChange(changeId: string): Promise<{
  status: 'applied'
  result_reference: string
  versions: Record<string, unknown>
}> {
  return request(`/admin/configuration-changes/${changeId}/apply`, {
    method: 'POST',
    body: JSON.stringify({ confirm: true }),
  })
}

// --- Terms / calendar reads ----------------------------------------------

export interface TermList {
  items: Term[]
  total: number
  offset: number
  limit: number
}

export async function listTerms(params: {
  offset: number
  limit: number
  admin?: boolean
}): Promise<TermList> {
  const path = params.admin ? '/admin/terms' : '/terms'
  const query = new URLSearchParams({
    offset: String(params.offset),
    limit: String(params.limit),
  })
  return request(`${path}?${query.toString()}`)
}

export async function getTerm(termId: string): Promise<Term> {
  return request(`/admin/terms/${termId}`)
}

export async function readCalendar(params: {
  from: string
  to: string
  admin?: boolean
}): Promise<Calendar> {
  const path = params.admin ? '/admin/calendar' : '/calendar'
  const query = new URLSearchParams({
    from: params.from,
    to: params.to,
  })
  return request(`${path}?${query.toString()}`)
}

// --- Teacher read-only context -------------------------------------------

export async function getClassContext(): Promise<ClassContext> {
  return request('/class-context')
}

export async function resetTeacherPassword(teacherId: string, payload: { new_password: string; expected_version: number }): Promise<{ account: Account; sessions_revoked: boolean }> {
  return request(`/admin/teachers/${teacherId}/password-reset`, { method: 'POST', body: JSON.stringify(payload) })
}

// --- I3 manual daily plan -------------------------------------------------
// Teacher path: never send class_id / term_id (server derives both from the
// assignment and the persisted calendar). Admin path: class_id is explicit
// and required; term_id is never sent.

export async function getDailyPlanByDate(planDate: string, classId?: string): Promise<DailyPlan> {
  const query = new URLSearchParams({ plan_date: planDate })
  if (classId) query.set('class_id', classId)
  return request(`/daily-plans/by-date?${query.toString()}`)
}

export async function createDailyPlan(payload: DailyPlanCreateIn): Promise<DailyPlan> {
  return request('/daily-plans', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getDailyPlan(planId: string, classId?: string): Promise<DailyPlan> {
  const query = new URLSearchParams()
  if (classId) query.set('class_id', classId)
  const suffix = query.toString()
  return request(`/daily-plans/${planId}${suffix ? `?${suffix}` : ''}`)
}

export async function patchDailyPlan(planId: string, payload: DailyPlanPatchIn): Promise<DailyPlan> {
  return request(`/daily-plans/${planId}`, { method: 'PATCH', body: JSON.stringify(payload) })
}
