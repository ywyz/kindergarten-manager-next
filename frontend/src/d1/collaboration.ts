/**
 * Typed client for the authenticated local collaboration proxy.
 *
 * The online origin, TLS settings and teacher credential remain in the desktop
 * backend process.  This module only talks to the same-origin local API and
 * never stores the credential in localStorage/sessionStorage or a URL.
 */

import { ApiError, apiDelete, apiGet, apiPost, pathSegment, sessionHeaders } from './client'
import { isIndeterminate } from './operations'
import type { GameLocation } from './types'

export interface CollaborationTeacher {
  teacher_id: string
  display_name: string
  school_id: string
  school_name: string
}

export interface CollaborationClass {
  class_id: string
  display_name: string
}

export interface CollaborationMembership {
  teacher_id: string
  school_id: string
  class_id: string
  class_name: string
  selected_at: string
}

export interface CollaborationClassmate {
  teacher_id: string
  display_name: string
  config_version: number
  config_updated_at: string | null
}

export interface CollaborationGamePayload {
  locations: GameLocation[]
  game_scope: string | null
  guidance: string | null
}

export interface CollaborationTextDiff {
  source: string | null
  target: string | null
  changed: boolean
}

export interface CollaborationLocationsDiff {
  source: GameLocation[]
  target: GameLocation[]
  changed: boolean
}

export interface CollaborationGameDiff {
  locations: CollaborationLocationsDiff
  game_scope: CollaborationTextDiff
  guidance: CollaborationTextDiff
  changed: boolean
}

export interface CollaborationRecoveryBinding {
  teacherId: string
  schoolId: string
}

export interface CollaborationStatus {
  configured: boolean
  connected: boolean
  teacher: CollaborationTeacher | null
  message: string | null
}

export interface CollaborationConfig {
  class_id: string
  config_version: number
  payload: CollaborationGamePayload
}

export interface CollaborationSaveResult {
  request_id: string
  class_id: string
  config_version: number
  changed: boolean
  payload: CollaborationGamePayload
  replayed?: boolean
}

export interface CollaborationPreview {
  request_id: string
  preview_token: string
  expires_at: string
  class_id: string
  source_teacher_id: string
  source_teacher_name: string
  source_version: number
  target_version: number
  source_payload: CollaborationGamePayload
  target_payload: CollaborationGamePayload
  diff: CollaborationGameDiff
}

export interface CollaborationConfirmResult {
  request_id: string
  class_id: string
  source_teacher_id: string
  source_version: number
  target_version: number
  config_version: number
  changed: boolean
  payload: CollaborationGamePayload
  replayed?: boolean
}

export type CollaborationOperation =
  | { request_id: string; kind: 'save'; result: CollaborationSaveResult }
  | { request_id: string; kind: 'import'; result: CollaborationConfirmResult }

export interface CollaborationSaveInput {
  request_id: string
  class_id: string
  expected_version: number
  change: {
    kind: 'class_games'
    locations: GameLocation[]
    game_scope: string | null
    guidance: string | null
  }
}

export interface CollaborationPreviewInput {
  request_id: string
  class_id: string
  source_teacher_id: string
}

export interface CollaborationConfirmInput {
  request_id: string
  preview_token: string
  source_teacher_id: string
  source_version: number
  target_version: number
}

export interface CollaborationApi {
  status(): Promise<CollaborationStatus>
  connect(
    credential: string,
    binding?: CollaborationRecoveryBinding | null,
  ): Promise<CollaborationStatus>
  disconnect(): Promise<CollaborationStatus>
  classes(): Promise<CollaborationClass[]>
  membership(): Promise<CollaborationMembership | null>
  selectClass(classId: string): Promise<CollaborationMembership>
  leaveClass(): Promise<{ removed: boolean }>
  classmates(): Promise<CollaborationClassmate[]>
  ownConfig(): Promise<CollaborationConfig>
  saveConfig(input: CollaborationSaveInput): Promise<CollaborationSaveResult>
  previewImport(input: CollaborationPreviewInput): Promise<CollaborationPreview>
  confirmImport(input: CollaborationConfirmInput): Promise<CollaborationConfirmResult>
  getOperation(requestId: string): Promise<CollaborationOperation>
}

/**
 * The local client has no generic PUT helper.  Keep the same-origin session
 * header and error envelope without adding a dependency or storing the token.
 */
async function apiPut<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'PUT',
      headers: {
        'cache-control': 'no-store',
        ...sessionHeaders(),
        'content-type': 'application/json',
      },
      mode: 'same-origin',
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '网络请求异常，请稍后重试')
  }
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = (payload as {
      error?: {
        code?: string
        message?: string
        details?: Record<string, unknown>
      }
    } | null)?.error
    throw new ApiError(
      response.status,
      error?.message || '请求失败',
      error?.code,
      error?.details,
    )
  }
  if (payload === null) {
    throw new ApiError(0, '响应无法解析，结果未知')
  }
  return payload as T
}

export function createCollaborationApi(): CollaborationApi {
  return {
    status: () => apiGet<CollaborationStatus>('/api/local/collaboration/status'),
    connect: (credential, binding) =>
      apiPost<CollaborationStatus>('/api/local/collaboration/connect', {
        credential,
        ...(binding
          ? {
              expected_teacher_id: binding.teacherId,
              expected_school_id: binding.schoolId,
            }
          : {}),
      }),
    disconnect: () => apiPost<CollaborationStatus>('/api/local/collaboration/disconnect'),
    classes: () => apiGet<CollaborationClass[]>('/api/local/collaboration/classes'),
    membership: async () => {
      const data = await apiGet<{
        membership: CollaborationMembership | null
      }>('/api/local/collaboration/class')
      return data.membership
    },
    selectClass: (classId) =>
      apiPut('/api/local/collaboration/class', { class_id: classId }),
    leaveClass: () =>
      apiDelete<{ removed: boolean }>('/api/local/collaboration/class', {}),
    classmates: () => apiGet<CollaborationClassmate[]>('/api/local/collaboration/classmates'),
    ownConfig: () => apiGet<CollaborationConfig>('/api/local/collaboration/game-config'),
    saveConfig: (input) =>
      apiPut<CollaborationSaveResult>(
        '/api/local/collaboration/game-config',
        input,
      ),
    previewImport: (input) =>
      apiPost<CollaborationPreview>('/api/local/collaboration/game-config/preview', input),
    confirmImport: (input) =>
      apiPost<CollaborationConfirmResult>('/api/local/collaboration/game-config/confirm', input),
    getOperation: (requestId) =>
      apiGet<CollaborationOperation>(
        `/api/local/collaboration/game-config/operations/${pathSegment(requestId)}`,
      ),
  }
}

/**
 * Writes are reconciled through the original request ID when the outcome is
 * unknown.  A session change during an in-flight write is also ambiguous: the
 * online request may already have committed, so it must keep its pending
 * receipt instead of being treated as a definite conflict.
 */
export function collaborationWriteIndeterminate(err: unknown): boolean {
  if (isIndeterminate(err)) return true
  return err instanceof ApiError && err.code === 'COLLABORATION_SESSION_CHANGED'
}

const COLLABORATION_CONFLICT_CODES = new Set([
  'COLLABORATION_SOURCE_VERSION_CHANGED',
  'COLLABORATION_TARGET_VERSION_CHANGED',
  'COLLABORATION_MEMBERSHIP_CHANGED',
  'COLLABORATION_PREVIEW_INVALID',
  'COLLABORATION_PREVIEW_EXPIRED',
  'COLLABORATION_PREVIEW_BINDING_MISMATCH',
])

export function isCollaborationConflictError(err: unknown): boolean {
  return (
    err instanceof ApiError
    && typeof err.code === 'string'
    && COLLABORATION_CONFLICT_CODES.has(err.code)
  )
}

const RESUBMIT_UNCOMMITTED_SAVE_CODES = new Set([
  'COLLABORATION_TARGET_VERSION_CHANGED',
])

const RESUBMIT_UNCOMMITTED_IMPORT_CODES = new Set([
  'COLLABORATION_PREVIEW_EXPIRED',
  'COLLABORATION_SOURCE_VERSION_CHANGED',
  'COLLABORATION_TARGET_VERSION_CHANGED',
  'COLLABORATION_MEMBERSHIP_CHANGED',
  'COLLABORATION_SOURCE_CONFIG_MISSING',
])

/**
 * Only the explicit same-request resubmit can prove that no receipt was
 * committed: the collaboration service checks the existing operation before
 * these live version/membership/expiry checks.  A query 404, network failure,
 * auth/permission error or any error raised before the receipt check remains
 * an unknown write and keeps the pending receipt.
 */
export function isCollaborationResubmitUncommittedError(
  err: unknown,
  kind: 'save' | 'import',
): boolean {
  if (!(err instanceof ApiError) || typeof err.code !== 'string') return false
  return (
    kind === 'save'
      ? RESUBMIT_UNCOMMITTED_SAVE_CODES.has(err.code)
      : RESUBMIT_UNCOMMITTED_IMPORT_CODES.has(err.code)
  )
}

export function isCollaborationAuthError(err: unknown): boolean {
  return (
    err instanceof ApiError
    && (err.status === 401 || err.code === 'COLLABORATION_AUTH_FAILED')
  )
}

export function isCollaborationSessionInvalidError(err: unknown): boolean {
  return (
    isCollaborationAuthError(err)
    || (
      err instanceof ApiError
      && (
        err.code === 'COLLABORATION_SESSION_CHANGED'
        || err.code === 'COLLABORATION_NOT_CONNECTED'
      )
    )
  )
}

/** Only display messages authored by the local proxy, never upstream text. */
export function collaborationErrorMessage(
  err: unknown,
  fallback: string,
): string {
  if (
    err instanceof ApiError
    && typeof err.code === 'string'
    && err.code.startsWith('COLLABORATION_')
  ) {
    return err.message
  }
  return fallback
}
