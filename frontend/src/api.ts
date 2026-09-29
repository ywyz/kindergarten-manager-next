import { reset } from './auth'
import type {
  Account,
  Calendar,
  ClassContext,
  ClassDetail,
  ClassInfo,
  ConfigurationChange,
  DailyMissingEntry,
  DailyPlan,
  DailyPlanCreateIn,
  DailyPlanPatchIn,
  ErrorBody,
  ExportDownloadResult,
  ExportWarning,
  Me,
  SchoolSettings,
  TeacherListItem,
  Term,
  WeeklyExportRequest,
  WeeklyPlanConfirmation,
  WeeklyPlanConfirmationList,
  WeeklyPlanConfirmIn,
  WeeklyPlanCreateIn,
  WeeklyPlanDetail,
  WeeklyPlanFacts,
  WeeklyPlanList,
  WeeklyPlanPatchIn,
} from './types'

const API_BASE = '/api'

export interface ApiError extends Error {
  status: number
  code: string
  fields?: Record<string, string>
  /** Present on I4 409 CONFIRM_ACK_REQUIRED: latest recomputed facts. */
  facts?: WeeklyPlanFacts
}

function makeError(message: string, status: number, body: ErrorBody | null): ApiError {
  const err = new Error(message) as ApiError
  err.status = status
  err.code = body?.error?.code || 'UNKNOWN_ERROR'
  err.fields = body?.error?.fields
  err.facts = body?.error?.facts
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

// --- I4 manual weekly plan -------------------------------------------------
// Teacher path: never send class_id at all (the backend 422s on presence,
// including explicit null). Admin path: an explicit class_id query parameter
// is required on every read and write; admins never call createWeeklyPlan.

function classIdSuffix(classId?: string): string {
  return classId ? `?class_id=${encodeURIComponent(classId)}` : ''
}

function withClassQuery(base: string, classId?: string): string {
  if (!classId) return base
  return `${base}${base.includes('?') ? '&' : '?'}class_id=${encodeURIComponent(classId)}`
}

export async function listWeeklyPlans(params: {
  offset: number
  limit: number
  term_id?: string
  classId?: string
}): Promise<WeeklyPlanList> {
  const query = new URLSearchParams()
  query.set('offset', String(params.offset))
  query.set('limit', String(params.limit))
  if (params.term_id) query.set('term_id', params.term_id)
  if (params.classId) query.set('class_id', params.classId)
  return request(`/weekly-plans?${query.toString()}`)
}

export async function createOrOpenWeeklyPlan(
  payload: WeeklyPlanCreateIn,
): Promise<WeeklyPlanDetail> {
  // class_id is intentionally never included here, not even as null.
  return request('/weekly-plans', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getWeeklyPlan(
  planId: string,
  classId?: string,
): Promise<WeeklyPlanDetail> {
  return request(`/weekly-plans/${planId}${classIdSuffix(classId)}`)
}

export async function patchWeeklyPlan(
  planId: string,
  payload: WeeklyPlanPatchIn,
  classId?: string,
): Promise<WeeklyPlanDetail> {
  return request(withClassQuery(`/weekly-plans/${planId}`, classId), {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function refreshWeeklyPlanSources(
  planId: string,
  payload: { expected_draft_version: number },
  classId?: string,
): Promise<WeeklyPlanDetail> {
  return request(withClassQuery(`/weekly-plans/${planId}/refresh-sources`, classId), {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function confirmWeeklyPlan(
  planId: string,
  payload: WeeklyPlanConfirmIn,
  classId?: string,
): Promise<WeeklyPlanConfirmation> {
  return request(withClassQuery(`/weekly-plans/${planId}/confirm`, classId), {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function listWeeklyPlanConfirmations(
  planId: string,
  classId?: string,
): Promise<WeeklyPlanConfirmationList> {
  return request(`/weekly-plans/${planId}/confirmations${classIdSuffix(classId)}`)
}

export async function getWeeklyPlanConfirmation(
  planId: string,
  version: number,
  classId?: string,
): Promise<WeeklyPlanConfirmation> {
  return request(
    `/weekly-plans/${planId}/confirmations/${version}${classIdSuffix(classId)}`,
  )
}

// --- I5 Word export (slice 3) ----------------------------------------------
// Binary helper: DOCX must never ride the JSON `request<T>()` path. A
// successful download returns the blob plus the server-decided filename and
// warning header; every failure keeps the slice-3 error fields (facts,
// expected_context, reason, limit, selected_count) so the views can drive
// the 409 ack loop. The requests still carry credentials, JSON content type
// and the same-origin Origin header; 401 resets the session like elsewhere.

/** Extended error shape maintained by exportBinary (I5 slice 3). */
export interface ExportError extends Error {
  status: number
  code: string
  /** 409 EXPORT_ACK_REQUIRED: server-grouped daily missing facts. */
  facts?: DailyMissingEntry[]
  /** 409 EXPORT_ACK_REQUIRED: echo back unchanged after user confirms. */
  expected_context?: Record<string, unknown> | null
  /** 'missing' | 'context_changed'. */
  reason?: string
  /** 422 EXPORT_RANGE_TOO_LARGE. */
  limit?: number
  selected_count?: number
}

export type { WeeklyExportRequest }

function makeExportError(
  message: string,
  status: number,
  body: Record<string, unknown> | null,
): ExportError {
  const err = new Error(message) as ExportError
  err.status = status
  err.code = (body?.error as Record<string, unknown> | undefined)?.code as string || 'UNKNOWN_ERROR'
  const error = (body?.error ?? {}) as Record<string, unknown>
  if (error.facts) err.facts = error.facts as DailyMissingEntry[]
  if (error.expected_context !== undefined) {
    err.expected_context = error.expected_context as Record<string, unknown> | null
  }
  if (error.reason) err.reason = error.reason as string
  if (error.limit !== undefined) err.limit = error.limit as number
  if (error.selected_count !== undefined) err.selected_count = error.selected_count as number
  return err
}

function parseWarningsHeader(value: string | null): ExportWarning[] {
  if (!value) return []
  try {
    const parsed: unknown = JSON.parse(value)
    if (Array.isArray(parsed)) {
      return parsed
        .filter(
          (item): item is ExportWarning =>
            !!item &&
            typeof (item as ExportWarning).code === 'string' &&
            (item as ExportWarning).code !== '',
        )
        .map((item) => ({
          code: item.code,
          ...(typeof item.reason === 'string' ? { reason: item.reason } : {}),
        }))
    }
  } catch {
    // Defensive: a future format change still surfaces something readable.
  }
  const trimmed = value.trim()
  return trimmed ? [{ code: trimmed }] : []
}

/** Extracts the download filename from Content-Disposition (RFC 5987 first). */
export function filenameFromDisposition(value: string | null): string {
  if (!value) return ''
  const utf8 = /filename\*=UTF-8''([^;\s]+)/i.exec(value)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      // fall through to the ASCII fallback
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(value)
  return ascii ? ascii[1] : ''
}

async function exportBinary(path: string, payload: unknown): Promise<ExportDownloadResult> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json, application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
    body: JSON.stringify(payload),
  })
  if (res.ok) {
    const blob = await res.blob()
    return {
      blob,
      filename: filenameFromDisposition(res.headers.get('Content-Disposition')),
      warnings: parseWarningsHeader(res.headers.get('X-Export-Warnings')),
    }
  }
  if (res.status === 401) {
    dispatchUnauthorized()
  }
  let body: Record<string, unknown> | null = null
  try {
    const text = await res.text()
    body = text ? (JSON.parse(text) as Record<string, unknown>) : null
  } catch {
    // non-JSON error body
  }
  throw makeExportError(
    (body?.error as Record<string, unknown> | undefined)?.message as string || `HTTP ${res.status}`,
    res.status,
    body,
  )
}

export async function exportDailyPlans(payload: {
  from: string
  to: string
  ack_missing?: boolean
  expected_context?: Record<string, unknown> | null
  class_id?: string
}): Promise<ExportDownloadResult> {
  return exportBinary('/exports/daily-plans', payload)
}

export async function exportWeeklyPlans(
  payload: WeeklyExportRequest,
): Promise<ExportDownloadResult> {
  return exportBinary('/exports/weekly-plans', payload)
}
