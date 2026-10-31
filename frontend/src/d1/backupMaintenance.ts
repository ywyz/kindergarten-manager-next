/**
 * B2 backup/restore UI contract and pure state helpers.
 *
 * This module is intentionally UI-facing: the real native file chooser, file
 * handles, page ticket, session and core/runtime maintenance engine live in
 * the host adapter owned by the integrating session.  The panel never sees a
 * path, PID, command or URL; it only receives opaque request/operation ids and
 * display-safe DTOs.
 */

export type MaintenanceKind = 'backup' | 'restore'

export type MaintenancePhase =
  | 'idle'
  | 'selecting'
  | 'password'
  | 'creating'
  | 'verifying'
  | 'preview'
  | 'waiting'
  | 'protection'
  | 'switching'
  | 'reopening'
  | 'completed'
  | 'cancelled'
  | 'error'
  | 'recovery_required'

export interface MaintenanceRequestRef {
  requestId: string
}

export interface MaintenanceOperationRef {
  requestId: string
  operationId: string
  generation: number
}

/** Query/cancel accepts either the original request key or the active ref. */
export type MaintenanceLookupRef =
  | MaintenanceRequestRef
  | { operationId: string; generation: number }

export interface BackupTargetSelection {
  targetId: string
  displayName: string
}

export interface RestoreSelection {
  selectionId: string
  displayName: string
  encrypted: boolean
}

export interface BackupStartInput extends MaintenanceRequestRef {
  targetId: string
  password: string | null
  explicitPlaintext: boolean
}

export interface RestoreVerifyInput extends MaintenanceRequestRef {
  selectionId: string
  password: string | null
}

export interface RestoreConfirmInput extends MaintenanceRequestRef {
  operationId: string
  generation: number
  confirmationToken: string
}

export interface MaintenanceProgress {
  stage: string
  message?: string
  done?: number
  total?: number
  indeterminate?: boolean
}

export interface RestorePreviewView {
  displayName: string
  createdAt: string
  appVersion: string
  formatVersion: number
  dbRevision: string
  /** Opaque token bound to this operation/snapshot; never a path. */
  confirmationToken: string
  profileLabel?: string
  classLabel?: string
  termLabel?: string
  counts: {
    plans: number
    observations: number
    photos: number
    others?: number
  }
  credentialAvailability: 'available' | 'needs_reentry' | 'unknown'
}

export interface MaintenanceErrorView {
  code: string
  message: string
  committed: boolean
  nextAction:
    | 'retry_password'
    | 'retry_start'
    | 'retry_verify'
    | 'retry'
    | 'restart_app'
    | 'contact_support'
}

export interface MaintenanceStatus {
  requestId: string
  operationId: string | null
  generation: number
  kind: MaintenanceKind
  phase: MaintenancePhase
  progress?: MaintenanceProgress
  preview?: RestorePreviewView
  protection?: { displayText: string }
  error?: MaintenanceErrorView
  cancelRequested?: boolean
  stale?: boolean
  /** Restore only: host has reopened the new data and the UI may continue. */
  reopened?: boolean
}

export interface MaintenanceCompletion {
  kind: MaintenanceKind
  requestId: string
  operationId: string | null
  committed: boolean
  reopened: boolean
  protectionDisplay?: string
}

export type MaintenanceQuery =
  | { state: 'found'; status: MaintenanceStatus }
  | { state: 'unknown' }
  | { state: 'unavailable' }

export type CancelAck = {
  accepted: boolean
  state: 'cancelled' | 'too_late' | 'completed' | 'unknown'
}

export interface BackupRestoreHost {
  getStartupMaintenanceState(): Promise<{
    state: 'ready' | 'recovery_required'
    detail?: string
  }>
  chooseBackupTarget(): Promise<
    { ok: true; target: BackupTargetSelection } | { ok: false; canceled: true }
  >
  chooseRestoreSource(): Promise<
    { ok: true; selection: RestoreSelection } | { ok: false; canceled: true }
  >
  startBackup(input: BackupStartInput): Promise<MaintenanceOperationRef>
  startRestoreVerify(input: RestoreVerifyInput): Promise<MaintenanceOperationRef>
  confirmRestore(input: RestoreConfirmInput): Promise<MaintenanceOperationRef>
  queryMaintenance(input: MaintenanceLookupRef): Promise<MaintenanceQuery>
  cancelMaintenance(input: MaintenanceLookupRef): Promise<CancelAck>
}

export const REOPEN_FAILED_MESSAGE = '资料已恢复，重新打开失败，请重启应用'

const TERMINAL_PHASES: ReadonlySet<MaintenancePhase> = new Set([
  'completed',
  'cancelled',
  'error',
])

const ACTIVE_PHASES: ReadonlySet<MaintenancePhase> = new Set([
  'selecting',
  'password',
  'creating',
  'verifying',
  'preview',
  'waiting',
  'protection',
  'switching',
  'reopening',
])

export function isTerminalPhase(phase: MaintenancePhase): boolean {
  return TERMINAL_PHASES.has(phase)
}

export function isActivePhase(phase: MaintenancePhase): boolean {
  return ACTIVE_PHASES.has(phase)
}

/** Cancel is offered until a terminal state; switching/reopening answer honestly. */
export function canCancelPhase(phase: MaintenancePhase): boolean {
  return isActivePhase(phase)
}

export function canClosePhase(phase: MaintenancePhase): boolean {
  return phase === 'idle' || isTerminalPhase(phase)
}

const PHASE_RANK: Record<MaintenancePhase, number> = {
  idle: 0,
  selecting: 1,
  password: 2,
  creating: 3,
  verifying: 4,
  preview: 5,
  waiting: 6,
  protection: 7,
  switching: 8,
  reopening: 9,
  completed: 10,
  cancelled: 10,
  error: 10,
  recovery_required: 10,
}

/** Same-operation phases are irreversible; a late lower phase is stale. */
export function isPhaseRegression(
  current: MaintenancePhase,
  next: MaintenancePhase,
): boolean {
  return PHASE_RANK[next] < PHASE_RANK[current]
}

export function progressPercent(progress?: MaintenanceProgress): number | null {
  if (
    !progress ||
    progress.indeterminate ||
    typeof progress.done !== 'number' ||
    typeof progress.total !== 'number' ||
    !Number.isFinite(progress.done) ||
    !Number.isFinite(progress.total) ||
    progress.done < 0 ||
    progress.total <= 0
  ) {
    return null
  }
  return Math.max(0, Math.min(100, Math.round((progress.done / progress.total) * 100)))
}

export function progressLabel(progress?: MaintenanceProgress): string {
  if (!progress) return '等待维护操作…'
  const base = progress.stage || '等待维护操作…'
  return progress.message ? `${base}：${progress.message}` : base
}

export function errorText(error?: MaintenanceErrorView): string {
  if (!error) return ''
  if (error.code === 'REOPEN_FAILED') return REOPEN_FAILED_MESSAGE
  if (error.code === 'WRONG_PASSWORD') {
    return error.message || '密码不正确，请重新输入'
  }
  return error.message || '维护操作失败，请按提示处理'
}

/** A state reply is only accepted when it matches this exact operation/request. */
export function statusMatchesRef(
  ref: MaintenanceLookupRef,
  status: MaintenanceStatus,
): boolean {
  if (status.stale) return false
  if ('operationId' in ref) {
    return (
      status.operationId === ref.operationId &&
      status.generation === ref.generation
    )
  }
  return status.requestId === ref.requestId
}

export function operationRefOf(
  status: MaintenanceStatus,
): MaintenanceOperationRef | null {
  if (!status.operationId || status.stale) return null
  return {
    requestId: status.requestId,
    operationId: status.operationId,
    generation: status.generation,
  }
}

export function newRequestId(): string {
  return crypto.randomUUID()
}

export function phaseText(phase: MaintenancePhase, kind: MaintenanceKind): string {
  switch (phase) {
    case 'idle':
      return kind === 'restore' ? '从本地备份恢复' : '备份与恢复'
    case 'selecting':
      return '等待本地文件选择…'
    case 'password':
      return '输入备份密码'
    case 'creating':
      return '正在创建完整备份…'
    case 'verifying':
      return '正在校验备份…'
    case 'preview':
      return '校验完成：确认预览'
    case 'waiting':
      return '正在保存当前工作并等待已接受操作完成…'
    case 'protection':
      return '正在保留恢复前完整保护副本…'
    case 'switching':
      return '正在替换当前档案…'
    case 'reopening':
      return '正在重新打开资料…'
    case 'completed':
      return kind === 'restore' ? '恢复完成' : '备份完成'
    case 'cancelled':
      return '已取消，当前档案未更改'
    case 'error':
      return '维护操作未完成'
    case 'recovery_required':
      return '需要处理上次恢复状态'
  }
}
