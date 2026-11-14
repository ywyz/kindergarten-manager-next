/**
 * Curriculum deliberation client core.
 *
 * The module owns the local API contract, the table-content shape, the
 * adjustment-status conflict check, the version-bound preview and the
 * authenticated DOCX read used by the existing native Save As bridge.
 */
import { ApiError, apiGet, apiPost, pathSegment, sessionHeaders } from './client'
import { isIndeterminate } from './operations'
import type { AiTaskProgress } from './types'

export type CurriculumFormKind =
  | ''
  | 'collective'
  | 'area'
  | 'parent_child'
  | 'small_group'
  | 'other'

export type CurriculumAdjustmentStatus = '' | 'unchanged' | 'adjusted'

export type CurriculumDocument = Record<string, unknown>

export interface CurriculumContent {
  activity_name: string
  activity_form: string
  activity_form_other: string
  institution: string
  class_name: string
  child_count: string
  organizer: string
  recorder: string
  activity_date: string
  goals_original: string
  goals_status: string
  goals_adjustment: string
  preparation_original: string
  preparation_status: string
  preparation_adjustment: string
  process_original: string
  process_adjustment: string
  reason: string
  lesson_original: string
  lesson_revised: string
}

export const CURRICULUM_CONTENT_FIELDS = [
  'activity_name',
  'activity_form',
  'activity_form_other',
  'institution',
  'class_name',
  'child_count',
  'organizer',
  'recorder',
  'activity_date',
  'goals_original',
  'goals_status',
  'goals_adjustment',
  'preparation_original',
  'preparation_status',
  'preparation_adjustment',
  'process_original',
  'process_adjustment',
  'reason',
  'lesson_original',
  'lesson_revised',
] as const satisfies ReadonlyArray<keyof CurriculumContent>

export const CURRICULUM_FORM_OPTIONS: ReadonlyArray<{
  value: Exclude<CurriculumFormKind, ''>
  label: string
}> = [
  { value: 'collective', label: '集体' },
  { value: 'area', label: '区域' },
  { value: 'parent_child', label: '亲子' },
  { value: 'small_group', label: '小组' },
  { value: 'other', label: '其他' },
]

export const CURRICULUM_STATUS_OPTIONS: ReadonlyArray<{
  value: Exclude<CurriculumAdjustmentStatus, ''>
  label: string
}> = [
  { value: 'unchanged', label: '保持原设计不变' },
  { value: 'adjusted', label: '有所调整' },
]
const FORM_VALUES = new Set(CURRICULUM_FORM_OPTIONS.map((item) => item.value))
const STATUS_VALUES = new Set(
  CURRICULUM_STATUS_OPTIONS.map((item) => item.value),
)

export function emptyCurriculumContent(): CurriculumContent {
  return {
    activity_name: '',
    activity_form: '',
    activity_form_other: '',
    institution: '',
    class_name: '',
    child_count: '',
    organizer: '',
    recorder: '',
    activity_date: '',
    goals_original: '',
    goals_status: '',
    goals_adjustment: '',
    preparation_original: '',
    preparation_status: '',
    preparation_adjustment: '',
    process_original: '',
    process_adjustment: '',
    reason: '',
    lesson_original: '',
    lesson_revised: '',
  }
}

/** Coerce one API content object without trimming body text. */
export function normalizeCurriculumContent(
  value: Partial<CurriculumContent> | null | undefined,
): CurriculumContent {
  const result = emptyCurriculumContent()
  if (!value || typeof value !== 'object') return result
  const source = value as Record<string, unknown>
  for (const field of CURRICULUM_CONTENT_FIELDS) {
    const raw = source[field]
    if (typeof raw === 'string') result[field] = raw
  }
  return result
}

export function cloneCurriculumContent(
  value: Partial<CurriculumContent> | null | undefined,
): CurriculumContent {
  return normalizeCurriculumContent(value)
}

export function curriculumContentEquals(
  left: Partial<CurriculumContent> | null | undefined,
  right: Partial<CurriculumContent> | null | undefined,
): boolean {
  const a = normalizeCurriculumContent(left)
  const b = normalizeCurriculumContent(right)
  return CURRICULUM_CONTENT_FIELDS.every((field) => a[field] === b[field])
}

function sortDocumentValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortDocumentValue)
  if (value && typeof value === 'object') {
    const source = value as Record<string, unknown>
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(source).sort()) {
      result[key] = sortDocumentValue(source[key])
    }
    return result
  }
  return value
}

export function cloneCurriculumDocument(
  value: unknown,
): CurriculumDocument | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  try {
    return JSON.parse(JSON.stringify(value)) as CurriculumDocument
  } catch {
    return null
  }
}

export function curriculumDocumentEquals(
  left: unknown,
  right: unknown,
): boolean {
  const a = cloneCurriculumDocument(left)
  const b = cloneCurriculumDocument(right)
  if (a === null || b === null) return a === b
  return (
    JSON.stringify(sortDocumentValue(a)) ===
    JSON.stringify(sortDocumentValue(b))
  )
}
export interface CurriculumConflict {
  key: 'goals' | 'preparation'
  label: string
  statusField: 'goals_status' | 'preparation_status'
  adjustmentField: 'goals_adjustment' | 'preparation_adjustment'
}

const CONFLICT_DEFINITIONS: ReadonlyArray<CurriculumConflict> = [
  {
    key: 'goals',
    label: '活动目标',
    statusField: 'goals_status',
    adjustmentField: 'goals_adjustment',
  },
  {
    key: 'preparation',
    label: '活动准备',
    statusField: 'preparation_status',
    adjustmentField: 'preparation_adjustment',
  },
]

/**
 * A checked "unchanged" option with adjustment text is a real ambiguity:
 * the Word checkbox and the retained text must be reconciled by the teacher,
 * never by silently clearing either side.
 */
export function curriculumConflicts(
  content: Partial<CurriculumContent> | null | undefined,
): CurriculumConflict[] {
  const normalized = normalizeCurriculumContent(content)
  return CONFLICT_DEFINITIONS.filter(
    (definition) =>
      normalized[definition.statusField] === 'unchanged' &&
      normalized[definition.adjustmentField].trim() !== '',
  ).map((definition) => ({ ...definition }))
}
export type CurriculumConflictChoice = 'keep' | 'clear'

export function applyCurriculumConflictChoice(
  content: CurriculumContent,
  conflict: CurriculumConflict,
  choice: CurriculumConflictChoice,
): CurriculumContent {
  const next = normalizeCurriculumContent(content)
  if (choice === 'keep') {
    next[conflict.statusField] = 'adjusted'
  } else {
    next[conflict.adjustmentField] = ''
  }
  return next
}

function isIsoDate(value: string): boolean {
  const match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value)
  if (!match) return false
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1) return false
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return day <= lastDay
}

/** Local field checks that must keep the teacher on the page. */
export function curriculumValidationErrors(
  content: Partial<CurriculumContent> | null | undefined,
): string[] {
  const normalized = normalizeCurriculumContent(content)
  const errors: string[] = []
  if (normalized.child_count && !/^[0-9]+$/.test(normalized.child_count)) {
    errors.push('幼儿人数请填写非负整数')
  }
  if (normalized.activity_date && !isIsoDate(normalized.activity_date)) {
    errors.push('活动时间请填写有效日期')
  }
  if (
    normalized.activity_form &&
    !FORM_VALUES.has(normalized.activity_form as Exclude<CurriculumFormKind, ''>)
  ) {
    errors.push('活动形式不在可选范围内')
  }
  for (const definition of CONFLICT_DEFINITIONS) {
    const status = normalized[definition.statusField]
    if (
      status &&
      !STATUS_VALUES.has(
        status as Exclude<CurriculumAdjustmentStatus, ''>,
      )
    ) {
      errors.push(`${definition.label}修订状态不在可选范围内`)
    }
  }
  return errors
}
export function newCurriculumRecordId(): string {
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

export function formatCurriculumUpdatedAt(value: string): string {
  if (!value) return ''
  return value.replace('T', ' ').slice(0, 16)
}

export interface CurriculumListRecord {
  id: string
  version: number
  activity_name: string
  activity_date: string
  updated_at: string
}

export interface CurriculumListResponse {
  records: CurriculumListRecord[]
  defaults: CurriculumContent
}

export interface CurriculumRecord {
  id: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  updated_at: string
}

export interface CurriculumExportPreview {
  id: string
  version: number
  activity_name: string
  activity_date: string
  missing: string[]
  appendices: Array<'original' | 'revised'>
}

export type CurriculumSaveOutcome =
  | 'saved'
  | 'unchanged'
  | 'failed'
  | 'conflict'
  | 'indeterminate'

const API_ROOT = '/api/local/curriculum-deliberations'
function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function versionValue(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0
}

function normalizeListRecord(value: unknown): CurriculumListRecord | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const id = stringValue(raw.id)
  if (!id) return null
  return {
    id,
    version: versionValue(raw.version),
    activity_name: stringValue(raw.activity_name),
    activity_date: stringValue(raw.activity_date),
    updated_at: stringValue(raw.updated_at),
  }
}

function normalizeRecord(value: unknown, fallbackId: string): CurriculumRecord {
  const raw =
    value && typeof value === 'object'
      ? (value as Record<string, unknown>)
      : {}
  return {
    id: stringValue(raw.id) || fallbackId,
    version: versionValue(raw.version),
    content: normalizeCurriculumContent(
      raw.content as Partial<CurriculumContent> | undefined,
    ),
    document: cloneCurriculumDocument(raw.document),
    updated_at: stringValue(raw.updated_at),
  }
}
export async function listCurriculumDeliberations(): Promise<CurriculumListResponse> {
  const data = await apiGet<{ records?: unknown; defaults?: unknown }>(API_ROOT)
  const records = Array.isArray(data.records)
    ? data.records
        .map(normalizeListRecord)
        .filter((item): item is CurriculumListRecord => item !== null)
    : []
  return {
    records,
    defaults: normalizeCurriculumContent(
      data.defaults as Partial<CurriculumContent> | undefined,
    ),
  }
}

export async function getCurriculumDeliberation(
  id: string,
): Promise<CurriculumRecord> {
  const data = await apiGet<unknown>(`${API_ROOT}/${pathSegment(id)}`)
  return normalizeRecord(data, id)
}

export async function saveCurriculumDeliberation(
  id: string,
  expectedVersion: number,
  content: CurriculumContent,
  document: CurriculumDocument | null = null,
): Promise<CurriculumRecord> {
  const data = await apiPost<unknown>(
    `${API_ROOT}/${pathSegment(id)}/save`,
    {
      expected_version: expectedVersion,
      content: normalizeCurriculumContent(content),
      document: cloneCurriculumDocument(document),
    },
  )
  const record = normalizeRecord(data, id)
  if (!data || typeof data !== 'object' || !('document' in data)) {
    record.document = cloneCurriculumDocument(document)
  }
  return record
}

export async function previewCurriculumDeliberation(
  id: string,
  version: number,
): Promise<CurriculumExportPreview> {
  const data = await apiGet<unknown>(
    `${API_ROOT}/${pathSegment(id)}/export-preview?version=${encodeURIComponent(String(version))}`,
  )
  const raw =
    data && typeof data === 'object'
      ? (data as Record<string, unknown>)
      : {}
  const appendices = Array.isArray(raw.appendices)
    ? raw.appendices.filter(
        (item): item is 'original' | 'revised' =>
          item === 'original' || item === 'revised',
      )
    : []
  return {
    id: stringValue(raw.id) || id,
    version: versionValue(raw.version),
    activity_name: stringValue(raw.activity_name),
    activity_date: stringValue(raw.activity_date),
    missing: Array.isArray(raw.missing)
      ? raw.missing.filter((item): item is string => typeof item === 'string')
      : [],
    appendices,
  }
}
function parseFilename(disposition: string): string {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      return encoded[1]
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : ''
}

export interface CurriculumWordFile {
  blob: Blob
  filename: string
}

export async function fetchCurriculumWord(
  id: string,
  version: number,
): Promise<CurriculumWordFile> {
  let response: Response
  try {
    response = await fetch(
      `${API_ROOT}/${pathSegment(id)}/word?version=${encodeURIComponent(String(version))}`,
      {
        method: 'GET',
        headers: { 'cache-control': 'no-store', ...sessionHeaders() },
        mode: 'same-origin',
      },
    )
  } catch (error) {
    throw new ApiError(0, `网络请求异常：${String(error)}`)
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = (
      body as
        | { error?: { code?: string; message?: string; details?: Record<string, unknown> } }
        | null
    )?.error
    throw new ApiError(
      response.status,
      error?.message || `导出失败（HTTP ${response.status}）`,
      error?.code,
      error?.details,
    )
  }
  let blob: Blob
  try {
    blob = await response.blob()
  } catch (error) {
    throw new ApiError(0, `文档读取失败：${String(error)}`)
  }
  return {
    blob,
    filename:
      parseFilename(response.headers.get('content-disposition') || '') ||
      '课程审议记录.docx',
  }
}
export async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const chunk = 0x8000
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk))
  }
  return btoa(binary)
}

export function isCurriculumVersionConflict(error: unknown): boolean {
  return (
    error instanceof ApiError
      ? error.status === 409
      : typeof error === 'object' &&
        error !== null &&
        (error as { status?: unknown }).status === 409
  )
}

export function isCurriculumIndeterminateError(error: unknown): boolean {
  return (
    error instanceof ApiError
      ? error.status === 0
      : typeof error === 'object' &&
        error !== null &&
        (error as { status?: unknown }).status === 0
  )
}

export function curriculumErrorMessage(error: unknown): string {
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

export function curriculumAppendixLabels(
  appendices: ReadonlyArray<'original' | 'revised'>,
): string[] {
  return appendices.map((item) =>
    item === 'original' ? '附教案：原稿' : '二次修改',
  )
}
export type CurriculumAiKind = 'split' | 'review' | 'edit'
export type CurriculumAiSection = 'goals' | 'preparation' | 'process' | 'other'
export type CurriculumAiTaskStatus =
  | 'pending'
  | 'claimed'
  | 'dispatching'
  | 'retry_wait'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'outcome_unknown'
  | 'cancelled'
export type CurriculumAiEditStatus = 'proposed' | 'clarify' | 'no_change'

export interface CurriculumAiQuestion {
  id: string
  source_id: string
  quote: string | null
  question: string
  section: CurriculumAiSection | null
}

export interface CurriculumAiCandidate {
  kind: string
  patch: Record<string, unknown>
  document: CurriculumDocument | null
  questions: CurriculumAiQuestion[]
  status: CurriculumAiEditStatus
  reason_suggestion: string
}

export interface CurriculumAiExecution {
  id: string
  generation: number
  attempt_no: number | null
}

export interface CurriculumAiTask {
  id: string
  status: CurriculumAiTaskStatus
  reason: string | null
  candidate: CurriculumAiCandidate | null
  execution: CurriculumAiExecution | null
}

export interface CurriculumAiSelection {
  field: string
  start: number
  end: number
  text: string
}

export interface CurriculumAiResolution {
  id: string
  section: CurriculumAiSection
}

export interface CurriculumAiCreateBody {
  request_id: string
  kind: CurriculumAiKind
  version: number
  content: CurriculumContent
  age_group?: string
  instruction?: string
  document?: CurriculumDocument | null
  split_task_id?: string
  resolutions?: CurriculumAiResolution[]
  selection?: CurriculumAiSelection
}

export interface CurriculumAiSnapshot {
  recordId: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  profileEpoch: number
}

export type CurriculumAiAdoptMode = 'patch' | 'reason' | 'both'

export interface CurriculumAiAdoptPayload {
  mode: CurriculumAiAdoptMode
  patch: Record<string, unknown>
  document: CurriculumDocument | null
  reasonSuggestion: string
  snapshot: CurriculumAiSnapshot
}
export const CURRICULUM_HEADER_FIELDS = [
  'activity_name',
  'activity_form',
  'activity_form_other',
  'institution',
  'class_name',
  'child_count',
  'organizer',
  'recorder',
  'activity_date',
] as const satisfies ReadonlyArray<keyof CurriculumContent>

const HEADER_FIELD_SET = new Set<string>(CURRICULUM_HEADER_FIELDS)

export const CURRICULUM_FIELD_LABELS: Record<keyof CurriculumContent, string> = {
  activity_name: '活动名称',
  activity_form: '活动形式',
  activity_form_other: '其他形式说明',
  institution: '实施单位',
  class_name: '班级（年龄段）',
  child_count: '幼儿人数',
  organizer: '组织教师',
  recorder: '记录人',
  activity_date: '活动时间',
  goals_original: '活动目标原稿',
  goals_status: '活动目标修订状态',
  goals_adjustment: '活动目标调整内容',
  preparation_original: '活动准备原稿',
  preparation_status: '活动准备修订状态',
  preparation_adjustment: '活动准备调整内容',
  process_original: '活动过程原稿',
  process_adjustment: '活动过程调整内容',
  reason: '调整理由',
  lesson_original: '附教案：原稿',
  lesson_revised: '二次修改',
}

export function curriculumFieldLabel(field: string): string {
  return CURRICULUM_FIELD_LABELS[field as keyof CurriculumContent] ?? field
}
const AI_STATUS_LABELS: Record<CurriculumAiTaskStatus, string> = {
  pending: '排队中',
  claimed: '已领取，准备发送',
  dispatching: '正在等待供应商返回',
  retry_wait: '等待安全重试',
  paused: '已暂停',
  succeeded: '已生成候选',
  failed: '失败',
  outcome_unknown: '结果不明（可能已发送）',
  cancelled: '已取消',
}

export function curriculumAiStatusLabel(status: string): string {
  return AI_STATUS_LABELS[status as CurriculumAiTaskStatus] ?? status
}

const AI_REASON_LABELS: Record<string, string> = {
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
  wire_framing_invalid: '响应分帧无效：结果不明，不会自动重发',
  reasoning_only: '只收到推理内容，没有可用正文：本次未生成候选',
  output_length: '供应商输出达到长度上限：本次未生成候选',
  candidate_contract_invalid: '候选结构校验未通过：本次未生成候选',
  user_stop: '已按你的要求停止等待（不表示供应商已停止处理）',
  restart: '应用重启后暂停：需手动继续',
  source_changed: '生成输入已变化：只能重新发起，不会暗中换输入',
}

export function curriculumAiReasonLabel(
  reason: string | null | undefined,
): string {
  if (!reason) return ''
  return AI_REASON_LABELS[reason] ?? reason
}

export function curriculumAiTaskIsLive(status: string): boolean {
  return (
    status === 'pending' ||
    status === 'claimed' ||
    status === 'dispatching' ||
    status === 'retry_wait'
  )
}

export function curriculumAiTaskIsTerminal(status: string): boolean {
  return (
    status === 'succeeded' ||
    status === 'failed' ||
    status === 'paused' ||
    status === 'outcome_unknown' ||
    status === 'cancelled'
  )
}
const AI_SECTIONS = new Set<CurriculumAiSection>([
  'goals',
  'preparation',
  'process',
  'other',
])

function normalizeAiQuestion(value: unknown): CurriculumAiQuestion | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  const id = stringValue(raw.id)
  const question = stringValue(raw.question)
  if (!id || !question) return null
  const section = stringValue(raw.section)
  return {
    id,
    source_id: stringValue(raw.source_id),
    quote: typeof raw.quote === 'string' ? raw.quote : null,
    question,
    section: AI_SECTIONS.has(section as CurriculumAiSection)
      ? (section as CurriculumAiSection)
      : null,
  }
}
function normalizeAiCandidate(value: unknown): CurriculumAiCandidate | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  const patch =
    raw.patch && typeof raw.patch === 'object' && !Array.isArray(raw.patch)
      ? (raw.patch as Record<string, unknown>)
      : {}
  const status = stringValue(raw.status)
  return {
    kind: stringValue(raw.kind),
    patch,
    document: cloneCurriculumDocument(raw.document),
    questions: Array.isArray(raw.questions)
      ? raw.questions
          .map(normalizeAiQuestion)
          .filter((item): item is CurriculumAiQuestion => item !== null)
      : [],
    status:
      status === 'clarify' || status === 'no_change'
        ? (status as CurriculumAiEditStatus)
        : 'proposed',
    reason_suggestion: stringValue(raw.reason_suggestion),
  }
}
function normalizeAiExecution(value: unknown): CurriculumAiExecution | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  const id = stringValue(raw.id)
  if (!id) return null
  const generation = typeof raw.generation === 'number' ? raw.generation : 0
  const attempt =
    typeof raw.attempt_no === 'number' && Number.isFinite(raw.attempt_no)
      ? raw.attempt_no
      : null
  return { id, generation, attempt_no: attempt }
}

export function normalizeCurriculumAiTask(
  value: unknown,
  fallbackId = '',
): CurriculumAiTask {
  const raw =
    value && typeof value === 'object'
      ? (value as Record<string, unknown>)
      : {}
  const status = stringValue(raw.status)
  return {
    id: stringValue(raw.id) || fallbackId,
    status: (status || 'failed') as CurriculumAiTaskStatus,
    reason: typeof raw.reason === 'string' ? raw.reason : null,
    candidate: normalizeAiCandidate(raw.candidate),
    execution: normalizeAiExecution(raw.execution),
  }
}

export async function createCurriculumAiTask(
  recordId: string,
  body: CurriculumAiCreateBody,
): Promise<CurriculumAiTask> {
  const data = await apiPost<unknown>(
    `${API_ROOT}/${pathSegment(recordId)}/ai/tasks`,
    body,
  )
  return normalizeCurriculumAiTask(data)
}

export async function getCurriculumAiTask(
  recordId: string,
  taskId: string,
): Promise<CurriculumAiTask> {
  const data = await apiGet<unknown>(
    `${API_ROOT}/${pathSegment(recordId)}/ai/tasks/${pathSegment(taskId)}`,
  )
  return normalizeCurriculumAiTask(data, taskId)
}

/** Read-only provider progress for this record's current execution. */
export async function getCurriculumAiTaskProgress(
  recordId: string,
  taskId: string,
): Promise<AiTaskProgress> {
  return apiGet<AiTaskProgress>(
    `${API_ROOT}/${pathSegment(recordId)}/ai/tasks/${pathSegment(taskId)}/progress`,
  )
}

export function isCurriculumAiIndeterminateError(error: unknown): boolean {
  return isIndeterminate(error)
}
export function buildCurriculumAiSplitBody(input: {
  requestId: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  ageGroup?: string
}): CurriculumAiCreateBody {
  const body: CurriculumAiCreateBody = {
    request_id: input.requestId,
    kind: 'split',
    version: input.version,
    content: cloneCurriculumContent(input.content),
    document: cloneCurriculumDocument(input.document),
  }
  const ageGroup = (input.ageGroup ?? '').trim()
  if (ageGroup) body.age_group = ageGroup
  return body
}

export function buildCurriculumAiReviewBody(input: {
  requestId: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  ageGroup?: string
  instruction?: string
  splitTaskId: string
  resolutions: CurriculumAiResolution[]
}): CurriculumAiCreateBody {
  const body: CurriculumAiCreateBody = {
    request_id: input.requestId,
    kind: 'review',
    version: input.version,
    content: cloneCurriculumContent(input.content),
    document: cloneCurriculumDocument(input.document),
    split_task_id: input.splitTaskId,
    resolutions: input.resolutions.map((item) => ({ ...item })),
  }
  const ageGroup = (input.ageGroup ?? '').trim()
  if (ageGroup) body.age_group = ageGroup
  const instruction = (input.instruction ?? '').trim()
  if (instruction) body.instruction = instruction
  return body
}

export function buildCurriculumAiEditBody(input: {
  requestId: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  ageGroup?: string
  instruction: string
  selection: CurriculumAiSelection
}): CurriculumAiCreateBody {
  const body: CurriculumAiCreateBody = {
    request_id: input.requestId,
    kind: 'edit',
    version: input.version,
    content: cloneCurriculumContent(input.content),
    document: cloneCurriculumDocument(input.document),
    instruction: input.instruction.trim(),
    selection: { ...input.selection },
  }
  const ageGroup = (input.ageGroup ?? '').trim()
  if (ageGroup) body.age_group = ageGroup
  return body
}
function hasCurriculumText(value: string): boolean {
  return value.trim() !== ''
}


const REVISION_GROUPS = [
  {
    original: 'goals_original',
    status: 'goals_status',
    adjustment: 'goals_adjustment',
  },
  {
    original: 'preparation_original',
    status: 'preparation_status',
    adjustment: 'preparation_adjustment',
  },
] as const

function groupTouched(
  patch: Record<string, unknown>,
  group: (typeof REVISION_GROUPS)[number],
): boolean {
  return (
    group.original in patch ||
    group.status in patch ||
    group.adjustment in patch
  )
}

function resolveGroupStatus(
  next: CurriculumContent,
  group: (typeof REVISION_GROUPS)[number],
  patch: Record<string, unknown>,
): void {
  const explicit = patch[group.status]
  if (
    Object.prototype.hasOwnProperty.call(patch, group.status) &&
    typeof explicit === 'string' &&
    (explicit === 'unchanged' || explicit === 'adjusted')
  ) {
    next[group.status] = explicit
    return
  }
  if (hasCurriculumText(next[group.adjustment])) {
    next[group.status] = 'adjusted'
    return
  }
  if (next[group.status] === 'adjusted') {
    next[group.status] = hasCurriculumText(next[group.original])
      ? 'unchanged'
      : ''
  }
}

export interface CurriculumAiPatchEntry {
  field: keyof CurriculumContent
  label: string
  before: string
  after: string
}

export interface CurriculumAiPatchResult {
  content: CurriculumContent
  ignoredHeaderFields: string[]
  entries: CurriculumAiPatchEntry[]
}

export function applyCurriculumAiPatch(
  content: CurriculumContent,
  patch: Record<string, unknown>,
): CurriculumAiPatchResult {
  const before = cloneCurriculumContent(content)
  const next = cloneCurriculumContent(content)
  const ignoredHeaderFields: string[] = []
  for (const [field, raw] of Object.entries(patch)) {
    if (HEADER_FIELD_SET.has(field)) {
      ignoredHeaderFields.push(field)
      continue
    }
    if (!(CURRICULUM_CONTENT_FIELDS as readonly string[]).includes(field)) {
      continue
    }
    if (typeof raw !== 'string') continue
    next[field as keyof CurriculumContent] = raw
  }
  for (const group of REVISION_GROUPS) {
    if (groupTouched(patch, group)) resolveGroupStatus(next, group, patch)
  }
  const changed = new Set<keyof CurriculumContent>()
  for (const field of CURRICULUM_CONTENT_FIELDS) {
    if (before[field] !== next[field]) changed.add(field)
  }
  const entries = CURRICULUM_CONTENT_FIELDS.filter((field) =>
    changed.has(field),
  ).map((field) => ({
    field,
    label: curriculumFieldLabel(field),
    before: before[field],
    after: next[field],
  }))
  return {
    content: next,
    ignoredHeaderFields,
    entries,
  }
}
export interface CurriculumSelectionCapture {
  selection: CurriculumAiSelection | null
  error: string
}

export function captureCurriculumSelection(
  content: CurriculumContent,
  field: string,
  start: number,
  end: number,
): CurriculumSelectionCapture {
  if (!(CURRICULUM_CONTENT_FIELDS as readonly string[]).includes(field)) {
    return { selection: null, error: '选段字段不合法' }
  }
  const value = content[field as keyof CurriculumContent]
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    end > value.length
  ) {
    return { selection: null, error: '选段范围不合法' }
  }
  return {
    selection: {
      field,
      start,
      end,
      text: value.slice(start, end),
    },
    error: '',
  }
}

export function wholeCurriculumSelection(
  content: CurriculumContent,
  field: string,
): CurriculumAiSelection | null {
  const captured = captureCurriculumSelection(
    content,
    field,
    0,
    content[field as keyof CurriculumContent]?.length ?? 0,
  )
  return captured.selection
}

export function validateCurriculumSelection(
  content: CurriculumContent,
  selection: CurriculumAiSelection,
): string {
  const captured = captureCurriculumSelection(
    content,
    selection.field,
    selection.start,
    selection.end,
  )
  if (!captured.selection) return captured.error
  if (captured.selection.text !== selection.text) {
    return '选段与当前正文不一致，请重新选择'
  }
  return ''
}

export function captureCurriculumAiSnapshot(input: {
  recordId: string
  version: number
  content: CurriculumContent
  document: CurriculumDocument | null
  profileEpoch: number
}): CurriculumAiSnapshot {
  return {
    recordId: input.recordId,
    version: input.version,
    content: cloneCurriculumContent(input.content),
    document: cloneCurriculumDocument(input.document),
    profileEpoch: input.profileEpoch,
  }
}

export function curriculumAiSnapshotEquals(
  left: CurriculumAiSnapshot,
  right: CurriculumAiSnapshot,
): boolean {
  return (
    left.recordId === right.recordId &&
    left.version === right.version &&
    left.profileEpoch === right.profileEpoch &&
    curriculumContentEquals(left.content, right.content) &&
    curriculumDocumentEquals(left.document, right.document)
  )
}
export function curriculumAiPatchPreview(
  content: CurriculumContent,
  patch: Record<string, unknown>,
): {
  entries: CurriculumAiPatchEntry[]
  ignoredHeaderFields: string[]
} {
  const result = applyCurriculumAiPatch(content, patch)
  return {
    entries: result.entries,
    ignoredHeaderFields: result.ignoredHeaderFields,
  }
}

export function curriculumAiCandidateAdoptable(
  candidate: CurriculumAiCandidate,
): boolean {
  return candidate.status === 'proposed'
}

export function curriculumAiResolutionsComplete(
  questions: CurriculumAiQuestion[],
  resolutions: CurriculumAiResolution[],
): boolean {
  return questions.every((question) =>
    resolutions.some(
      (resolution) =>
        resolution.id === question.id &&
        AI_SECTIONS.has(resolution.section),
    ),
  )
}

export function curriculumAiTaskMessage(task: CurriculumAiTask): string {
  const reason = curriculumAiReasonLabel(task.reason)
  if (reason) return reason
  if (task.status === 'outcome_unknown') {
    return '任务结果不明：只能查询原任务状态，不会自动重发供应商请求'
  }
  if (task.status === 'paused') {
    return '任务已暂停：原请求保留，可稍后查询'
  }
  return curriculumAiStatusLabel(task.status)
}

export function curriculumAiDocumentChanged(
  current: CurriculumDocument | null,
  candidate: CurriculumDocument | null,
): boolean {
  return !curriculumDocumentEquals(current, candidate)
}

export const CURRICULUM_AI_EDIT_FIELDS: ReadonlyArray<{
  field: keyof CurriculumContent
  label: string
}> = [
  { field: 'lesson_original', label: '附教案：原稿' },
  { field: 'lesson_revised', label: '二次修改' },
  { field: 'goals_original', label: '活动目标原稿' },
  { field: 'goals_adjustment', label: '活动目标调整内容' },
  { field: 'preparation_original', label: '活动准备原稿' },
  { field: 'preparation_adjustment', label: '活动准备调整内容' },
  { field: 'process_original', label: '活动过程原稿' },
  { field: 'process_adjustment', label: '活动过程调整内容' },
  { field: 'reason', label: '调整理由' },
]