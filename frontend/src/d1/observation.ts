/**
 * D4 E09/E10 observation editor helpers (product C1-C33, Contract §2-§6).
 *
 * Pure form/payload adaptation only: the server canonical payload stays the
 * authority, the form keeps teacher text, and the dirty baseline is the
 * server-normalized payload. No business state machine lives here.
 */

export type ObservationRecordType = 'public' | 'indoor' | 'outdoor'

export const OBSERVATION_RECORD_TYPES: ObservationRecordType[] = [
  'public',
  'indoor',
  'outdoor',
]

export const RECORD_TYPE_LABELS: Record<ObservationRecordType, string> = {
  public: '公共区域',
  indoor: '室内区域',
  outdoor: '户外区域',
}

export const EVALUATION_KEYS = [
  'health',
  'language',
  'social',
  'science',
  'arts',
] as const

export type EvaluationKey = (typeof EVALUATION_KEYS)[number]

export const EVALUATION_LABELS: Record<EvaluationKey, string> = {
  health: '健康',
  language: '语言',
  social: '社会',
  science: '科学',
  arts: '艺术',
}

export type ObservationTarget =
  | 'observation_goal'
  | 'observation_process'
  | 'analysis_evaluation'
  | 'support_strategy'

export const OBSERVATION_TARGETS: ObservationTarget[] = [
  'observation_goal',
  'observation_process',
  'analysis_evaluation',
  'support_strategy',
]

export const TARGET_LABELS: Record<ObservationTarget, string> = {
  observation_goal: '观察目标',
  observation_process: '观察记录',
  analysis_evaluation: '评价分析',
  support_strategy: '支持策略',
}

export interface ObservationSubject {
  name: string
}

export interface ObservationPayload {
  record_type: ObservationRecordType
  observation_date: string | null
  start_time: string | null
  end_time: string | null
  term_id?: string | null
  school_name: string | null
  class_name: string | null
  observer_name: string | null
  adult_count: number | null
  child_count: number | null
  age_years: number | null
  subjects: ObservationSubject[]
  environment: string | null
  observation_goal: string
  observation_process: string
  support_strategy: string
  analysis_evaluation: Record<EvaluationKey, string>
}

export interface ObservationPhoto {
  asset_id: string
  content_hash: string
  format: string
  width: number
  height: number
  orientation: number | null
  sort_order: number
  caption: string | null
}

export interface ObservationCurrent {
  observation_id: string
  revision: number
  payload: ObservationPayload
  payload_hash: string
  photos: ObservationPhoto[]
  current_version: number | null
  latest_version_hash?: string | null
  created_at: string
  updated_at: string
}

/** Contract C27: four-column text or a valid photo makes a record non-empty. */
export function observationHasContent(
  payload: ObservationPayload,
  photoCount = 0,
): boolean {
  if (photoCount > 0) return true
  if (
    ['observation_goal', 'observation_process', 'support_strategy'].some(
      (key) => String(payload[key as keyof ObservationPayload] ?? '').trim() !== '',
    )
  ) {
    return true
  }
  return EVALUATION_KEYS.some(
    (key) => String(payload.analysis_evaluation?.[key] ?? '').trim() !== '',
  )
}

export interface ObservationSaveResult {
  observation_id: string
  revision: number
  payload_hash: string
  photos: ObservationPhoto[]
  current_version: number | null
  changed: boolean
  history_created: boolean
  term_warnings: string[]
  target_hashes: Record<string, string>
  saved_at: string
}

export interface ObservationListItem {
  observation_id: string
  record_type: ObservationRecordType
  observation_date: string | null
  start_time: string | null
  end_time: string | null
  term_id: string | null
  term_name: string | null
  school_name: string | null
  class_name: string | null
  observer_name: string | null
  subjects: string[]
  environment: string | null
  adult_count: number | null
  child_count: number | null
  age_years: number | null
  current_draft_revision: number
  current_version: number | null
  created_at: string
  updated_at: string
}

export interface ObservationListPayload {
  items: ObservationListItem[]
  total: number
  offset: number
  limit: number
}

export interface ObservationHistoryItem {
  version: number
  id: string
  payload_hash: string
  source_kind: string
  created_at: string
  is_current: boolean
}

export interface ObservationHistoryDetail {
  version: number
  id: string
  payload: ObservationPayload
  payload_hash: string
  photos: ObservationPhoto[]
  source_kind: string
  created_at: string
}

export interface ObservationForm {
  observation_date: string
  start_time: string
  end_time: string
  school_name: string
  class_name: string
  observer_name: string
  adult_count: string
  child_count: string
  age_years: string
  subjects: string[]
  environment: string
  observation_goal: string
  observation_process: string
  support_strategy: string
  analysis_evaluation: Record<EvaluationKey, string>
}

export class ObservationFormError extends Error {
  field: string

  constructor(field: string, message: string) {
    super(message)
    this.field = field
  }
}

export function emptyObservationForm(): ObservationForm {
  return {
    observation_date: '',
    start_time: '',
    end_time: '',
    school_name: '',
    class_name: '',
    observer_name: '',
    adult_count: '',
    child_count: '',
    age_years: '',
    subjects: [],
    environment: '',
    observation_goal: '',
    observation_process: '',
    support_strategy: '',
    analysis_evaluation: {
      health: '',
      language: '',
      social: '',
      science: '',
      arts: '',
    },
  }
}

export function observationFormFromPayload(
  payload: ObservationPayload,
): ObservationForm {
  const form = emptyObservationForm()
  form.observation_date = payload.observation_date ?? ''
  form.start_time = payload.start_time ?? ''
  form.end_time = payload.end_time ?? ''
  form.school_name = payload.school_name ?? ''
  form.class_name = payload.class_name ?? ''
  form.observer_name = payload.observer_name ?? ''
  form.adult_count =
    payload.adult_count === null || payload.adult_count === undefined
      ? ''
      : String(payload.adult_count)
  form.child_count =
    payload.child_count === null || payload.child_count === undefined
      ? ''
      : String(payload.child_count)
  form.age_years =
    payload.age_years === null || payload.age_years === undefined
      ? ''
      : String(payload.age_years)
  form.subjects = (payload.subjects ?? []).map((item) => item.name ?? '')
  form.environment = payload.environment ?? ''
  form.observation_goal = payload.observation_goal ?? ''
  form.observation_process = payload.observation_process ?? ''
  form.support_strategy = payload.support_strategy ?? ''
  for (const key of EVALUATION_KEYS) {
    form.analysis_evaluation[key] = payload.analysis_evaluation?.[key] ?? ''
  }
  return form
}

function countValue(value: string, field: string): number | null {
  const text = value.trim()
  if (text === '') return null
  if (!/^\d+$/.test(text)) {
    throw new ObservationFormError(field, '人数与年龄必须是非负整数')
  }
  const number = Number(text)
  // Never silently round or turn a huge digit string into null/Infinity.
  if (!Number.isSafeInteger(number) || number < 0) {
    throw new ObservationFormError(field, '人数与年龄超出可精确保存的范围')
  }
  return number
}

function textOrNull(value: string): string | null {
  const text = value.trim()
  return text === '' ? null : value
}

export function observationPayloadFromForm(
  form: ObservationForm,
  recordType: ObservationRecordType,
): ObservationPayload {
  const subjects = form.subjects
    .map((name) => name.trim())
    .filter((name) => name !== '')
    .map((name) => ({ name }))
  return {
    record_type: recordType,
    observation_date: form.observation_date || null,
    start_time: form.start_time || null,
    end_time: form.end_time || null,
    school_name: textOrNull(form.school_name),
    class_name: textOrNull(form.class_name),
    observer_name: textOrNull(form.observer_name),
    adult_count: countValue(form.adult_count, 'adult_count'),
    child_count: countValue(form.child_count, 'child_count'),
    age_years: countValue(form.age_years, 'age_years'),
    subjects,
    environment: textOrNull(form.environment),
    observation_goal: form.observation_goal,
    observation_process: form.observation_process,
    support_strategy: form.support_strategy,
    analysis_evaluation: {
      health: form.analysis_evaluation.health,
      language: form.analysis_evaluation.language,
      social: form.analysis_evaluation.social,
      science: form.analysis_evaluation.science,
      arts: form.analysis_evaluation.arts,
    },
  }
}

/** Server-normalized baseline for the dirty check (term fields excluded). */
export function observationBaselineFromPayload(
  payload: ObservationPayload,
): ObservationPayload {
  return observationPayloadFromForm(
    observationFormFromPayload(payload),
    payload.record_type,
  )
}

export function observationIsDirty(
  form: ObservationForm,
  recordType: ObservationRecordType,
  baseline: ObservationPayload | null,
): boolean {
  if (!baseline) return false
  try {
    return (
      canonicalObservationJson(observationPayloadFromForm(form, recordType)) !==
      canonicalObservationJson(observationBaselineFromPayload(baseline))
    )
  } catch {
    // An invalid numeric field is an edit in progress: never report clean.
    return true
  }
}

export function canonicalObservationJson(value: unknown): string {
  return JSON.stringify(sortValue(value))
}

function sortValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortValue)
  if (value !== null && typeof value === 'object') {
    const result: Record<string, unknown> = {}
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      result[key] = sortValue((value as Record<string, unknown>)[key])
    }
    return result
  }
  return value
}

export function observationIdentity(
  observationId: string,
  epoch: number,
): string {
  return `${observationId}:${epoch}`
}

export function subjectNames(payload: ObservationPayload | null): string {
  if (!payload) return ''
  return (payload.subjects ?? [])
    .map((item) => item.name)
    .filter((name) => name)
    .join('、')
}

export function availableTargets(
  taskType: string,
  raw: Record<string, unknown>,
): ObservationTarget[] {
  if (taskType === 'game_observation_generate') {
    return [...OBSERVATION_TARGETS]
  }
  const target = raw.target
  return OBSERVATION_TARGETS.includes(target as ObservationTarget)
    ? [target as ObservationTarget]
    : []
}

export function candidateTargetText(
  raw: Record<string, unknown>,
  target: ObservationTarget,
  taskType = 'game_observation_generate',
): string {
  if (target === 'analysis_evaluation') {
    const evaluation = (raw.analysis_evaluation ?? {}) as Record<string, unknown>
    return EVALUATION_KEYS.map(
      (key) => `${EVALUATION_LABELS[key]}：${String(evaluation[key] ?? '')}`,
    ).join('\n')
  }
  // Rewrite candidates carry their single target in ``text``; generate
  // candidates carry the four columns by name. Never read the wrong shape.
  if (taskType === 'game_observation_rewrite') {
    return String(raw.text ?? '')
  }
  return String(raw[target] ?? '')
}

/** Split photos into bounded display chunks (never all originals at once). */
export function chunkPhotos<T>(photos: T[], size = 8): T[][] {
  if (size < 1) throw new Error('chunk size must be positive')
  const chunks: T[][] = []
  for (let index = 0; index < photos.length; index += size) {
    chunks.push(photos.slice(index, index + size))
  }
  return chunks
}

export interface TermOption {
  id: string
  name: string
  start_date: string
  end_date: string
}

export interface TermDecisionChoice {
  decision: 'keep_current' | 'assign_selected' | 'unassigned'
  selectedTermId: string | null
}

/**
 * Build the explicit term choices the save dialog offers. A current
 * attribution is always kept first; matching terms and "unassigned" remain
 * explicit alternatives (never auto-migrated).
 */
export function termDecisionChoices(
  currentTermId: string | null,
  options: TermOption[],
  selectedTermId: string | null = null,
): TermDecisionChoice[] {
  const choices: TermDecisionChoice[] = []
  if (currentTermId) {
    choices.push({ decision: 'keep_current', selectedTermId: null })
  }
  const seen = new Set<string>()
  for (const option of options) {
    if (!option.id || seen.has(option.id)) continue
    seen.add(option.id)
    if (option.id === currentTermId) continue
    choices.push({ decision: 'assign_selected', selectedTermId: option.id })
  }
  if (selectedTermId && !seen.has(selectedTermId)) {
    choices.push({
      decision: 'assign_selected',
      selectedTermId,
    })
  }
  choices.push({ decision: 'unassigned', selectedTermId: null })
  return choices
}

export const BASIC_FIELD_LABELS: Record<string, string> = {
  school_name: '园所',
  class_name: '班级',
  observer_name: '观察者',
  observation_date: '观察日期',
  start_time: '起始时间',
  end_time: '结束时间',
  adult_count: '成人数目',
  child_count: '儿童数目',
  age_years: '统一年龄',
  subjects: '重点观察幼儿',
  environment: '观察环境',
}

export function observationBasicMissing(form: ObservationForm): string[] {
  const missing: string[] = []
  if (!form.school_name.trim()) missing.push('school_name')
  if (!form.class_name.trim()) missing.push('class_name')
  if (!form.observer_name.trim()) missing.push('observer_name')
  if (!form.observation_date) missing.push('observation_date')
  if (!form.start_time) missing.push('start_time')
  if (!form.end_time) missing.push('end_time')
  if (!form.adult_count.trim()) missing.push('adult_count')
  if (!form.child_count.trim()) missing.push('child_count')
  if (!form.age_years.trim()) missing.push('age_years')
  if (!form.subjects.some((name) => name.trim())) missing.push('subjects')
  if (!form.environment.trim()) missing.push('environment')
  return missing
}

export function observationContradictions(form: ObservationForm): string[] {
  const warnings: string[] = []
  const subjectCount = form.subjects.filter((name) => name.trim()).length
  const childCount = form.child_count.trim()
  if (/^\d+$/.test(childCount) && subjectCount > Number(childCount)) {
    warnings.push('儿童总数少于重点观察幼儿人数，请复核；不会自动改数')
  }
  if (
    /^([01]\d|2[0-3]):[0-5]\d$/.test(form.start_time) &&
    /^([01]\d|2[0-3]):[0-5]\d$/.test(form.end_time) &&
    form.end_time < form.start_time
  ) {
    warnings.push('结束时间早于开始时间，请复核；不会自动改时间')
  }
  return warnings
}

export function observationAiMinimumMissing(
  form: ObservationForm,
  photoCount: number,
): string[] {
  const missing: string[] = []
  if (!form.subjects.some((name) => name.trim())) missing.push('重点观察幼儿姓名')
  if (!form.age_years.trim()) missing.push('统一观察年龄')
  if (!form.environment.trim()) missing.push('观察环境')
  if (photoCount < 1) missing.push('至少一张有效照片')
  return missing
}

export function termLabel(
  terms: TermOption[],
  termId: string | null,
): string {
  if (!termId) return '未归属学期'
  return terms.find((term) => term.id === termId)?.name ?? '未知学期'
}

// ---------------------------------------------------------------------------
// D4 E11 cross-page explicit selection and stable/manual order
// ---------------------------------------------------------------------------

export interface ObservationExportRecord {
  observation_id: string
  record_type: ObservationRecordType
  observation_date: string | null
  start_time: string | null
  subjects: string[]
  revision: number
  payload_hash: string
  photo_count: number
}

export interface ObservationExportMissing {
  observation_id: string
  field: string
}

export interface ObservationExportWarning {
  observation_id: string
  code?: string
  message?: string
  [key: string]: unknown
}

export interface ObservationExportPreview {
  snapshot_id: string
  manifest_hash: string
  expires_at: string
  selection_hash: string
  missing_hash: string
  missing: ObservationExportMissing[]
  warnings: ObservationExportWarning[]
  requires_ack: boolean
  suggested_filename: string
  records: ObservationExportRecord[]
}

export interface ObservationExportCreated {
  export_id: string
  snapshot_id: string
  manifest_hash: string
  expires_at: string
  filename: string
  byte_size: number
  content_hash: string
  missing: ObservationExportMissing[]
  warnings: ObservationExportWarning[]
}

/** Stable default order: date asc, no date last; start time asc, no time last;
 * creation order; id tie-break. Filtering/paging never mutates this order. */
export function compareObservationListItems(
  a: ObservationListItem,
  b: ObservationListItem,
): number {
  const aMissingDate = !a.observation_date
  const bMissingDate = !b.observation_date
  if (aMissingDate !== bMissingDate) return aMissingDate ? 1 : -1
  if (!aMissingDate && a.observation_date !== b.observation_date) {
    return a.observation_date! < b.observation_date! ? -1 : 1
  }
  const aMissingTime = !a.start_time
  const bMissingTime = !b.start_time
  if (aMissingTime !== bMissingTime) return aMissingTime ? 1 : -1
  if (!aMissingTime && a.start_time !== b.start_time) {
    return a.start_time! < b.start_time! ? -1 : 1
  }
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1
  if (a.observation_id === b.observation_id) return 0
  return a.observation_id < b.observation_id ? -1 : 1
}

/** Insert one explicitly selected id without changing existing order. */
export function insertSelectedId(
  order: string[],
  items: Record<string, ObservationListItem>,
  id: string,
  manual: boolean,
): string[] {
  if (order.includes(id)) return order
  if (manual) return [...order, id]
  const incoming = items[id]
  if (!incoming) return [...order, id]
  const next = [...order]
  const index = next.findIndex((existingId) => {
    const existing = items[existingId]
    return existing ? compareObservationListItems(incoming, existing) < 0 : false
  })
  if (index < 0) next.push(id)
  else next.splice(index, 0, id)
  return next
}

export function moveSelectedId(
  order: string[],
  id: string,
  delta: -1 | 1,
): string[] {
  const index = order.indexOf(id)
  if (index < 0) return order
  const target = index + delta
  if (target < 0 || target >= order.length) return order
  const next = [...order]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

export function removeSelectedId(order: string[], id: string): string[] {
  return order.filter((item) => item !== id)
}

export function selectedObservationItems(
  order: string[],
  items: Record<string, ObservationListItem>,
): ObservationListItem[] {
  return order
    .map((id) => items[id])
    .filter((item): item is ObservationListItem => item !== undefined)
}

export function observationMissingLabel(field: string): string {
  if (field.startsWith('analysis_evaluation.')) {
    const key = field.slice('analysis_evaluation.'.length) as EvaluationKey
    return EVALUATION_LABELS[key] ?? field
  }
  return BASIC_FIELD_LABELS[field] ?? field
}
