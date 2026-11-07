/**
 * One-to-one listening Word export client and pure selection helpers.
 *
 * Preview/generation are server-authorized by the launch session and the
 * explicitly selected workbench term. The page never downloads arbitrary
 * paths; the restricted host channel performs the native Save As.
 */
import { ApiError, apiGet, apiPost, pathSegment } from './client'
import {
  LISTENING_DOMAINS,
  type ListeningDomain,
  type ListeningListResponse,
  type ListeningRecordSummary,
} from './listening'

export type ListeningExportMode = 'record' | 'domain'

export interface ListeningExportPhoto {
  group_id: string
  position: number
  asset_id: string
  source_sha256: string
  source_bytes: number
  source_mime_type: string
  source_width: number
  source_height: number
  orientation: number | null
  work_sha256: string
  work_bytes: number
  work_mime_type: string
  width: number
  height: number
}

export interface ListeningExportPreviewUnit {
  record_id: string
  child_name: string
  domain: ListeningDomain
  revision: number
  template_version: string
  template_sha256: string
  photo_count: number
  photos: ListeningExportPhoto[]
  missing_count: number
}

export interface ListeningExportMissing {
  record_id: string
  child_name: string
  domain: ListeningDomain
  field: string
  label: string
  group_id?: string
  position?: number
  item_id?: string
}

export interface ListeningExportPreview {
  preview_id: string
  mode: ListeningExportMode
  domain: ListeningDomain | null
  term_id: string
  class_id: string
  grade: string
  expires_at: string
  record_ids: string[]
  units: ListeningExportPreviewUnit[]
  missing: ListeningExportMissing[]
  missing_count: number
  default_filename: string
}

export interface ListeningExportReady {
  status: 'ready'
  export_id: string
  preview_id: string
  filename: string
  bytes: number
  sha256: string
  expires_at: string
}

export interface ListeningExportOperation {
  status: 'ready'
  export_id: string
  preview_id: string
  filename: string
  bytes: number
  sha256: string
  expires_at: string
}

export const EXPORT_DOMAIN_OPTIONS = LISTENING_DOMAINS.map((domain) => ({
  value: domain,
  label:
    domain === 'health'
      ? '健康'
      : domain === 'language'
        ? '语言'
        : domain === 'social'
          ? '社会'
          : domain === 'science'
            ? '科学'
            : '艺术',
}))

const API_ROOT = '/api/listening-exports'

export async function previewListeningExport(input: {
  mode: ListeningExportMode
  term_id: string
  record_id?: string
  domain?: ListeningDomain
  record_ids?: string[]
}): Promise<ListeningExportPreview> {
  return apiPost<ListeningExportPreview>(`${API_ROOT}/preview`, {
    mode: input.mode,
    term_id: input.term_id,
    ...(input.record_id === undefined ? {} : { record_id: input.record_id }),
    ...(input.domain === undefined ? {} : { domain: input.domain }),
    ...(input.record_ids === undefined ? {} : { record_ids: input.record_ids }),
  })
}

export async function generateListeningExport(input: {
  preview_id: string
  request_id: string
  filename: string
  ack_missing: boolean
}): Promise<ListeningExportReady> {
  return apiPost<ListeningExportReady>(`${API_ROOT}/generate`, {
    preview_id: input.preview_id,
    request_id: input.request_id,
    filename: input.filename,
    ack_missing: input.ack_missing,
  })
}

export async function getListeningExportReceipt(
  requestId: string,
): Promise<ListeningExportOperation> {
  return apiGet<ListeningExportOperation>(
    `${API_ROOT}/operations/${pathSegment(requestId)}`,
  )
}

export function requiresMissingAck(preview: ListeningExportPreview): boolean {
  return preview.missing_count > 0
}

export function canGenerate(
  preview: ListeningExportPreview,
  acknowledged: boolean,
): boolean {
  return !requiresMissingAck(preview) || acknowledged === true
}

/**
 * Fetch every page. The service default domain selection and the visible
 * checkboxes must never silently stop at the first page.
 */
export async function loadAllListeningRecords(
  termId: string,
  fetchPage: (
    termId: string,
    offset: number,
    limit: number,
  ) => Promise<ListeningListResponse>,
  pageLimit = 100,
): Promise<ListeningRecordSummary[]> {
  const items: ListeningRecordSummary[] = []
  const seen = new Set<string>()
  let offset = 0
  for (let page = 0; page < 1000; page += 1) {
    const response = await fetchPage(termId, offset, pageLimit)
    if (!Array.isArray(response.items)) {
      throw new Error('记录列表响应不合法')
    }
    for (const item of response.items) {
      if (!item || typeof item.record_id !== 'string') continue
      if (seen.has(item.record_id)) continue
      seen.add(item.record_id)
      items.push(item)
    }
    const total = Number(response.total)
    offset = Number(response.offset) + response.items.length
    if (
      !Number.isFinite(total) ||
      total < 0 ||
      response.items.length === 0 ||
      offset >= total
    ) {
      return items
    }
  }
  throw new Error('记录列表分页过多，无法取全')
}

export function toggleSelectedRecord(
  order: string[],
  recordId: string,
  selected: boolean,
): string[] {
  if (!recordId) return order.slice()
  const next = order.filter((id) => id !== recordId)
  if (selected) next.push(recordId)
  return next
}

export function moveSelectedRecord(
  order: string[],
  recordId: string,
  direction: -1 | 1,
): string[] {
  const next = order.slice()
  const index = next.indexOf(recordId)
  if (index < 0) return next
  const target = index + direction
  if (target < 0 || target >= next.length) return next
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

export function orderedRecordSummaries(
  records: ListeningRecordSummary[],
  order: string[],
): ListeningRecordSummary[] {
  const byId = new Map(records.map((item) => [item.record_id, item]))
  const result: ListeningRecordSummary[] = []
  for (const id of order) {
    const item = byId.get(id)
    if (item) result.push(item)
  }
  return result
}

export function exportFailureMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return error instanceof Error ? error.message : String(error)
}
