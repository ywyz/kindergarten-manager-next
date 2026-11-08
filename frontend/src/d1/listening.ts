/**
 * One-to-one listening client core (L2).
 *
 * The module owns the HTTP contract, the five-domain working/baseline state,
 * partial-patch construction, shared save coordination and the explicit
 * unknown-result retry protocol. Vue views only render this state; they do not
 * invent a second save machine.
 *
 * All image bytes are fetched through the authenticated Blob helper; the
 * session token never enters a URL. Photo object URLs are owned by the view's
 * PhotoUrlCache and invalidated on record/domain/profile changes.
 */

import {
  ApiError,
  apiDelete,
  apiGet,
  apiGetBlob,
  apiPatch,
  apiPost,
  apiUpload,
  pathSegment,
} from './client'

export const LISTENING_DOMAINS = [
  'health',
  'language',
  'social',
  'science',
  'art',
] as const

export type ListeningDomain = (typeof LISTENING_DOMAINS)[number]

export const DOMAIN_LABELS: Record<ListeningDomain, string> = {
  health: '健康',
  language: '语言',
  social: '社会',
  science: '科学',
  art: '艺术',
}

export const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

export type SaveOutcome =
  | 'unchanged'
  | 'saved'
  | 'failed'
  | 'conflict'
  | 'indeterminate'

export interface ListeningRecordSummary {
  record_id: string
  child_name: string
  grade: string
  class_id: string
  term_id: string
  revision: number
  created_at: string
  updated_at: string
}

export interface ListeningListResponse {
  items: ListeningRecordSummary[]
  total: number
  offset: number
  limit: number
}

export interface ListeningGroup {
  group_id: string
  position: number | null
  work_date: string | null
  listening_text: string | null
  asset_id: string | null
}

export interface ListeningEvaluation {
  item_id: string
  stars: number | null
}

export interface ListeningDomainState {
  domain: ListeningDomain
  domain_label: string
  template_version: string
  template_sha256: string
  observation_date: string | null
  adult_count: string | null
  child_age: string | null
  goal: string | null
  observation_area: string | null
  overall_evaluation: string | null
  support_strategy: string | null
  groups: ListeningGroup[]
  evaluation: ListeningEvaluation[]
}

export interface ListeningRecordDetail {
  record_id: string
  child_name: string
  class_id: string
  term_id: string
  grade: string
  revision: number
  created_at: string
  updated_at: string
  domains: ListeningDomainState[]
  /** Same read transaction as `revision`; asset id -> manual quarters. */
  rotations?: Record<string, number>
}

export interface ListeningTemplateItem {
  item_id: string
  level1: string
  level2: string
  requirement: string
  standards: Record<'1' | '2' | '3', string>
}

export interface ListeningTemplate {
  grade: string
  grade_label: string
  domain: ListeningDomain
  domain_label: string
  version: string
  sha256: string
  title: string | null
  items: ListeningTemplateItem[]
}

export interface ListeningTemplatesResponse {
  grade: string
  record_id?: string
  templates: ListeningTemplate[]
}

export interface ListeningNameResult {
  record_id: string
  child_name: string
  revision: number
  changed: boolean
  saved_at?: string
}

export interface ListeningDomainResult {
  record_id: string
  domain: ListeningDomain
  revision: number
  changed: boolean
  saved_at?: string
}

export interface ListeningPhotoResult {
  record_id: string
  domain: ListeningDomain
  group_id: string
  asset_id: string
  old_asset_id: string | null
  revision: number
  changed: boolean
  rotation_quarters?: number
  saved_at?: string
}

export interface ListeningRotateResult {
  record_id: string
  domain: ListeningDomain
  group_id: string
  asset_id: string
  revision: number
  old_rotation_quarters: number
  rotation_quarters: number
  orientation: number | null
  changed: boolean
  saved_at?: string
}

export interface ListeningRotationsResponse {
  record_id: string
  revision?: number
  rotations: Record<string, number>
  orientations?: Record<string, number | null>
}

export interface ListeningRemoveResult {
  record_id: string
  domain: ListeningDomain
  group_id: string
  asset_id: null
  old_asset_id: string | null
  revision: number
  changed: boolean
  saved_at?: string
}

/** Batch import limits mirror the reviewed single-photo technical envelope. */
export const MAX_BATCH_PHOTOS = 15
export const MAX_BATCH_PHOTO_BYTES = 25 * 1024 * 1024
export const MAX_BATCH_TOTAL_BYTES = 75 * 1024 * 1024

export interface ListeningBatchFileInfo {
  name: string
  size: number
}

export interface ListeningBatchAssignment {
  domain: ListeningDomain
  groupId: string
  slotLabel: string
  fileIndex: number
  displayName: string
  size: number
}

export interface ListeningBatchPlan {
  assignments: ListeningBatchAssignment[]
  totalBytes: number
}

export type ListeningBatchPlanResult =
  | { ok: true; plan: ListeningBatchPlan }
  | { ok: false; reason: string }

function batchSizeReason(files: ListeningBatchFileInfo[]): string | null {
  let total = 0
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index]
    const label = `第 ${index + 1} 张照片「${file.name || '未命名'}」`
    if (!Number.isFinite(file.size) || file.size <= 0) {
      return `${label}为空文件`
    }
    if (file.size > MAX_BATCH_PHOTO_BYTES) {
      return `${label}超过 25 MB 单张上限`
    }
    total += file.size
  }
  if (total > MAX_BATCH_TOTAL_BYTES) {
    return `本批照片合计 ${Math.ceil(total / (1024 * 1024))} MB，超过 75 MB 总请求上限`
  }
  return null
}

/**
 * Plan a whole batch against currently empty slots only.
 *
 * Order is the visible domain order, then this selection's file order, then
 * each domain's empty-slot order. Existing photos are never candidates, so a
 * plan can only fill empty positions; capacity overflow is a hard refusal.
 */
export function planListeningPhotoBatch(
  files: ListeningBatchFileInfo[],
  forms: Partial<Record<ListeningDomain, ListeningDomainState>>,
): ListeningBatchPlanResult {
  if (files.length < 1) {
    return { ok: false, reason: '请一次选择 1～15 张照片' }
  }
  if (files.length > MAX_BATCH_PHOTOS) {
    return {
      ok: false,
      reason: `一次最多选择 ${MAX_BATCH_PHOTOS} 张照片，本次选择了 ${files.length} 张`,
    }
  }
  const sizeReason = batchSizeReason(files)
  if (sizeReason) return { ok: false, reason: sizeReason }

  const slots: Array<{
    domain: ListeningDomain
    groupId: string
    slotLabel: string
  }> = []
  for (const domain of LISTENING_DOMAINS) {
    const groups = forms[domain]?.groups ?? []
    const empty = groups
      .filter((group) => group.asset_id === null)
      .slice(0, 3)
    empty.forEach((group) => {
      const position = groups.findIndex((item) => item.group_id === group.group_id)
      slots.push({
        domain,
        groupId: group.group_id,
        slotLabel: `${DOMAIN_LABELS[domain]}领域第 ${position + 1} 组`,
      })
    })
  }
  if (slots.length === 0) {
    return {
      ok: false,
      reason: '当前记录没有空余图位；已有照片不会被替换，请先移除照片或减少选择',
    }
  }
  if (slots.length < files.length) {
    return {
      ok: false,
      reason: `当前只有 ${slots.length} 个空余图位，本批选择了 ${files.length} 张；已有照片不会被替换，请减少照片或先移除已有照片`,
    }
  }
  const assignments = files.map((file, index) => {
    const slot = slots[index]
    return {
      domain: slot.domain,
      groupId: slot.groupId,
      slotLabel: slot.slotLabel,
      fileIndex: index,
      displayName: file.name || `photo-${index + 1}`,
      size: file.size,
    }
  })
  return {
    ok: true,
    plan: {
      assignments,
      totalBytes: files.reduce((sum, file) => sum + file.size, 0),
    },
  }
}

export type ListeningBatchSelectionCheck =
  | { ok: true }
  | { ok: false; reason: string }

/**
 * Revalidate the teacher's current preview against live record forms.
 *
 * The locked target set must still be unique, belong to this record and match
 * the currently empty slots exactly. This function never mutates selections;
 * callers keep the preview visible and surface the reason.
 */
export function validateListeningBatchSelection(
  assignments: ListeningBatchAssignment[],
  files: ListeningBatchFileInfo[],
  forms: Partial<Record<ListeningDomain, ListeningDomainState>>,
): ListeningBatchSelectionCheck {
  const plan = planListeningPhotoBatch(files, forms)
  if (!plan.ok) return plan
  if (assignments.length !== files.length) {
    return {
      ok: false,
      reason: '本批照片落位数量不一致，已保留本批选择；请重新预览后再试',
    }
  }
  const locked = new Set<string>()
  const fileIndexes = new Set<number>()
  for (const assignment of assignments) {
    const key = `${assignment.domain}:${assignment.groupId}`
    if (locked.has(key)) {
      return {
        ok: false,
        reason: '本批照片落位重复，已保留本批选择；请重新预览后再试',
      }
    }
    locked.add(key)
    if (
      !Number.isInteger(assignment.fileIndex) ||
      assignment.fileIndex < 0 ||
      assignment.fileIndex >= files.length ||
      fileIndexes.has(assignment.fileIndex)
    ) {
      return {
        ok: false,
        reason: '本批照片与落位对应关系失效，已保留本批选择；请重新预览后再试',
      }
    }
    fileIndexes.add(assignment.fileIndex)
  }
  const expected = new Set(
    plan.plan.assignments.map(
      (assignment) => `${assignment.domain}:${assignment.groupId}`,
    ),
  )
  if (
    locked.size !== expected.size ||
    [...expected].some((target) => !locked.has(target))
  ) {
    return {
      ok: false,
      reason:
        '预览落位已失效或目标图位已有照片，已保留本批选择；请重新预览后再试',
    }
  }
  return { ok: true }
}

/**
 * Swap the target slots of two planned files. The target set is unchanged, so
 * a swap can never exceed a domain's three slots or touch an existing photo.
 */
export function swapListeningBatchTargets(
  assignments: ListeningBatchAssignment[],
  fromIndex: number,
  toIndex: number,
): ListeningBatchAssignment[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= assignments.length ||
    toIndex >= assignments.length
  ) {
    return assignments.map((assignment) => ({ ...assignment }))
  }
  return assignments.map((assignment, index) => {
    if (index === fromIndex) {
      return {
        ...assignment,
        domain: assignments[toIndex].domain,
        groupId: assignments[toIndex].groupId,
        slotLabel: assignments[toIndex].slotLabel,
      }
    }
    if (index === toIndex) {
      return {
        ...assignment,
        domain: assignments[fromIndex].domain,
        groupId: assignments[fromIndex].groupId,
        slotLabel: assignments[fromIndex].slotLabel,
      }
    }
    return { ...assignment }
  })
}

export interface ListeningBatchItemResult {
  domain: ListeningDomain
  group_id: string
  asset_id: string
  old_asset_id: string | null
  content_hash: string
  format: string
  width: number
  height: number
  orientation: number | null
  rotation_quarters?: number
  byte_size: number
}

export interface ListeningBatchResult {
  record_id: string
  revision: number
  changed: boolean
  saved_at?: string
  items: ListeningBatchItemResult[]
}

export interface ListeningBatchEntry {
  domain: ListeningDomain
  groupId: string
  file: File
}

/** Strict 0–3 quarter-turn value; null means the caller supplied garbage. */
export function rotationQuarters(value: unknown): number | null {
  return typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 3
    ? value
    : null
}

/** One teacher click: -1 = left/counter-clockwise, +1 = right/clockwise. */
export function rotatePhotoQuarters(
  current: number,
  direction: -1 | 1,
): number {
  const base = rotationQuarters(current) ?? 0
  return ((base + direction) % 4 + 4) % 4
}

export function rotationTransform(quarters: number): string {
  const value = rotationQuarters(quarters) ?? 0
  return value === 0 ? '' : `rotate(${value * 90}deg)`
}

export interface ListeningMonth {
  year: number
  month: number
}

export interface ListeningDateIssue {
  groupId: string
  position: number
  value: string
  reason: string
}

export interface ListeningDateRange {
  min: string
  max: string
}

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

/** Strict YYYY-MM; legacy free text returns null and is never reformatted. */
export function parseListeningMonth(value: unknown): ListeningMonth | null {
  if (typeof value !== 'string') return null
  const match = /^([0-9]{4})-([0-9]{2})$/.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  if (!Number.isInteger(year) || year < 1 || month < 1 || month > 12) {
    return null
  }
  return { year, month }
}

/** Strict YYYY-MM-DD; legacy free text returns null. */
export function parseListeningDate(value: unknown): {
  year: number
  month: number
  day: number
  iso: string
} | null {
  if (typeof value !== 'string') return null
  const match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1
  ) {
    return null
  }
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
  if (day > lastDay) return null
  return { year, month, day, iso: match[0] }
}

export function termMonthRange(
  termStart: string,
  termEnd: string,
): ListeningDateRange | null {
  const start = parseListeningDate(termStart)
  const end = parseListeningDate(termEnd)
  if (!start || !end || start.iso > end.iso) return null
  return {
    min: `${start.iso.slice(0, 7)}`,
    max: `${end.iso.slice(0, 7)}`,
  }
}

export function workDateRange(
  termStart: string,
  termEnd: string,
  observationMonth: string,
): ListeningDateRange | null {
  const month = parseListeningMonth(observationMonth)
  const start = parseListeningDate(termStart)
  const end = parseListeningDate(termEnd)
  if (!month || !start || !end || start.iso > end.iso) return null
  const first = `${month.year}-${pad2(month.month)}-01`
  const lastDay = new Date(
    Date.UTC(month.year, month.month, 0),
  ).getUTCDate()
  const last = `${month.year}-${pad2(month.month)}-${pad2(lastDay)}`
  const min = first > start.iso ? first : start.iso
  const max = last < end.iso ? last : end.iso
  return min <= max ? { min, max } : null
}

/**
 * Local per-group warnings for the current observation month.
 *
 * A legacy work-date text is retained but flagged as undecidable; the teacher
 * must explicitly replace it with a date or clear it before a month change is
 * saved.
 */
export function listeningDateIssues(
  observationDate: string | null | undefined,
  groups: ListeningGroup[],
  termStart: string,
  termEnd: string,
): ListeningDateIssue[] {
  const month = parseListeningMonth(observationDate)
  if (!month) return []
  const range = workDateRange(termStart, termEnd, observationDate ?? '')
  const issues: ListeningDateIssue[] = []
  groups.forEach((group, index) => {
    const value = normalizeText(group.work_date)
    if (!value) return
    const position = group.position ?? index
    if (!range) {
      issues.push({
        groupId: group.group_id,
        position,
        value,
        reason: '观察月与学期没有可用日期',
      })
      return
    }
    const date = parseListeningDate(value)
    if (!date) {
      issues.push({
        groupId: group.group_id,
        position,
        value,
        reason: '原作品日期不是规范日期，请选择日期替换或清空',
      })
      return
    }
    if (date.iso < range.min || date.iso > range.max) {
      issues.push({
        groupId: group.group_id,
        position,
        value,
        reason: `作品日期不在 ${range.min}～${range.max} 交集内`,
      })
    }
  })
  return issues
}

export function dateFieldsChanged(
  current: ListeningDomainState,
  baseline: ListeningDomainState,
): boolean {
  if (
    normalizeText(current.observation_date) !==
    normalizeText(baseline.observation_date)
  ) {
    return true
  }
  return current.groups.some((group) => {
    const saved = baseline.groups.find(
      (item) => item.group_id === group.group_id,
    )
    return (
      normalizeText(group.work_date) !== normalizeText(saved?.work_date)
    )
  })
}

export interface ListeningOrderResult {
  record_id: string
  domain: ListeningDomain
  group_ids: string[]
  revision: number
  changed: boolean
  saved_at?: string
}

export interface ListeningOperationReceipt {
  request_id: string
  operation_kind: string
  record_id: string
  result: Record<string, unknown>
  created_at: string
}

export interface ListeningCreateResult {
  record_id: string
  revision: number
  child_name: string
  class_id: string
  term_id: string
  grade: string
  templates: Record<string, { version: string; sha256: string }>
  created_at: string
}

export interface ListeningApi {
  listRecords(termId: string, offset: number, limit: number): Promise<ListeningListResponse>
  getRecord(recordId: string): Promise<ListeningRecordDetail>
  getTemplates(recordId: string): Promise<ListeningTemplatesResponse>
  createRecord(termId: string, childName: string, requestId: string): Promise<ListeningCreateResult>
  patchName(
    recordId: string,
    requestId: string,
    expectedRevision: number,
    childName: string,
  ): Promise<ListeningNameResult>
  saveDomain(
    recordId: string,
    domain: ListeningDomain,
    requestId: string,
    expectedRevision: number,
    patch: Record<string, unknown>,
  ): Promise<ListeningDomainResult>
  uploadPhoto(
    recordId: string,
    domain: ListeningDomain,
    groupId: string,
    form: FormData,
  ): Promise<ListeningPhotoResult>
  uploadPhotoBatch(
    recordId: string,
    form: FormData,
  ): Promise<ListeningBatchResult>
  reorder(
    recordId: string,
    domain: ListeningDomain,
    requestId: string,
    expectedRevision: number,
    groupIds: string[],
  ): Promise<ListeningOrderResult>
  removePhoto(
    recordId: string,
    domain: ListeningDomain,
    groupId: string,
    requestId: string,
    expectedRevision: number,
  ): Promise<ListeningRemoveResult>
  getRotations?(recordId: string): Promise<ListeningRotationsResponse>
  rotatePhoto(
    recordId: string,
    domain: ListeningDomain,
    groupId: string,
    requestId: string,
    expectedRevision: number,
    rotationQuarters: number,
  ): Promise<ListeningRotateResult>
  getOperation(recordId: string, requestId: string): Promise<ListeningOperationReceipt>
  loadAsset(recordId: string, assetId: string, signal?: AbortSignal): Promise<Blob>
}

const API_ROOT = '/api/listening'

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const listeningApi: ListeningApi = {
  listRecords(termId, offset, limit) {
    return apiGet<ListeningListResponse>(
      `${API_ROOT}/records${query({ term_id: termId, offset, limit })}`,
    )
  },
  getRecord(recordId) {
    return apiGet<ListeningRecordDetail>(
      `${API_ROOT}/records/${pathSegment(recordId)}`,
    )
  },
  getTemplates(recordId) {
    return apiGet<ListeningTemplatesResponse>(
      `${API_ROOT}/templates${query({ record_id: recordId })}`,
    )
  },
  createRecord(termId, childName, requestId) {
    return apiPost<ListeningCreateResult>(`${API_ROOT}/records`, {
      request_id: requestId,
      term_id: termId,
      child_name: childName,
    })
  },
  patchName(recordId, requestId, expectedRevision, childName) {
    return apiPatch<ListeningNameResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
        child_name: childName,
      },
    )
  },
  saveDomain(recordId, domain, requestId, expectedRevision, patch) {
    return apiPatch<ListeningDomainResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/domains/${domain}`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
        ...patch,
      },
    )
  },
  uploadPhoto(recordId, domain, groupId, form) {
    return apiUpload<ListeningPhotoResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/domains/${domain}/photos/${pathSegment(groupId)}`,
      form,
    )
  },
  uploadPhotoBatch(recordId, form) {
    return apiUpload<ListeningBatchResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/photos/batch`,
      form,
    )
  },
  reorder(recordId, domain, requestId, expectedRevision, groupIds) {
    return apiPost<ListeningOrderResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/domains/${domain}/photos/order`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
        group_ids: groupIds,
      },
    )
  },
  removePhoto(recordId, domain, groupId, requestId, expectedRevision) {
    return apiDelete<ListeningRemoveResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/domains/${domain}/photos/${pathSegment(groupId)}`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
      },
    )
  },
  getRotations(recordId) {
    return apiGet<ListeningRotationsResponse>(
      `${API_ROOT}/records/${pathSegment(recordId)}/photos/rotations`,
    )
  },
  rotatePhoto(
    recordId,
    domain,
    groupId,
    requestId,
    expectedRevision,
    rotationQuarters,
  ) {
    return apiPost<ListeningRotateResult>(
      `${API_ROOT}/records/${pathSegment(recordId)}/domains/${domain}/photos/${pathSegment(groupId)}/rotate`,
      {
        request_id: requestId,
        expected_revision: expectedRevision,
        rotation_quarters: rotationQuarters,
      },
    )
  },
  getOperation(recordId, requestId) {
    return apiGet<ListeningOperationReceipt>(
      `${API_ROOT}/records/${pathSegment(recordId)}/operations/${pathSegment(requestId)}`,
    )
  },
  loadAsset(recordId, assetId, signal) {
    return apiGetBlob(
      `${API_ROOT}/records/${pathSegment(recordId)}/assets/${pathSegment(assetId)}/content`,
      signal,
    )
  },
}

export function listListeningRecords(
  termId: string,
  offset = 0,
  limit = 50,
): Promise<ListeningListResponse> {
  return listeningApi.listRecords(termId, offset, limit)
}

export function createListeningRecord(
  termId: string,
  childName: string,
  requestId: string,
): Promise<ListeningCreateResult> {
  return listeningApi.createRecord(termId, childName, requestId)
}

export function getListeningCreateOperation(
  requestId: string,
): Promise<ListeningOperationReceipt> {
  return apiGet<ListeningOperationReceipt>(
    `${API_ROOT}/records/operations/${pathSegment(requestId)}`,
  )
}

export function newRequestId(): string {
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

export function shortRecordId(recordId: string): string {
  return recordId.length > 10 ? `${recordId.slice(0, 8)}…` : recordId
}

export function formatRecordTime(value: string): string {
  if (!value) return ''
  return value.replace('T', ' ').slice(0, 16)
}

export function normalizeText(value: string | null | undefined): string | null {
  const text = (value ?? '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  return text.length > 0 ? text : null
}

export function cloneDomain(domain: ListeningDomainState): ListeningDomainState {
  return JSON.parse(JSON.stringify(domain)) as ListeningDomainState
}

const HEADER_FIELDS = [
  'observation_date',
  'adult_count',
  'child_age',
  'goal',
  'observation_area',
  'overall_evaluation',
  'support_strategy',
] as const

const GROUP_TEXT_FIELDS = ['work_date', 'listening_text'] as const

export function groupIdsInOrder(groups: ListeningGroup[]): string[] {
  return groups.map((group) => group.group_id)
}

export function orderChanged(
  current: ListeningDomainState,
  baseline: ListeningDomainState,
): boolean {
  const currentIds = groupIdsInOrder(current.groups)
  const baselineIds = groupIdsInOrder(baseline.groups)
  return (
    currentIds.length !== baselineIds.length ||
    currentIds.some((id, index) => id !== baselineIds[index])
  )
}

export function assetAssociationChanged(
  current: ListeningDomainState,
  baseline: ListeningDomainState,
): boolean {
  if (current.groups.length !== baseline.groups.length) return true
  return current.groups.some((group) => {
    const saved = baseline.groups.find((item) => item.group_id === group.group_id)
    return saved ? saved.asset_id !== group.asset_id : true
  })
}

/** Build a backend partial patch: only changed fields, explicit null clears. */
export function buildDomainPatch(
  current: ListeningDomainState,
  baseline: ListeningDomainState,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  for (const field of HEADER_FIELDS) {
    const next = normalizeText(current[field])
    const before = normalizeText(baseline[field])
    if (next !== before) patch[field] = next
  }
  const groupPatches: Array<Record<string, unknown>> = []
  for (const group of current.groups) {
    const before = baseline.groups.find(
      (item) => item.group_id === group.group_id,
    )
    if (!before) continue
    const changed: Record<string, unknown> = { group_id: group.group_id }
    let touched = false
    for (const field of GROUP_TEXT_FIELDS) {
      const next = normalizeText(group[field])
      const old = normalizeText(before[field])
      if (next !== old) {
        changed[field] = next
        touched = true
      }
    }
    if (touched) groupPatches.push(changed)
  }
  if (groupPatches.length > 0) patch.groups = groupPatches
  const evaluation: Record<string, number | null> = {}
  const baselineStars = new Map(
    baseline.evaluation.map((item) => [item.item_id, item.stars]),
  )
  for (const item of current.evaluation) {
    const before = baselineStars.get(item.item_id) ?? null
    if (item.stars !== before) evaluation[item.item_id] = item.stars
  }
  if (Object.keys(evaluation).length > 0) patch.evaluation = evaluation
  return patch
}

/** Apply a confirmed patch to the baseline clone, not to the live input. */
export function applyPatchToBaseline(
  baseline: ListeningDomainState,
  patch: Record<string, unknown>,
): void {
  for (const field of HEADER_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(patch, field)) {
      ;(baseline as unknown as Record<string, unknown>)[field] =
        normalizeText(patch[field] as string | null)
    }
  }
  const groups = Array.isArray(patch.groups) ? patch.groups : []
  for (const change of groups as Array<Record<string, unknown>>) {
    const group = baseline.groups.find(
      (item) => item.group_id === change.group_id,
    )
    if (!group) continue
    if (Object.prototype.hasOwnProperty.call(change, 'work_date')) {
      group.work_date = normalizeText(change.work_date as string | null)
    }
    if (Object.prototype.hasOwnProperty.call(change, 'listening_text')) {
      group.listening_text = normalizeText(
        change.listening_text as string | null,
      )
    }
  }
  const evaluation =
    patch.evaluation && typeof patch.evaluation === 'object'
      ? (patch.evaluation as Record<string, number | null>)
      : {}
  for (const [itemId, stars] of Object.entries(evaluation)) {
    const item = baseline.evaluation.find((entry) => entry.item_id === itemId)
    if (item) item.stars = stars
  }
}

/** Apply one confirmed group order to the baseline, preserving saved text. */
export function applyOrderToBaseline(
  baseline: ListeningDomainState,
  orderedIds: string[],
): void {
  const byId = new Map(baseline.groups.map((group) => [group.group_id, group]))
  const ordered: ListeningGroup[] = []
  orderedIds.forEach((groupId, index) => {
    const group = byId.get(groupId)
    if (group) ordered.push({ ...group, position: index })
  })
  baseline.groups = ordered
}

export function createListeningState(
  recordId: string,
  domain: ListeningDomain = 'health',
): ListeningSessionState {
  return {
    recordId,
    record: null,
    templates: {},
    forms: {},
    baselines: {},
    rotations: {},
    domain,
    name: '',
    nameBaseline: '',
    revision: 0,
    busy: false,
    loaded: false,
    error: '',
    unknown: null,
    editEpoch: 0,
    profileEpoch: 0,
    loadSeq: 0,
    lifecycle: 0,
    savePromise: null,
  }
}

export interface PendingUnknown {
  kind: 'name' | 'domain' | 'order' | 'photo' | 'batch' | 'rotate' | 'remove'
  requestId: string
  expectedRevision: number
  label: string
  retry: () => Promise<SaveOutcome>
  describe: () => string
}

export interface ListeningSessionState {
  recordId: string
  record: ListeningRecordDetail | null
  templates: Partial<Record<ListeningDomain, ListeningTemplate>>
  forms: Partial<Record<ListeningDomain, ListeningDomainState>>
  baselines: Partial<Record<ListeningDomain, ListeningDomainState>>
  /** asset id -> teacher manual clockwise quarter turns (0–3). */
  rotations: Record<string, number>
  domain: ListeningDomain
  name: string
  nameBaseline: string
  revision: number
  busy: boolean
  loaded: boolean
  error: string
  unknown: PendingUnknown | null
  editEpoch: number
  profileEpoch: number
  loadSeq: number
  /** Invalidates every late save/retry/receipt result after reset. */
  lifecycle: number
  savePromise: Promise<SaveOutcome> | null
}

function isApiError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError ||
    (typeof error === 'object' &&
      error !== null &&
      typeof (error as { status?: unknown }).status === 'number')
  )
}

function errorMessage(error: unknown): string {
  if (isApiError(error) && error.message) return error.message
  return String(error)
}

export class ListeningSession {
  readonly state: ListeningSessionState
  private readonly api: ListeningApi

  constructor(api: ListeningApi, state: ListeningSessionState) {
    this.api = api
    this.state = state
  }

  form(domain = this.state.domain): ListeningDomainState | undefined {
    return this.state.forms[domain]
  }

  baseline(domain = this.state.domain): ListeningDomainState | undefined {
    return this.state.baselines[domain]
  }

  template(domain = this.state.domain): ListeningTemplate | undefined {
    return this.state.templates[domain]
  }

  private normalizedRotationMap(
    source: unknown,
  ): Record<string, number> {
    if (!source || typeof source !== 'object' || Array.isArray(source)) {
      throw new Error('照片方向记录不合法')
    }
    const normalized: Record<string, number> = {}
    for (const [assetId, value] of Object.entries(
      source as Record<string, unknown>,
    )) {
      const quarters = rotationQuarters(value)
      if (!assetId || quarters === null) {
        throw new Error('照片方向记录不合法')
      }
      normalized[assetId] = quarters
    }
    return normalized
  }

  /**
   * Resolve the direction map against the exact same record revision.
   *
   * New backends include `rotations` in the record DTO's read transaction.
   * For an older projection, a separate rotation GET is accepted only when
   * its revision matches; otherwise both record and direction are re-read.
   */
  private async consistentRecordAndRotations(
    initial: ListeningRecordDetail,
  ): Promise<{
    record: ListeningRecordDetail
    rotations: Record<string, number>
  }> {
    if (initial.rotations !== undefined) {
      return {
        record: initial,
        rotations: this.normalizedRotationMap(initial.rotations),
      }
    }
    if (!this.api.getRotations) {
      return { record: initial, rotations: {} }
    }
    let record = initial
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const response = await this.api.getRotations(this.state.recordId)
      if (response.record_id !== record.record_id) {
        throw new Error('照片方向记录身份不一致')
      }
      const rotations = this.normalizedRotationMap(response.rotations)
      if (
        response.revision === undefined ||
        response.revision === record.revision
      ) {
        return { record, rotations }
      }
      record = await this.api.getRecord(this.state.recordId)
      if (record.rotations !== undefined) {
        return {
          record,
          rotations: this.normalizedRotationMap(record.rotations),
        }
      }
    }
    throw new Error('照片方向与记录修订不一致，请重新进入记录')
  }

  async load(): Promise<boolean> {
    const seq = ++this.state.loadSeq
    this.state.busy = true
    this.state.error = ''
    try {
      const initial = await this.api.getRecord(this.state.recordId)
      const templates = await this.api.getTemplates(this.state.recordId)
      if (seq !== this.state.loadSeq) return false
      const snapshot = await this.consistentRecordAndRotations(initial)
      if (seq !== this.state.loadSeq) return false
      const record = snapshot.record
      const normalizedRotations = snapshot.rotations
      if (
        templates.record_id !== undefined &&
        templates.record_id !== record.record_id
      ) {
        this.state.error = '模板记录身份不一致'
        return false
      }
      if (record.domains.length !== LISTENING_DOMAINS.length) {
        this.state.error = '倾听领域不完整'
        return false
      }
      const byDomain = new Map(
        templates.templates.map((template) => [template.domain, template]),
      )
      const forms: Partial<Record<ListeningDomain, ListeningDomainState>> = {}
      const baselines: Partial<Record<ListeningDomain, ListeningDomainState>> =
        {}
      const boundTemplates: Partial<
        Record<ListeningDomain, ListeningTemplate>
      > = {}
      for (const domain of LISTENING_DOMAINS) {
        const source = record.domains.find((item) => item.domain === domain)
        const template = byDomain.get(domain)
        if (!source || !template) {
          this.state.error = `领域 ${DOMAIN_LABELS[domain]} 缺少绑定模板`
          return false
        }
        if (
          template.version !== source.template_version ||
          template.sha256 !== source.template_sha256
        ) {
          this.state.error = `领域 ${DOMAIN_LABELS[domain]} 的模板与记录绑定不一致`
          return false
        }
        forms[domain] = cloneDomain(source)
        baselines[domain] = cloneDomain(source)
        boundTemplates[domain] = template
      }
      this.state.record = record
      this.state.forms = forms
      this.state.baselines = baselines
      this.state.rotations = normalizedRotations
      this.state.templates = boundTemplates
      this.state.name = record.child_name
      this.state.nameBaseline = record.child_name
      this.state.revision = record.revision
      this.state.loaded = true
      this.state.domain = record.domains[0]?.domain ?? this.state.domain
      return true
    } catch (error) {
      if (seq !== this.state.loadSeq) return false
      this.state.error = errorMessage(error)
      return false
    } finally {
      if (seq === this.state.loadSeq) this.state.busy = false
    }
  }

  setName(value: string): void {
    this.state.name = value
    this.state.editEpoch += 1
  }

  setField(
    field: (typeof HEADER_FIELDS)[number],
    value: string | null,
  ): void {
    const form = this.form()
    if (!form) return
    form[field] = value
    this.state.editEpoch += 1
  }

  setGroupField(
    groupId: string,
    field: (typeof GROUP_TEXT_FIELDS)[number],
    value: string | null,
  ): void {
    const group = this.form()?.groups.find((item) => item.group_id === groupId)
    if (!group) return
    group[field] = value
    this.state.editEpoch += 1
  }

  /** Explicit cancel of local observation/work-date edits; never autosaves. */
  restoreDateBaseline(domain = this.state.domain): boolean {
    const form = this.state.forms[domain]
    const baseline = this.state.baselines[domain]
    if (!form || !baseline) return false
    form.observation_date = baseline.observation_date
    for (const group of form.groups) {
      const saved = baseline.groups.find(
        (item) => item.group_id === group.group_id,
      )
      if (saved) group.work_date = saved.work_date
    }
    this.state.editEpoch += 1
    return true
  }

  applyConfirmedAdoption(
    domain: ListeningDomain,
    revision: number,
    patch: Record<string, unknown>,
  ): void {
    const baseline = this.state.baselines[domain]
    const form = this.state.forms[domain]
    if (!baseline || !form || !Number.isInteger(revision) || revision < 1) return
    const clean: Record<string, unknown> = {}
    for (const field of [
      'goal',
      'overall_evaluation',
      'support_strategy',
    ] as const) {
      if (field in patch && form[field] === baseline[field]) {
        clean[field] = patch[field]
      }
    }
    if (Array.isArray(patch.groups)) {
      const cleanGroups: Array<Record<string, unknown>> = []
      for (const item of patch.groups as Array<Record<string, unknown>>) {
        const groupId = String(item.group_id || '')
        const saved = baseline.groups.find((group) => group.group_id === groupId)
        const current = form.groups.find((group) => group.group_id === groupId)
        if (!saved || !current) continue
        const change: Record<string, unknown> = { group_id: groupId }
        if (
          'listening_text' in item &&
          current.listening_text === saved.listening_text
        ) {
          change.listening_text = item.listening_text
        }
        if ('work_date' in item && current.work_date === saved.work_date) {
          change.work_date = item.work_date
        }
        if (Object.keys(change).length > 1) cleanGroups.push(change)
      }
      if (cleanGroups.length) clean.groups = cleanGroups
    }
    if (patch.evaluation && typeof patch.evaluation === 'object') {
      const cleanStars: Record<string, number | null> = {}
      for (const [itemId, stars] of Object.entries(
        patch.evaluation as Record<string, number | null>,
      )) {
        const saved = baseline.evaluation.find((item) => item.item_id === itemId)
        const current = form.evaluation.find((item) => item.item_id === itemId)
        if (saved && current && current.stars === saved.stars) {
          cleanStars[itemId] = stars
        }
      }
      if (Object.keys(cleanStars).length) clean.evaluation = cleanStars
    }
    applyPatchToBaseline(baseline, patch)
    applyPatchToBaseline(form, clean)
    this.state.revision = revision
    if (this.state.record) this.state.record.revision = revision
    this.state.editEpoch += 1
  }

  setStars(itemId: string, stars: number | null): void {
    const item = this.form()?.evaluation.find(
      (entry) => entry.item_id === itemId,
    )
    if (!item) return
    item.stars = stars
    this.state.editEpoch += 1
  }

  moveGroup(groupId: string, direction: -1 | 1): void {
    const groups = this.form()?.groups
    if (!groups) return
    const index = groups.findIndex((group) => group.group_id === groupId)
    const target = index + direction
    if (index < 0 || target < 0 || target >= groups.length) return
    const [group] = groups.splice(index, 1)
    groups.splice(target, 0, group)
    groups.forEach((item, position) => {
      item.position = position
    })
    this.state.editEpoch += 1
  }

  isDirty(): boolean {
    if (!this.state.loaded) return false
    if (this.state.name !== this.state.nameBaseline) return true
    // A late input may belong to a domain the teacher is no longer viewing.
    // Leave/switch decisions must consider every domain, not just the tab.
    for (const domain of LISTENING_DOMAINS) {
      const form = this.state.forms[domain]
      const baseline = this.state.baselines[domain]
      if (!form || !baseline) continue
      if (Object.keys(buildDomainPatch(form, baseline)).length > 0) return true
      if (orderChanged(form, baseline)) return true
      if (assetAssociationChanged(form, baseline)) return true
    }
    return false
  }

  identity(): string {
    return `${this.state.recordId}:${this.state.domain}:${this.state.editEpoch}`
  }

  async setDomain(domain: ListeningDomain): Promise<SaveOutcome> {
    if (domain === this.state.domain) return 'unchanged'
    const lifecycle = this.state.lifecycle
    const identityBefore = this.identity()
    const outcome = await this.saveCurrent()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    if (outcome !== 'saved' && outcome !== 'unchanged') return outcome
    if (this.isDirty() || this.identity() !== identityBefore) {
      // New input arrived while the save was in flight (or another domain is
      // still dirty). Never hide it behind a tab switch; the teacher must see
      // the confirmed baseline and save again.
      this.state.error = '保存期间有新输入或其它领域尚未保存，未切换领域'
      return 'failed'
    }
    this.state.domain = domain
    this.state.editEpoch += 1
    this.state.error = ''
    return outcome
  }

  saveCurrent(): Promise<SaveOutcome> {
    if (this.state.savePromise) return this.state.savePromise
    const lifecycle = this.state.lifecycle
    const promise = this.saveInternal().finally(() => {
      // A reset may have started a newer save; the old chain must not clear it.
      if (lifecycle === this.state.lifecycle) this.state.savePromise = null
    })
    this.state.savePromise = promise
    return promise
  }

  private async saveInternal(): Promise<SaveOutcome> {
    if (!this.state.loaded) return 'unchanged'
    if (this.state.unknown) {
      // An unknown result is never re-sent implicitly by a normal save,
      // tab switch, back navigation or close. Only the teacher's explicit
      // "retry original request" / receipt check may advance it.
      this.state.error =
        this.state.unknown.describe() ||
        '保存结果未知；请明确重试原请求或核对回执'
      return 'indeterminate'
    }
    const lifecycle = this.state.lifecycle
    let changed = false
    if (this.state.name !== this.state.nameBaseline) {
      const outcome = await this.saveName(lifecycle)
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      if (outcome !== 'saved' && outcome !== 'unchanged') return outcome
      changed = changed || outcome === 'saved'
    }
    // Save every dirty domain, not just the currently visible tab. A late
    // input from another tab must not be lost when the teacher leaves.
    for (const domain of LISTENING_DOMAINS) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      const form = this.state.forms[domain]
      const baseline = this.state.baselines[domain]
      if (!form || !baseline) continue
      const patch = buildDomainPatch(form, baseline)
      if (Object.keys(patch).length > 0) {
        const outcome = await this.saveDomainPatch(domain, patch, lifecycle)
        if (lifecycle !== this.state.lifecycle) return 'indeterminate'
        if (outcome !== 'saved' && outcome !== 'unchanged') return outcome
        changed = changed || outcome === 'saved'
      }
      if (orderChanged(form, baseline)) {
        const outcome = await this.saveOrder(domain, lifecycle)
        if (lifecycle !== this.state.lifecycle) return 'indeterminate'
        if (outcome !== 'saved' && outcome !== 'unchanged') return outcome
        changed = changed || outcome === 'saved'
      }
    }
    return changed ? 'saved' : 'unchanged'
  }

  private async saveName(lifecycle: number): Promise<SaveOutcome> {
    const snapshot = this.state.name
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    this.state.busy = true
    try {
      const result = await this.api.patchName(
        this.state.recordId,
        requestId,
        expectedRevision,
        snapshot,
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      this.state.revision = result.revision
      this.state.nameBaseline = snapshot
      if (this.state.record) this.state.record.child_name = result.child_name
      this.state.error = ''
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'name',
        requestId,
        expectedRevision,
        label: '姓名',
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.patchName(
              this.state.recordId,
              requestId,
              expectedRevision,
              snapshot,
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            this.state.revision = result.revision
            this.state.nameBaseline = snapshot
            this.state.unknown = null
            this.state.error = ''
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError)
          }
        },
        describe: () => '姓名保存结果未知；可用原请求重试或核对回执',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  private async saveDomainPatch(
    domain: ListeningDomain,
    patch: Record<string, unknown>,
    lifecycle: number,
  ): Promise<SaveOutcome> {
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    const snapshot = patch
    this.state.busy = true
    try {
      const result = await this.api.saveDomain(
        this.state.recordId,
        domain,
        requestId,
        expectedRevision,
        snapshot,
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      this.state.revision = result.revision
      const baseline = this.state.baselines[domain]
      if (baseline) applyPatchToBaseline(baseline, snapshot)
      this.state.error = ''
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'domain',
        requestId,
        expectedRevision,
        label: `${DOMAIN_LABELS[domain]}领域`,
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.saveDomain(
              this.state.recordId,
              domain,
              requestId,
              expectedRevision,
              snapshot,
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            this.state.revision = result.revision
            const baseline = this.state.baselines[domain]
            if (baseline) applyPatchToBaseline(baseline, snapshot)
            this.state.unknown = null
            this.state.error = ''
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError)
          }
        },
        describe: () => `${DOMAIN_LABELS[domain]}领域保存结果未知；可用原请求重试`,
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  private async saveOrder(
    domain: ListeningDomain,
    lifecycle: number,
  ): Promise<SaveOutcome> {
    const form = this.state.forms[domain]
    if (!form) return 'unchanged'
    const groupIds = groupIdsInOrder(form.groups)
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    this.state.busy = true
    try {
      const result = await this.api.reorder(
        this.state.recordId,
        domain,
        requestId,
        expectedRevision,
        groupIds,
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      this.state.revision = result.revision
      const baseline = this.state.baselines[domain]
      if (baseline) applyOrderToBaseline(baseline, groupIds)
      this.state.error = ''
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'order',
        requestId,
        expectedRevision,
        label: `${DOMAIN_LABELS[domain]}图文换序`,
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.reorder(
              this.state.recordId,
              domain,
              requestId,
              expectedRevision,
              groupIds,
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            this.state.revision = result.revision
            const baseline = this.state.baselines[domain]
            if (baseline) applyOrderToBaseline(baseline, groupIds)
            this.state.unknown = null
            this.state.error = ''
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError)
          }
        },
        describe: () => '图文换序结果未知；可用原请求重试',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  private handleSaveError(
    error: unknown,
    pending: PendingUnknown,
  ): SaveOutcome {
    if (isApiError(error) && error.status === 409) {
      this.state.error = error.message || '内容版本冲突'
      return 'conflict'
    }
    if (
      isApiError(error) &&
      (error.status === 0 ||
        this.isUncertainCommitFailure(error, pending.kind))
    ) {
      this.state.unknown = {
        kind: pending.kind,
        requestId: pending.requestId,
        expectedRevision: pending.expectedRevision,
        label: pending.label,
        retry: pending.retry,
        describe: pending.describe,
      }
      this.state.error = pending.describe()
      return 'indeterminate'
    }
    this.state.error = errorMessage(error)
    return 'failed'
  }

  private isUncertainCommitFailure(
    error: unknown,
    kind: PendingUnknown['kind'] | undefined,
  ): boolean {
    if (!isApiError(error) || error.status !== 503) return false
    if (error.code === 'LISTENING_BATCH_COMMIT_UNCERTAIN') return true
    return (
      kind === 'rotate' &&
      error.code === 'LISTENING_ROTATION_COMMIT_UNCERTAIN'
    )
  }

  private handleRetryError(
    error: unknown,
    kind?: PendingUnknown['kind'],
  ): SaveOutcome {
    if (kind === 'batch' || kind === 'rotate') {
      // A retry failure only proves this retry did not succeed. The original
      // request may still have committed, so keep its id, target and version
      // until the original receipt can be checked.
      this.state.error =
        '重试未成功，原请求结果仍待核对；请核对原回执或再次重试原请求'
      return 'indeterminate'
    }
    if (isApiError(error) && error.status === 409) {
      this.state.unknown = null
      this.state.error = error.message || '内容版本冲突'
      return 'conflict'
    }
    if (
      isApiError(error) &&
      (error.status === 0 || this.isUncertainCommitFailure(error, kind))
    ) {
      this.state.error = '保存结果仍未知；原请求保留，可再次重试或核对回执'
      return 'indeterminate'
    }
    this.state.unknown = null
    this.state.error = errorMessage(error)
    return 'failed'
  }

  async retryUnknown(): Promise<SaveOutcome> {
    const pending = this.state.unknown
    if (!pending) return 'unchanged'
    const lifecycle = this.state.lifecycle
    const outcome = await pending.retry()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    return outcome
  }

  async checkUnknownReceipt(): Promise<boolean> {
    const pending = this.state.unknown
    if (!pending) return false
    const lifecycle = this.state.lifecycle
    try {
      await this.api.getOperation(this.state.recordId, pending.requestId)
      if (lifecycle !== this.state.lifecycle) return false
      // The receipt proves the original request committed.  Keep the pending
      // payload so the explicit "retry original request" path can apply the
      // exact same body (the receipt itself does not carry the submitted
      // patch for name/domain operations).
      this.state.error =
        '已找到原请求回执；请点击“重试原请求”按原载荷确认，不要另换请求'
      return true
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return false
      if (isApiError(error) && error.status === 404) {
        this.state.error =
          '尚未找到原请求回执；请不要换新请求，可明确重试原请求'
        return false
      }
      this.state.error = errorMessage(error)
      return false
    }
  }

  async importPhoto(groupId: string, file: File | null): Promise<SaveOutcome> {
    if (!file) return 'unchanged'
    const lifecycle = this.state.lifecycle
    const saved = await this.saveCurrent()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    if (saved !== 'saved' && saved !== 'unchanged') return saved
    const domain = this.state.domain
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    const form = this.state.forms[domain]
    const group = form?.groups.find((item) => item.group_id === groupId)
    if (!group) return 'failed'
    const buildForm = () => {
      const data = new FormData()
      data.set('request_id', requestId)
      data.set('expected_revision', String(expectedRevision))
      data.set('display_name', file.name || 'photo')
      data.set('file', file, file.name || 'photo')
      return data
    }
    this.state.busy = true
    try {
      const result = await this.api.uploadPhoto(
        this.state.recordId,
        domain,
        groupId,
        buildForm(),
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      this.state.revision = result.revision
      group.asset_id = result.asset_id
      if (result.old_asset_id) delete this.state.rotations[result.old_asset_id]
      this.state.rotations[result.asset_id] =
        rotationQuarters(result.rotation_quarters) ?? 0
      const baseline = this.state.baselines[domain]
      const savedGroup = baseline?.groups.find((item) => item.group_id === groupId)
      if (savedGroup) savedGroup.asset_id = result.asset_id
      this.state.error = ''
      return 'saved'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'photo',
        requestId,
        expectedRevision,
        label: '照片上传',
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.uploadPhoto(
              this.state.recordId,
              domain,
              groupId,
              buildForm(),
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            this.state.revision = result.revision
            group.asset_id = result.asset_id
            if (result.old_asset_id) {
              delete this.state.rotations[result.old_asset_id]
            }
            this.state.rotations[result.asset_id] =
              rotationQuarters(result.rotation_quarters) ?? 0
            const baseline = this.state.baselines[domain]
            const savedGroup = baseline?.groups.find(
              (item) => item.group_id === groupId,
            )
            if (savedGroup) savedGroup.asset_id = result.asset_id
            this.state.unknown = null
            this.state.error = ''
            return 'saved'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError)
          }
        },
        describe: () => '照片上传结果未知；可用原请求重试（不会自动新建记录）',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  /**
   * Persist one manual display rotation (absolute quarters, clockwise).
   *
   * The original asset bytes and hash never change; preview CSS and the Word/AI
   * working image both apply EXIF first and this value afterwards.
   */
  async rotatePhoto(groupId: string, target: number): Promise<SaveOutcome> {
    const normalized = rotationQuarters(target)
    if (normalized === null) {
      this.state.error = '照片方向必须是 0～3 个四分之一圈'
      return 'failed'
    }
    const lifecycle = this.state.lifecycle
    const domain = this.state.domain
    const form = this.state.forms[domain]
    const group = form?.groups.find((item) => item.group_id === groupId)
    if (!group?.asset_id) {
      this.state.error = '该图位尚未上传照片'
      return 'failed'
    }
    const assetId = group.asset_id
    if ((this.state.rotations[assetId] ?? 0) === normalized) {
      return 'unchanged'
    }
    const saved = await this.saveCurrent()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    if (saved !== 'saved' && saved !== 'unchanged') return saved
    const currentGroup = this.state.forms[domain]?.groups.find(
      (item) => item.group_id === groupId,
    )
    if (currentGroup?.asset_id !== assetId) {
      this.state.error = '照片在保存期间发生变化，请重试'
      return 'failed'
    }
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    const apply = (result: ListeningRotateResult): void => {
      this.state.revision = result.revision
      this.state.rotations[result.asset_id] = result.rotation_quarters
      this.state.error = ''
    }
    this.state.busy = true
    try {
      const result = await this.api.rotatePhoto(
        this.state.recordId,
        domain,
        groupId,
        requestId,
        expectedRevision,
        normalized,
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      apply(result)
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'rotate',
        requestId,
        expectedRevision,
        label: '照片方向',
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.rotatePhoto(
              this.state.recordId,
              domain,
              groupId,
              requestId,
              expectedRevision,
              normalized,
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            apply(result)
            this.state.unknown = null
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError, 'rotate')
          }
        },
        describe: () => '照片方向保存结果未知；可用原请求重试',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  /**
   * Save 1–15 selected files as one protected operation.
   *
   * The whole batch carries one request id, one expected revision and one
   * revision increment. A replay/retry reuses the exact same multipart body;
   * an invalid plan returns before any save or upload, so it cannot leave a
   * partial association or replace an existing photo.
   */
  async importPhotoBatch(entries: ListeningBatchEntry[]): Promise<SaveOutcome> {
    if (entries.length === 0) return 'unchanged'
    if (entries.length > MAX_BATCH_PHOTOS) {
      this.state.error = `一次最多选择 ${MAX_BATCH_PHOTOS} 张照片`
      return 'failed'
    }
    const seenGroups = new Set<string>()
    let totalBytes = 0
    for (const entry of entries) {
      if (seenGroups.has(entry.groupId)) {
        this.state.error = '本批照片落位重复，请重新预览后再保存'
        return 'failed'
      }
      seenGroups.add(entry.groupId)
      const group = this.state.forms[entry.domain]?.groups.find(
        (item) => item.group_id === entry.groupId,
      )
      if (!group) {
        this.state.error = '目标图位不属于当前记录，请重新预览'
        return 'failed'
      }
      if (group.asset_id !== null) {
        this.state.error = '目标图位已有照片，已有照片不会被替换，请重新预览'
        return 'failed'
      }
      if (!entry.file || entry.file.size <= 0) {
        this.state.error = '本批照片含空文件，请重新选择'
        return 'failed'
      }
      if (entry.file.size > MAX_BATCH_PHOTO_BYTES) {
        this.state.error = '单张照片超过 25 MB 上限，请压缩后重试'
        return 'failed'
      }
      totalBytes += entry.file.size
    }
    if (totalBytes > MAX_BATCH_TOTAL_BYTES) {
      this.state.error = '本批照片合计超过 75 MB 总请求上限，请减少照片'
      return 'failed'
    }

    const lifecycle = this.state.lifecycle
    const saved = await this.saveCurrent()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    if (saved !== 'saved' && saved !== 'unchanged') return saved
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    const buildForm = () => {
      const data = new FormData()
      data.set('request_id', requestId)
      data.set('expected_revision', String(expectedRevision))
      data.set(
        'assignments',
        JSON.stringify(
          entries.map((entry, index) => ({
            index,
            domain: entry.domain,
            group_id: entry.groupId,
            display_name: entry.file.name || `photo-${index + 1}`,
          })),
        ),
      )
      entries.forEach((entry, index) => {
        data.set(
          `file_${index}`,
          entry.file,
          entry.file.name || `photo-${index + 1}`,
        )
      })
      return data
    }
    const apply = (result: ListeningBatchResult): void => {
      this.state.revision = result.revision
      for (const item of result.items) {
        const form = this.state.forms[item.domain]
        const group = form?.groups.find(
          (candidate) => candidate.group_id === item.group_id,
        )
        if (group) group.asset_id = item.asset_id
        this.state.rotations[item.asset_id] =
          rotationQuarters(item.rotation_quarters) ?? 0
        const baseline = this.state.baselines[item.domain]
        const savedGroup = baseline?.groups.find(
          (candidate) => candidate.group_id === item.group_id,
        )
        if (savedGroup) savedGroup.asset_id = item.asset_id
      }
    }
    this.state.busy = true
    try {
      const result = await this.api.uploadPhotoBatch(
        this.state.recordId,
        buildForm(),
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      apply(result)
      this.state.error = ''
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'batch',
        requestId,
        expectedRevision,
        label: '整批照片',
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.uploadPhotoBatch(
              this.state.recordId,
              buildForm(),
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            apply(result)
            this.state.unknown = null
            this.state.error = ''
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError, 'batch')
          }
        },
        describe: () =>
          '整批照片保存结果未知；可用原请求重试（不会重复、覆盖或部分写入）',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  async removePhoto(groupId: string): Promise<SaveOutcome> {
    const lifecycle = this.state.lifecycle
    const saved = await this.saveCurrent()
    if (lifecycle !== this.state.lifecycle) return 'indeterminate'
    if (saved !== 'saved' && saved !== 'unchanged') return saved
    const domain = this.state.domain
    const form = this.state.forms[domain]
    const group = form?.groups.find((item) => item.group_id === groupId)
    if (!group) return 'failed'
    const requestId = newRequestId()
    const expectedRevision = this.state.revision
    this.state.busy = true
    try {
      const result = await this.api.removePhoto(
        this.state.recordId,
        domain,
        groupId,
        requestId,
        expectedRevision,
      )
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      this.state.revision = result.revision
      group.asset_id = null
      if (result.old_asset_id) delete this.state.rotations[result.old_asset_id]
      const baseline = this.state.baselines[domain]
      const savedGroup = baseline?.groups.find(
        (item) => item.group_id === groupId,
      )
      if (savedGroup) savedGroup.asset_id = null
      this.state.error = ''
      return result.changed ? 'saved' : 'unchanged'
    } catch (error) {
      if (lifecycle !== this.state.lifecycle) return 'indeterminate'
      return this.handleSaveError(error, {
        kind: 'remove',
        requestId,
        expectedRevision,
        label: '照片移除',
        retry: async () => {
          if (lifecycle !== this.state.lifecycle) return 'indeterminate'
          try {
            const result = await this.api.removePhoto(
              this.state.recordId,
              domain,
              groupId,
              requestId,
              expectedRevision,
            )
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            this.state.revision = result.revision
            group.asset_id = null
            if (result.old_asset_id) {
              delete this.state.rotations[result.old_asset_id]
            }
            const baseline = this.state.baselines[domain]
            const savedGroup = baseline?.groups.find(
              (item) => item.group_id === groupId,
            )
            if (savedGroup) savedGroup.asset_id = null
            this.state.unknown = null
            this.state.error = ''
            return result.changed ? 'saved' : 'unchanged'
          } catch (retryError) {
            if (lifecycle !== this.state.lifecycle) return 'indeterminate'
            return this.handleRetryError(retryError)
          }
        },
        describe: () => '照片移除结果未知；可用原请求重试',
      })
    } finally {
      if (lifecycle === this.state.lifecycle) this.state.busy = false
    }
  }

  async loadAsset(assetId: string, signal?: AbortSignal): Promise<Blob> {
    return this.api.loadAsset(this.state.recordId, assetId, signal)
  }

  reset(): void {
    this.state.lifecycle += 1
    this.state.loadSeq += 1
    this.state.record = null
    this.state.templates = {}
    this.state.forms = {}
    this.state.baselines = {}
    this.state.rotations = {}
    this.state.name = ''
    this.state.nameBaseline = ''
    this.state.revision = 0
    this.state.busy = false
    this.state.loaded = false
    this.state.error = ''
    this.state.unknown = null
    this.state.savePromise = null
  }
}
