/**
 * Curriculum deliberation client core.
 *
 * The module owns the local API contract, the table-content shape, the
 * adjustment-status conflict check, the version-bound preview and the
 * authenticated DOCX read used by the existing native Save As bridge.
 */
import { ApiError, apiGet, apiPost, pathSegment, sessionHeaders } from './client'

export type CurriculumFormKind =
  | ''
  | 'collective'
  | 'area'
  | 'parent_child'
  | 'small_group'
  | 'other'

export type CurriculumAdjustmentStatus = '' | 'unchanged' | 'adjusted'

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
): Promise<CurriculumRecord> {
  const data = await apiPost<unknown>(
    `${API_ROOT}/${pathSegment(id)}/save`,
    {
      expected_version: expectedVersion,
      content: normalizeCurriculumContent(content),
    },
  )
  return normalizeRecord(data, id)
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