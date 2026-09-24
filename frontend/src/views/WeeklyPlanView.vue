<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElDialog,
  ElInput,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import * as api from '../api'
import type { ApiError } from '../api'
import type {
  DeterministicField,
  OutdoorSlot,
  OutdoorSlotKey,
  RefreshedSource,
  SourceCandidate,
  WeeklyColumnKey,
  WeeklyPlanConfirmation,
  WeeklyPlanConfirmedSummary,
  WeeklyPlanDetail,
  WeeklyPlanFacts,
} from '../types'
import {
  OUTDOOR_SLOT_KEYS,
  SLOT_LABELS,
  WEEKLY_COLUMN_KEYS,
  WEEKLY_COLUMN_LABELS,
  buildManualSlot,
  buildPatchPayload,
  candidateSourceLabel,
  candidateToFocus,
  candidateToSlot,
  detKey,
  emptyDirty,
  focusSourceDate,
  groupCandidates,
  isAuthError,
  isDirtyEmpty,
  missingFactLabel,
  refreshedSourceLabel,
  serverToForm,
  shortDate,
  slotSourceDate,
  sourceKeyOf,
  staleFactLabel,
  weeklyPlanErrorMessage,
} from '../weekly-plan-content'
import type { DetFormRow, SaveDirty, WeeklyPlanForm } from '../weekly-plan-content'

const props = defineProps<{
  planId: string
  /** Admin class context; must be absent on the teacher path (never null). */
  classId?: string
}>()

const emit = defineEmits<{
  (e: 'back'): void
}>()

type Phase = 'opening' | 'ready' | 'failed'
type ConflictAction = 'save' | 'refresh' | 'confirm'

interface ConflictState {
  action: ConflictAction
  /** Draft version the local edit/confirm was based on. */
  baseVersion: number
  /** expected_draft_version of the last rejected submit. */
  attemptedVersion: number
  server: WeeklyPlanDetail | null
  /**
   * How the conflict arose: a submit rejected with 409 (`rejected`) or a
   * background state read that found the server draft advanced while local
   * dirty input was still based on `baseVersion` (`server_advanced`).
   */
  reason: 'rejected' | 'server_advanced'
}

const phase = ref<Phase>('opening')
const detail = ref<WeeklyPlanDetail | null>(null)
const form = ref<WeeklyPlanForm>(serverToForm({
  theme: '',
  deterministic: [],
  outdoor_game_slots: { collective_1: null, collective_2: null, free_choice_1: null },
  focus_area: null,
  weekly_columns: {
    key_week_focus: '',
    environment_setup: '',
    habit_culture: '',
    home_cooperation: '',
  },
  materials: null,
}))
const dirty = reactive<SaveDirty>(emptyDirty())
const openError = ref('')
const saving = ref(false)
const refreshing = ref(false)
const confirming = ref(false)
const conflict = ref<ConflictState | null>(null)
const loadSeq = ref(0)
/**
 * Draft version the current unsaved local input is actually based on.
 *
 * `detail.draft.version` is the server's displayed version; it can advance
 * through a background state read (e.g. the post-confirm GET) while local
 * dirty input stays rooted in an older draft. Saving must use this baseline,
 * never the displayed version and never the confirmation target, so a
 * concurrent server save can never be silently overwritten by a stale local
 * edit.
 */
const editBaseVersion = ref<number | null>(null)

/**
 * Explicit confirmation target: the saved server draft the next confirm
 * request will act on (version + content snapshot).
 *
 * Kept apart from `form`/`dirty` (local unsaved edits) and from
 * `editBaseVersion` (the save baseline of those edits). Adopting a newer
 * server draft as the confirmation target — e.g. after a confirm-side
 * VERSION_CONFLICT review — must never rebase the local edit baseline, and
 * dirty fields in the main editor must not hide what is actually being
 * confirmed: the dialog previews this snapshot so overlapping dirty fields
 * can still be reviewed against their real saved content.
 */
const confirmTarget = ref<{
  version: number
  content: WeeklyPlanDetail['draft']['content']
} | null>(null)

const confirmations = ref<WeeklyPlanConfirmedSummary[]>([])
const confirmationsLoading = ref(false)
/**
 * Monotonic token for history loads: an earlier request that resolves after
 * a later one (confirm-triggered refresh vs. the initial page load) must not
 * overwrite the newer list. Only the most recently issued request writes.
 */
const confirmationsSeq = ref(0)
const viewedConfirmation = ref<WeeklyPlanConfirmation | null>(null)
const confirmationViewOpen = ref(false)
const confirmationLoading = ref(false)
const confirmationSeq = ref(0)

const confirmOpen = ref(false)
const confirmFacts = ref<{ missing: WeeklyPlanFacts['missing']; stale_sources: WeeklyPlanFacts['stale_sources'] }>({
  missing: [],
  stale_sources: [],
})
const ackMissing = ref(false)
const ackStale = ref(false)
const confirmNote = ref('')
const confirmError = ref('')

const refreshedPanel = ref<RefreshedSource[] | null>(null)

const manualDialog = reactive({
  open: false,
  slotKey: null as OutdoorSlotKey | null,
  isNew: true,
  name: '',
  shared_objectives: '',
  guidance_points: '',
  focus_guidance: '',
  error: '',
})

const slotPicks = reactive<
  Record<OutdoorSlotKey, { name: string; sourceKey: string }>
>({
  collective_1: { name: '', sourceKey: '' },
  collective_2: { name: '', sourceKey: '' },
  free_choice_1: { name: '', sourceKey: '' },
})
const focusPick = reactive({ name: '', sourceKey: '' })

const CONFIRMATION_STATUS_LABELS: Record<string, string> = {
  never_confirmed: '从未确认',
  draft_ahead: '草稿领先于确认版本（待负责人确认）',
  draft_current: '当前草稿已确认',
}

const GRADE_LABELS: Record<string, string> = {
  small: '小班',
  middle: '中班',
  large: '大班',
}

const canEdit = computed(() => detail.value?.can_edit === true)
const canConfirm = computed(() => detail.value?.can_confirm === true)
const anyDirty = computed(() => !isDirtyEmpty(dirty))
const conflictActive = computed(() => conflict.value !== null)
const readOnly = computed(() => detail.value !== null && !canEdit.value)
/** Version the next PATCH will target (the dirty-input baseline, not the display). */
const saveTargetVersion = computed(
  () => editBaseVersion.value ?? detail.value?.draft.version ?? 0,
)

const confirmationStatusText = computed<string>(() => {
  const d = detail.value
  if (!d) return ''
  if (d.confirmation_status === 'never_confirmed') return CONFIRMATION_STATUS_LABELS.never_confirmed
  if (d.confirmation_status === 'draft_current') {
    return d.confirmed
      ? `当前草稿已确认（确认版本 V${d.confirmed.version}）`
      : CONFIRMATION_STATUS_LABELS.draft_current
  }
  return d.confirmed
    ? `已确认 V${d.confirmed.version}（对应草稿 v${d.confirmed.draft_version}）；当前草稿 v${d.draft.version} 待确认`
    : CONFIRMATION_STATUS_LABELS.draft_ahead
})

const acksSatisfied = computed(() => {
  const facts = confirmFacts.value
  const missingOk = facts.missing.length === 0 || ackMissing.value
  const staleOk = facts.stale_sources.length === 0 || ackStale.value
  return missingOk && staleOk
})

function classIdParam(): string | undefined {
  return props.classId
}

function notify(err: unknown, fallback: string): void {
  if (isAuthError(err)) return
  ElMessage.error(weeklyPlanErrorMessage(err, fallback))
}

function resetDirty(): void {
  dirty.theme = false
  dirty.detFields.clear()
  dirty.slots.clear()
  dirty.focus = false
  dirty.columns.clear()
}

/** Install server content into the form; dirty sections are kept when asked. */
function applyFormFrom(
  next: WeeklyPlanForm,
  base?: WeeklyPlanForm,
  keepDirty = false,
): void {
  if (!keepDirty || !base) {
    form.value = next
    resetDirty()
    return
  }
  const merged = next
  if (dirty.theme) merged.theme = base.theme
  merged.deterministic = next.deterministic.map((row) => {
    const prev = base.deterministic.find((r) => r.date === row.date)
    if (!prev) return row
    const keepMorning = dirty.detFields.has(detKey(row.date, 'morning_talk_topic'))
    const keepGroup = dirty.detFields.has(detKey(row.date, 'group_activity_theme'))
    return {
      ...row,
      valueMorning: keepMorning ? prev.valueMorning : row.valueMorning,
      valueGroup: keepGroup ? prev.valueGroup : row.valueGroup,
    }
  })
  for (const key of OUTDOOR_SLOT_KEYS) {
    if (dirty.slots.has(key)) merged.slots[key] = base.slots[key]
  }
  if (dirty.focus) merged.focus = base.focus
  for (const key of WEEKLY_COLUMN_KEYS) {
    if (dirty.columns.has(key)) merged.columns[key] = base.columns[key]
  }
  form.value = merged
}

function applyDetail(
  next: WeeklyPlanDetail,
  opts: { keepDirty: boolean },
): void {
  const base = form.value
  detail.value = next
  applyFormFrom(serverToForm(next.draft.content), base, opts.keepDirty)
  if (!opts.keepDirty) {
    resetSlotPicks()
    // Fresh server content is now the form baseline.
    editBaseVersion.value = next.draft.version
    // A newly installed saved baseline supersedes any pending confirmation
    // target; the dialog (if reopened) adopts the displayed draft again.
    confirmTarget.value = null
  }
}

function resetSlotPicks(): void {
  for (const key of OUTDOOR_SLOT_KEYS) {
    slotPicks[key] = { name: '', sourceKey: '' }
  }
  focusPick.name = ''
  focusPick.sourceKey = ''
}

function resetConfirmFacts(): void {
  const d = detail.value
  confirmFacts.value = {
    missing: d ? [...d.missing] : [],
    stale_sources: d ? [...d.stale_sources] : [],
  }
  ackMissing.value = false
  ackStale.value = false
  confirmError.value = ''
}

async function loadConfirmations(seq: number): Promise<void> {
  const token = ++confirmationsSeq.value
  confirmationsLoading.value = true
  try {
    const res = await api.listWeeklyPlanConfirmations(props.planId, classIdParam())
    if (token !== confirmationsSeq.value || seq !== loadSeq.value) return
    confirmations.value = res.items
  } catch (err) {
    if (token !== confirmationsSeq.value || seq !== loadSeq.value) return
    notify(err, '加载确认历史失败')
  } finally {
    if (token === confirmationsSeq.value) confirmationsLoading.value = false
  }
}

async function load(): Promise<void> {
  const seq = ++loadSeq.value
  phase.value = 'opening'
  openError.value = ''
  try {
    const found = await api.getWeeklyPlan(props.planId, classIdParam())
    if (seq !== loadSeq.value) return
    detail.value = found
    applyFormFrom(serverToForm(found.draft.content))
    resetSlotPicks()
    editBaseVersion.value = found.draft.version
    confirmTarget.value = null
    conflict.value = null
    refreshedPanel.value = null
    phase.value = 'ready'
    void loadConfirmations(seq)
  } catch (err) {
    if (seq !== loadSeq.value) return
    openError.value = weeklyPlanErrorMessage(err, '读取周计划失败')
    phase.value = 'failed'
  }
}

watch(
  () => [props.planId, props.classId] as const,
  () => {
    void load()
  },
)

// --- deterministic editing -------------------------------------------------

function markDet(date: string, field: DeterministicField): void {
  dirty.detFields.add(detKey(date, field))
}

function markTheme(): void {
  dirty.theme = true
}

function markColumn(key: WeeklyColumnKey): void {
  dirty.columns.add(key)
}

function clearOverride(row: DetFormRow, field: DeterministicField): void {
  if (!canEdit.value || saving.value) return
  if (field === 'morning_talk_topic') {
    row.valueMorning = row.sourceMorning ?? ''
  } else {
    row.valueGroup = row.sourceGroup ?? ''
  }
  markDet(row.date, field)
}

function sourceDisplay(row: DetFormRow, field: DeterministicField): string {
  if (row.dayState === 'rest') return '休息日'
  if (row.planState === 'no_plan') return '缺日计划'
  const value = field === 'morning_talk_topic' ? row.sourceMorning : row.sourceGroup
  if (value === null || value === '') return '（字段为空）'
  return value
}

function effectiveEmpty(row: DetFormRow, field: DeterministicField): boolean {
  const value = field === 'morning_talk_topic' ? row.valueMorning : row.valueGroup
  return value === ''
}

function overrideOf(row: DetFormRow, field: DeterministicField): string | null {
  return field === 'morning_talk_topic' ? row.overrideMorning : row.overrideGroup
}

function setFieldValue(row: DetFormRow, field: DeterministicField, value: string): void {
  if (field === 'morning_talk_topic') {
    row.valueMorning = value
  } else {
    row.valueGroup = value
  }
}

// --- outdoor slots ---------------------------------------------------------

function slotCategory(key: OutdoorSlotKey): 'collective' | 'free_choice' {
  return key === 'free_choice_1' ? 'free_choice' : 'collective'
}

function slotGroups(key: OutdoorSlotKey) {
  return groupCandidates(detail.value?.source_candidates || [], slotCategory(key))
}

function focusGroups() {
  return groupCandidates(detail.value?.source_candidates || [], 'focus')
}

/** Same category + same name occupies one quota: block the sibling collective slot. */
function isNameTakenBySibling(key: OutdoorSlotKey, name: string): boolean {
  if (key === 'free_choice_1' || !name) return false
  const sibling: OutdoorSlotKey = key === 'collective_1' ? 'collective_2' : 'collective_1'
  const slot = form.value.slots[sibling]
  return !!slot && slot.name === name
}

function slotIsStale(key: OutdoorSlotKey): boolean {
  return (detail.value?.stale_sources || []).some((s) => s.slot === key)
}

function focusIsStale(): boolean {
  return (detail.value?.stale_sources || []).some((s) => s.slot === 'focus_area')
}

function commitSlot(key: OutdoorSlotKey, entry: OutdoorSlot): void {
  form.value.slots[key] = entry
  dirty.slots.add(key)
  if (entry) {
    slotPicks[key] = {
      name: entry.name,
      sourceKey: entry.source_kind === 'daily_plan' ? sourceKeyOf(entry) : '',
    }
  } else {
    slotPicks[key] = { name: '', sourceKey: '' }
  }
}

function onPickName(key: OutdoorSlotKey, value: unknown): void {
  if (!canEdit.value || saving.value) return
  const name = typeof value === 'string' ? value : ''
  if (!name) {
    slotPicks[key] = { name: '', sourceKey: '' }
    return
  }
  if (isNameTakenBySibling(key, name)) {
    ElMessage.warning('同类别同名游戏只能占据一个名额，请先清空另一槽位')
    slotPicks[key] = { name: '', sourceKey: '' }
    return
  }
  const group = slotGroups(key).find((g) => g.name === name)
  if (!group) return
  if (group.sources.length === 1) {
    commitSlot(key, candidateToSlot(group.sources[0]))
  } else {
    // Multiple real sources: wait for an explicit source choice.
    slotPicks[key] = { name, sourceKey: '' }
  }
}

function onPickSource(key: OutdoorSlotKey, value: unknown): void {
  if (!canEdit.value || saving.value) return
  const pick = slotPicks[key]
  const sourceKey = typeof value === 'string' ? value : ''
  if (!pick.name || !sourceKey) return
  const group = slotGroups(key).find((g) => g.name === pick.name)
  const candidate = group?.sources.find((s) => sourceKeyOf(s) === sourceKey)
  if (!candidate) return
  commitSlot(key, candidateToSlot(candidate))
}

function pickSources(key: OutdoorSlotKey): SourceCandidate[] {
  const pick = slotPicks[key]
  if (!pick.name) return []
  const group = slotGroups(key).find((g) => g.name === pick.name)
  return group ? group.sources : []
}

function clearSlot(key: OutdoorSlotKey): void {
  if (!canEdit.value || saving.value) return
  commitSlot(key, null)
}

function openManual(key: OutdoorSlotKey): void {
  if (!canEdit.value || saving.value) return
  const existing = form.value.slots[key]
  const isManual = !!existing && existing.source_kind === 'manual'
  manualDialog.slotKey = key
  manualDialog.isNew = !isManual
  manualDialog.name = isManual ? existing.name : ''
  manualDialog.shared_objectives =
    isManual && existing.shared_objectives != null ? existing.shared_objectives : ''
  manualDialog.guidance_points =
    isManual && existing.guidance_points != null ? existing.guidance_points : ''
  manualDialog.focus_guidance =
    isManual && existing.focus_guidance != null ? existing.focus_guidance : ''
  manualDialog.error = ''
  manualDialog.open = true
}

function saveManual(): void {
  const key = manualDialog.slotKey
  if (!key) return
  const name = manualDialog.name.trim()
  if (!name) {
    manualDialog.error = '名称不能为空'
    return
  }
  const entry = buildManualSlot(form.value.slots[key], {
    name,
    shared_objectives: manualDialog.shared_objectives,
    guidance_points: manualDialog.guidance_points,
    focus_guidance: manualDialog.focus_guidance,
  })
  commitSlot(key, entry)
  manualDialog.open = false
}

function slotGroupTexts(slot: OutdoorSlot): Array<{ label: string; value: string }> {
  if (!slot) return []
  const out: Array<{ label: string; value: string }> = []
  const push = (label: string, value: string | null | undefined) => {
    if (value) out.push({ label, value })
  }
  push('共用目标', slot.shared_objectives)
  push('指导要点', slot.guidance_points)
  push('重点指导', slot.focus_guidance)
  return out
}

function slotMeta(slot: OutdoorSlot): string {
  if (!slot) return ''
  if (slot.source_kind === 'manual') return '手工补充（非日计划来源）'
  const date = slotSourceDate(slot, detail.value?.source_candidates || [])
  return `${date ? `${shortDate(date)} · ` : ''}内容 v${slot.content_version}`
}

// --- focus area ------------------------------------------------------------

function onFocusName(value: unknown): void {
  if (!canEdit.value || saving.value) return
  const name = typeof value === 'string' ? value : ''
  if (!name) {
    focusPick.name = ''
    focusPick.sourceKey = ''
    return
  }
  const group = focusGroups().find((g) => g.name === name)
  if (!group) return
  if (group.sources.length === 1) {
    commitFocus(group.sources[0])
  } else {
    focusPick.name = name
    focusPick.sourceKey = ''
  }
}

function onFocusSource(value: unknown): void {
  if (!canEdit.value || saving.value) return
  const sourceKey = typeof value === 'string' ? value : ''
  if (!focusPick.name || !sourceKey) return
  const group = focusGroups().find((g) => g.name === focusPick.name)
  const candidate = group?.sources.find((s) => sourceKeyOf(s) === sourceKey)
  if (!candidate) return
  commitFocus(candidate)
}

function commitFocus(candidate: SourceCandidate): void {
  form.value.focus = candidateToFocus(candidate)
  dirty.focus = true
  focusPick.name = candidate.name
  focusPick.sourceKey = sourceKeyOf(candidate)
}

function clearFocus(): void {
  if (!canEdit.value || saving.value) return
  form.value.focus = null
  dirty.focus = true
  focusPick.name = ''
  focusPick.sourceKey = ''
}

function focusPickSources(): SourceCandidate[] {
  if (!focusPick.name) return []
  const group = focusGroups().find((g) => g.name === focusPick.name)
  return group ? group.sources : []
}

function focusTexts(): Array<{ label: string; value: string }> {
  const focus = form.value.focus
  if (!focus) return []
  const out: Array<{ label: string; value: string }> = []
  if (focus.objectives) out.push({ label: '目标', value: focus.objectives })
  if (focus.guidance) out.push({ label: '指导', value: focus.guidance })
  if (focus.support_strategy) out.push({ label: '支持策略', value: focus.support_strategy })
  return out
}

function focusMeta(): string {
  const focus = form.value.focus
  if (!focus) return ''
  const date = focusSourceDate(focus, detail.value?.source_candidates || [])
  const context =
    focus.context_kind === 'area'
      ? focus.area || '室内区域'
      : focus.context_kind === 'outdoor'
        ? '户外'
        : '专用室'
  return `${date ? `${shortDate(date)} · ` : ''}${context} · 内容 v${focus.content_version}`
}

// --- save / refresh / confirm ---------------------------------------------

async function doSave(expectedVersion: number): Promise<void> {
  const d = detail.value
  if (!d || !canEdit.value || saving.value) return
  saving.value = true
  try {
    const payload = buildPatchPayload(form.value, dirty, expectedVersion)
    const next = await api.patchWeeklyPlan(props.planId, payload, classIdParam())
    applyDetail(next, { keepDirty: false })
    conflict.value = null
    ElMessage.success('已保存为草稿新版本')
  } catch (err) {
    const e = err as ApiError
    if (e.code === 'VERSION_CONFLICT') {
      await enterConflict('save', expectedVersion)
      return
    }
    notify(err, '保存失败，请检查网络后重试')
  } finally {
    saving.value = false
  }
}

function save(): void {
  const d = detail.value
  if (!d || conflictActive.value || isDirtyEmpty(dirty)) return
  // Save against the baseline the local input was actually edited on, never
  // the server display version: an implicit background refresh must not let a
  // stale local edit overwrite a newer server draft without a 409.
  void doSave(editBaseVersion.value ?? d.draft.version)
}

async function doRefresh(expectedVersion: number): Promise<void> {
  const d = detail.value
  if (!d || !canEdit.value || refreshing.value) return
  refreshing.value = true
  try {
    const next = await api.refreshWeeklyPlanSources(
      props.planId,
      { expected_draft_version: expectedVersion },
      classIdParam(),
    )
    // Dirty sections keep the local unsaved input; server-owned layers update.
    // Refresh is an explicit user action that advances the draft, so the new
    // version is adopted as the baseline for the kept dirty input.
    applyDetail(next, { keepDirty: true })
    editBaseVersion.value = next.draft.version
    conflict.value = null
    refreshedPanel.value = next.refreshed_sources || []
    ElMessage.success('已刷新到最新来源；主题、人工覆盖与手工栏目未改动')
  } catch (err) {
    const e = err as ApiError
    if (e.code === 'VERSION_CONFLICT') {
      await enterConflict('refresh', expectedVersion)
      return
    }
    notify(err, '刷新来源失败，请稍后重试')
  } finally {
    refreshing.value = false
  }
}

function refreshSources(): void {
  const d = detail.value
  if (!d || conflictActive.value) return
  void doRefresh(d.draft.version)
}

function openConfirm(): void {
  const d = detail.value
  if (!d || !canConfirm.value || conflictActive.value) return
  resetConfirmFacts()
  confirmNote.value = ''
  // Normal path: the confirmation target is the displayed saved draft —
  // explicitly, not derived from the local edit state.
  confirmTarget.value = { version: d.draft.version, content: d.draft.content }
  confirmOpen.value = true
}

async function doConfirm(expectedVersion: number): Promise<void> {
  const d = detail.value
  if (!d || !canConfirm.value || confirming.value) return
  confirming.value = true
  confirmError.value = ''
  try {
    const result = await api.confirmWeeklyPlan(
      props.planId,
      {
        expected_draft_version: expectedVersion,
        acknowledge_missing: ackMissing.value,
        acknowledge_stale: ackStale.value,
        note: confirmNote.value.trim() === '' ? null : confirmNote.value,
      },
      classIdParam(),
    )
    conflict.value = null
    confirmOpen.value = false
    confirmTarget.value = null
    ElMessage.success(`已确认，生成确认版本 V${result.version}`)
    // R2: never load() here — a full reload resets the form and dirty flags,
    // discarding unsaved local input. Refresh only server-owned state while
    // keeping every dirty field's value and dirty marker.
    await refreshAfterConfirm(expectedVersion)
  } catch (err) {
    const e = err as ApiError
    if (e.code === 'VERSION_CONFLICT') {
      // Local acks/note stay untouched; only the version is re-based later.
      await enterConflict('confirm', expectedVersion)
      return
    }
    if (e.code === 'CONFIRM_ACK_REQUIRED') {
      const facts = e.facts
      if (facts) {
        confirmFacts.value = {
          missing: facts.missing || [],
          stale_sources: facts.stale_sources || [],
        }
        // The server recomputes facts under lock: keep the page's live fact
        // lists in sync so closing and reopening the dialog cannot fall back
        // to the older GET-time snapshot (missing/stale would vanish).
        if (detail.value) {
          detail.value = {
            ...detail.value,
            missing: [...(facts.missing || [])],
            stale_sources: [...(facts.stale_sources || [])],
          }
        }
      } else {
        resetConfirmFacts()
      }
      // Never reuse previous checks, never auto-retry.
      ackMissing.value = false
      ackStale.value = false
      conflict.value = null
      confirmError.value = '服务端返回了最新的事实清单，请重新勾选对应确认后再提交'
      return
    }
    confirmError.value = weeklyPlanErrorMessage(err, '确认失败，请稍后重试')
  } finally {
    confirming.value = false
  }
}

function submitConfirm(): void {
  const d = detail.value
  if (!d || !acksSatisfied.value || conflictActive.value) return
  // Confirm targets the explicit confirmation target (the reviewed saved
  // draft), never a version derived from the local edit baseline.
  void doConfirm(confirmTarget.value?.version ?? d.draft.version)
}

/**
 * R2: post-confirm server-state refresh without touching local input.
 *
 * Confirm never changes the saved draft, so the only things that must
 * update are the confirmation status / summary, live facts, version
 * pointers and the history list. Dirty sections keep the user's local
 * values (including edits made while the confirm request was in flight);
 * non-dirty sections take the server values (identical content anyway).
 *
 * Race-R2 / final-fix separation: confirm commits against `baseVersion`
 * (the confirmation target), but the dirty input's real save baseline is
 * `editBaseVersion` — the version the local edits were actually made on.
 * These are different things: confirming a reviewed v2 while local edits
 * still derive from v1 must NOT advance the edit baseline to v2, or the
 * next PATCH would overwrite the other writer without a save-side 409.
 * Whenever the server version differs from the real edit baseline, server-
 * owned state is still displayed, but the edit baseline stays put and the
 * explicit conflict path is entered so the user must choose "discard local"
 * or "resubmit on the server baseline" before any re-base.
 */
async function refreshAfterConfirm(baseVersion: number): Promise<void> {
  const seq = loadSeq.value
  try {
    const fresh = await api.getWeeklyPlan(props.planId, classIdParam())
    if (seq !== loadSeq.value) return
    applyDetail(fresh, { keepDirty: true })
    void loadConfirmations(seq)
    const baseline = editBaseVersion.value ?? baseVersion
    if (!isDirtyEmpty(dirty) && fresh.draft.version !== baseline) {
      // Do not rebase: keep editBaseVersion at the version the local input was
      // edited on and force an explicit conflict decision.
      conflict.value = {
        action: 'save',
        baseVersion: baseline,
        attemptedVersion: baseVersion,
        server: fresh,
        reason: 'server_advanced',
      }
      ElMessage.warning(
        `确认成功，但服务端草稿已更新至 v${fresh.draft.version}；` +
          '本地未保存修改仍基于旧版本，请先处理冲突再保存',
      )
      return
    }
    // No stale dirty input (or the edit baseline is unchanged): the displayed
    // draft is a safe baseline for the local input.
    editBaseVersion.value = fresh.draft.version
  } catch (err) {
    if (seq !== loadSeq.value) return
    notify(err, '确认成功，但刷新页面状态失败，请重新打开本页核对')
  }
}

/**
 * R1 + final fix: confirm-side conflict resolution = latest-draft review
 * state with an independent confirmation target.
 *
 * Adopts the conflict-time server detail as the page display (latest
 * version, content for non-dirty fields, missing/stale lists), installs the
 * server draft as the new *confirmation target* (version + content
 * snapshot, previewed in the dialog so dirty fields cannot hide it), clears
 * both acks, keeps the note, and reopens the confirm dialog. It never sends
 * a confirm request — the user must review and click confirm again; a
 * repeated conflict (v2 → v3) re-enters the same flow.
 *
 * It deliberately does NOT touch `editBaseVersion` while local unsaved
 * input exists: reviewing/confirming a newer server draft is not an edit
 * rebase. The dirty input keeps its real baseline (v1 here), so a later
 * save of that input must still hit the save-side VERSION_CONFLICT instead
 * of silently overwriting the other writer's v2 changes. Only with no dirty
 * input at all does the displayed draft become the trivially-safe baseline.
 */
function enterConfirmReview(server: WeeklyPlanDetail): void {
  applyDetail(server, { keepDirty: true })
  if (isDirtyEmpty(dirty)) {
    // Nothing unsaved: the form already equals the server content, so the
    // displayed draft is the truthful edit baseline.
    editBaseVersion.value = server.draft.version
  }
  confirmTarget.value = { version: server.draft.version, content: server.draft.content }
  conflict.value = null
  resetConfirmFacts()
  confirmError.value = `服务端草稿已更新至 v${server.draft.version}，已将该版本设为本次确认目标并载入最新事实清单；此前勾选已清空、备注已保留。页面中的本地未保存修改不属于本次确认目标，其保存基线也未改变，请重新审阅后再确认。`
  confirmOpen.value = true
  ElMessage.info(`已载入最新草稿 v${server.draft.version} 作为确认目标，请重新审阅后确认`)
}

// --- version conflict handling --------------------------------------------

async function enterConflict(
  action: ConflictAction,
  attemptedVersion: number,
): Promise<void> {
  const baseVersion = detail.value?.draft.version ?? attemptedVersion
  let server: WeeklyPlanDetail | null = null
  try {
    server = await api.getWeeklyPlan(props.planId, classIdParam())
  } catch (err) {
    notify(err, '读取服务端最新版本失败')
  }
  // The confirm dialog sits above the page-level conflict alert; close it so
  // the two explicit actions are reachable. acks/note stay in memory.
  if (action === 'confirm') {
    confirmOpen.value = false
  }
  conflict.value = { action, baseVersion, attemptedVersion, server, reason: 'rejected' }
}

async function reloadConflictServer(): Promise<void> {
  const state = conflict.value
  if (!state) return
  try {
    const latest = await api.getWeeklyPlan(props.planId, classIdParam())
    conflict.value = { ...state, server: latest }
  } catch (err) {
    notify(err, '读取服务端最新版本失败')
  }
}

function discardConflict(): void {
  const state = conflict.value
  const server = state?.server
  if (!server) return
  applyDetail(server, { keepDirty: false })
  conflict.value = null
  if (state.action === 'confirm') {
    // Local confirm input (acks/note) was explicitly discarded with the rest.
    confirmOpen.value = false
    resetConfirmFacts()
    confirmNote.value = ''
  }
  ElMessage.info('已放弃本地修改，当前显示服务端最新草稿')
}

function resubmitConflict(): void {
  const state = conflict.value
  if (!state?.server) return
  const expected = state.server.draft.version
  if (state.action === 'save') {
    void doSave(expected)
  } else if (state.action === 'refresh') {
    void doRefresh(expected)
  } else {
    // R1: never blind-resubmit confirm against a draft the user has not
    // re-reviewed; enter the latest-draft review state instead.
    enterConfirmReview(state.server)
  }
}

// --- confirmation history --------------------------------------------------

async function viewConfirmation(version: number): Promise<void> {
  confirmationViewOpen.value = true
  viewedConfirmation.value = null
  confirmationLoading.value = true
  const seq = ++confirmationSeq.value
  try {
    const single = await api.getWeeklyPlanConfirmation(
      props.planId,
      version,
      classIdParam(),
    )
    if (seq !== confirmationSeq.value) return
    viewedConfirmation.value = single
  } catch (err) {
    if (seq !== confirmationSeq.value) return
    notify(err, '读取确认版本失败')
  } finally {
    if (seq === confirmationSeq.value) confirmationLoading.value = false
  }
}

function confirmationFactsText(facts: WeeklyPlanFacts): string {
  return `缺失 ${(facts.missing || []).length} · 陈旧 ${(facts.stale_sources || []).length}`
}

function confirmedContentRows(content: WeeklyPlanDetail['draft']['content']) {
  return content?.deterministic || []
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="weekly-plan">
    <div class="toolbar">
      <h2>
        周计划
        <template v-if="detail">· {{ detail.class_name }} · 第{{ detail.week_number }}周</template>
      </h2>
      <div class="actions">
        <template v-if="phase === 'ready' && detail">
          <el-tag size="small" :type="detail.needs_confirm ? 'warning' : 'success'">
            {{ detail.needs_confirm ? '待确认' : '无需再次确认' }}
          </el-tag>
          <el-tag size="small" :type="canEdit ? 'success' : 'info'">
            {{ canEdit ? '可编辑' : '只读' }}
          </el-tag>
        </template>
        <el-button @click="$emit('back')">返回</el-button>
      </div>
    </div>

    <el-card v-if="phase === 'opening'" class="section" v-loading="true">
      <p class="muted">正在读取周计划…</p>
    </el-card>

    <el-card v-else-if="phase === 'failed'" class="section">
      <el-alert :title="openError || '读取周计划失败'" type="error" :closable="false" />
      <div class="actions-row">
        <el-button @click="load">重试</el-button>
        <el-button @click="$emit('back')">返回</el-button>
      </div>
    </el-card>

    <template v-else-if="phase === 'ready' && detail">
      <!-- 维度四：投影待消费（与确认状态分开） -->
      <el-alert
        v-if="detail.projection_pending"
        type="info"
        :closable="false"
        class="section"
        title="日计划侧有新的待消费投影变化"
      >
        <p>
          本周日计划在周计划上次消费之后有保存动作。来源是否陈旧以下方逐条清单为准；
          刷新需要您显式点击，系统不会自动刷新。
        </p>
      </el-alert>

      <!-- 表头（U1=A 创建时快照，不随班级资料变动） -->
      <el-card class="section">
        <template #header>表头（创建时快照）</template>
        <div class="meta">
          <span>园所：{{ detail.school_name || '（未填写）' }}</span>
          <span>班级：{{ detail.class_name }}（{{ GRADE_LABELS[detail.grade] || detail.grade }}）</span>
          <span>
            教师名单：
            {{ detail.header_teacher_names.length
              ? detail.header_teacher_names.join('、')
              : '（未填写）' }}
          </span>
          <span>保育员：{{ detail.caregiver_name || '（未填写）' }}</span>
          <span>第{{ detail.week_number }}周</span>
        </div>
        <p class="muted">
          表头在创建周计划时写入，之后修改班级资料不会回填本页。
        </p>
      </el-card>

      <!-- 版本冲突（409 VERSION_CONFLICT）：本地输入保留 -->
      <el-alert
        v-if="conflict"
        type="warning"
        :closable="false"
        class="section conflict-alert"
        :title="conflict.reason === 'server_advanced'
          ? '服务端草稿已更新：本地未保存修改仍基于旧版本，未被覆盖'
          : '草稿版本冲突（409）：本地输入已保留，未被覆盖'"
      >
        <div class="conflict-body">
          <p v-if="conflict.reason === 'server_advanced'">
            确认成功后读取到服务端草稿已推进；本地未保存修改仍基于草稿版本
            v{{ conflict.baseVersion }}，不会静默改以新版本为基准。
          </p>
          <p v-else>
            本地操作基于草稿版本 v{{ conflict.baseVersion }}
            <template v-if="conflict.attemptedVersion !== conflict.baseVersion">
              ；上次提交（期望 v{{ conflict.attemptedVersion }}）被服务端拒绝
            </template>
            。
          </p>
          <template v-if="conflict.server">
            <p>
              服务端最新草稿版本：
              <strong>v{{ conflict.server.draft.version }}</strong>
              （更新于 {{ conflict.server.updated_at }}）
            </p>
            <p class="conflict-hint">
              请选择处理方式：放弃本地修改并载入服务端版本，或保留本地输入、以服务端最新版本为基准重新提交。
              系统不会静默覆盖，也不会自动重试；再次冲突仍按冲突处理。
            </p>
            <p v-if="conflict.action === 'confirm'" class="conflict-hint">
              确认冲突下“以服务端为基准重提”只会把服务端最新草稿设为本次确认目标，
              并载入其内容与事实供您重新审阅，不会直接发送确认请求；
              需您再次明确点击确认后才会提交。该操作不会推进本地未保存修改的保存基线，
              之后保存本地修改仍按其原有基线做版本保护。
            </p>
            <div class="actions-row">
              <el-button
                :disabled="saving || refreshing || confirming"
                @click="discardConflict"
              >
                放弃本地，载入服务端版本
              </el-button>
              <el-button
                type="primary"
                :loading="saving || refreshing || confirming"
                @click="resubmitConflict"
              >
                以服务端为基准重提
              </el-button>
            </div>
          </template>
          <template v-else>
            <p>读取服务端最新版本失败，请重试后再处理冲突。</p>
            <el-button @click="reloadConflictServer">重新读取服务端版本</el-button>
          </template>
        </div>
      </el-alert>

      <el-alert
        v-if="refreshedPanel && refreshedPanel.length"
        type="success"
        closable
        class="section"
        title="已刷新的来源"
        @close="refreshedPanel = null"
      >
        <ul class="fact-list">
          <li v-for="(item, i) in refreshedPanel" :key="i">
            {{ refreshedSourceLabel(item) }}
          </li>
        </ul>
      </el-alert>

      <!-- 确认状态区：四个维度分开展示，不合并成一个 status -->
      <el-card class="section">
        <template #header>确认状态</template>
        <div class="status-grid">
          <div class="status-item">
            <span class="label">确认状态</span>
            <el-tag
              size="small"
              :type="detail.confirmation_status === 'draft_current'
                ? 'success'
                : detail.confirmation_status === 'draft_ahead'
                  ? 'warning'
                  : 'info'"
            >
              {{ confirmationStatusText }}
            </el-tag>
          </div>
          <div class="status-item">
            <span class="label">待确认</span>
            <el-tag size="small" :type="detail.needs_confirm ? 'warning' : 'info'">
              {{ detail.needs_confirm ? '当前草稿需要负责人确认' : '当前草稿已确认' }}
            </el-tag>
          </div>
          <div class="status-item">
            <span class="label">当前草稿</span>
            <span>
              v{{ detail.draft.version }}
              · 最近编辑：{{ detail.draft.editor_role === 'admin' ? '管理员' : '负责人' }}
              · {{ detail.draft.created_at }}
            </span>
          </div>
          <div class="status-item">
            <span class="label">已确认摘要</span>
            <span v-if="detail.confirmed">
              确认版本 V{{ detail.confirmed.version }}
              （确认时草稿 v{{ detail.confirmed.draft_version }}）
              · {{ detail.confirmed.created_at }}
              · {{ confirmationFactsText(detail.confirmed.facts) }}
              <el-button
                size="small"
                text
                type="primary"
                @click="viewConfirmation(detail.confirmed!.version)"
              >
                查看确认全文
              </el-button>
            </span>
            <span v-else class="muted">尚未确认（无已确认版本）</span>
          </div>
          <div class="status-item">
            <span class="label">缺失事实（{{ detail.missing.length }}）</span>
            <el-collapse v-if="detail.missing.length" class="inline-collapse">
              <el-collapse-item name="missing">
                <template #title><span class="link-like">展开缺失清单</span></template>
                <ul class="fact-list">
                  <li v-for="(fact, i) in detail.missing" :key="i">
                    {{ missingFactLabel(fact) }}
                  </li>
                </ul>
              </el-collapse-item>
            </el-collapse>
            <span v-else class="muted">无</span>
          </div>
          <div class="status-item">
            <span class="label">陈旧来源（{{ detail.stale_sources.length }}）</span>
            <el-collapse v-if="detail.stale_sources.length" class="inline-collapse">
              <el-collapse-item name="stale">
                <template #title><span class="link-like">展开陈旧清单</span></template>
                <ul class="fact-list">
                  <li v-for="(fact, i) in detail.stale_sources" :key="i">
                    {{ staleFactLabel(fact) }}
                  </li>
                </ul>
                <el-collapse class="inline-collapse">
                  <el-collapse-item name="stale-raw">
                    <template #title><span class="link-like">来源版本明细（可展开）</span></template>
                    <pre class="raw-block">{{ JSON.stringify(detail.stale_sources, null, 2) }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </el-collapse-item>
            </el-collapse>
            <span v-else class="muted">无</span>
          </div>
        </div>
        <p class="muted">
          确认状态、缺失、来源陈旧、投影待消费是彼此独立的维度，不会合并成一个状态标签。
        </p>
      </el-card>

      <!-- 主题（允许为空，空主题只记入缺失事实） -->
      <el-card class="section">
        <template #header>周计划主题</template>
        <el-input
          v-model="form.theme"
          :disabled="!canEdit || saving"
          placeholder="可留空；空主题会记入确认时的缺失事实"
          @input="markTheme"
        />
        <p v-if="dirty.theme" class="muted">主题有未保存的本地修改。</p>
      </el-card>

      <!-- 确定性栏目：effective 可编辑、source 展示、覆盖标记 -->
      <el-card class="section">
        <template #header>每日确定性栏目（晨间谈话 / 集体活动）</template>
        <el-table :data="form.deterministic" size="small">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="状态" width="150">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.dayState === 'teaching' ? 'success' : 'info'"
              >
                {{ row.dayState === 'teaching' ? '教学日' : '休息日' }}
              </el-tag>
              <el-tag
                size="small"
                :type="row.planState === 'saved' ? 'success'
                  : row.planState === 'no_plan' ? 'warning' : 'info'"
                class="state-tag"
              >
                {{ row.planState === 'saved' ? '已保存日计划'
                  : row.planState === 'no_plan' ? '缺日计划' : '无需日计划' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="晨间谈话话题">
            <template #default="{ row }">
              <div v-if="row.dayState === 'rest'" class="muted">休息日，不填写</div>
              <template v-else>
                <el-input
                  :model-value="row.valueMorning"
                  size="small"
                  :disabled="!canEdit || saving"
                  @update:model-value="(v: string) => { setFieldValue(row as DetFormRow, 'morning_talk_topic', v); markDet(row.date, 'morning_talk_topic') }"
                />
                <div class="src-line">
                  <span class="muted">来源：{{ sourceDisplay(row as DetFormRow, 'morning_talk_topic') }}</span>
                  <el-tag
                    v-if="overrideOf(row as DetFormRow, 'morning_talk_topic') !== null"
                    size="small"
                    type="warning"
                  >
                    人工覆盖
                  </el-tag>
                  <span v-if="effectiveEmpty(row as DetFormRow, 'morning_talk_topic')" class="muted">（生效值为空）</span>
                  <el-button
                    v-if="canEdit && overrideOf(row as DetFormRow, 'morning_talk_topic') !== null"
                    size="small"
                    text
                    type="primary"
                    :disabled="saving"
                    @click="clearOverride(row as DetFormRow, 'morning_talk_topic')"
                  >
                    清除覆盖
                  </el-button>
                </div>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="集体活动主题">
            <template #default="{ row }">
              <div v-if="row.dayState === 'rest'" class="muted">休息日，不填写</div>
              <template v-else>
                <el-input
                  :model-value="row.valueGroup"
                  size="small"
                  :disabled="!canEdit || saving"
                  @update:model-value="(v: string) => { setFieldValue(row as DetFormRow, 'group_activity_theme', v); markDet(row.date, 'group_activity_theme') }"
                />
                <div class="src-line">
                  <span class="muted">来源：{{ sourceDisplay(row as DetFormRow, 'group_activity_theme') }}</span>
                  <el-tag
                    v-if="overrideOf(row as DetFormRow, 'group_activity_theme') !== null"
                    size="small"
                    type="warning"
                  >
                    人工覆盖
                  </el-tag>
                  <span v-if="effectiveEmpty(row as DetFormRow, 'group_activity_theme')" class="muted">（生效值为空）</span>
                  <el-button
                    v-if="canEdit && overrideOf(row as DetFormRow, 'group_activity_theme') !== null"
                    size="small"
                    text
                    type="primary"
                    :disabled="saving"
                    @click="clearOverride(row as DetFormRow, 'group_activity_theme')"
                  >
                    清除覆盖
                  </el-button>
                </div>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted">
          缺日计划、字段为空、休息日分别显示，系统不会自动补写；修改写入人工覆盖层，
          刷新与保存不会清除已保存的覆盖。
        </p>
      </el-card>

      <!-- 户外游戏：两项集体 + 一项自选 -->
      <el-card class="section">
        <template #header>户外游戏（两项集体游戏 + 一项自选游戏）</template>
        <div v-for="key in OUTDOOR_SLOT_KEYS" :key="key" class="slot-block">
          <div class="slot-head">
            <strong>{{ SLOT_LABELS[key] }}</strong>
            <template v-if="form.slots[key]">
              <el-tag
                size="small"
                :type="form.slots[key]!.source_kind === 'manual' ? 'warning' : 'success'"
              >
                {{ form.slots[key]!.source_kind === 'manual' ? '手工补充' : '日计划来源' }}
              </el-tag>
              <el-tag v-if="slotIsStale(key)" size="small" type="danger">
                来源已陈旧
              </el-tag>
              <span class="slot-name">{{ form.slots[key]!.name || '（未命名）' }}</span>
              <span class="muted">{{ slotMeta(form.slots[key]) }}</span>
            </template>
            <el-tag v-else size="small" type="info">未选择</el-tag>
          </div>

          <el-collapse v-if="form.slots[key] && slotGroupTexts(form.slots[key]).length" class="inline-collapse">
            <el-collapse-item :name="`slot-text-${key}`">
              <template #title><span class="link-like">查看整组文本（与来源同组）</span></template>
              <p v-for="t in slotGroupTexts(form.slots[key])" :key="t.label" class="group-text">
                <strong>{{ t.label }}：</strong>{{ t.value }}
              </p>
            </el-collapse-item>
          </el-collapse>

          <template v-if="canEdit">
            <div class="slot-actions">
              <el-select
                v-model="slotPicks[key].name"
                placeholder="选择游戏名称（同类别同名已合并为一个名额）"
                clearable
                filterable
                :disabled="saving"
                class="pick-select"
                @change="onPickName(key, $event)"
              >
                <el-option
                  v-for="group in slotGroups(key)"
                  :key="group.name"
                  :label="`${group.name}（${group.sources.map((s) => shortDate(s.date)).join('、')}）`"
                  :value="group.name"
                  :disabled="isNameTakenBySibling(key, group.name)"
                />
              </el-select>
              <el-select
                v-if="slotPicks[key].name && pickSources(key).length > 1"
                v-model="slotPicks[key].sourceKey"
                placeholder="选择来源日期"
                :disabled="saving"
                class="pick-source"
                @change="onPickSource(key, $event)"
              >
                <el-option
                  v-for="source in pickSources(key)"
                  :key="sourceKeyOf(source)"
                  :label="candidateSourceLabel(source)"
                  :value="sourceKeyOf(source)"
                />
              </el-select>
              <el-button size="small" :disabled="saving" @click="openManual(key)">
                手工补充
              </el-button>
              <el-button
                size="small"
                :disabled="saving || !form.slots[key]"
                @click="clearSlot(key)"
              >
                清空
              </el-button>
            </div>
            <p v-if="slotPicks[key].name && pickSources(key).length > 1 && !slotPicks[key].sourceKey" class="muted">
              该游戏在多个日期存在来源，请选择具体来源后再继续。
            </p>
            <p v-if="slotGroups(key).length === 0" class="muted">
              本周日计划中暂无该类别的游戏来源，可使用“手工补充”（不会伪造日计划来源）。
            </p>
          </template>
        </div>
        <p class="muted">
          选择日计划来源会携带该来源的完整引用与整组文本；手工补充仅适用于户外游戏槽位，
          标识由服务端生成并在后续编辑中保留。
        </p>
      </el-card>

      <!-- 重点区域：仅真实日计划来源或清空，无手工补充 -->
      <el-card class="section">
        <template #header>重点区域</template>
        <template v-if="form.focus">
          <div class="slot-head">
            <strong>{{ form.focus.name || '（未命名）' }}</strong>
            <el-tag size="small" type="success">日计划来源</el-tag>
            <el-tag v-if="focusIsStale()" size="small" type="danger">来源已陈旧</el-tag>
            <span class="muted">{{ focusMeta() }}</span>
          </div>
          <el-collapse v-if="focusTexts().length" class="inline-collapse">
            <el-collapse-item name="focus-text">
              <template #title><span class="link-like">查看整组文本（与来源同组）</span></template>
              <p v-for="t in focusTexts()" :key="t.label" class="group-text">
                <strong>{{ t.label }}：</strong>{{ t.value }}
              </p>
            </el-collapse-item>
          </el-collapse>
        </template>
        <p v-else class="muted">未选择（缺项以空值表达，不自动补写）。</p>

        <template v-if="canEdit">
          <div class="slot-actions">
            <el-select
              v-model="focusPick.name"
              placeholder="选择重点区域来源（按名称合并，多来源需选定日期）"
              clearable
              filterable
              :disabled="saving"
              class="pick-select"
              @change="onFocusName($event)"
            >
              <el-option
                v-for="group in focusGroups()"
                :key="group.name"
                :label="`${group.name}（${group.sources.map((s) => shortDate(s.date)).join('、')}）`"
                :value="group.name"
              />
            </el-select>
            <el-select
              v-if="focusPick.name && focusPickSources().length > 1"
              v-model="focusPick.sourceKey"
              placeholder="选择来源日期"
              :disabled="saving"
              class="pick-source"
              @change="onFocusSource($event)"
            >
              <el-option
                v-for="source in focusPickSources()"
                :key="sourceKeyOf(source)"
                :label="candidateSourceLabel(source)"
                :value="sourceKeyOf(source)"
              />
            </el-select>
            <el-button size="small" :disabled="saving || !form.focus" @click="clearFocus">
              清空
            </el-button>
          </div>
          <p v-if="focusGroups().length === 0" class="muted">
            本周日计划中暂无集体活动后游戏来源可选。
          </p>
          <p class="muted">重点区域只允许选择真实日计划来源或清空，不提供手工补充入口。</p>
        </template>
      </el-card>

      <!-- 四个手工栏目 -->
      <el-card class="section">
        <template #header>手工栏目</template>
        <div class="field-grid">
          <div v-for="key in WEEKLY_COLUMN_KEYS" :key="key" class="field">
            <label>{{ WEEKLY_COLUMN_LABELS[key] }}</label>
            <el-input
              v-model="form.columns[key]"
              type="textarea"
              :rows="3"
              :disabled="!canEdit || saving"
              @input="markColumn(key)"
            />
            <p v-if="dirty.columns.has(key)" class="muted">有未保存的本地修改。</p>
          </div>
        </div>
      </el-card>

      <!-- 材料：只读显示缺项，无生成入口 -->
      <el-card class="section">
        <template #header>材料</template>
        <p class="muted">缺项（本阶段不提供材料填写入口，也不会自动补写）。</p>
      </el-card>

      <!-- 确认区（U4 双路径：R 刷新 / C 确认当前未更新） -->
      <el-card class="section">
        <template #header>确认</template>

        <el-alert
          v-if="detail.stale_sources.length > 0"
          type="warning"
          :closable="false"
          title="来源已陈旧：日计划内容已更新，草稿仍保留旧来源"
          class="stale-banner"
        >
          <ul class="fact-list">
            <li v-for="(fact, i) in detail.stale_sources" :key="i">
              {{ staleFactLabel(fact) }}
            </li>
          </ul>
          <p v-if="anyDirty" class="muted">
            存在未保存的本地修改；刷新与确认都不会提交这些修改，也不会丢弃它们，
            请在需要时单独保存。
          </p>
          <div v-if="!conflictActive && (canEdit || canConfirm)" class="actions-row">
            <el-button
              v-if="canEdit"
              type="primary"
              :loading="refreshing"
              :disabled="saving || confirming"
              @click="refreshSources"
            >
              刷新到最新来源（R）
            </el-button>
            <el-button
              v-if="canConfirm"
              :loading="confirming"
              :disabled="saving || refreshing"
              @click="openConfirm"
            >
              确认当前未更新内容（C）
            </el-button>
          </div>
          <p v-if="conflictActive" class="muted">版本冲突处理中，请先处理上方冲突。</p>
          <p v-else-if="canEdit && !canConfirm" class="muted">
            可执行刷新；确认须由本班负责人完成。
          </p>
        </el-alert>

        <template v-else>
          <el-alert
            v-if="detail.missing.length > 0"
            type="warning"
            :closable="false"
            title="内容存在缺失事实，确认前需要显式知晓"
            class="missing-banner"
          >
            <ul class="fact-list">
              <li v-for="(fact, i) in detail.missing" :key="i">
                {{ missingFactLabel(fact) }}
              </li>
            </ul>
            <p v-if="anyDirty" class="muted">
              存在未保存的本地修改；确认只针对已保存的草稿版本，不会包含这些修改。
            </p>
            <div v-if="canConfirm && !conflictActive" class="actions-row">
              <el-button
                type="primary"
                :loading="confirming"
                :disabled="saving"
                @click="openConfirm"
              >
                确认当前草稿
              </el-button>
            </div>
            <p v-if="conflictActive && canConfirm" class="muted">
              版本冲突处理中，请先处理上方冲突。
            </p>
          </el-alert>
          <div v-else-if="canConfirm && !conflictActive" class="actions-row">
            <el-button
              type="primary"
              :loading="confirming"
              :disabled="saving"
              @click="openConfirm"
            >
              确认当前草稿
            </el-button>
            <span class="muted">确认针对已保存的草稿 v{{ detail.draft.version }}。</span>
          </div>
          <p v-else-if="canConfirm && conflictActive" class="muted">
            版本冲突处理中，请先处理上方冲突。
          </p>
        </template>

        <p v-if="canEdit && !canConfirm" class="muted admin-hint">
          管理员可编辑与刷新，但确认须由本班负责人完成；管理员保存后计划继续处于待负责人确认。
        </p>
        <p v-if="readOnly" class="muted">
          只读视图：同班其他教师可查看内容与确认历史，不能保存、刷新或确认。
        </p>
      </el-card>

      <!-- 确认历史（只读；与当前草稿版本号分开） -->
      <el-card class="section">
        <template #header>确认历史</template>
        <el-table
          :data="confirmations"
          v-loading="confirmationsLoading"
          size="small"
          empty-text="尚无确认记录"
        >
          <el-table-column label="确认版本" width="110">
            <template #default="{ row }">V{{ row.version }}</template>
          </el-table-column>
          <el-table-column label="确认时草稿" width="110">
            <template #default="{ row }">v{{ row.draft_version }}</template>
          </el-table-column>
          <el-table-column label="确认时间" min-width="160">
            <template #default="{ row }">{{ row.created_at }}</template>
          </el-table-column>
          <el-table-column label="确认时事实" min-width="150">
            <template #default="{ row }">{{ confirmationFactsText(row.facts) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="viewConfirmation(row.version)">
                查看全文
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted">
          确认版本不可修改；当前草稿与历史确认版本的版本号分开显示，互不混用。
        </p>
      </el-card>

      <!-- 保存 -->
      <div v-if="canEdit" class="actions-row footer-actions">
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!anyDirty || conflictActive || refreshing || confirming"
          @click="save"
        >
          保存
        </el-button>
        <span v-if="conflictActive" class="muted">
          冲突处理中：请先选择放弃本地或以服务端为基准重提
        </span>
        <span v-else-if="anyDirty" class="muted">
          有未保存的本地修改 · 保存目标草稿 v{{ saveTargetVersion }}
          <template v-if="detail && saveTargetVersion !== detail.draft.version">
            （服务端当前为 v{{ detail.draft.version }}，保存时将按版本冲突处理，不会静默覆盖）
          </template>
        </span>
        <span v-else class="muted">草稿 v{{ detail.draft.version }}（无本地修改）</span>
      </div>
    </template>

    <!-- 手工补充对话框（仅户外游戏槽位） -->
    <el-dialog
      v-model="manualDialog.open"
      :title="manualDialog.isNew ? '手工补充游戏' : '编辑手工游戏'"
      width="560px"
    >
      <p class="muted">
        手工补充不会伪造日计划来源；标识由服务端生成，后续编辑时保留。
        <template v-if="manualDialog.slotKey">目标槽位：{{ SLOT_LABELS[manualDialog.slotKey] }}</template>
      </p>
      <div class="field">
        <label>名称（必填）</label>
        <el-input v-model="manualDialog.name" :disabled="saving" />
      </div>
      <div class="field">
        <label>共用目标</label>
        <el-input v-model="manualDialog.shared_objectives" type="textarea" :rows="2" :disabled="saving" />
      </div>
      <div class="field">
        <label>指导要点</label>
        <el-input v-model="manualDialog.guidance_points" type="textarea" :rows="2" :disabled="saving" />
      </div>
      <div class="field">
        <label>重点指导</label>
        <el-input v-model="manualDialog.focus_guidance" type="textarea" :rows="2" :disabled="saving" />
      </div>
      <p v-if="manualDialog.error" class="warn">{{ manualDialog.error }}</p>
      <template #footer>
        <el-button @click="manualDialog.open = false">取消</el-button>
        <el-button type="primary" :disabled="saving" @click="saveManual">确定</el-button>
      </template>
    </el-dialog>

    <!-- 确认对话框：缺失/陈旧事实 + 显式勾选，note 可选 -->
    <el-dialog
      v-model="confirmOpen"
      :title="confirmFacts.stale_sources.length ? '确认当前未更新内容' : '确认当前草稿'"
      width="680px"
      :close-on-click-modal="false"
    >
      <p>
        当前已保存草稿版本：<strong>v{{ confirmTarget?.version ?? detail?.draft.version }}</strong>
        （本次确认目标）
      </p>
      <p class="muted">
        确认生成不可修改的确认版本，只包含该确认目标的已保存草稿内容；未保存的本地修改不会包含在内。
        确认不会刷新来源，陈旧来源将按草稿现状原样保留。
      </p>

      <!-- 确认目标内容快照：dirty 字段在主编辑区显示本地输入时，
           必须能在此查看确认目标在重叠字段上的真实已保存内容 -->
      <el-alert
        v-if="confirmTarget && anyDirty"
        type="info"
        :closable="false"
        class="inline-alert"
        :title="`确认目标内容（服务端已保存草稿 v${confirmTarget.version}）`"
      >
        <p class="muted">
          主编辑区中带“未保存的本地修改”标记的字段显示的是本地输入，它们不属于本次确认目标、
          不会被提交也不会被丢弃；以下才是本次确认目标在这些字段上的真实已保存内容。
        </p>
        <p><strong>主题：</strong>{{ confirmTarget.content.theme || '（空）' }}</p>

        <h4 class="facts-title">每日确定性栏目</h4>
        <el-table :data="confirmedContentRows(confirmTarget.content)" size="small">
          <el-table-column prop="date" label="日期" width="110" />
          <el-table-column label="晨间谈话话题（生效）">
            <template #default="{ row }">
              {{ row.effective?.morning_talk_topic || '（空）' }}
              <el-tag v-if="row.override?.morning_talk_topic != null" size="small" type="warning">
                覆盖
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="集体活动主题（生效）">
            <template #default="{ row }">
              {{ row.effective?.group_activity_theme || '（空）' }}
              <el-tag v-if="row.override?.group_activity_theme != null" size="small" type="warning">
                覆盖
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <h4 class="facts-title">户外游戏</h4>
        <div v-for="key in OUTDOOR_SLOT_KEYS" :key="`target-${key}`" class="snapshot-line">
          <strong>{{ SLOT_LABELS[key] }}：</strong>
          <template v-if="confirmTarget.content.outdoor_game_slots?.[key]">
            {{ confirmTarget.content.outdoor_game_slots[key]!.name || '（未命名）' }}
            <span
              v-if="confirmTarget.content.outdoor_game_slots[key]!.source_kind === 'manual'"
              class="muted"
            >
              手工补充
            </span>
          </template>
          <span v-else class="muted">未选择</span>
        </div>

        <h4 class="facts-title">重点区域</h4>
        <p v-if="confirmTarget.content.focus_area" class="snapshot-line">
          {{ confirmTarget.content.focus_area.name || '（未命名）' }}
        </p>
        <p v-else class="muted">未选择</p>

        <h4 class="facts-title">手工栏目</h4>
        <div v-for="key in WEEKLY_COLUMN_KEYS" :key="`target-${key}`" class="snapshot-line">
          <strong>{{ WEEKLY_COLUMN_LABELS[key] }}：</strong>
          {{ confirmTarget.content.weekly_columns?.[key] || '（空）' }}
        </div>
      </el-alert>

      <template v-if="confirmFacts.missing.length > 0">
        <h4 class="facts-title">缺失事实（{{ confirmFacts.missing.length }}）——必须知晓后确认</h4>
        <ul class="fact-list">
          <li v-for="(fact, i) in confirmFacts.missing" :key="i">
            {{ missingFactLabel(fact) }}
          </li>
        </ul>
        <el-checkbox v-model="ackMissing">我已知晓以上缺失事实</el-checkbox>
      </template>

      <template v-if="confirmFacts.stale_sources.length > 0">
        <h4 class="facts-title">来源未更新（{{ confirmFacts.stale_sources.length }}）——确认后保留旧来源</h4>
        <ul class="fact-list">
          <li v-for="(fact, i) in confirmFacts.stale_sources" :key="i">
            {{ staleFactLabel(fact) }}
          </li>
        </ul>
        <el-collapse class="inline-collapse">
          <el-collapse-item name="ack-stale-raw">
            <template #title><span class="link-like">来源版本明细（可展开）</span></template>
            <pre class="raw-block">{{ JSON.stringify(confirmFacts.stale_sources, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
        <el-checkbox v-model="ackStale">我已知晓以上来源未更新，确认后仍保留草稿中的旧来源</el-checkbox>
      </template>

      <p v-if="confirmFacts.missing.length === 0 && confirmFacts.stale_sources.length === 0" class="muted">
        当前没有缺失或陈旧事实。
      </p>

      <div class="field">
        <label>备注（可选，可留空）</label>
        <el-input v-model="confirmNote" type="textarea" :rows="2" :disabled="confirming" />
      </div>

      <el-alert
        v-if="confirmError"
        type="warning"
        :closable="false"
        :title="confirmError"
        class="inline-alert"
      />

      <template #footer>
        <el-button :disabled="confirming" @click="confirmOpen = false">取消</el-button>
        <el-button
          type="primary"
          :loading="confirming"
          :disabled="!acksSatisfied || conflictActive"
          @click="submitConfirm"
        >
          {{ confirmFacts.stale_sources.length ? '确认当前未更新内容' : '确认当前草稿' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 单个确认版本（只读全文） -->
    <el-dialog
      v-model="confirmationViewOpen"
      title="确认版本（只读全文）"
      width="760px"
      class="confirmation-dialog"
    >
      <div v-loading="confirmationLoading">
        <template v-if="viewedConfirmation">
          <div class="meta">
            <span>确认版本：V{{ viewedConfirmation.version }}</span>
            <span>确认时草稿：v{{ viewedConfirmation.draft_version }}</span>
            <span>确认时间：{{ viewedConfirmation.created_at }}</span>
            <span>
              事实：{{ confirmationFactsText(viewedConfirmation.facts) }}
              · 缺失知晓：{{ viewedConfirmation.facts.ack_missing ? '是' : '否' }}
              · 陈旧知晓：{{ viewedConfirmation.facts.ack_stale ? '是' : '否' }}
            </span>
            <span>备注：{{ viewedConfirmation.facts.note || '（无）' }}</span>
          </div>

          <el-card class="section inner-card">
            <template #header>缺失事实（确认时固化）</template>
            <ul v-if="(viewedConfirmation.facts.missing || []).length" class="fact-list">
              <li v-for="(fact, i) in viewedConfirmation.facts.missing" :key="i">
                {{ missingFactLabel(fact) }}
              </li>
            </ul>
            <p v-else class="muted">无</p>
          </el-card>

          <el-card class="section inner-card">
            <template #header>陈旧来源（确认时固化）</template>
            <ul v-if="(viewedConfirmation.facts.stale_sources || []).length" class="fact-list">
              <li v-for="(fact, i) in viewedConfirmation.facts.stale_sources" :key="i">
                {{ staleFactLabel(fact) }}
              </li>
            </ul>
            <p v-else class="muted">无</p>
          </el-card>

          <el-card class="section inner-card">
            <template #header>内容快照</template>
            <p><strong>主题：</strong>{{ viewedConfirmation.content.theme || '（空）' }}</p>

            <h4>每日确定性栏目</h4>
            <el-table :data="confirmedContentRows(viewedConfirmation.content)" size="small">
              <el-table-column prop="date" label="日期" width="110" />
              <el-table-column label="状态" width="140">
                <template #default="{ row }">
                  {{ row.day_state === 'teaching' ? '教学日' : '休息日' }}
                  ·
                  {{ row.plan_state === 'saved' ? '已保存日计划'
                    : row.plan_state === 'no_plan' ? '缺日计划' : '无需日计划' }}
                </template>
              </el-table-column>
              <el-table-column label="晨间谈话话题（生效）">
                <template #default="{ row }">
                  {{ row.effective?.morning_talk_topic || '（空）' }}
                  <el-tag v-if="row.override?.morning_talk_topic != null" size="small" type="warning">
                    覆盖
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="集体活动主题（生效）">
                <template #default="{ row }">
                  {{ row.effective?.group_activity_theme || '（空）' }}
                  <el-tag v-if="row.override?.group_activity_theme != null" size="small" type="warning">
                    覆盖
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>

            <h4>户外游戏</h4>
            <div v-for="key in OUTDOOR_SLOT_KEYS" :key="key" class="snapshot-line">
              <strong>{{ SLOT_LABELS[key] }}：</strong>
              <template v-if="viewedConfirmation.content.outdoor_game_slots?.[key]">
                <el-tag
                  size="small"
                  :type="viewedConfirmation.content.outdoor_game_slots[key]!.source_kind === 'manual'
                    ? 'warning' : 'success'"
                >
                  {{ viewedConfirmation.content.outdoor_game_slots[key]!.source_kind === 'manual'
                    ? '手工补充' : '日计划来源' }}
                </el-tag>
                {{ viewedConfirmation.content.outdoor_game_slots[key]!.name || '（未命名）' }}
                <span
                  v-if="viewedConfirmation.content.outdoor_game_slots[key]!.source_kind === 'daily_plan'"
                  class="muted"
                >
                  内容 v{{ viewedConfirmation.content.outdoor_game_slots[key]!.content_version }}
                </span>
              </template>
              <span v-else class="muted">未选择</span>
            </div>

            <h4>重点区域</h4>
            <p v-if="viewedConfirmation.content.focus_area" class="snapshot-line">
              {{ viewedConfirmation.content.focus_area.name || '（未命名）' }}
              <span class="muted">内容 v{{ viewedConfirmation.content.focus_area.content_version }}</span>
            </p>
            <p v-else class="muted">未选择</p>

            <h4>手工栏目</h4>
            <div v-for="key in WEEKLY_COLUMN_KEYS" :key="key" class="snapshot-line">
              <strong>{{ WEEKLY_COLUMN_LABELS[key] }}：</strong>
              {{ viewedConfirmation.content.weekly_columns?.[key] || '（空）' }}
            </div>

            <p class="muted">材料：缺项</p>
          </el-card>
        </template>
        <p v-else-if="!confirmationLoading" class="muted">读取确认版本失败，请关闭后重试。</p>
      </div>
      <template #footer>
        <el-button @click="confirmationViewOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.weekly-plan { max-width: 960px; }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.section { margin-top: 16px; }
.muted { color: #909399; font-size: 0.85rem; }
.warn { color: #f56c6c; font-size: 0.875rem; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 20px; color: #606266; font-size: 0.9rem; }
.actions-row { display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
.inline-alert { margin-top: 12px; }
.footer-actions { margin-top: 20px; }
.status-grid { display: flex; flex-direction: column; gap: 10px; }
.status-item { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 0.9rem; }
.status-item .label { color: #909399; min-width: 110px; }
.state-tag { margin-left: 4px; }
.src-line { display: flex; align-items: center; gap: 8px; margin-top: 4px; flex-wrap: wrap; }
.slot-block { border: 1px solid #ebeef5; border-radius: 4px; padding: 12px; margin-bottom: 12px; background: #fafbfc; }
.slot-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.slot-name { font-weight: 600; }
.slot-actions { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.pick-select { width: 320px; max-width: 100%; }
.pick-source { width: 220px; }
.field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.field { margin-top: 8px; }
.field label { display: block; margin-bottom: 4px; color: #606266; font-size: 0.85rem; }
.inline-collapse { border: none; }
.inline-collapse :deep(.el-collapse-item__header) { height: 28px; line-height: 28px; border: none; }
.inline-collapse :deep(.el-collapse-item__wrap) { border: none; }
.link-like { color: #409eff; font-size: 0.85rem; }
.fact-list { margin: 6px 0; padding-left: 18px; }
.fact-list li { margin: 2px 0; font-size: 0.875rem; }
.raw-block {
  margin: 6px 0 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.75rem;
  max-height: 220px;
  overflow: auto;
}
.group-text { margin: 4px 0; font-size: 0.875rem; }
.facts-title { margin: 14px 0 6px; }
.stale-banner :deep(.el-alert__content p:last-child),
.missing-banner :deep(.el-alert__content p:last-child) { margin-bottom: 0; }
.admin-hint { margin-top: 12px; }
.conflict-body { margin-top: 4px; }
.conflict-hint { color: #b88230; font-size: 0.875rem; }
.inner-card { margin-top: 12px; }
.snapshot-line { margin: 6px 0; font-size: 0.9rem; }
.confirmation-dialog h4 { margin: 14px 0 6px; }
</style>
