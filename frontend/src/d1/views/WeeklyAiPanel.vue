<script setup lang="ts">
import type { BlockingDraft, SaveOutcome } from '../leave'
import type { WeeklyEditorController } from '../weekly-editor'
import type { WeeklyDetail, WeeklyDraftContent } from '../weekly'
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createWeeklyApi, newWeeklyRequestId } from '../weekly'
import { getSessionEpoch } from '../client'
import { isIndeterminate } from '../operations'
import { acceptedProgress, progressPhaseLabel, progressMatchesTask, type AiProgressView } from '../ai-progress'
import { WEEKLY_AI_COLUMNS, candidateLines, createWeeklyAiApi, groupStatus, groupStatusLabel, eligibilityLabel, taskStatusLabel, certaintyLabel, targetLabel, projectWeeklyAiError, weeklyEditSignature, type WeeklyAiCandidate, type WeeklyAiColumn, type WeeklyAiCreateOut, type WeeklyAiSelection, type WeeklyAiTask, type WeeklyAiAdoptionPreview, type WeeklyAiAdoptionResult } from '../weekly-ai'
import DirectionalRevisionDialog from '../components/DirectionalRevisionDialog.vue'
import DirectionalRevisionTrigger from '../components/DirectionalRevisionTrigger.vue'
import {
  captureDirectionalSelection,
  directionalSelectionKey,
  validateDirectionalSelection,
  wholeDirectionalSelection,
  type DirectionalAdoptPayload,
  type DirectionalApplyResult,
  type DirectionalOpenRequest,
  type DirectionalScope,
  type DirectionalSelection,
} from '../directional-revision'
const props = withDefaults(defineProps<{ controller: WeeklyEditorController; planId: string; detail: WeeklyDetail | null; focusSelected?: boolean; disabled?: boolean; profileEpoch?: number; sessionEpoch?: number }>(), { disabled: false, focusSelected: false, profileEpoch: 0, sessionEpoch: 0 })
const emit = defineEmits<{ (e: 'busy', value: boolean): void; (e: 'blocking', value: BlockingDraft | null): void; (e: 'focus-area'): void }>()
const api = createWeeklyAiApi()
const weeklyApi = createWeeklyApi()
const selectedFields = ref<WeeklyAiColumn[]>([])
const tasks = ref<WeeklyAiTask[]>([])
const candidates = ref<WeeklyAiCandidate[]>([])
const preservedCandidates = ref<WeeklyAiCandidate[]>([])
const batch = ref<WeeklyAiCreateOut | null>(null)
const preview = ref<WeeklyAiAdoptionPreview | null>(null)
const selectedKeys = ref<string[]>([])
const candidateEdits = ref<Record<string, Record<string, string>>>({})
const candidateEditBaselines = ref<Record<string, string>>({})
const regenerateInstructions = ref<Record<string, string>>({})
const regeneratedNotice = ref('')
const submitted = ref<WeeklyDraftContent | null>(null)
const aiBusy = ref(false)
const error = ref('')
const readError = ref('')
const batchReadPending = ref(false)
const notice = ref('')
const retryAckByTask = ref<Record<string, boolean>>({})
const materialText = ref('')
const materialTouched = ref(false)
const directionalOpen = ref(false)
const directionalBusy = ref(false)
const directionalRequest = ref<DirectionalOpenRequest | null>(null)
const directionalSelections = ref<Record<string, DirectionalSelection>>({})
const directionalNotice = ref('')
const directionalNoticeCandidateId = ref('')
let alive = true
let aiBusyToken = 0
let adoptGateRelease: (() => void) | null = null
function holdAdoptGate(): void {
  if (adoptGateRelease) return
  adoptGateRelease = props.controller.beginExternalBusy('weekly-ai-adopt-pending')
}
function releaseAdoptGate(): void {
  if (!adoptGateRelease) return
  adoptGateRelease()
  adoptGateRelease = null
}
let panelRequestFlight = false
let refreshGeneration = 0
function beginAiBusy(): number { const token = ++aiBusyToken; aiBusy.value = true; return token }
function endAiBusy(token: number): void { if (token === aiBusyToken) aiBusy.value = false }
onBeforeUnmount(() => { alive = false; aiBusyToken += 1; refreshGeneration += 1; panelRequestFlight = false; directionalOpen.value = false; directionalBusy.value = false; directionalRequest.value = null; releaseAdoptGate(); emit('busy', false); emit('blocking', null) })
const progress = ref<Record<string, AiProgressView>>({})
const materialsFocusReady = computed(() => props.focusSelected || Boolean(props.controller.getContent().focus_area))
const focusHint = '未选择重点区域时，AI 只依据当前班级年龄、已保存周主题和已有可靠选择给出“建议材料”，每项无原文证据，请预览核对后采用。'
watch(materialsFocusReady, (ready) => { if (ready && notice.value === focusHint) notice.value = '' })
function saveBlockedMessage(outcome: SaveOutcome): string {
  const failure = props.controller.getLastFailure?.() ?? null
  const message = failure?.message ?? (outcome === 'indeterminate' ? '保存结果未确认，请先核对原请求' : '保存未完成')
  return `保存未完成：${message}。当前输入已保留，请先处理保存后再继续`
}
function reportSaveBlocked(outcome: SaveOutcome): void {
  error.value = saveBlockedMessage(outcome)
  notice.value = ''
}
function requestFocusArea(): void {
  if (props.disabled) return
  error.value = ''
  notice.value = focusHint
  emit('focus-area')
}
type PanelEpoch = { session: number; profile: number; plan: string; identity: string; controller: object }
const pendingCreate = ref<{ kind: 'games' | 'columns' | 'materials'; body: Record<string, unknown>; planId: string; requestId: string; epoch: PanelEpoch; preservePrevious: boolean } | null>(null)
const pendingAdopt = ref<{ body: Record<string, unknown>; planId: string; preview: WeeklyAiAdoptionPreview; guard: { identity: string; input_revision: number; sequence: number }; submitted: WeeklyDraftContent; epoch: PanelEpoch } | null>(null)
const adoptCommitted = ref<WeeklyAiAdoptionResult | null>(null)
const pendingAction = ref<{ taskId: string; kind: 'cancel' | 'resume' | 'retry'; body: Record<string, unknown>; planId: string; epoch: PanelEpoch } | null>(null)

const visibleCandidates = computed(() => {
  const byId = new Map<string, WeeklyAiCandidate>()
  for (const candidate of [...preservedCandidates.value, ...candidates.value]) {
    byId.set(candidate.candidate_id, candidate)
  }
  return [...byId.values()]
})
const blocking = computed<BlockingDraft | null>(() => directionalBusy.value ? { kind: 'weekly', message: '定向修改正在生成或原受理结果待核对：请先处理后再离开' } : aiBusy.value ? { kind: 'weekly', message: '周计划 AI 正在处理，请等待或查询原请求' } : preview.value ? { kind: 'candidate', message: 'AI 候选预览尚未采用或关闭，请先处理' } : (pendingCreate.value || pendingAdopt.value || pendingAction.value) ? { kind: 'weekly', message: 'AI 请求结果未确认，请先只读核对这次原操作' } : anyCandidateEditDirty() ? { kind: 'candidate', message: '候选有未采用的编辑：请采用并保存，或取消本次候选编辑后再离开' } : null)
watch([aiBusy, directionalBusy, blocking], () => { emit('busy', aiBusy.value || directionalBusy.value); emit('blocking', blocking.value) }, { immediate: true })
function syncMaterialFromActual(): void {
  const detailMaterials = props.detail?.draft.content.materials ?? null
  const actual = props.controller.getContent().materials
  if (props.controller.isDirty() && actual !== detailMaterials) {
    materialText.value = actual ?? ''
    materialTouched.value = true
    return
  }
  materialText.value = actual ?? detailMaterials ?? ''
  materialTouched.value = false
}
watch(() => props.detail, syncMaterialFromActual, { immediate: true })
watch(() => props.planId, () => {
  refreshGeneration += 1
  batch.value = null; tasks.value = []; candidates.value = []; selectedKeys.value = []; candidateEdits.value = {}; candidateEditBaselines.value = {}; regenerateInstructions.value = {}; regeneratedNotice.value = ''; preview.value = null; pendingCreate.value = null; pendingAdopt.value = null; adoptCommitted.value = null; pendingAction.value = null; releaseAdoptGate(); progress.value = {}; error.value = ''; readError.value = ''; batchReadPending.value = false; notice.value = ''; directionalOpen.value = false; directionalBusy.value = false; directionalRequest.value = null; directionalSelections.value = {}; directionalNotice.value = ''; directionalNoticeCandidateId.value = ''
  void refreshBatch()
})
function fail(errorValue: unknown) { const projected = projectWeeklyAiError(errorValue); error.value = projected.message; notice.value = ''; return projected }
function epoch(): PanelEpoch { return { session: getSessionEpoch(), profile: props.profileEpoch, plan: props.planId, identity: props.controller.identity(), controller: props.controller } }
function currentEpoch(value: PanelEpoch): boolean { return alive && toRaw(value.controller) === toRaw(props.controller) && value.session === getSessionEpoch() && value.profile === props.profileEpoch && value.plan === props.planId && value.identity === props.controller.identity() }
function candidateTargets(candidate: WeeklyAiCandidate): WeeklyAiSelection[] { return (candidate.available_targets.length ? candidate.available_targets : [candidate.target]).map((target) => ({ candidate_id: candidate.candidate_id, target })) }
const OUTDOOR_KEYS = ['collective_1', 'collective_2', 'free_choice_1'] as const
const GAME_EDIT_FIELDS = ['name', 'shared_objectives', 'guidance_points', 'focus_guidance'] as const
const FOCUS_EDIT_FIELDS = ['name', 'objectives', 'guidance', 'support_strategy'] as const
function rec(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function initCandidateEdit(candidate: WeeklyAiCandidate): Record<string, string> {
  const data = rec(candidate.data)
  const state: Record<string, string> = {}
  if (candidate.target !== 'games' && candidate.target !== 'materials') {
    state.text = String(data.text ?? '')
    return state
  }
  if (candidate.target === 'materials') {
    const items = Array.isArray(data.items) ? data.items : []
    items.forEach((item, index) => { state[`item.${index}.text`] = String(rec(item).text ?? '') })
    return state
  }
  const slots = rec(data.outdoor_game_slots)
  for (const key of OUTDOOR_KEYS) {
    const item = rec(slots[key])
    if (!Object.keys(item).length) continue
    for (const field of GAME_EDIT_FIELDS) state[`slot.${key}.${field}`] = String(item[field] ?? '')
  }
  const focus = rec(data.focus_area)
  if (Object.keys(focus).length) {
    for (const field of FOCUS_EDIT_FIELDS) state[`focus.${field}`] = String(focus[field] ?? '')
  }
  return state
}
function resetCandidateEdit(candidate: WeeklyAiCandidate, unselect = true): void {
  if (directionalNoticeCandidateId.value === candidate.candidate_id) {
    directionalNotice.value = ''
    directionalNoticeCandidateId.value = ''
  }
  const state = initCandidateEdit(candidate)
  candidateEdits.value = { ...candidateEdits.value, [candidate.candidate_id]: state }
  candidateEditBaselines.value = { ...candidateEditBaselines.value, [candidate.candidate_id]: weeklyEditSignature(state) }
  regenerateInstructions.value = { ...regenerateInstructions.value, [candidate.candidate_id]: '' }
  if (unselect) {
    const keys = new Set(candidateTargets(candidate).map((item) => keyForSelection(item)))
    selectedKeys.value = selectedKeys.value.filter((key) => !keys.has(key))
  }
}
function syncCandidateEdits(): void {
  const edits: Record<string, Record<string, string>> = {}
  const baselines: Record<string, string> = {}
  for (const candidate of visibleCandidates.value) {
    const existing = candidateEdits.value[candidate.candidate_id]
    const state = existing ?? initCandidateEdit(candidate)
    edits[candidate.candidate_id] = state
    baselines[candidate.candidate_id] =
      candidateEditBaselines.value[candidate.candidate_id] ??
      weeklyEditSignature(state)
  }
  candidateEdits.value = edits
  candidateEditBaselines.value = baselines
  for (const key of Object.keys(regenerateInstructions.value)) {
    if (!edits[key]) delete regenerateInstructions.value[key]
  }
}
function editField(candidate: WeeklyAiCandidate, key: string): string { return candidateEdits.value[candidate.candidate_id]?.[key] ?? '' }
function fieldEditLabel(candidate: WeeklyAiCandidate, key: string, original: unknown): string {
  return editField(candidate, key) === String(original ?? '') ? '当前候选文字' : '改写建议'
}
function setEditField(candidate: WeeklyAiCandidate, key: string, value: string): void {
  const state = { ...(candidateEdits.value[candidate.candidate_id] ?? {}), [key]: value }
  candidateEdits.value = { ...candidateEdits.value, [candidate.candidate_id]: state }
}
function candidateEditDirty(candidate: WeeklyAiCandidate): boolean {
  return weeklyEditSignature(candidateEdits.value[candidate.candidate_id] ?? {}) !== (candidateEditBaselines.value[candidate.candidate_id] ?? '{}')
}
function anyCandidateEditDirty(): boolean { return visibleCandidates.value.some(candidateEditDirty) }
function directionalCandidate(id: string): WeeklyAiCandidate | null {
  return (
    visibleCandidates.value.find((item) => item.candidate_id === id) ?? null
  )
}

const directionalLiveScope = computed<DirectionalScope | null>(() => {
  const request = directionalRequest.value
  if (!request) return null
  return {
    ...request.scope,
    version: props.controller.savedDraftRef().version,
  }
})

const directionalLiveFieldText = computed(() => {
  const request = directionalRequest.value
  if (!request) return ''
  const candidate = directionalCandidate(request.scope.candidate_id ?? '')
  return candidate ? editField(candidate, request.scope.field) : ''
})

function rememberDirectionalSelection(event: Event): void {
  const captured = captureDirectionalSelection(event)
  if (!captured) return
  directionalSelections.value = {
    ...directionalSelections.value,
    [captured.key]: captured.selection,
  }
}

function directionalKeyLabel(key: string): string {
  if (key === 'text') return '候选正文'
  const slot = /^slot\.([^.]+)\.(.+)$/.exec(key)
  if (slot) {
    return `${OUTDOOR_LABELS[slot[1]] ?? slot[1]} · ${
      GAME_FIELD_LABELS[slot[2]] ?? slot[2]
    }（候选）`
  }
  const focus = /^focus\.(.+)$/.exec(key)
  if (focus) {
    return `重点区域 · ${FOCUS_FIELD_LABELS[focus[1]] ?? focus[1]}（候选）`
  }
  const item = /^item\.(\d+)\.text$/.exec(key)
  if (item) return `材料第 ${Number(item[1]) + 1} 项（候选）`
  return key
}

function openDirectional(
  candidate: WeeklyAiCandidate,
  key: string,
  whole: boolean,
): void {
  if (
    !alive ||
    props.disabled ||
    aiBusy.value ||
    directionalBusy.value ||
    panelRequestFlight ||
    pendingCreate.value ||
    pendingAdopt.value ||
    pendingAction.value ||
    preview.value
  ) {
    return
  }
  if (candidate.eligibility !== 'eligible') {
    error.value = '该候选来源或规则已变化，只能查看'
    return
  }
  const text = editField(candidate, key)
  const selection = whole
    ? wholeDirectionalSelection(text)
    : directionalSelections.value[
        directionalSelectionKey(key, '', candidate.candidate_id)
      ]
  if (!selection) {
    error.value = '请先在候选文字中选择内容，或使用「整栏修改」'
    return
  }
  if (!whole && text === '') {
    error.value = '空栏请使用「整栏修改」明确范围'
    return
  }
  const selectionError = validateDirectionalSelection(text, selection)
  if (selectionError) {
    error.value = selectionError
    return
  }
  const saved = props.controller.savedDraftRef()
  const scope: DirectionalScope = {
    kind: 'weekly_candidate',
    record_id: props.planId,
    version: saved.version,
    candidate_id: candidate.candidate_id,
    field: key,
  }
  const sourceLines = [
    ...candidateLines(candidate),
    `草稿版本 v${saved.version}`,
    `候选状态：${eligibilityLabel(candidate.eligibility)}`,
  ]
  directionalRequest.value = {
    scope,
    fieldText: text,
    selection,
    sourceLabel: `${targetLabel(candidate.target)} · ${directionalKeyLabel(key)}`,
    sourceLines,
    sourceStale: candidateEditDirty(candidate),
  }
  directionalOpen.value = true
}

function applyDirectionalAdoption(
  payload: DirectionalAdoptPayload,
): DirectionalApplyResult {
  const request = directionalRequest.value
  if (!request || payload.snapshot.scope.kind !== 'weekly_candidate') {
    return { ok: false, message: '定向修改目标已失效，请重新选择' }
  }
  const submitted = payload.snapshot
  const saved = props.controller.savedDraftRef()
  if (
    submitted.scope.record_id !== props.planId ||
    submitted.scope.version !== saved.version ||
    submitted.scope.candidate_id !==
      (request.scope.candidate_id ?? '') ||
    submitted.scope.field !== request.scope.field
  ) {
    return {
      ok: false,
      message: '周计划、候选或草稿版本已变化：候选和前后文字已保留，请重新选择',
    }
  }
  if (submitted.profileEpoch !== props.profileEpoch) {
    return { ok: false, message: '本地档案已切换：未采用，请重新选择' }
  }
  if (submitted.sessionEpoch !== getSessionEpoch()) {
    return { ok: false, message: '本机会话已变化：未采用，请重新选择' }
  }
  const candidate = directionalCandidate(
    submitted.scope.candidate_id ?? '',
  )
  if (!candidate || candidate.eligibility !== 'eligible') {
    return {
      ok: false,
      message: '候选来源或规则已变化：候选和前后文字已保留，请重新选择',
    }
  }
  const currentText = editField(candidate, submitted.scope.field)
  if (currentText !== submitted.fieldText) {
    return {
      ok: false,
      message: '当前候选文字已变化：候选和前后文字已保留，请重新选择',
    }
  }
  const selectionError = validateDirectionalSelection(
    currentText,
    submitted.selection,
  )
  if (selectionError) {
    return { ok: false, message: selectionError }
  }
  setEditField(candidate, submitted.scope.field, payload.fieldAfter)
  directionalNotice.value =
    '已写入候选待采用区，尚未写入周计划；仍需点击「采用并保存」'
  directionalNoticeCandidateId.value = candidate.candidate_id
  directionalOpen.value = false
  return { ok: true }
}

function closePreservedCandidates(): void {
  const ids = new Set(preservedCandidates.value.map((candidate) => candidate.candidate_id))
  if (ids.has(directionalNoticeCandidateId.value)) {
    directionalNotice.value = ''
    directionalNoticeCandidateId.value = ''
  }
  preservedCandidates.value = []
  const edits = { ...candidateEdits.value }
  const baselines = { ...candidateEditBaselines.value }
  for (const id of ids) {
    delete edits[id]
    delete baselines[id]
  }
  candidateEdits.value = edits
  candidateEditBaselines.value = baselines
  selectedKeys.value = selectedKeys.value.filter((key) => {
    const candidateId = key.split(':')[0]
    return !ids.has(candidateId)
  })
}
function resetAllCandidateEdits(): void {
  for (const candidate of visibleCandidates.value) resetCandidateEdit(candidate, false)
  selectedKeys.value = []
  regeneratedNotice.value = ''
  directionalNotice.value = ''
  directionalNoticeCandidateId.value = ''
  notice.value = '已取消本次候选编辑；未写入正文'
  error.value = ''
}
function buildCandidateEdit(candidate: WeeklyAiCandidate): Record<string, unknown> | null {
  const data = rec(candidate.data)
  if (candidate.target !== 'games' && candidate.target !== 'materials') {
    return { text: editField(candidate, 'text') }
  }
  if (candidate.target === 'materials') {
    const items = Array.isArray(data.items) ? data.items : []
    return {
      items: items.map((_item, index) => ({ text: editField(candidate, `item.${index}.text`) })),
    }
  }
  const originalSlots = rec(data.outdoor_game_slots)
  const slots: Record<string, Record<string, string>> = {}
  for (const key of OUTDOOR_KEYS) {
    if (!Object.keys(rec(originalSlots[key])).length) continue
    slots[key] = Object.fromEntries(
      GAME_EDIT_FIELDS.map((field) => [field, editField(candidate, `slot.${key}.${field}`)]),
    ) as Record<string, string>
  }
  const focus = Object.keys(rec(data.focus_area)).length
    ? Object.fromEntries(
        FOCUS_EDIT_FIELDS.map((field) => [field, editField(candidate, `focus.${field}`)]),
      )
    : null
  return { outdoor_game_slots: slots, focus_area: focus }
}
function selectionsFor(chosen: WeeklyAiCandidate[]): WeeklyAiSelection[] {
  return chosen.map((candidate) => ({
    candidate_id: candidate.candidate_id,
    target: candidate.target,
    edit: buildCandidateEdit(candidate) ?? undefined,
  }))
}
function selectedCandidates(): WeeklyAiCandidate[] {
  return visibleCandidates.value.filter((candidate) =>
    candidateTargets(candidate).some((item) => selectedKeys.value.includes(keyForSelection(item))),
  )
}
const OUTDOOR_LABELS: Record<string, string> = {
  collective_1: '集体游戏一',
  collective_2: '集体游戏二',
  free_choice_1: '自选游戏',
}
const GAME_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  shared_objectives: '共同目标',
  guidance_points: '指导',
  focus_guidance: '重点指导',
}
const FOCUS_FIELD_LABELS: Record<string, string> = {
  name: '名称',
  objectives: '目标',
  guidance: '指导',
  support_strategy: '支持策略',
}
function gameSlots(candidate: WeeklyAiCandidate): Record<string, unknown> {
  return rec(rec(candidate.data).outdoor_game_slots)
}
function gameItem(candidate: WeeklyAiCandidate, key: string): Record<string, unknown> | null {
  const item = rec(gameSlots(candidate)[key])
  return Object.keys(item).length ? item : null
}
function focusItem(candidate: WeeklyAiCandidate): Record<string, unknown> | null {
  const item = rec(rec(candidate.data).focus_area)
  return Object.keys(item).length ? item : null
}
function materialItems(candidate: WeeklyAiCandidate): unknown[] {
  const items = rec(candidate.data).items
  return Array.isArray(items) ? items : []
}

function materialEvidence(
  candidate: WeeklyAiCandidate,
  index: number,
): string[] {
  const row = rec(materialItems(candidate)[index])
  const refs = Array.isArray(row.evidence_refs) ? row.evidence_refs : []
  return refs.map((ref) => {
    const value = rec(ref)
    const quote = String(value.quote ?? '')
    const fieldPath = String(value.field_path ?? '')
    const source = rec(value.source)
    const origin = String(
      source.date ?? source.name ?? source.kind ?? '',
    )
    return `原文：${quote || '（空）'}${
      origin ? ` · ${origin}` : ''
    }${fieldPath ? ` · ${fieldPath}` : ''}`
  })
}

function sourceLineFor(
  candidate: WeeklyAiCandidate,
  prefix: string,
): string {
  return (
    candidateLines(candidate).find((line) => line.startsWith(prefix)) ?? ''
  )
}
function candidateFieldDisabled(candidate: WeeklyAiCandidate): boolean {
  return (
    props.disabled ||
    aiBusy.value ||
    directionalBusy.value ||
    candidate.eligibility !== 'eligible'
  )
}
async function ensureSaved(ctx: PanelEpoch): Promise<boolean> {
  try {
    const outcome = await props.controller.saveCurrent()
    if (!currentEpoch(ctx)) return false
    if (outcome !== 'saved' && outcome !== 'unchanged') { reportSaveBlocked(outcome); return false }
    error.value = ''
    return true
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return false
    const failure = props.controller.getLastFailure?.() ?? null
    if (failure) { error.value = `保存未完成：${failure.message}。当前输入已保留，请先处理保存后再继续`; notice.value = '' }
    else fail(errorValue)
    return false
  }
}
/**
 * The shared earlier savePromise may predate a focus chosen while that save
 * was pending. In that case the controller remains dirty relative to the
 * accepted saved draft even though the live form has a focus. Do not send and
 * do not silently start another save: keep the late input and point at the
 * existing Save button for an explicit save-then-retry.
 */
function materialsContextSaved(ctx: PanelEpoch): boolean {
  if (!currentEpoch(ctx)) return false
  if (!props.controller.isDirty()) return true
  error.value = '保存开始后选择的“重点区域”或较晚输入尚未保存到服务器；本次未生成材料，当前输入已保留。请先点“保存”，保存成功后再生成材料'
  notice.value = ''
  return false
}
async function allTasks(planId: string, ctx: PanelEpoch): Promise<WeeklyAiTask[] | null> {
  const result: WeeklyAiTask[] = []
  let cursor: string | undefined
  do {
    const page = await api.tasks(planId, { limit: 100, cursor })
    if (!currentEpoch(ctx)) return null
    result.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return result
}
async function allCandidates(planId: string, ctx: PanelEpoch): Promise<WeeklyAiCandidate[] | null> {
  const result: WeeklyAiCandidate[] = []
  let cursor: string | undefined
  do {
    const page = await api.candidates(planId, { limit: 100, cursor })
    if (!currentEpoch(ctx)) return null
    result.push(...page.items)
    cursor = page.next_cursor ?? undefined
  } while (cursor)
  return result
}
function activateBatch(response: WeeklyAiCreateOut, preservePrevious = false): void {
  if (preservePrevious) {
    const byId = new Map<string, WeeklyAiCandidate>()
    for (const candidate of [...preservedCandidates.value, ...candidates.value]) {
      byId.set(candidate.candidate_id, candidate)
    }
    preservedCandidates.value = [...byId.values()]
  } else {
    preservedCandidates.value = []
    selectedKeys.value = []
    candidateEdits.value = {}
    candidateEditBaselines.value = {}
    regenerateInstructions.value = {}
  }
  batch.value = response
  tasks.value = []
  candidates.value = []
  batchReadPending.value = true
  readError.value = ''
}
async function refreshBatch(): Promise<void> {
  const ctx = epoch()
  const planId = ctx.plan
  const generation = ++refreshGeneration
  const currentGeneration = (): boolean => generation === refreshGeneration
  const known = batch.value ? new Set(batch.value.tasks.map((item) => item.task_id)) : null
  try {
    const allTaskRows = await allTasks(planId, ctx)
    if (!allTaskRows || !currentEpoch(ctx) || !currentGeneration()) return
    const taskRows = known ? allTaskRows.filter((item) => known.has(item.task_id)) : allTaskRows
    const listed = await allCandidates(planId, ctx)
    if (!listed || !currentEpoch(ctx) || !currentGeneration()) return
    const candidatesInScope = known ? listed.filter((item) => known.has(item.task_id)) : listed
    const details: WeeklyAiCandidate[] = []
    for (const item of candidatesInScope) {
      const detail = await api.candidate(planId, item.candidate_id)
      if (!currentEpoch(ctx) || !currentGeneration()) return
      details.push(detail)
    }
    if (!currentEpoch(ctx) || !currentGeneration()) return
    tasks.value = taskRows
    candidates.value = details
    syncCandidateEdits()
    batchReadPending.value = false
    readError.value = ''
  } catch {
    if (!currentEpoch(ctx) || !currentGeneration()) return
    readError.value = 'AI 任务与候选读取失败，请刷新后重试；原任务和候选不会被修改'
  }
}
onMounted(() => { void refreshBatch() })
async function sendCreate(kind: 'games' | 'columns' | 'materials', body: Record<string, unknown>, planId: string): Promise<WeeklyAiCreateOut> {
  if (kind === 'games') return api.games(planId, body as { request_id: string; expected_draft_version: number })
  if (kind === 'columns') return api.columns(planId, body as { request_id: string; expected_draft_version: number; selected_fields: WeeklyAiColumn[] })
  return api.materials(planId, body as { request_id: string; expected_draft_version: number })
}
async function create(kind: 'games' | 'columns' | 'materials'): Promise<void> {
  if (!alive || props.disabled || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) { if (alive && !aiBusy.value) error.value = '请先处理已保留的未确认 AI 请求'; return }
  panelRequestFlight = true
  const ctx = epoch()
  if (!(await ensureSaved(ctx))) { panelRequestFlight = false; return }
  if (!currentEpoch(ctx)) { panelRequestFlight = false; return }
  if (kind === 'materials' && !materialsContextSaved(ctx)) { panelRequestFlight = false; return }
  const saved = props.controller.savedDraftRef()
  const common = { request_id: newWeeklyRequestId(), expected_draft_version: saved.version }
  const body: Record<string, unknown> = kind === 'columns' ? { ...common, selected_fields: [...selectedFields.value] } : common
  pendingCreate.value = { kind, body, planId: ctx.plan, requestId: common.request_id, epoch: ctx, preservePrevious: false }
  submitted.value = props.controller.getContent()
  const busyToken = beginAiBusy(); error.value = ''; notice.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const response = await sendCreate(kind, body, ctx.plan)
    if (!currentEpoch(ctx)) { if (pendingCreate.value?.requestId === common.request_id) pendingCreate.value = null; return }
    activateBatch(response)
    pendingCreate.value = null
    await refreshBatch()
    if (!currentEpoch(ctx)) return
    notice.value = `已提交 ${batch.value?.tasks.length ?? 0} 个 AI 子任务`
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return
    const projected = fail(errorValue)
    if (projected.retry !== 'query') pendingCreate.value = null
  } finally { panelRequestFlight = false; release(); endAiBusy(busyToken) }
}
async function queryCreate(): Promise<void> {
  const pending = pendingCreate.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const operation = await api.operation(pending.planId, pending.requestId)
    if (!currentEpoch(pending.epoch)) return
    if (operation.result && operation.result.weekly_plan_id === pending.planId && Array.isArray(operation.result.tasks)) { activateBatch(operation.result as unknown as WeeklyAiCreateOut, pending.preservePrevious); pendingCreate.value = null; await refreshBatch() }
    else error.value = '原请求尚未产生可读取的创建回执，请勿重建表单'
  } catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue); error.value = '查询未返回原提交，不能据此视为未提交；请保留原请求' } finally { release(); endAiBusy(busyToken) }
}
async function retryCreate(): Promise<void> {
  const pending = pendingCreate.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const response = await sendCreate(pending.kind, pending.body, pending.planId)
    if (!currentEpoch(pending.epoch)) return
    activateBatch(response, pending.preservePrevious)
    pendingCreate.value = null
    await refreshBatch()
  } catch (errorValue) {
    if (!currentEpoch(pending.epoch)) return
    fail(errorValue)
  } finally { release(); endAiBusy(busyToken) }
}
function progressFor(task: WeeklyAiTask): AiProgressView | null {
  const stored = progress.value[task.task_id]
  if (!stored) return null
  return progressMatchesTask(
    task.task_id,
    task.execution?.id ?? null,
    null,
    stored,
  )
    ? stored
    : null
}

function progressReasoningFor(task: WeeklyAiTask): string {
  return progressFor(task)?.reasoning?.trim() ?? ''
}

async function loadProgress(task: WeeklyAiTask): Promise<void> {
  const ctx = epoch()
  try {
    const value = await api.progress(ctx.plan, task.task_id)
    if (!currentEpoch(ctx)) return
    const accepted = acceptedProgress(
      task.task_id,
      task.execution?.id ?? null,
      null,
      value,
    )
    if (!accepted) {
      notice.value = '进度回包与当前任务执行不一致：已忽略，不影响任务状态'
      return
    }
    progress.value = { ...progress.value, [task.task_id]: accepted }
  } catch (errorValue) { if (!currentEpoch(ctx)) return; fail(errorValue) }
}
async function action(task: WeeklyAiTask, kind: 'cancel' | 'resume' | 'retry'): Promise<void> {
  if (!alive || props.disabled || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) return
  if (!task.allowed_actions.includes(kind)) { error.value = '该任务当前不允许此操作'; return }
  if (kind === 'retry' && task.retry_requires_ack && !retryAckByTask.value[task.task_id]) { error.value = '请先确认该任务可能产生重复请求'; return }
  const expected = task.execution?.id ?? null
  if (!expected && kind !== 'cancel') { error.value = '该任务没有可用的执行身份'; return }
  const ctx = epoch()
  const body: Record<string, unknown> = { request_id: newWeeklyRequestId(), expected_execution_id: expected, ...(kind === 'retry' ? { ack_duplicate_cost: Boolean(retryAckByTask.value[task.task_id]) } : {}) }
  pendingAction.value = { taskId: task.task_id, kind, body, planId: ctx.plan, epoch: ctx }
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    await sendTaskAction(ctx.plan, task.task_id, kind, body)
    if (!currentEpoch(ctx)) { if (pendingAction.value?.body.request_id === body.request_id) pendingAction.value = null; return }
    pendingAction.value = null
    await refreshBatch()
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return
    const projected = fail(errorValue)
    if (projected.retry !== 'query') pendingAction.value = null
  } finally {
    if (kind === 'retry') delete retryAckByTask.value[task.task_id]
    release()
    endAiBusy(busyToken)
  }
}
async function sendTaskAction(planId: string, taskId: string, kind: 'cancel' | 'resume' | 'retry', body: Record<string, unknown>): Promise<void> {
  if (kind === 'cancel') await api.cancel(planId, taskId, body as { request_id: string; expected_execution_id: string | null })
  else if (kind === 'resume') await api.resume(planId, taskId, body as { request_id: string; expected_execution_id: string })
  else await api.retry(planId, taskId, body as { request_id: string; expected_execution_id: string; ack_duplicate_cost: boolean })
}
async function queryAction(): Promise<void> {
  const pending = pendingAction.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const operation = await api.taskOperation(String(pending.body.request_id))
    if (!currentEpoch(pending.epoch)) return
    const expectedKind = `ai_task_${pending.kind}`
    const result = operation.result
    const matches = operation.request_id === pending.body.request_id
      && operation.operation_kind === expectedKind
      && result && result.task_id === pending.taskId
      && result.source_kind === 'weekly_plan'
      && result.source_id === pending.planId
      && result.weekly_plan_id === pending.planId
    if (matches) { pendingAction.value = null; await refreshBatch() }
    else { error.value = '原任务操作回执与原任务或周计划不一致，保留原请求'; return }
  } catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue); error.value = '查询未返回原任务提交，不能据此重复发送' } finally { release(); endAiBusy(busyToken) }
}
async function retryAction(): Promise<void> {
  const pending = pendingAction.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    await sendTaskAction(pending.planId, pending.taskId, pending.kind, pending.body)
    if (!currentEpoch(pending.epoch)) return
    pendingAction.value = null
    await refreshBatch()
  } catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue) } finally { release(); endAiBusy(busyToken) }
}
async function adoptCandidates(chosen: WeeklyAiCandidate[]): Promise<void> {
  if (!alive || props.disabled || !chosen.length || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) {
    if (alive && !aiBusy.value && !chosen.length) error.value = '请选择至少一个可用候选'
    return
  }
  if (chosen.some((candidate) => candidate.eligibility !== 'eligible')) { error.value = '所选候选的来源或规则已变化，只能查看'; return }
  const batchIds = new Set(chosen.map((candidate) => candidate.create_operation_id ?? '__none__'))
  if (batchIds.size !== 1) { error.value = '不同批候选不能一起采用；请保留原批次或新批次中的一组'; return }
  const selections = selectionsFor(chosen)
  const selectionSignature = weeklyEditSignature(selections)
  panelRequestFlight = true
  const ctx = epoch()
  if (!(await ensureSaved(ctx))) { panelRequestFlight = false; return }
  if (!currentEpoch(ctx)) { panelRequestFlight = false; return }
  if (weeklyEditSignature(selectionsFor(chosen)) !== selectionSignature) {
    panelRequestFlight = false
    error.value = '保存期间候选编辑已变化：本次未采用，请重新点击'
    return
  }
  const guard = props.controller.snapshot()
  const submittedContent = props.controller.getContent()
  const busyToken = beginAiBusy(); error.value = ''; notice.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const response = await api.adoptionPreview(ctx.plan, {
      expected_draft_version: props.controller.savedDraftRef().version,
      selections,
    })
    if (!currentEpoch(ctx)) return
    const now = props.controller.snapshot()
    if (
      now.identity !== guard.identity ||
      now.input_revision !== guard.input_revision ||
      now.sequence !== guard.sequence ||
      weeklyEditSignature(selectionsFor(chosen)) !== selectionSignature
    ) {
      error.value = '预览期间输入、候选编辑或版本已变化，请重新采用'
      return
    }
    preview.value = response
    const previewGuardValue = {
      identity: guard.identity,
      input_revision: guard.input_revision,
      sequence: guard.sequence,
    }
    submitted.value = submittedContent
    const pending = {
      body: {
        request_id: newWeeklyRequestId(),
        expected_draft_version: response.draft.version,
        preview_token: response.preview_token,
      },
      planId: ctx.plan,
      guard: previewGuardValue,
      submitted: submittedContent,
      epoch: ctx,
    }
    const pendingWithPreview = { ...pending, preview: response }
    pendingAdopt.value = pendingWithPreview
    holdAdoptGate()
    try {
      const result = await api.adopt(
        pending.planId,
        pending.body as { request_id: string; expected_draft_version: number; preview_token: string },
      )
      if (!weeklyAdoptResultMatches(result, pendingWithPreview)) {
        error.value = '采用回执与当前请求不一致：请核对原采用，不要重复提交'
        return
      }
      adoptCommitted.value = result
      try {
        await finishAdopt(pending, result)
      } catch {
        if (!currentEpoch(pending.epoch)) return
        if (adoptCommitted.value) {
          error.value = '采用已保存，但正文读取失败：请核对原采用（只读重读，不重新采用）'
          return
        }
        pendingAdopt.value = null
        releaseAdoptGate()
        preview.value = null
      }
    } catch (errorValue) {
      if (!currentEpoch(pending.epoch)) return
      const projected = fail(errorValue)
      if (isIndeterminate(errorValue) || projected.retry === 'query') {
        error.value = '采用结果待核对：请核对原采用，不要重复提交'
        return
      }
      pendingAdopt.value = null
      releaseAdoptGate()
      adoptCommitted.value = null
      preview.value = null
    }
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return
    fail(errorValue)
  } finally {
    panelRequestFlight = false
    release()
    endAiBusy(busyToken)
  }
}

async function regenerateCandidate(candidate: WeeklyAiCandidate): Promise<void> {
  if (!alive || props.disabled || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) return
  if (candidate.eligibility !== 'eligible') { error.value = '该候选来源或规则已变化，不能作为重新生成基准'; return }
  const candidateId = candidate.candidate_id
  const instructionAtStart = (regenerateInstructions.value[candidateId] ?? '').trim()
  panelRequestFlight = true
  const ctx = epoch()
  if (!(await ensureSaved(ctx))) { panelRequestFlight = false; return }
  if (!currentEpoch(ctx)) { panelRequestFlight = false; return }
  if ((regenerateInstructions.value[candidateId] ?? '').trim() !== instructionAtStart) {
    panelRequestFlight = false
    error.value = '保存期间定向要求已变化：本次未重新生成，请重新点击'
    return
  }
  const saved = props.controller.savedDraftRef()
  if (candidate.source_revision != null && candidate.source_revision !== saved.version) {
    panelRequestFlight = false
    error.value = '原候选基于旧草稿，当前已保存内容变化；请用当前内容重新生成'
    return
  }
  const kind: 'games' | 'columns' | 'materials' = candidate.target === 'games'
    ? 'games'
    : candidate.target === 'materials'
      ? 'materials'
      : 'columns'
  const requestId = newWeeklyRequestId()
  const body: Record<string, unknown> = {
    request_id: requestId,
    expected_draft_version: saved.version,
    base_candidate_id: candidate.candidate_id,
  }
  const instruction = instructionAtStart
  if (instruction) body.revision_instruction = instruction
  if (kind === 'columns') body.selected_fields = [candidate.target]
  pendingCreate.value = { kind, body, planId: ctx.plan, requestId, epoch: ctx, preservePrevious: true }
  submitted.value = props.controller.getContent()
  const busyToken = beginAiBusy(); error.value = ''; notice.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const response = await sendCreate(kind, body, ctx.plan)
    if (!currentEpoch(ctx)) { if (pendingCreate.value?.requestId === requestId) pendingCreate.value = null; return }
    activateBatch(response, true)
    pendingCreate.value = null
    await refreshBatch()
    if (!currentEpoch(ctx)) return
    regeneratedNotice.value = candidate.candidate_id
    notice.value = '已提交重新生成；原候选仍保留，当前已保存周内容未被覆盖'
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return
    const projected = fail(errorValue)
    if (projected.retry !== 'query') pendingCreate.value = null
  } finally {
    panelRequestFlight = false
    release()
    endAiBusy(busyToken)
  }
}

function closePreview(clearSelection = true): void { preview.value = null; if (clearSelection) selectedKeys.value = [] }
function keyForSelection(item: WeeklyAiSelection): string { return `${item.candidate_id}:${item.target}` }
function sameSelections(left: WeeklyAiSelection[], right: WeeklyAiSelection[]): boolean {
  if (!Array.isArray(left) || !Array.isArray(right)) return false
  const canonical = (items: WeeklyAiSelection[]) => {
    if (!items.every((item) => item && typeof item.candidate_id === 'string' && typeof item.target === 'string')) return null
    return items.map(keyForSelection).sort().join('|')
  }
  const a = canonical(left)
  const b = canonical(right)
  return a !== null && a === b
}
function validSelectionShape(value: unknown): value is WeeklyAiSelection[] {
  if (!Array.isArray(value) || value.length === 0) return false
  const seen = new Set<string>()
  for (const item of value) {
    if (!item || typeof item !== 'object') return false
    const keys = Object.keys(item).sort()
    if (keys.length !== 2 || keys[0] !== 'candidate_id' || keys[1] !== 'target') return false
    const candidateId = (item as { candidate_id?: unknown }).candidate_id
    const target = (item as { target?: unknown }).target
    if (typeof candidateId !== 'string' || !candidateId) return false
    if (typeof target !== 'string' || !target) return false
    const key = `${candidateId}:${target}`
    if (seen.has(key)) return false
    seen.add(key)
  }
  return true
}
function weeklyAdoptResultMatches(
  result: unknown,
  pending: { body: Record<string, unknown>; planId: string; preview: WeeklyAiAdoptionPreview },
): boolean {
  try {
    if (!result || typeof result !== 'object') return false
    const value = result as Record<string, unknown>
    if (value.request_id !== pending.body.request_id) return false
    if (value.weekly_plan_id !== pending.planId) return false
    if (value.status !== 'committed') return false
    if (!validSelectionShape(value.selections)) return false
    if (!validSelectionShape(pending.preview.selections)) return false
    if (!sameSelections(value.selections, pending.preview.selections)) return false
    const draft = value.draft
    if (!draft || typeof draft !== 'object') return false
    const row = draft as Record<string, unknown>
    const expectedVersion = Number(pending.body.expected_draft_version)
    if (!Number.isInteger(expectedVersion) || expectedVersion < 1) return false
    if (typeof row.id !== 'string' || !row.id) return false
    if (row.version !== expectedVersion + 1) return false
    if (typeof row.content_hash !== 'string' || !/^[0-9a-f]{64}$/.test(row.content_hash)) return false
    return true
  } catch {
    return false
  }
}
function clearAdoptedCandidateState(selections: WeeklyAiSelection[]): void {
  const adoptedCandidates = new Set(selections.map((item) => item.candidate_id))
  const adoptedKeys = new Set(selections.map((item) => keyForSelection(item)))
  const edits = { ...candidateEdits.value }
  const baselines = { ...candidateEditBaselines.value }
  for (const candidateId of adoptedCandidates) {
    delete edits[candidateId]
    delete baselines[candidateId]
  }
  candidateEdits.value = edits
  candidateEditBaselines.value = baselines
  selectedKeys.value = selectedKeys.value.filter((key) => !adoptedKeys.has(key))
}
async function finishAdopt(pending: { body: Record<string, unknown>; planId: string; guard: { identity: string; input_revision: number; sequence: number }; submitted: WeeklyDraftContent; epoch: PanelEpoch }, result: WeeklyAiAdoptionResult): Promise<void> {
  if (!currentEpoch(pending.epoch)) { if (pendingAdopt.value?.body.request_id === pending.body.request_id) { pendingAdopt.value = null; releaseAdoptGate() }; return }
  const detail = await weeklyApi.get(pending.planId)
  if (!currentEpoch(pending.epoch)) { if (pendingAdopt.value?.body.request_id === pending.body.request_id) { pendingAdopt.value = null; releaseAdoptGate() }; return }
  const outcome = props.controller.reconcileExternalDraft(detail, pending.guard, pending.submitted, result.draft)
  if (outcome === 'stale') return
  if (outcome === 'conflict') {
    adoptCommitted.value = null
    pendingAdopt.value = null
    releaseAdoptGate()
    preview.value = null
    error.value = 'AI 采用回包与当前草稿不一致，请核对；候选编辑仍保留'
  } else {
    notice.value = 'AI 候选已采用'
    adoptCommitted.value = null
    pendingAdopt.value = null
    releaseAdoptGate()
    closePreview(false)
    clearAdoptedCandidateState(result.selections)
    if (
      directionalNoticeCandidateId.value &&
      result.selections.some(
        (item) =>
          item.candidate_id === directionalNoticeCandidateId.value,
      )
    ) {
      directionalNotice.value = ''
      directionalNoticeCandidateId.value = ''
    }
    await refreshBatch()
  }
}
async function queryAdopt(): Promise<void> {
  const pending = pendingAdopt.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const operation = await api.operation(pending.planId, String(pending.body.request_id))
    const result = operation.result as unknown as WeeklyAiAdoptionResult
    const envelopeMatches =
      operation.request_id === pending.body.request_id &&
      (operation.operation_kind === 'weekly_ai_adopt' || operation.operation_kind === 'adopt') &&
      operation.status === 'committed'
    if (!envelopeMatches || !weeklyAdoptResultMatches(result, pending)) {
      error.value = '原采用回执与当前请求、计划、选项或草稿版本不一致；保留原票据'
      return
    }
    adoptCommitted.value = result
    try {
      await finishAdopt(pending, result)
    } catch {
      if (currentEpoch(pending.epoch)) error.value = '采用已保存，但正文读取失败：请核对原采用（只读重读，不重新采用）'
    }
  } catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue); error.value = '查询未返回原提交，不能据此视为未提交；请保留原请求' } finally { release(); endAiBusy(busyToken) }
}
async function retryAdopt(): Promise<void> {
  const pending = pendingAdopt.value
  if (!pending || adoptCommitted.value || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const result = await api.adopt(
      pending.planId,
      pending.body as { request_id: string; expected_draft_version: number; preview_token: string },
    )
    if (!weeklyAdoptResultMatches(result, pending)) {
      error.value = '采用回执与当前请求不一致：保留原票据，请只读核对'
      return
    }
    adoptCommitted.value = result
    try {
      await finishAdopt(pending, result)
    } catch {
      if (currentEpoch(pending.epoch)) error.value = '采用已保存，但正文读取失败：请核对原采用（只读重读，不重新采用）'
    }
  } catch (errorValue) {
    if (!currentEpoch(pending.epoch)) return
    fail(errorValue)
    error.value = '原采用请求仍未确认：保留原票据，请只读核对'
  } finally { release(); endAiBusy(busyToken) }
}
function onMaterialInput(value: string): void {
  if (!alive || !materialEditable.value) return
  materialTouched.value = true
  materialText.value = value
  props.controller.updateContent((draft) => { draft.materials = value })
}
async function saveMaterials(): Promise<void> {
  if (props.disabled || aiBusy.value) return
  if (!materialEditable.value) { error.value = '材料尚无可信采用依据，不能手工创建'; return }
  const ctx = epoch()
  if (await ensureSaved(ctx) && currentEpoch(ctx)) notice.value = '材料正文已保存'
}
function selectionKey(candidate: WeeklyAiCandidate, target: WeeklyAiSelection['target']): string { return `${candidate.candidate_id}:${target}` }
const batchStatus = computed(() => groupStatus(tasks.value))
const materialEditable = computed(() => Boolean(props.detail?.draft.content.materials_provenance))
</script>

<template>
  <section
    class="weekly-ai"
    data-d1="weekly-ai"
    @select.capture="rememberDirectionalSelection"
    @mouseup.capture="rememberDirectionalSelection"
    @keyup.capture="rememberDirectionalSelection"
    @blur.capture="rememberDirectionalSelection"
  >
    <h3>周计划 AI 辅助</h3>
    <p>三个操作各自生成候选；普通保存、改选和采用均不会自动连发。</p>
    <div class="actions">
      <el-button :disabled="disabled || aiBusy" @click="create('games')">选择周游戏</el-button>
      <el-button :disabled="disabled || aiBusy || !selectedFields.length" @click="create('columns')">生成所选周栏目</el-button>
      <el-button :disabled="disabled || aiBusy" @click="create('materials')">生成材料</el-button>
      <el-button :disabled="disabled || aiBusy" @click="refreshBatch">刷新候选与状态</el-button>
    </div>
    <div class="columns">
      <el-checkbox v-for="field in WEEKLY_AI_COLUMNS" :key="field" v-model="selectedFields" :value="field" :disabled="disabled || aiBusy">{{ field === 'key_week_focus' ? '本周重点' : field === 'environment_setup' ? '环境创设' : field === 'habit_culture' ? '习惯与文化' : '家园合作' }}</el-checkbox>
    </div>
    <p v-if="!materialsFocusReady" class="focus-hint">
      {{ focusHint }}
      <el-button size="small" :disabled="disabled || aiBusy" @click="requestFocusArea">前往重点区域</el-button>
    </p>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-alert v-if="readError" :title="readError" type="warning" :closable="false" />
    <div v-if="readError" class="actions"><el-button :disabled="disabled || aiBusy" @click="refreshBatch">重新读取任务与候选</el-button></div>
    <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <el-alert
      v-if="directionalNotice"
      :title="directionalNotice"
      type="success"
      :closable="false"
      data-d1="weekly-directional-notice"
    />
    <el-alert v-if="pendingCreate" title="AI 创建请求结果未确认；保留这次原操作，请只读核对或按原操作重试" type="warning" :closable="false" />
    <div v-if="pendingCreate" class="actions"><el-button @click="queryCreate">核对原创建</el-button><el-button @click="retryCreate">重试这次原创建</el-button></div>
    <el-alert
      v-if="pendingAdopt"
      :title="adoptCommitted ? '采用已保存，正文待重读；请只读核对原采用，不会重新采用' : 'AI 采用请求结果未确认；原预览与这次原操作仍保留，请只读核对或按原操作重试'"
      type="warning"
      :closable="false"
    />
    <div v-if="pendingAdopt" class="actions">
      <el-button data-d1="weekly-adopt-query" @click="queryAdopt">核对原采用</el-button>
      <el-button v-if="!adoptCommitted" data-d1="weekly-adopt-retry" @click="retryAdopt">重试这次原采用</el-button>
    </div>
    <el-alert v-if="pendingAction" title="AI 任务操作结果未确认；原任务与这次原操作保留，请只读核对或按原操作重试" type="warning" :closable="false" />
    <div v-if="pendingAction" class="actions"><el-button @click="queryAction">核对原任务操作</el-button><el-button @click="retryAction">重试这次原任务操作</el-button></div>
    <template v-if="batch || tasks.length || visibleCandidates.length">
      <p v-if="batchReadPending">本批状态：待刷新/待核对 · {{ pendingCreate || pendingAdopt || pendingAction ? '原请求仍保留' : '任务状态待刷新' }}</p>
      <p v-else>本批状态：{{ groupStatusLabel(batchStatus) }} · 子任务 {{ tasks.length }} 个</p>
      <div v-for="task in tasks" :key="task.task_id" class="task">
        <strong>{{ targetLabel(task.target) }} · {{ taskStatusLabel(task.status) }}</strong>
        <span v-if="task.processing_certainty"> · {{ certaintyLabel(task.processing_certainty) }}</span>
        <div class="actions">
          <el-button size="small" :disabled="disabled || aiBusy" @click="loadProgress(task)">只读进度</el-button>
          <el-button v-if="task.allowed_actions.includes('cancel')" size="small" :disabled="disabled || aiBusy" @click="action(task, 'cancel')">取消</el-button>
          <el-button v-if="task.allowed_actions.includes('resume')" size="small" :disabled="disabled || aiBusy || !task.execution" @click="action(task, 'resume')">继续</el-button>
          <el-button v-if="task.allowed_actions.includes('retry')" size="small" :disabled="disabled || aiBusy || !task.execution" @click="action(task, 'retry')">明确重试</el-button>
          <el-checkbox v-if="task.retry_requires_ack" v-model="retryAckByTask[task.task_id]">我确认此任务重试可能产生新的请求或费用</el-checkbox>
          <span v-if="progressFor(task)" class="muted" data-d1="weekly-ai-progress-phase">
            {{ progressPhaseLabel(progressFor(task)?.phase ?? '') }}
          </span>
          <pre v-if="progressReasoningFor(task)" class="progress-reasoning" data-d1="weekly-ai-progress-reasoning">{{ progressReasoningFor(task) }}</pre>
        </div>
      </div>
      <div v-for="candidate in visibleCandidates" :key="candidate.candidate_id" class="candidate" :data-d1="`weekly-candidate-${candidate.candidate_id}`">
        <div>
          <strong>{{ targetLabel(candidate.target) }} · {{ eligibilityLabel(candidate.eligibility) }}</strong>
          <span v-if="preservedCandidates.some((item) => item.candidate_id === candidate.candidate_id)" class="muted"> · 原候选批次</span>
        </div>
        <p class="candidate-source-title"><strong>原候选来源/证据（只读）</strong></p>
        <ul><li v-for="line in candidateLines(candidate)" :key="line">{{ line }}</li></ul>
        <p v-if="candidateEditDirty(candidate)" class="candidate-source-stale" data-d1="weekly-candidate-edit-stale">
          候选文字已被手改：上方原来源/证据可能不再对应，请以改写建议和正式采用预览为准。
        </p>
        <el-checkbox v-for="target in candidate.available_targets" :key="target" v-model="selectedKeys" :value="selectionKey(candidate, target)" :disabled="candidate.eligibility !== 'eligible'">{{ targetLabel(target) }}</el-checkbox>

        <div v-if="candidate.target !== 'games' && candidate.target !== 'materials'" class="candidate-edit">
          <p class="candidate-edit-title">候选编辑区（未改字段保持当前候选；采用仍走原预览）</p>
          <p class="candidate-edit-label">{{ fieldEditLabel(candidate, 'text', rec(candidate.data).text) }}</p>
          <el-input
            type="textarea"
            :rows="4"
            :model-value="editField(candidate, 'text')"
            :disabled="candidateFieldDisabled(candidate)"
            :data-d1="`weekly-edit-${candidate.candidate_id}`"
            data-directional-field="text"
            :data-directional-candidate-id="candidate.candidate_id"
            @update:model-value="(value: string) => setEditField(candidate, 'text', value)"
          />
          <DirectionalRevisionTrigger
            :test-id="`weekly-directional-${candidate.candidate_id}-text`"
            :disabled="candidateFieldDisabled(candidate)"
            @request="(whole) => openDirectional(candidate, 'text', whole)"
          />
        </div>
        <div v-else-if="candidate.target === 'materials'" class="candidate-edit">
          <p class="candidate-edit-title">候选编辑区（未改字段保持当前候选；采用仍走原预览）</p>
          <div v-for="(item, index) in materialItems(candidate)" :key="index" class="candidate-edit-row">
            <span class="muted">{{ rec(item).origin === 'suggested' ? '原建议（无原文证据）' : '原提取（原文证据）' }}</span>
            <pre class="candidate-original">{{ rec(item).text || '（空）' }}</pre>
            <p v-for="evidence in materialEvidence(candidate, index)" :key="evidence" class="candidate-evidence">{{ evidence }}</p>
            <span class="muted">{{ fieldEditLabel(candidate, `item.${index}.text`, rec(item).text) }}</span>
            <el-input
              type="textarea"
              :rows="2"
              :model-value="editField(candidate, `item.${index}.text`)"
              :disabled="candidateFieldDisabled(candidate)"
              :data-d1="`weekly-edit-${candidate.candidate_id}-item-${index}`"
              :data-directional-field="`item.${index}.text`"
              :data-directional-candidate-id="candidate.candidate_id"
              @update:model-value="(value: string) => setEditField(candidate, `item.${index}.text`, value)"
            />
            <DirectionalRevisionTrigger
              :test-id="`weekly-directional-${candidate.candidate_id}-item-${index}`"
              :disabled="candidateFieldDisabled(candidate)"
              @request="
                (whole) =>
                  openDirectional(candidate, `item.${index}.text`, whole)
              "
            />
          </div>
        </div>
        <div v-else class="candidate-edit">
          <p class="candidate-edit-title">候选编辑区（未改字段保持当前候选；采用仍走原预览）</p>
          <div v-for="key in OUTDOOR_KEYS" :key="key" class="candidate-edit-group">
            <template v-if="gameItem(candidate, key)">
              <strong>{{ OUTDOOR_LABELS[key] }}</strong>
              <p class="candidate-evidence">原来源：{{ sourceLineFor(candidate, `${OUTDOOR_LABELS[key]}：`) || '未提供来源' }}</p>
              <label v-for="field in GAME_EDIT_FIELDS" :key="field" class="candidate-edit-row">
                <span class="muted">{{ GAME_FIELD_LABELS[field] }} · {{ fieldEditLabel(candidate, `slot.${key}.${field}`, gameItem(candidate, key)?.[field]) }}</span>
                <el-input
                  :model-value="editField(candidate, `slot.${key}.${field}`)"
                  :disabled="candidateFieldDisabled(candidate)"
                  :data-d1="`weekly-edit-${candidate.candidate_id}-${key}-${field}`"
                  :data-directional-field="`slot.${key}.${field}`"
                  :data-directional-candidate-id="candidate.candidate_id"
                  @update:model-value="(value: string) => setEditField(candidate, `slot.${key}.${field}`, value)"
                />
                <DirectionalRevisionTrigger
                  :test-id="`weekly-directional-${candidate.candidate_id}-${key}-${field}`"
                  :disabled="candidateFieldDisabled(candidate)"
                  @request="
                    (whole) =>
                      openDirectional(
                        candidate,
                        `slot.${key}.${field}`,
                        whole,
                      )
                  "
                />
              </label>
            </template>
          </div>
          <div v-if="focusItem(candidate)" class="candidate-edit-group">
            <strong>重点区域</strong>
            <p class="candidate-evidence">原来源：{{ sourceLineFor(candidate, '重点区域：') || '未提供来源' }}</p>
            <label v-for="field in FOCUS_EDIT_FIELDS" :key="field" class="candidate-edit-row">
              <span class="muted">{{ FOCUS_FIELD_LABELS[field] }} · {{ fieldEditLabel(candidate, `focus.${field}`, focusItem(candidate)?.[field]) }}</span>
              <el-input
                :model-value="editField(candidate, `focus.${field}`)"
                :disabled="candidateFieldDisabled(candidate)"
                :data-d1="`weekly-edit-${candidate.candidate_id}-focus-${field}`"
                :data-directional-field="`focus.${field}`"
                :data-directional-candidate-id="candidate.candidate_id"
                @update:model-value="(value: string) => setEditField(candidate, `focus.${field}`, value)"
              />
              <DirectionalRevisionTrigger
                :test-id="`weekly-directional-${candidate.candidate_id}-focus-${field}`"
                :disabled="candidateFieldDisabled(candidate)"
                @request="
                  (whole) =>
                    openDirectional(candidate, `focus.${field}`, whole)
                "
              />
            </label>
          </div>
        </div>

        <div class="actions">
          <el-button
            size="small"
            type="primary"
            :disabled="candidateFieldDisabled(candidate) || aiBusy || pendingCreate !== null || pendingAdopt !== null || pendingAction !== null"
            :data-d1="`weekly-adopt-${candidate.candidate_id}`"
            @click="adoptCandidates([candidate])"
          >
            采用并保存
          </el-button>
          <el-button
            size="small"
            :disabled="aiBusy || pendingCreate !== null || pendingAdopt !== null || pendingAction !== null"
            :data-d1="`weekly-cancel-${candidate.candidate_id}`"
            @click="resetCandidateEdit(candidate)"
          >
            取消本次候选编辑
          </el-button>
        </div>
        <div class="candidate-edit-group">
          <el-input
            v-model="regenerateInstructions[candidate.candidate_id]"
            type="textarea"
            :rows="2"
            maxlength="500"
            show-word-limit
            placeholder="定向修改要求（可选：说明希望怎么改）"
            :disabled="candidateFieldDisabled(candidate) || aiBusy"
            :data-d1="`weekly-regenerate-instruction-${candidate.candidate_id}`"
          />
          <el-button
            size="small"
            :disabled="candidateFieldDisabled(candidate) || aiBusy || pendingCreate !== null || pendingAdopt !== null || pendingAction !== null"
            :data-d1="`weekly-regenerate-${candidate.candidate_id}`"
            @click="regenerateCandidate(candidate)"
          >
            重新生成
          </el-button>
        </div>
      </div>
      <div class="actions">
        <el-button :disabled="disabled || aiBusy || !selectedKeys.length" data-d1="weekly-adopt-selected" @click="adoptCandidates(selectedCandidates())">
          采用所选并保存
        </el-button>
        <el-button :disabled="aiBusy || pendingCreate !== null || pendingAdopt !== null || pendingAction !== null" data-d1="weekly-cancel-all" @click="resetAllCandidateEdits">
          取消全部候选编辑
        </el-button>
        <el-button v-if="preservedCandidates.length" :disabled="aiBusy || pendingCreate !== null || pendingAdopt !== null || pendingAction !== null" data-d1="weekly-close-preserved" @click="closePreservedCandidates">
          关闭原候选批次
        </el-button>
      </div>
      <el-alert v-if="regeneratedNotice" type="info" :closable="false" :title="`已提交重新生成（原候选 ${regeneratedNotice} 仍保留）`" />
    </template>
    <el-card v-if="materialEditable" shadow="never" class="materials">
      <h4>材料正文（已采用依据保留）</h4>
      <el-input v-model="materialText" type="textarea" :disabled="disabled || aiBusy" @input="onMaterialInput" />
      <el-button :disabled="disabled || aiBusy" @click="saveMaterials">保存材料正文</el-button>
    </el-card>

    <DirectionalRevisionDialog
      v-if="directionalRequest"
      :open="directionalOpen"
      :scope="directionalLiveScope"
      :field-text="directionalLiveFieldText"
      :selection="directionalRequest.selection"
      :profile-epoch="props.profileEpoch"
      :source-label="directionalRequest.sourceLabel"
      :source-lines="directionalRequest.sourceLines"
      :source-stale="directionalRequest.sourceStale"
      :disabled="props.disabled"
      :apply-adoption="applyDirectionalAdoption"
      @update:open="directionalOpen = $event"
      @busy="directionalBusy = $event"
    />
  </section>
</template>

<style scoped>
.progress-reasoning {
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  margin: 6px 0 0;
  padding: 6px 8px;
  background: var(--kgm-bg);
  border-radius: 4px;
}
.weekly-ai { margin: 1rem 0; }
.actions { display: flex; gap: .4rem; flex-wrap: wrap; margin: .4rem 0; }
.columns { display: flex; gap: .5rem; flex-wrap: wrap; margin: .4rem 0; }
.focus-hint { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; color: var(--kgm-muted); margin: .2rem 0 .5rem; }
.task, .candidate, .preview, .materials { margin: .6rem 0; }
.candidate-edit { margin: .4rem 0; }
.candidate-edit-group { margin: .5rem 0; padding: .4rem 0; border-top: 1px dashed var(--kgm-border); }
.candidate-edit-row { display: block; margin: .3rem 0; }
.candidate-edit-row > span { display: block; margin-bottom: 2px; font-size: .8rem; }
.candidate-source-title, .candidate-edit-title { margin: .5rem 0 .2rem; font-size: .85rem; }
.candidate-source-stale, .candidate-evidence { margin: .2rem 0; color: var(--kgm-muted); font-size: .8rem; }
.candidate-source-stale { color: var(--kgm-warning); }
.candidate-edit-label { margin: .1rem 0 .2rem; color: var(--kgm-muted); font-size: .8rem; }
.candidate-original {
  margin: .2rem 0 .3rem;
  padding: .3rem .5rem;
  border: 1px dashed var(--kgm-border);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--kgm-muted);
  font-size: .8rem;
}
</style>
