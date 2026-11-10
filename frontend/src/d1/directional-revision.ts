/**
 * Shared directional-revision client and pure guards.
 *
 * One teacher-selected range, one instruction and one immutable submission
 * snapshot. The dialog never writes business data: it previews the candidate
 * and hands an explicit adoption payload back to the owning page.
 */
import { ApiError, apiGet, apiPost, pathSegment } from './client'

export type DirectionalScopeKind =
  | 'listening_record'
  | 'listening_candidate'
  | 'weekly_candidate'

export type DirectionalListeningField =
  | 'listening_text'
  | 'goal'
  | 'overall_evaluation'
  | 'support_strategy'

export interface DirectionalScope {
  kind: DirectionalScopeKind
  record_id: string
  version: number
  candidate_id?: string
  task_id?: string
  domain?: string
  group_id?: string
  field: string
}

export interface DirectionalSelection {
  start: number
  end: number
  text: string
}

export interface DirectionalRevisionBody {
  request_id: string
  scope: DirectionalScope
  field_text: string
  selection: DirectionalSelection
  instruction: string
}

export type DirectionalTaskStatus =
  | 'pending'
  | 'claimed'
  | 'dispatching'
  | 'retry_wait'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'outcome_unknown'
  | 'cancelled'

export type DirectionalCandidateStatus = 'proposed' | 'clarify' | 'no_change'

export interface DirectionalCandidate {
  status: DirectionalCandidateStatus
  replacement: string | null
  question: string
  notice: string
}

export interface DirectionalTask {
  id: string
  status: DirectionalTaskStatus
  reason: string | null
  candidate: DirectionalCandidate | null
}

export interface DirectionalSnapshot {
  sessionEpoch: number
  profileEpoch: number
  scope: DirectionalScope
  fieldText: string
  selection: DirectionalSelection
}

export interface DirectionalAdoptPayload {
  replacement: string
  fieldAfter: string
  snapshot: DirectionalSnapshot
  candidate: DirectionalCandidate
}

export interface DirectionalApplyResult {
  ok: boolean
  message?: string
}

export class DirectionalResponseError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DirectionalResponseError'
  }
}

export interface DirectionalOpenRequest {
  scope: DirectionalScope
  fieldText: string
  selection: DirectionalSelection
  sourceLabel: string
  sourceLines: string[]
  sourceStale?: boolean
  target?: string
}

const STATUS_LABELS: Record<DirectionalTaskStatus, string> = {
  pending: '排队中',
  claimed: '已领取，准备发送',
  dispatching: '正在等待供应商返回',
  retry_wait: '等待安全重试',
  paused: '已暂停',
  succeeded: '已生成建议',
  failed: '失败',
  outcome_unknown: '结果不明（可能已发送）',
  cancelled: '已取消',
}

export function directionalStatusLabel(status: string): string {
  return STATUS_LABELS[status as DirectionalTaskStatus] ?? status
}

const REASON_LABELS: Record<string, string> = {
  auth_rejected: '供应商拒绝鉴权：请核对地址、模型与密钥',
  rate_limited: '供应商限流：请稍后再试',
  provider_error: '供应商返回错误',
  output_invalid: '供应商输出不符合约定结构：本次不会自动纠错重发',
  endpoint_blocked: '地址未通过安全校验，已拒绝连接',
  tls_invalid: 'TLS 证书校验失败，已终止本次请求',
  connection_unavailable: '无法连接供应商：请检查网络与地址',
  timeout_after_dispatch: '发送后超时：结果不明，不会自动重发',
  response_header_timeout: '等待供应商响应头超时：结果不明，不会自动重发',
  malformed_response: '供应商响应格式异常，无法解析：不会自动重发',
  incomplete_transfer: '响应传输中断：结果不明，不会自动重发',
  wire_framing_invalid: '响应分帧无效，传输未完整结束：不会自动重发',
  reasoning_only: '只收到推理内容，没有可用正文：本次未生成建议',
  output_length: '供应商输出达到长度上限：本次未生成建议',
  candidate_contract_invalid: '候选结构校验未通过：本次未生成建议',
  user_stop: '已按你的要求停止等待（不表示供应商已停止处理）',
  restart: '应用重启后暂停：需手动继续',
  source_changed: '生成输入已变化：只能重新发起，不会暗中换输入',
}

export function directionalReasonLabel(
  reason: string | null | undefined,
): string {
  if (!reason) return ''
  return REASON_LABELS[reason] ?? reason
}

export function directionalTaskIsLive(status: string): boolean {
  return (
    status === 'pending' ||
    status === 'claimed' ||
    status === 'dispatching' ||
    status === 'retry_wait'
  )
}

export function directionalTaskIsTerminal(status: string): boolean {
  return (
    status === 'succeeded' ||
    status === 'failed' ||
    status === 'paused' ||
    status === 'outcome_unknown' ||
    status === 'cancelled'
  )
}

const API_ROOT = '/api/local/directional-revisions'

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

const CANDIDATE_STATUSES = new Set<DirectionalCandidateStatus>([
  'proposed',
  'clarify',
  'no_change',
])

const TASK_STATUSES = new Set<DirectionalTaskStatus>([
  'pending',
  'claimed',
  'dispatching',
  'retry_wait',
  'paused',
  'succeeded',
  'failed',
  'outcome_unknown',
  'cancelled',
])

function normalizeCandidate(value: unknown): DirectionalCandidate | null {
  if (value === null || value === undefined) return null
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw new DirectionalResponseError('候选结构不合法')
  }
  const raw = value as Record<string, unknown>
  const status = stringValue(raw.status)
  if (!CANDIDATE_STATUSES.has(status as DirectionalCandidateStatus)) {
    throw new DirectionalResponseError('候选状态不合法')
  }
  const replacement =
    typeof raw.replacement === 'string' ? raw.replacement : null
  if (status === 'proposed' && replacement === null) {
    throw new DirectionalResponseError('候选缺少替换文字')
  }
  return {
    status: status as DirectionalCandidateStatus,
    replacement,
    question: stringValue(raw.question),
    notice: stringValue(raw.notice),
  }
}

export function normalizeDirectionalTask(
  value: unknown,
  fallbackId = '',
): DirectionalTask {
  const raw =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  const id = stringValue(raw.id)
  if (!id) throw new DirectionalResponseError('任务回包缺少 ID')
  if (fallbackId && id !== fallbackId) {
    throw new DirectionalResponseError('任务回包 ID 与请求不一致')
  }
  const status = stringValue(raw.status)
  if (!TASK_STATUSES.has(status as DirectionalTaskStatus)) {
    throw new DirectionalResponseError('任务状态不合法')
  }
  return {
    id,
    status: status as DirectionalTaskStatus,
    reason: typeof raw.reason === 'string' ? raw.reason : null,
    candidate: normalizeCandidate(raw.candidate),
  }
}

export async function createDirectionalRevision(
  body: DirectionalRevisionBody,
): Promise<DirectionalTask> {
  const data = await apiPost<unknown>(API_ROOT, body)
  return normalizeDirectionalTask(data)
}

export async function getDirectionalRevision(
  taskId: string,
): Promise<DirectionalTask> {
  const data = await apiGet<unknown>(
    `${API_ROOT}/${pathSegment(taskId)}`,
  )
  return normalizeDirectionalTask(data, taskId)
}

export function newDirectionalRequestId(): string {
  const cryptoObject = globalThis.crypto
  if (cryptoObject && typeof cryptoObject.randomUUID === 'function') {
    return cryptoObject.randomUUID()
  }
  const template = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
  return template.replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16)
    const digit = char === 'x' ? value : (value & 0x3) | 0x8
    return digit.toString(16)
  })
}

export function directionalIsIndeterminate(error: unknown): boolean {
  const status = (error as { status?: unknown })?.status
  if (typeof status !== 'number') return false
  if (status === 0) return true
  if (
    error instanceof ApiError &&
    error.code === 'AI_EXECUTOR_UNAVAILABLE'
  ) {
    return false
  }
  return status >= 500
}

export function directionalErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { message?: unknown }).message === 'string'
  ) {
    return (error as { message: string }).message
  }
  return String(error)
}

export function directionalSelectionKey(
  field: string,
  groupId = '',
  candidateId = '',
): string {
  return `${candidateId}:${field}:${groupId}`
}

function hasLoneSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1)
      if (!(next >= 0xdc00 && next <= 0xdfff)) return true
      index += 1
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true
    }
  }
  return false
}

function splitsSurrogate(value: string, index: number): boolean {
  if (index <= 0 || index >= value.length) return false
  const before = value.charCodeAt(index - 1)
  const after = value.charCodeAt(index)
  return (
    before >= 0xd800 &&
    before <= 0xdbff &&
    after >= 0xdc00 &&
    after <= 0xdfff
  )
}

export function validateDirectionalSelection(
  fieldText: string,
  selection: DirectionalSelection,
): string {
  if (
    !Number.isInteger(selection.start) ||
    !Number.isInteger(selection.end) ||
    selection.start < 0 ||
    selection.end < selection.start ||
    selection.end > fieldText.length
  ) {
    return '选段范围不合法'
  }
  if (
    splitsSurrogate(fieldText, selection.start) ||
    splitsSurrogate(fieldText, selection.end)
  ) {
    return '选段不能切断文字字符，请重新选择'
  }
  if (selection.start === selection.end && fieldText !== '') {
    return '非空正文的选区不能为空；请选择文字或使用整栏修改'
  }
  if (hasLoneSurrogate(fieldText.slice(selection.start, selection.end))) {
    return '选段不能切断文字字符，请重新选择'
  }
  if (fieldText.slice(selection.start, selection.end) !== selection.text) {
    return '选段与当前文字不一致，请重新选择'
  }
  return ''
}

export function wholeDirectionalSelection(fieldText: string): DirectionalSelection {
  return { start: 0, end: fieldText.length, text: fieldText }
}

export function applyDirectionalReplacement(
  fieldText: string,
  selection: DirectionalSelection,
  replacement: string,
): string {
  return (
    fieldText.slice(0, selection.start) +
    replacement +
    fieldText.slice(selection.end)
  )
}

export interface CapturedDirectionalSelection {
  key: string
  field: string
  groupId: string
  candidateId: string
  selection: DirectionalSelection
}

export function captureDirectionalSelection(
  event: Event,
): CapturedDirectionalSelection | null {
  const target = event.target as {
    value?: unknown
    selectionStart?: unknown
    selectionEnd?: unknown
    closest?: (selector: string) => Element | null
  } | null
  if (
    !target ||
    typeof target.value !== 'string' ||
    typeof target.selectionStart !== 'number' ||
    typeof target.selectionEnd !== 'number' ||
    typeof target.closest !== 'function'
  ) {
    return null
  }
  const holder = target.closest(
    '[data-directional-field]',
  ) as HTMLElement | null
  const field = holder?.dataset.directionalField ?? ''
  if (!field) return null
  const groupId = holder?.dataset.directionalGroupId ?? ''
  const candidateId = holder?.dataset.directionalCandidateId ?? ''
  const start = target.selectionStart
  const end = target.selectionEnd
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    end > target.value.length
  ) {
    return null
  }
  return {
    key: directionalSelectionKey(field, groupId, candidateId),
    field,
    groupId,
    candidateId,
    selection: {
      start,
      end,
      text: target.value.slice(start, end),
    },
  }
}

const SLOT_LABELS: Record<string, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
}

const WEEKLY_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  shared_objectives: '共同目标',
  guidance_points: '指导',
  focus_guidance: '重点指导',
  objectives: '目标',
  guidance: '指导',
  support_strategy: '支持策略',
}

export function directionalFieldLabel(field: string): string {
  if (field === 'listening_text') return '倾听正文'
  if (field === 'goal') return '观察目标'
  if (field === 'overall_evaluation') return '综合评价'
  if (field === 'support_strategy') return '支持策略'
  if (field === 'text') return '栏目正文'
  const slot = /^slot\.([^.]+)\.(.+)$/.exec(field)
  if (slot) {
    return `${SLOT_LABELS[slot[1]] ?? slot[1]} · ${
      WEEKLY_FIELD_LABELS[slot[2]] ?? slot[2]
    }`
  }
  const focus = /^focus\.(.+)$/.exec(field)
  if (focus) {
    return `重点区域 · ${WEEKLY_FIELD_LABELS[focus[1]] ?? focus[1]}`
  }
  const item = /^item\.(\d+)\.text$/.exec(field)
  if (item) return `材料第 ${Number(item[1]) + 1} 项`
  return field
}

function cloneScope(scope: DirectionalScope): DirectionalScope {
  const next: DirectionalScope = {
    kind: scope.kind,
    record_id: scope.record_id,
    version: scope.version,
    field: scope.field,
  }
  if (scope.candidate_id) next.candidate_id = scope.candidate_id
  if (scope.task_id) next.task_id = scope.task_id
  if (scope.domain) next.domain = scope.domain
  if (scope.group_id) next.group_id = scope.group_id
  return next
}

export function buildDirectionalRevisionBody(input: {
  requestId?: string
  scope: DirectionalScope
  fieldText: string
  selection: DirectionalSelection
  instruction: string
}): DirectionalRevisionBody {
  return {
    request_id: input.requestId ?? newDirectionalRequestId(),
    scope: cloneScope(input.scope),
    field_text: input.fieldText,
    selection: { ...input.selection },
    instruction: input.instruction.trim(),
  }
}

export function directionalScopeEquals(
  left: DirectionalScope,
  right: DirectionalScope,
): boolean {
  return (
    left.kind === right.kind &&
    left.record_id === right.record_id &&
    left.version === right.version &&
    left.field === right.field &&
    (left.candidate_id ?? '') === (right.candidate_id ?? '') &&
    (left.task_id ?? '') === (right.task_id ?? '') &&
    (left.domain ?? '') === (right.domain ?? '') &&
    (left.group_id ?? '') === (right.group_id ?? '')
  )
}

export function directionalSnapshotMatches(
  current: DirectionalSnapshot,
  submitted: DirectionalSnapshot,
): boolean {
  return (
    current.sessionEpoch === submitted.sessionEpoch &&
    current.profileEpoch === submitted.profileEpoch &&
    directionalScopeEquals(current.scope, submitted.scope) &&
    current.fieldText === submitted.fieldText &&
    current.selection.start === submitted.selection.start &&
    current.selection.end === submitted.selection.end &&
    current.selection.text === submitted.selection.text
  )
}