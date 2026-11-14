<script setup lang="ts">
/**
 * Settings / configuration maintenance (D1 spec §10.2): profile, current
 * class, terms and per-day calendar overrides, all through the preview →
 * confirm → apply protocol. Every change shows its real before/after values,
 * the calendar diff and the complete impact facts (existing plans retain
 * their old headers and are listed, never rewritten); confirmed tokens are
 * never reused after an input change or a preview close.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import type {
  ConfigApplyResult,
  ConfigChange,
  ConfigPreview,
  LocalContext,
} from '../types'
import type { SettingsDraftTarget, SettingsDraftTargetKind } from '../leave'
import AiSettingsPanel from './AiSettingsPanel.vue'
import GameConfigPanel from './GameConfigPanel.vue'
import CollaborationPanel from './CollaborationPanel.vue'
import { createCollaborationApi } from '../collaboration'
import type { CollaborationPromotionTerm } from '../collaboration'

const props = defineProps<{
  context: LocalContext
  frozen?: boolean
  section?: 'collaboration' | null
  focusPrompt?: string
  reloadContext?: () => Promise<LocalContext>
}>()
const emit = defineEmits<{
  (e: 'draft-targets', targets: SettingsDraftTarget[]): void
  (e: 'draft-active', active: boolean): void
  (e: 'leave', run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed'): void
  (e: 'open-maintenance'): void
  (e: 'section', section: 'collaboration' | null): void
}>()

type SettingsSection = 'main' | 'collaboration'
type SettingsGroup = 'backup' | 'terms' | 'calendar' | 'games'

const activeSection = ref<SettingsSection>(
  props.section === 'collaboration' ? 'collaboration' : 'main',
)

const expandedGroups = reactive<Record<SettingsGroup, boolean>>({
  backup: false,
  terms: false,
  calendar: false,
  games: false,
})
const autoOpenGroups = reactive<Record<SettingsGroup, boolean>>({
  backup: false,
  terms: false,
  calendar: false,
  games: true,
})
function groupOpen(name: SettingsGroup): boolean {
  return expandedGroups[name] || autoOpenGroups[name]
}

const TARGET_GROUPS: Partial<Record<SettingsDraftTargetKind, SettingsGroup>> = {
  term: 'terms',
  'new-term': 'terms',
  override: 'calendar',
  'game-config': 'games',
}

function setSettingsSection(section: SettingsSection): void {
  activeSection.value = section
  emit('section', section === 'collaboration' ? 'collaboration' : null)
}

function openCollaborationSection(): void {
  setSettingsSection('collaboration')
}

function openMainSection(): void {
  setSettingsSection('main')
}

function onGroupToggle(name: SettingsGroup, event: Event): void {
  const target = event.target as HTMLDetailsElement | null
  autoOpenGroups[name] = false
  if (target) expandedGroups[name] = target.open
}

watch(
  () => props.section,
  (value) => {
    activeSection.value = value === 'collaboration' ? 'collaboration' : 'main'
  },
)

const GRADE_LABELS: Record<string, string> = { small: '小班', middle: '中班', large: '大班' }
const STATE_LABELS: Record<string, string> = {
  teaching: '上课',
  non_teaching: '停课',
  unknown: '未备年份',
  outside_term: '学期外',
}
const DAILY_IMPACT_REASON_LABELS: Record<string, string> = {
  header_retained: '保留旧表头',
  outside_new_range: '日期不在新学期范围内',
  date_state_changed: '日期状态变化',
  week_changed: '周次变化',
}
const WEEKLY_IMPACT_REASON_LABELS: Record<string, string> = {
  weekly_header_retained: '保留旧表头',
  weekly_creation_context_retained: '保留创建学期、周次与日历',
  weekly_anchor_outside_new_term: '周锚点不在调整后的学期内',
  weekly_anchor_outside_own_term: '周锚点不在所属学期的当前范围内',
  weekly_calendar_override_in_week: '本周内有日历例外',
}
function impactReasonTextList(
  reasons: string[],
  labels: Record<string, string>,
): string {
  return reasons.map((reason) => labels[reason] ?? '其他影响').join('、')
}

const profileName = ref(props.context.profile?.display_name ?? '')
const schoolName = ref(props.context.school_name ?? '')
const className = ref(props.context.class?.name ?? '')
const classGrade = ref<'small' | 'middle' | 'large'>(
  props.context.class?.grade ?? 'middle',
)
const headerTeacherNamesText = ref(
  (props.context.class?.header_teacher_names ?? []).join('\n'),
)
const caregiverName = ref(props.context.class?.caregiver_name ?? '')

/** One name per line; empty lines are ignored and order/duplicates are kept. */
function parsedHeaderTeacherNames(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

interface TermForm {
  id: string
  name: string
  start_date: string
  end_date: string
}
const termForms = ref<TermForm[]>(
  props.context.terms.map((term) => ({
    id: term.id,
    name: term.name,
    start_date: term.start_date,
    end_date: term.end_date,
  })),
)
const readingPromotionTerms = ref(false)
const promotionTermNotice = ref('')
const promotionTerms = ref<CollaborationPromotionTerm[]>([])

const newTermName = ref('')
const newTermRange = ref<string[]>([])

const overrideTermId = ref(props.context.terms[0]?.id ?? '')
const overrideDate = ref('')
const overrideState = ref<'teaching' | 'non_teaching' | 'none'>('teaching')
const overrideReason = ref('')

const previewData = ref<ConfigPreview | null>(null)
const previewing = ref(false)
const applying = ref(false)
const errorText = ref('')
const applyResultText = ref('')
const committedConfigVersion = ref<{ from: number; to: number } | null>(null)
const confirmedContext = ref<LocalContext>(props.context)
/** D2 W5: AI settings and class-game panels own their own unsaved drafts. */
const aiDraftActive = ref(false)
const gameDraftActive = ref(false)
const collaborationDraftActive = ref(false)
const aiPanelRef = ref<{ draftTargets?: () => SettingsDraftTargetKind[]; focusDraftTarget?: (kind?: string) => void; focusPromptTask?: (taskType: string) => void | Promise<void> } | null>(null)
const gamePanelRef = ref<{ draftTargets?: () => SettingsDraftTargetKind[]; focusDraftTarget?: (kind?: string) => void } | null>(null)
watch(
  () => props.focusPrompt,
  async (value) => {
    if (!value) return
    setSettingsSection('main')
    await nextTick()
    await aiPanelRef.value?.focusPromptTask?.(value)
  },
  { immediate: true },
)
const collaborationPanelRef = ref<{
  draftTargets?: () => string[]
  pendingWrite?: () => unknown
  pendingPromotion?: () => unknown
  promotionStale?: () => boolean
  currentStatus?: () => {
    connected: boolean
    teacher?: { teacher_id: string; school_id: string } | null
  } | null
  currentPreview?: () => unknown
  currentPublishPreview?: () => unknown
} | null>(null)
let pendingRequestId = ''
let promotionReadGeneration = 0
/**
 * Input version: bumped by every local input change / preview cancel /
 * context update / unmount. A preview response only lands when its captured
 * version is still current, so a late answer can never restore an old
 * confirmation (R4).
 */
let inputSeq = 0
/** Preview binding: the input version and configuration version it confirmed. */
let previewBinding: { seq: number; configVersion: number | null } | null = null
/**
 * A one-click confirm that has sent apply but not yet resolved. The whole
 * original request (id, body and submitted change) is frozen here: later
 * input, a context reload or a frozen prop must never change what a retry
 * re-submits. Only an explicit receipt query or the same-request retry may
 * clear it.
 */
interface PendingConfirm {
  requestId: string
  expectedVersion: number
  body: Record<string, unknown>
  change: ConfigChange
  submitted: ConfigChange
}
const pendingConfirm = ref<PendingConfirm | null>(null)
/**
 * After a successful apply the server may already be at a newer configuration
 * version while the parent's context re-read is still in flight. The next
 * ordinary confirm is queued until that exact version is re-read; it must
 * never post the known-old expected_config_version.
 */
const awaitingContextVersion = ref<number | null>(null)
const queuedConfirm = ref<{change: ConfigChange; submit: () => ConfigChange} | null>(null)
const contextReloadFailed = ref(false)
let reloadRequestedFor: number | null = null
let resyncAfterReload = false
/**
 * The change applied but not yet reflected in the context: the reload merge
 * only rebases the fields that still carry the submitted values, keeping any
 * other drafts and inputs typed while the apply was in flight (R3).
 */
interface PendingApplied {
  change: ConfigChange
  submitted: ConfigChange
}
let pendingAppliedMerge: PendingApplied | null = null

const activeLocalTerm = computed(() => props.context.term)

function currentTerm(termId: string) {
  return props.context.terms.find((term) => term.id === termId) ?? null
}

const overrideTerm = computed(() => currentTerm(overrideTermId.value))

const draftActive = computed(() => {
  const confirmed = confirmedContext.value
  if (profileName.value !== (confirmed.profile?.display_name ?? '')) return true
  if (schoolName.value !== (confirmed.school_name ?? '')) return true
  if (className.value !== (confirmed.class?.name ?? '')) return true
  if (classGrade.value !== (confirmed.class?.grade ?? 'middle')) return true
  if (
    parsedHeaderTeacherNames(headerTeacherNamesText.value).join('\n') !==
    (confirmed.class?.header_teacher_names ?? []).join('\n')
  ) {
    return true
  }
  if (
    (caregiverName.value.trim() || '') !==
    (confirmed.class?.caregiver_name ?? '')
  ) {
    return true
  }
  const forms = termForms.value
  if (forms.length !== confirmed.terms.length) return true
  for (let i = 0; i < forms.length; i += 1) {
    const form = forms[i]
    const term = confirmed.terms[i]
    if (
      form.id !== term.id ||
      form.name !== term.name ||
      form.start_date !== term.start_date ||
      form.end_date !== term.end_date
    ) {
      return true
    }
  }
  if (newTermName.value || newTermRange.value.length === 2) return true
  if (overrideDate.value || overrideReason.value) return true
  if (previewData.value || pendingConfirm.value || queuedConfirm.value) return true
  if (aiDraftActive.value || gameDraftActive.value) return true
  if (collaborationDraftActive.value) return true
  return false
})

watch(draftActive, (value) => emit('draft-active', value), { immediate: true })

/** The shell uses this ordered list; it never writes to the page. */
watch(
  () => [draftActive.value, confirmedContext.value, termForms.value, profileName.value, schoolName.value, className.value, classGrade.value, caregiverName.value, newTermName.value, newTermRange.value, overrideDate.value, overrideReason.value, pendingConfirm.value, awaitingContextVersion.value, contextReloadFailed.value, previewData.value, aiPanelRef.value?.draftTargets?.(), gamePanelRef.value?.draftTargets?.(), collaborationPanelRef.value?.draftTargets?.()],
  () => emit('draft-targets', draftTargets()),
  { deep: true, immediate: true },
)

function clearPreview(): void {
  previewData.value = null
  pendingRequestId = ''
  previewBinding = null
  inputSeq += 1
}

function syncFormsFrom(context: LocalContext): void {
  profileName.value = context.profile?.display_name ?? ''
  schoolName.value = context.school_name ?? ''
  className.value = context.class?.name ?? ''
  classGrade.value = context.class?.grade ?? 'middle'
  headerTeacherNamesText.value = (
    context.class?.header_teacher_names ?? []
  ).join('\n')
  caregiverName.value = context.class?.caregiver_name ?? ''
  termForms.value = context.terms.map((term) => ({
    id: term.id,
    name: term.name,
    start_date: term.start_date,
    end_date: term.end_date,
  }))
  newTermName.value = ''
  newTermRange.value = []
  overrideDate.value = ''
  overrideReason.value = ''
  clearPreview()
}

/** Page-side normalization used to compare form values with submissions. */
function pageNormalize(value: unknown): unknown {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed === '' ? null : trimmed
  }
  return value === undefined ? null : value
}

/** The page-built change object for the current form inputs (R4 binding). */
function currentChangeFor(change: ConfigChange): ConfigChange | null {
  if (change.kind === 'profile') return changeProfile()
  if (change.kind === 'current_class') return changeClass()
  if (change.kind === 'term_update') {
    const form = termForms.value.find((term) => term.id === change.term_id)
    return form ? termChange(form) : null
  }
  if (change.kind === 'term_create') {
    if (!newTermName.value.trim() || newTermRange.value.length !== 2) return null
    return {
      kind: 'term_create',
      name: newTermName.value,
      start_date: newTermRange.value[0],
      end_date: newTermRange.value[1],
    }
  }
  if (change.kind === 'calendar_override') {
    return {
      kind: 'calendar_override',
      term_id: overrideTermId.value,
      date: overrideDate.value,
      state: overrideState.value === 'none' ? null : overrideState.value,
      reason: overrideState.value === 'none' ? null : overrideReason.value,
    }
  }
  return null
}

/** True when the current inputs still build exactly the confirmed change. */
function changeStillBound(normalizedChange: ConfigChange): boolean {
  const current = currentChangeFor(normalizedChange)
  if (!current) return false
  const keys = new Set([
    ...Object.keys(current),
    ...Object.keys(normalizedChange),
  ])
  for (const key of keys) {
    const left = JSON.stringify(
      pageNormalize((current as Record<string, unknown>)[key]),
    )
    const right = JSON.stringify(
      pageNormalize((normalizedChange as Record<string, unknown>)[key]),
    )
    if (left !== right) return false
  }
  return true
}

// The parent owns the fetched context: the reload result arrives as a prop
// update. Only the fields of the just-applied change are rebased (and only
// while they still carry the submitted values); every other draft and any
// input typed while the apply was in flight is preserved (R3).
watch(
  () => props.context,
  (fresh) => {
    const expected = awaitingContextVersion.value
    if (expected !== null && (fresh.config_version ?? 0) < expected) return
    confirmedContext.value = fresh
    clearPreview()
    const pending = pendingAppliedMerge
    if (pending) {
      pendingAppliedMerge = null
      mergeAppliedBaseline(fresh, pending)
    } else if (!draftActive.value && !queuedConfirm.value) {
      // No pending draft: safe to re-sync every field from the fresh context.
      syncFormsFrom(fresh)
    }
    if (settleContextVersion(fresh) === 'exact') flushQueuedConfirm()
  },
)

function mergeAppliedBaseline(
  fresh: LocalContext,
  pending: PendingApplied,
): void {
  const change = pending.change
  const submitted = pending.submitted as Record<string, unknown>
  const still = (key: string, current: unknown): boolean =>
    pageNormalize(current) === pageNormalize(submitted[key])
  if (change.kind === 'profile') {
    if (still('display_name', profileName.value)) {
      profileName.value = fresh.profile?.display_name ?? ''
    }
    if (still('school_name', schoolName.value)) {
      schoolName.value = fresh.school_name ?? ''
    }
    return
  }
  if (change.kind === 'current_class') {
    if (still('name', className.value)) {
      className.value = fresh.class?.name ?? ''
    }
    if (still('grade', classGrade.value)) {
      classGrade.value = fresh.class?.grade ?? 'middle'
    }
    const submittedNames = Array.isArray(submitted.header_teacher_names)
      ? (submitted.header_teacher_names as string[])
      : []
    if (
      parsedHeaderTeacherNames(headerTeacherNamesText.value).join('\n') ===
      submittedNames.join('\n')
    ) {
      headerTeacherNamesText.value = (
        fresh.class?.header_teacher_names ?? []
      ).join('\n')
    }
    if (still('caregiver_name', caregiverName.value.trim() || null)) {
      caregiverName.value = fresh.class?.caregiver_name ?? ''
    }
    return
  }
  if (change.kind === 'term_update') {
    const form = termForms.value.find((term) => term.id === change.term_id)
    const freshTerm = fresh.terms.find((term) => term.id === change.term_id)
    if (!form || !freshTerm) return
    if (still('name', form.name)) form.name = freshTerm.name
    if (still('start_date', form.start_date)) form.start_date = freshTerm.start_date
    if (still('end_date', form.end_date)) form.end_date = freshTerm.end_date
    return
  }
  if (change.kind === 'term_create') {
    // The new term now exists: clear the draft fields only when they still
    // carry the submitted values, and list any newly created term.
    if (still('name', newTermName.value)) newTermName.value = ''
    if (
      still('start_date', newTermRange.value[0]) &&
      still('end_date', newTermRange.value[1])
    ) {
      newTermRange.value = []
    }
    const known = new Set(termForms.value.map((term) => term.id))
    for (const term of fresh.terms) {
      if (!known.has(term.id)) {
        termForms.value.push({
          id: term.id,
          name: term.name,
          start_date: term.start_date,
          end_date: term.end_date,
        })
      }
    }
    return
  }
  if (change.kind === 'calendar_override') {
    const submittedState = pageNormalize(submitted.state)
    const currentState = pageNormalize(
      overrideState.value === 'none' ? null : overrideState.value,
    )
    if (
      still('date', overrideDate.value) &&
      submittedState === currentState &&
      still('reason', overrideReason.value)
    ) {
      overrideDate.value = ''
      overrideReason.value = ''
    }
  }
}

onBeforeUnmount(() => {
  // A response arriving after leaving settings must never restore a
  // confirmation on the next visit.
  inputSeq += 1
  promotionReadGeneration += 1
  previewBinding = null
})

watch(
  [profileName, schoolName, className, classGrade, headerTeacherNamesText, caregiverName],
  () => clearPreview(),
)
watch(termForms, () => clearPreview(), { deep: true })
watch([newTermName, newTermRange], () => clearPreview())
watch([overrideTermId, overrideDate, overrideState, overrideReason], () => clearPreview())


/** Read through the awaitable parent callback; never rely on emit() return. */
function invokeContextReload(): Promise<LocalContext> {
  if (typeof props.reloadContext === 'function') return props.reloadContext()
  return Promise.reject(new Error('reload_callback_missing'))
}

/**
 * Request the committed configuration re-read and keep the page in a visible
 * waiting state until the parent's context prop reaches that version. A
 * failed read never clears drafts or unblocks a write; the teacher can retry
 * the read explicitly.
 */
/**
 * One settlement rule for every successful context read.
 *
 * - stale (older than the committed wait): consume nothing, keep the gate.
 * - exact: release the gate and let an already-queued ordinary confirm run.
 * - newer: release the gate, cancel the queued click (the teacher confirms
 *   again on the new snapshot) and keep every draft.
 */
function settleContextVersion(fresh: LocalContext): 'stale' | 'exact' | 'newer' | 'none' {
  const expected = awaitingContextVersion.value
  if (expected === null) return 'none'
  const version = fresh.config_version ?? expected
  if (version < expected) return 'stale'
  awaitingContextVersion.value = null
  reloadRequestedFor = null
  contextReloadFailed.value = false
  if (version > expected) {
    if (queuedConfirm.value) {
      queuedConfirm.value = null
      errorText.value =
        '配置已有更新版本：请基于最新配置再次确认本次修改。'
    }
    return 'newer'
  }
  return 'exact'
}
function requestContextReload(expectedVersion?: number): void {
  if (typeof expectedVersion === 'number') {
    awaitingContextVersion.value = expectedVersion
    if (reloadRequestedFor !== expectedVersion) {
      reloadRequestedFor = expectedVersion
      contextReloadFailed.value = false
      void invokeContextReload().then(
        (fresh) => {
          if (settleContextVersion(fresh) === 'exact') flushQueuedConfirm()
        },
        () => {
          contextReloadFailed.value = true
          if (queuedConfirm.value) {
            errorText.value =
              '最新配置读取失败：修改尚未提交，草稿仍保留；请重新读取配置后再确认。'
          }
        },
      )
    }
    return
  }
  reloadRequestedFor = null
  awaitContextVersionOnManualRead()
}

function flushQueuedConfirm(): void {
  const queued = queuedConfirm.value
  if (queued && awaitingContextVersion.value === null) {
    queuedConfirm.value = null
    void runQueuedConfirm(queued)
  }
}

function requestReload(): void {
  // Legacy preview/error paths only refresh the parent context; they never
  // consume a committed-version gate or queue an ordinary confirm.
  if (typeof props.reloadContext === 'function') {
    void props.reloadContext().catch(() => undefined)
    return
  }
}


function awaitContextVersionOnManualRead(): void {
  void invokeContextReload().then(
    (fresh) => {
      if (settleContextVersion(fresh) === 'exact') flushQueuedConfirm()
    },
    () => {
      contextReloadFailed.value = true
      errorText.value =
        '最新配置读取失败：所有草稿仍保留；请重新读取配置后再确认。'
    },
  )
}

function changeProfile(): ConfigChange {
  return {
    kind: 'profile',
    display_name: profileName.value,
    school_name: schoolName.value.trim() ? schoolName.value : null,
  }
}

function changeClass(): ConfigChange {
  return {
    kind: 'current_class',
    name: className.value,
    grade: classGrade.value,
    header_teacher_names: parsedHeaderTeacherNames(
      headerTeacherNamesText.value,
    ),
    caregiver_name: caregiverName.value.trim() || null,
  }
}

async function previewChange(change: ConfigChange): Promise<void> {
  if (props.frozen || pendingConfirm.value) return
  if (previewing.value || applying.value) return
  const seq = inputSeq
  const configVersion = props.context.config_version
  previewing.value = true
  errorText.value = ''
  applyResultText.value = ''
  try {
    const preview = await apiPost<ConfigPreview>('/api/local/config/preview', {
      expected_config_version: configVersion,
      change,
    })
    if (seq !== inputSeq || configVersion !== props.context.config_version) {
      // The inputs or the configuration changed while the preview was in
      // flight: never restore the old confirmation (R4).
      return
    }
    if (!changeStillBound(preview.normalized_change)) return
    previewData.value = preview
    previewBinding = { seq, configVersion }
    pendingRequestId = crypto.randomUUID()
  } catch (err) {
    if (seq !== inputSeq) {
      // A stale answer never clobbers newer input or a newer confirmation;
      // a moved configuration still refreshes the context.
      if (
        err instanceof ApiError &&
        (err.code === 'CONFIG_VERSION_CONFLICT' ||
          err.code === 'CONFIG_PREVIEW_STALE')
      ) {
        requestReload()
      }
      return
    }
    handleConfigError(err)
  } finally {
    previewing.value = false
  }
}

async function previewTermChange(form: TermForm): Promise<void> {
  await previewChange(termChange(form))
}

async function previewNewTerm(): Promise<void> {
  if (props.frozen) return
  if (!newTermName.value.trim() || newTermRange.value.length !== 2) {
    errorText.value = '请填写学期名称与起止日期'
    return
  }
  await previewChange({
    kind: 'term_create',
    name: newTermName.value,
    start_date: newTermRange.value[0],
    end_date: newTermRange.value[1],
  })
}

async function readPromotionTerms(): Promise<void> {
  if (props.frozen || readingPromotionTerms.value) return
  const status = collaborationPanelRef.value?.currentStatus?.()
  const teacher = status?.teacher
  if (status?.connected !== true || !teacher) {
    promotionTermNotice.value = ''
    errorText.value = '请先连接在线班级，再读取园所学期名称'
    return
  }
  if (previewData.value || pendingConfirm.value || queuedConfirm.value) {
    errorText.value = '请先处理当前预览或未定提交，再读取园所学期名称'
    return
  }
  const identity = `${teacher.teacher_id}:${teacher.school_id}`
  const generation = promotionReadGeneration
  const startSeq = inputSeq
  const previewToken = (previewData.value as ConfigPreview | null)?.preview_token ?? ''
  const originalNames = new Map(
    termForms.value.map((form) => [form.id, form.name]),
  )
  readingPromotionTerms.value = true
  errorText.value = ''
  promotionTermNotice.value = ''
  try {
    const overview = await createCollaborationApi().getPromotion()
    const currentStatus = collaborationPanelRef.value?.currentStatus?.()
    const currentTeacher = currentStatus?.teacher
    const currentIdentity = currentTeacher
      ? `${currentTeacher.teacher_id}:${currentTeacher.school_id}`
      : ''
    if (
      generation !== promotionReadGeneration
      || props.frozen
      || inputSeq !== startSeq
      || ((previewData.value as ConfigPreview | null)?.preview_token ?? '') !== previewToken
      || currentStatus?.connected !== true
      || currentIdentity !== identity
    ) {
      if (generation === promotionReadGeneration && !props.frozen) {
        promotionTermNotice.value =
          '在线连接或当前表单已变化，本次读取结果已忽略；未修改当前表单。'
      }
      return
    }
    const terms = Array.isArray(overview.terms) ? overview.terms : []
    promotionTerms.value = terms
    if (terms.length === 0) {
      promotionTermNotice.value = '园所当前没有可读取的学期名称；未修改当前表单。'
      return
    }
    let filled = 0
    let parsed = 0
    let missing = 0
    let ambiguous = 0
    for (const form of termForms.value) {
      if (form.name !== originalNames.get(form.id)) {
        parsed += 1
        continue
      }
      const matches = terms.filter(
        (term) =>
          term.start_date === form.start_date
          && term.end_date === form.end_date,
      )
      if (matches.length === 0) {
        missing += 1
        continue
      }
      if (matches.length > 1) {
        ambiguous += 1
        continue
      }
      const original = currentTerm(form.id)
      if (!form.name.trim() || form.name === original?.name) {
        form.name = matches[0].name
        filled += 1
      } else {
        parsed += 1
      }
    }
    if (filled === 0) {
      if (parsed > 0) {
        promotionTermNotice.value =
          '已读取园所学期名称；当前表单已有自定义名称，未覆盖。本操作未提交修改。'
      } else if (ambiguous > 0) {
        promotionTermNotice.value =
          '园所学期存在起止日期完全相同的多条记录，未自动填入；本操作未提交修改。'
      } else {
        promotionTermNotice.value =
          '未找到起止日期完全一致的园所学期；未修改当前表单，也未提交修改。'
      }
      return
    }
    const extras = [
      parsed > 0 ? `${parsed} 个自定义名称保留` : '',
      missing > 0 ? `${missing} 个学期没有日期匹配` : '',
      ambiguous > 0 ? `${ambiguous} 个学期有多条同日期记录` : '',
    ].filter(Boolean)
    promotionTermNotice.value =
      `已读取园所学期名称，填入 ${filled} 个当前表单`
      + (extras.length ? `；${extras.join('，')}` : '')
      + '。请核对后自行预览并确认，本操作未提交修改。'
  } catch (exc) {
    errorText.value = exc instanceof ApiError
      ? exc.message
      : '读取园所学期名称失败，请检查在线连接后重试'
  } finally {
    readingPromotionTerms.value = false
  }
}

async function previewOverride(): Promise<void> {
  if (props.frozen) return
  if (!overrideDate.value) {
    errorText.value = '请选择日期'
    return
  }
  await previewChange({
    kind: 'calendar_override',
    term_id: overrideTermId.value,
    date: overrideDate.value,
    state: overrideState.value === 'none' ? null : overrideState.value,
    reason: overrideState.value === 'none' ? null : overrideReason.value,
  })
}

/**
 * One-click ordinary confirm: preview and then apply inside the same teacher
 * action. The preview passes the same input/context/frozen binding as the
 * two-step flow; only then is its token used for apply.
 */
async function confirmChange(change: ConfigChange, submit: () => ConfigChange = () => change): Promise<void> {
  if (props.frozen || pendingConfirm.value) return
  if (awaitingContextVersion.value !== null) {
    queuedConfirm.value = { change, submit }
    errorText.value =
      '上一项已提交，正在等最新配置读取完成：期间不会提交已知过期版本。'
    requestContextReload(awaitingContextVersion.value)
    return
  }
  if (previewing.value || applying.value) return
  const seq = inputSeq
  const configVersion = props.context.config_version
  previewing.value = true
  errorText.value = ''
  applyResultText.value = ''
  try {
    const preview = await apiPost<ConfigPreview>('/api/local/config/preview', {
      expected_config_version: configVersion,
      change,
    })
    if (
      props.frozen ||
      seq !== inputSeq ||
      configVersion !== props.context.config_version ||
      !changeStillBound(preview.normalized_change)
    ) {
      return
    }
    if (!preview.changed) {
      ElMessage.info('没有实际修改')
      return
    }
    const submitted = submit()
    const requestId = crypto.randomUUID()
    const body = {
      request_id: requestId,
      expected_config_version: preview.expected_config_version,
      change: preview.normalized_change,
      preview_token: preview.preview_token,
    }
    pendingConfirm.value = {
      requestId,
      expectedVersion: preview.expected_config_version,
      body,
      change: preview.normalized_change,
      submitted,
    }
    previewing.value = false
    await submitPendingConfirm()
  } catch (err) {
    if (seq !== inputSeq) {
      if (
        err instanceof ApiError &&
        (err.code === 'CONFIG_VERSION_CONFLICT' || err.code === 'CONFIG_PREVIEW_STALE')
      ) {
        requestReload()
      }
      return
    }
    handleConfigError(err)
  } finally {
    previewing.value = false
  }
}
/** Send the frozen body (first attempt or the explicit same-request retry). */
async function submitPendingConfirm(): Promise<void> {
  const pending = pendingConfirm.value
  if (!pending || applying.value) return
  applying.value = true
  errorText.value = ''
  try {
    const result = await apiPost<ConfigApplyResult>(
      '/api/local/config/apply',
      pending.body,
    )
    finishPendingConfirm(pending, result)
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      errorText.value =
        '提交结果未知：可查询提交回执，或用同一请求再次提交。原始请求内容保持不变。'
      return
    }
    pendingConfirm.value = null
    handleConfigError(err)
  } finally {
    applying.value = false
  }
}

/** Explicit retry of the unresolved request, with the same id and body. */
async function retryPendingConfirm(): Promise<void> {
  if (props.frozen || !pendingConfirm.value || applying.value) return
  await submitPendingConfirm()
}
/** Existing receipt query: resolve or prove missing for the frozen request. */
async function queryPendingConfirm(): Promise<void> {
  const pending = pendingConfirm.value
  if (!pending || applying.value) return
  applying.value = true
  errorText.value = ''
  try {
    const result = await apiGet<ConfigApplyResult>(
      `/api/local/config/operations/${pathSegment(pending.requestId)}`,
    )
    if (
      !result ||
      result.request_id !== pending.requestId ||
      (result.status !== 'applied' && result.status !== 'unchanged') ||
      typeof result.config_version !== 'number'
    ) {
      errorText.value =
        '回执与原始请求不一致或格式不可用：原请求仍未确认，不能用它改写或丢弃。'
      return
    }
    finishPendingConfirm(pending, result)
  } catch (err) {
    if (err instanceof ApiError && err.code === 'CONFIG_OPERATION_NOT_FOUND') {
      errorText.value =
        '尚未查到该提交的回执：不能用新请求代替；请保留原请求并明确重试或稍后再查。'
      return
    }
    errorText.value =
      '回执查询失败：原请求仍未确认；请查询或使用同一请求再次提交。'
  } finally {
    applying.value = false
  }
}


/** Run the queued ordinary confirm only after the committed version is read. */
async function runQueuedConfirm(queued: { change: ConfigChange; submit: () => ConfigChange }): Promise<void> {
  await confirmChange(queued.change, queued.submit)
}

/** Manual recovery for a failed configuration re-read; drafts stay intact. */
function retryContextRead(): void {
  if (props.frozen) return
  contextReloadFailed.value = false
  awaitContextVersionOnManualRead()
}
function finishPendingConfirm(pending: PendingConfirm, result: ConfigApplyResult): void {
  if (pendingConfirm.value !== pending) return
  pendingConfirm.value = null
  applyResultText.value = describeApplyResult(result)
  if (
    result.status === 'applied' &&
    result.config_version === pending.expectedVersion + 1
  ) {
    committedConfigVersion.value = {
      from: pending.expectedVersion,
      to: result.config_version,
    }
  }
  pendingAppliedMerge = {
    change: pending.change,
    submitted: pending.submitted,
  }
  clearPreview()
  requestContextReload(result.config_version)
}
function termChange(form: TermForm): ConfigChange {
  const change: ConfigChange = {
    kind: 'term_update',
    term_id: form.id,
    name: form.name,
    start_date: form.start_date,
    end_date: form.end_date,
  }
  return change
}

function currentTermChange(form: TermForm): ConfigChange | null {
  return currentChangeFor(termChange(form))
}

async function confirmTermChange(form: TermForm): Promise<void> {
  await confirmChange(termChange(form), () => currentTermChange(form) ?? termChange(form))
}

async function confirmNewTerm(): Promise<void> {
  if (props.frozen || pendingConfirm.value) return
  if (!newTermName.value.trim() || newTermRange.value.length !== 2) {
    errorText.value = '请填写学期名称与起止日期'
    return
  }
  const change: ConfigChange = {
    kind: 'term_create',
    name: newTermName.value,
    start_date: newTermRange.value[0],
    end_date: newTermRange.value[1],
  }
  await confirmChange(
    change,
    () => currentChangeFor(change) ?? change,
  )
}
function handleConfigError(err: unknown): void {
  if (err instanceof ApiError) {
    if (err.code === 'CONFIG_VERSION_CONFLICT') {
      errorText.value = '配置已被其他操作更新：已重新读取最新配置，请重新预览确认'
      requestReload()
      clearPreview()
      return
    }
    if (err.code === 'CONFIG_PREVIEW_STALE') {
      errorText.value = '确认对象已变化：请重新预览并确认'
      requestReload()
      clearPreview()
      return
    }
    if (err.code === 'CONFIG_PREVIEW_EXPIRED') {
      errorText.value = '预览已过期：请重新预览并确认'
      clearPreview()
      return
    }
    errorText.value = err.message
    return
  }
  errorText.value = `操作失败：${String(err)}`
}

async function applyPreview(): Promise<void> {
  if (props.frozen) return
  const preview = previewData.value
  if (!preview || applying.value) return
  if (!preview.changed) {
    // changed=false previews are closed by the UI without calling apply.
    ElMessage.info('没有实际修改')
    clearPreview()
    return
  }
  // Re-check the binding before committing: the confirmation must still
  // correspond to the current inputs and configuration version (R4).
  if (
    !previewBinding ||
    previewBinding.configVersion !== props.context.config_version ||
    previewBinding.seq !== inputSeq ||
    !changeStillBound(preview.normalized_change)
  ) {
    errorText.value = '预览对应的输入已变化：已清除旧确认，请重新预览后再确认'
    clearPreview()
    return
  }
  const submitted = currentChangeFor(preview.normalized_change)
  applying.value = true
  errorText.value = ''
  try {
    const result = await apiPost<ConfigApplyResult>('/api/local/config/apply', {
      request_id: pendingRequestId,
      expected_config_version: preview.expected_config_version,
      change: preview.normalized_change,
      preview_token: preview.preview_token,
    })
    applyResultText.value = describeApplyResult(result)
    // The game panel stays mounted with the old cached class-games snapshot
    // while the context reload is still in flight. A successful ordinary
    // setting apply is a known local commit, so it can advance that cached
    // version without a class-games re-read. Only the exact adjacent commit
    // is shared; any external change still has to conflict on preview.
    if (
      result.status === 'applied' &&
      result.config_version === preview.expected_config_version + 1
    ) {
      committedConfigVersion.value = {
        from: preview.expected_config_version,
        to: result.config_version,
      }
    }
    // Only the fields of this change are rebased once the fresh context
    // lands; other drafts and inputs typed during the apply are preserved.
    pendingAppliedMerge = {
      change: preview.normalized_change,
      submitted: submitted ?? preview.normalized_change,
    }
    clearPreview()
    requestReload()
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) {
      // The result is unclear: keep the SAME request id; retrying consults
      // the committed receipt first (spec §10.2).
      errorText.value =
        '提交结果未知：可再次点击确认，应用会先查询提交回执（同一请求 ID）。'
      return
    }
    handleConfigError(err)
  } finally {
    applying.value = false
  }
}

function describeApplyResult(result: ConfigApplyResult): string {
  if (result.status === 'unchanged') return '无实际修改：未产生新配置版本。'
  const parts = [`配置已提交（新配置版本 ${result.config_version}）`]
  if (result.affected_plan_ids.length) {
    parts.push(`${result.affected_plan_ids.length} 条已保存计划保留原表头，不会改写`)
  }
  if (result.calendar_revision_id) {
    parts.push('已生成新日历修订')
  }
  return parts.join('；')
}

function beforeAfterText(): string[] {
  const preview = previewData.value
  if (!preview) return []
  const lines: string[] = []
  const format = (value: Record<string, unknown> | null): string =>
    value === null
      ? '（无）'
      : Object.entries(value)
          .map(([key, item]) => `${key}=${item === null ? '（空）' : String(item)}`)
          .join('，')
  if (preview.before || preview.after) {
    lines.push(`修改前：${format(preview.before)}`)
    lines.push(`修改后：${format(preview.after)}`)
  }
  return lines
}

function termById(termId: string) {
  return props.context.terms.find((term) => term.id === termId) ?? null
}

function backToWorkbench(): void {
  if (props.frozen || pendingConfirm.value || awaitingContextVersion.value !== null) {
    errorText.value =
      '提交结果或最新配置尚未确认：请完成回执处理与配置重读后再离开。'
    return
  }
  emit('leave', () => 'left')
}

onMounted(() => {
  // Verification hook for the packaged selftest driver: real state and real
  // preview/apply operations only.
  ;(window as unknown as { __d1Settings?: object }).__d1Settings = {
    draftActive: () => draftActive.value,
    previewVisible: () => previewData.value !== null,
    previewChanged: () => previewData.value?.changed ?? null,
    errorText: () => errorText.value,
    applyResult: () => applyResultText.value,
    /** Input version: increments when a change invalidates old previews. */
    inputVersion: () => inputSeq,
    setProfile: (name: string, school: string) => {
      profileName.value = name
      schoolName.value = school
    },
    setClassDraft: (name: string) => {
      className.value = name
    },
    classDraft: () => className.value,
    previewProfile: () => previewChange(changeProfile()),
    applyPreview: () => applyPreview(),
    confirmProfile: () => confirmChange(changeProfile()),
    pendingConfirm: () => pendingConfirm.value !== null,
    queryPendingConfirm: () => queryPendingConfirm(),
    retryPendingConfirm: () => retryPendingConfirm(),
    awaitingContextVersion: () => awaitingContextVersion.value,
    queuedConfirm: () => queuedConfirm.value !== null,
    contextReloadFailed: () => contextReloadFailed.value,
    retryContextRead: () => retryContextRead(),
    draftTargets: () => draftTargets(),
    focusTarget: (target: SettingsDraftTarget) => focusTarget(target),
    cancelDraft: () => cancelDraft(),
    back: () => backToWorkbench(),
  }
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Settings?: object }).__d1Settings
})

function cancelDraft(): void {
  if (pendingConfirm.value || awaitingContextVersion.value !== null) {
    errorText.value =
      '提交结果或最新配置尚未确认：先完成回执处理与配置重读，不能取消丢弃原请求或草稿。'
    return
  }
  if (props.frozen) return
  profileName.value = confirmedContext.value.profile?.display_name ?? ''
  schoolName.value = confirmedContext.value.school_name ?? ''
  className.value = confirmedContext.value.class?.name ?? ''
  classGrade.value = confirmedContext.value.class?.grade ?? 'middle'
  headerTeacherNamesText.value = (
    confirmedContext.value.class?.header_teacher_names ?? []
  ).join('\n')
  caregiverName.value = confirmedContext.value.class?.caregiver_name ?? ''
  termForms.value = confirmedContext.value.terms.map((term) => ({
    id: term.id,
    name: term.name,
    start_date: term.start_date,
    end_date: term.end_date,
  }))
  newTermName.value = ''
  newTermRange.value = []
  overrideDate.value = ''
  overrideReason.value = ''
  clearPreview()
  errorText.value = ''
  applyResultText.value = ''
  ElMessage.info('已取消编辑，未应用任何修改')
}
/** Ordered structured targets for the current blocking draft (no parsing). */
function draftTargets(): SettingsDraftTarget[] {
  const targets: SettingsDraftTarget[] = []
  const confirmed = confirmedContext.value
  if (
    profileName.value !== (confirmed.profile?.display_name ?? '') ||
    schoolName.value !== (confirmed.school_name ?? '')
  ) targets.push({ kind: 'profile' })
  if (
    className.value !== (confirmed.class?.name ?? '') ||
    classGrade.value !== (confirmed.class?.grade ?? 'middle') ||
    parsedHeaderTeacherNames(headerTeacherNamesText.value).join('\n') !==
      (confirmed.class?.header_teacher_names ?? []).join('\n') ||
    (caregiverName.value.trim() || '') !== (confirmed.class?.caregiver_name ?? '')
  ) targets.push({ kind: 'class' })
  for (const form of termForms.value) {
    const term = confirmed.terms.find((item) => item.id === form.id)
    if (
      !term ||
      form.name !== term.name ||
      form.start_date !== term.start_date ||
      form.end_date !== term.end_date
    ) targets.push({ kind: 'term', id: form.id })
  }
  if (newTermName.value || newTermRange.value.length === 2) targets.push({ kind: 'new-term' })
  if (overrideDate.value || overrideReason.value) targets.push({ kind: 'override' })
  if (pendingConfirm.value) targets.push({ kind: 'pending-confirm' })
  if (awaitingContextVersion.value !== null || contextReloadFailed.value) {
    targets.push({ kind: 'context-read' })
  }
  if (previewData.value) targets.push({ kind: 'preview' })
  for (const target of aiPanelRef.value?.draftTargets?.() ?? []) {
    if (!targets.some((item) => item.kind === target)) targets.push({ kind: target })
  }
  if (gamePanelRef.value?.draftTargets?.().includes('game-config')) {
    targets.push({ kind: 'game-config' })
  }
  if (
    collaborationDraftActive.value
    || collaborationPanelRef.value?.draftTargets?.().includes('online-collaboration')
  ) {
    targets.push({ kind: 'online-collaboration' })
  }
  return targets
}

const FOCUS_SELECTORS: Record<SettingsDraftTargetKind, string> = {
  profile: '[data-d1="settings-profile-name"]',
  class: '[data-d1="settings-class-name"]',
  term: '[data-d1="term-row"] .term-name input',
  'new-term': '[data-d1="new-term-name"]',
  override: '[data-d1="override-date"]',
  preview: '[data-d1="settings-preview"]',
  'pending-confirm': '[data-d1="settings-pending-confirm"]',
  'context-read': '[data-d1="settings-context-pending"]',
  'ai-config': '[data-d1="ai-base-url"]',
  'ai-prompts': '[data-d1="ai-prompts"]',
  'game-config': '[data-d1="game-config"]',
  'online-collaboration': '[data-d1="collaboration"]',
}

/**
 * Online collaboration has several actionable regions.  Pending receipts must
 * win: connected -> query controls; disconnected -> the normal one-time code
 * input (the manual credential remains an explicit backup); otherwise focus
 * the explicit preview/publish area.
 */
function collaborationFocusSelector(
  pending: boolean,
  promotionPending: boolean,
  connected: boolean,
): string | null {
  if (!pending && !promotionPending) return null
  if (!connected) return '[data-d1="collaboration-redeem-code"]'
  return promotionPending
    ? '[data-d1="collaboration-query-promotion"]'
    : '[data-d1="collaboration-pending-actions"] button'
}

function openDetailsAncestors(element: Element | null): void {
  let node: Element | null = element
  while (node) {
    if (node.tagName === 'DETAILS') {
      ;(node as HTMLDetailsElement).open = true
    }
    node = node.parentElement
  }
}

function focusCollaborationDraft(): void {
  if (typeof document === 'undefined') return
  const pending = Boolean(collaborationPanelRef.value?.pendingWrite?.())
  const promotionPending = Boolean(
    collaborationPanelRef.value?.pendingPromotion?.(),
  )
  const connected = collaborationPanelRef.value?.currentStatus?.()?.connected === true
  const pendingSelector = collaborationFocusSelector(
    pending,
    promotionPending,
    connected,
  )
  let selector = pendingSelector ?? '[data-d1="collaboration"]'
  if (!pendingSelector && document.querySelector('[data-d1="collaboration-class-unknown"]')) {
    selector = '[data-d1="collaboration-class-unknown"]'
  } else if (collaborationPanelRef.value?.promotionStale?.()) {
    selector = '[data-d1="collaboration-promotion-form"]'
  } else if (collaborationPanelRef.value?.currentPreview?.()) {
    selector = '[data-d1="collaboration-preview"]'
  } else if (collaborationPanelRef.value?.currentPublishPreview?.()) {
    selector = '[data-d1="collaboration-publish-preview"]'
  }
  const element = document.querySelector(selector) as HTMLElement | null
  if (!element) return
  openDetailsAncestors(element)
  element.scrollIntoView?.({ block: 'center' })
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus?.()
}

/** Focus one structured target in this same instance; never remounts. */
async function focusTarget(target: SettingsDraftTarget): Promise<void> {
  if (target.kind === 'online-collaboration') {
    setSettingsSection('collaboration')
    await nextTick()
    if (typeof document !== 'undefined') {
      openDetailsAncestors(
        document.querySelector('[data-d1="collaboration"]'),
      )
      await nextTick()
      focusCollaborationDraft()
    }
    return
  }

  setSettingsSection('main')
  const group = TARGET_GROUPS[target.kind]
  if (group) expandedGroups[group] = true
  await nextTick()

  if (target.kind === 'ai-config' || target.kind === 'ai-prompts') {
    aiPanelRef.value?.focusDraftTarget?.(target.kind)
    return
  }
  if (target.kind === 'game-config') {
    gamePanelRef.value?.focusDraftTarget?.()
    return
  }
  if (typeof document === 'undefined') return

  const selector =
    target.kind === 'term'
      ? target.id
        ? `[data-d1="term-row"][data-term-id="${CSS.escape(target.id)}"] .term-name input`
        : '[data-d1="term-row"] .term-name input'
      : FOCUS_SELECTORS[target.kind]
  const element = selector
    ? (document.querySelector(selector) as HTMLElement | null)
    : null
  if (!element) return
  openDetailsAncestors(element)
  await nextTick()
  element.scrollIntoView?.({ block: 'center' })
  if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '-1')
  element.focus?.()
}

/** The App-facing projection of the current blocking state. */
function draftBlockingTargets(): SettingsDraftTarget[] {
  return draftTargets()
}

defineExpose({
  draftTargets,
  focusTarget,
  openCollaborationSection,
  openMainSection,
  collaborationFocusSelector,
})
</script>

<template>
  <div
    class="settings"
    :class="{ 'settings-collaboration-mode': activeSection === 'collaboration' }"
  >
    <div v-if="activeSection === 'collaboration'" class="toolbar focus-toolbar">
      <div>
        <h2>在线协作</h2>
        <p class="muted">
          输入管理员发的一次性码，连接后选择班级。
        </p>
      </div>
      <div class="actions">
        <el-button size="small" data-d1="settings-section-main" :disabled="frozen" @click="openMainSection">
          返回设置
        </el-button>
        <el-button size="small" data-d1="back-workbench" :disabled="frozen" @click="backToWorkbench">
          返回工作台
        </el-button>
      </div>
    </div>

    <div :hidden="activeSection !== 'main'" class="settings-main">
      <div class="toolbar">
        <h2>设置</h2>
        <div class="actions">
          <el-button size="small" data-d1="back-workbench" :disabled="frozen" @click="backToWorkbench">
            返回工作台
          </el-button>
        </div>
      </div>

      <el-alert v-if="errorText" type="error" :closable="false" class="section" data-d1="settings-error" :title="errorText" />
      <el-alert v-if="applyResultText" type="success" :closable="false" class="section" data-d1="settings-applied" :title="applyResultText" />

      <el-card class="section" shadow="never" data-d1="settings-data-boundary">
        <template #header>本机与在线数据边界</template>
        <p class="muted">
          本机 SQLite：个人档案、学期与日历、日计划、观察、周计划和本地班级游戏配置只保存在本机。
        </p>
        <p class="muted">
          在线 MySQL：只保存园所／教师、班级关系、同班在线游戏配置和在线共享周。
        </p>
        <p class="muted">
          日计划共享与 AI 在线设置当前不同步；密钥和本机档案不会上传。
        </p>
      </el-card>

      <el-card class="section" shadow="never" data-d1="settings-profile">
        <template #header>姓名与园所</template>
        <div class="fields">
          <div class="field">
            <label>姓名</label>
            <el-input v-model="profileName" maxlength="80" :disabled="frozen" data-d1="settings-profile-name" />
          </div>
          <div class="field">
            <label>园所名称（可清空）</label>
            <el-input v-model="schoolName" maxlength="120" :disabled="frozen" data-d1="settings-school" />
          </div>
          <el-button data-d1="preview-profile" data-d1-confirm="confirm-profile" type="primary" :loading="previewing || applying" :disabled="frozen || !!pendingConfirm || awaitingContextVersion !== null" @click="confirmChange(changeProfile())">
            确认修改
          </el-button>
        </div>
      </el-card>

      <el-card class="section" shadow="never" data-d1="settings-current-class">
        <template #header>当前本地班级</template>
        <p class="muted" data-d1="settings-class-summary">
          当前：{{ className || '（未填写班级名称）' }} · {{ GRADE_LABELS[classGrade] }}
        </p>
        <div class="fields">
          <div class="field">
            <label>班级名称</label>
            <el-input v-model="className" maxlength="80" :disabled="frozen" data-d1="settings-class-name" />
          </div>
          <div class="field">
            <label>年级</label>
            <el-select v-model="classGrade" class="class-grade-select" :disabled="frozen" data-d1="settings-class-grade">
              <el-option label="小班" value="small" />
              <el-option label="中班" value="middle" />
              <el-option label="大班" value="large" />
            </el-select>
          </div>
          <div class="field field-wide">
            <label>班级教师姓名（每行一个，可留空；顺序和同名保留）</label>
            <el-input
              v-model="headerTeacherNamesText"
              type="textarea"
              :rows="3"
              :disabled="frozen"
              data-d1="settings-class-teachers"
            />
          </div>
          <div class="field">
            <label>保育员姓名（可清空）</label>
            <el-input
              v-model="caregiverName"
              maxlength="80"
              :disabled="frozen"
              data-d1="settings-class-caregiver"
            />
          </div>
          <el-button data-d1="confirm-class" type="primary" :loading="previewing || applying" :disabled="frozen || !!pendingConfirm || awaitingContextVersion !== null" @click="confirmChange(changeClass())">
            确认修改
          </el-button>
        </div>
      </el-card>

      <el-card class="section" shadow="never" data-d1="settings-current-term">
        <template #header>当前学期</template>
        <template v-if="activeLocalTerm">
          <p>
            <strong>{{ activeLocalTerm.name }}</strong>
          </p>
          <p class="muted">
            {{ activeLocalTerm.start_date }} ~ {{ activeLocalTerm.end_date }}（本地当前学期）
          </p>
        </template>
        <p v-else class="muted">
          当前没有生效学期（休假或学期之间）。可在下方「其他学期与新建」中维护。
        </p>
      </el-card>

      <el-card class="section" shadow="never" data-d1="settings-open-collaboration-card">
        <template #header>在线协作</template>
        <p class="muted">
          在线发布、加入/恢复、选班和升班与本地设置相互独立，不会自动上传本机配置。
        </p>
        <el-button data-d1="settings-open-collaboration" :disabled="frozen" @click="openCollaborationSection">
          打开在线协作
        </el-button>
      </el-card>

      <el-card v-if="previewData" class="section" shadow="never" data-d1="settings-preview">
        <template #header>
          <div class="preview-head">
            <span>影响预览（确认后才会应用）</span>
            <el-tag size="small" :type="previewData.changed ? 'warning' : 'info'">
              {{ previewData.changed ? '有实际修改' : '无实际修改' }}
            </el-tag>
          </div>
        </template>
        <p v-for="(line, index) in beforeAfterText()" :key="index">{{ line }}</p>
        <div v-if="previewData.calendar_diff.length" class="diff-block">
          <h4>日期变化（前 {{ previewData.calendar_diff.length }} 项）</h4>
          <el-table :data="previewData.calendar_diff.slice(0, 60)" size="small">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column label="状态" width="180">
              <template #default="{ row }">
                {{ STATE_LABELS[row.before_state] || row.before_state }} →
                {{ STATE_LABELS[row.after_state] || row.after_state }}
              </template>
            </el-table-column>
            <el-table-column label="周次" width="120">
              <template #default="{ row }">
                {{ row.before_week ?? '—' }} → {{ row.after_week ?? '—' }}
              </template>
            </el-table-column>
            <el-table-column label="例外">
              <template #default="{ row }">
                {{ row.override_before ? `${STATE_LABELS[row.override_before.state] || row.override_before.state}（${row.override_before.reason}）` : '—' }}
                →
                {{ row.override_after ? `${STATE_LABELS[row.override_after.state] || row.override_after.state}（${row.override_after.reason}）` : '—' }}
              </template>
            </el-table-column>
          </el-table>
          <p v-if="previewData.calendar_diff.length > 60" class="muted">
            仅显示前 60 项，共 {{ previewData.calendar_diff.length }} 项。
          </p>
        </div>
        <div class="impact-block">
          <h4>
            已有日计划影响：保留旧表头 {{ previewData.impact.retained_header_count }} 条；本次涉及变化
            {{ previewData.impact.affected_plans.length }} 条
          </h4>
          <el-table
            v-if="previewData.impact.affected_plans.length"
            :data="previewData.impact.affected_plans"
            size="small"
            data-d1="impact-plans"
          >
            <el-table-column prop="plan_date" label="日期" width="110" />
            <el-table-column prop="content_version" label="内容版本" width="90" />
            <el-table-column label="存储周次 → 新解释" width="150">
              <template #default="{ row }">
                {{ row.stored_week_number ?? '—' }} → {{ row.proposed_week_number ?? '—' }}
              </template>
            </el-table-column>
            <el-table-column label="原因">
              <template #default="{ row }">
                {{ impactReasonTextList(row.reasons, DAILY_IMPACT_REASON_LABELS) }}
              </template>
            </el-table-column>
            <el-table-column label="之后可否新建" width="110">
              <template #default="{ row }">
                {{ row.creation_eligible_after ? '可以' : '不可以' }}
              </template>
            </el-table-column>
          </el-table>
          <p v-else class="muted">本条修改不影响任何已保存日计划的日期解释。</p>
          <h4 class="weekly-impact-head">
            已有周计划影响：保留旧表头 {{ previewData.impact.weekly_retained_header_count }} 条；相关周
            {{ previewData.impact.weekly_plans.length }} 条
          </h4>
          <el-table
            v-if="previewData.impact.weekly_plans.length"
            :data="previewData.impact.weekly_plans"
            size="small"
            data-d1="impact-weekly-plans"
          >
            <el-table-column prop="week_anchor_date" label="固定周锚点" width="120" />
            <el-table-column prop="week_number_snapshot" label="创建周次" width="90" />
            <el-table-column label="创建学期" width="220">
              <template #default="{ row }">
                {{ row.term_start_date }} ~ {{ row.term_end_date }}
              </template>
            </el-table-column>
            <el-table-column label="版本" width="130">
              <template #default="{ row }">
                草稿 v{{ row.current_draft_version }} / 确认
                {{ row.current_confirmed_version ?? '—' }}
              </template>
            </el-table-column>
            <el-table-column label="之后可否新建该周" width="140">
              <template #default="{ row }">
                {{ row.creation_eligible_after ? '可以' : '不可以' }}
              </template>
            </el-table-column>
            <el-table-column label="原因">
              <template #default="{ row }">
                {{ impactReasonTextList(row.reasons, WEEKLY_IMPACT_REASON_LABELS) }}
              </template>
            </el-table-column>
          </el-table>
          <p v-else class="muted">本条修改不涉及已保存的周计划。</p>
          <p class="muted">
            已保存计划仍可查看、编辑、确认与导出；日计划保留归属、周次、创建日历修订与表头，
            周计划保留固定周锚点、创建学期／周次／日历与表头，不会按当前学期重排。
          </p>
        </div>
        <div class="row">
          <el-button data-d1="apply-preview" type="primary" :loading="applying" :disabled="frozen" @click="applyPreview">
            确认应用
          </el-button>
          <el-button data-d1="cancel-preview" :disabled="applying || frozen" @click="clearPreview">
            取消预览
          </el-button>
        </div>
      </el-card>

      <el-card v-if="awaitingContextVersion !== null || contextReloadFailed" class="section" shadow="never" data-d1="settings-context-pending">
        <template #header>最新配置读取中</template>
        <p class="muted">
          <template v-if="contextReloadFailed">
            最新配置读取失败：所有草稿仍保留，页面不会提交已知过期版本。
          </template>
          <template v-else>
            上一项已提交，正在等待最新配置版本 {{ awaitingContextVersion }} 读取到位；期间不会提交新修改，草稿和输入保持不变。
          </template>
        </p>
        <el-button data-d1="retry-context-read" :disabled="frozen" @click="retryContextRead">
          重新读取配置
        </el-button>
      </el-card>

      <el-card v-if="pendingConfirm" class="section" shadow="never" data-d1="settings-pending-confirm">
        <template #header>提交结果未确认</template>
        <p class="muted">
          已提交的原始请求仍保持不变，页面不能离开、取消或改写它。请先核对回执；未找到回执时可明确用同一请求再次提交。
        </p>
        <div class="row">
          <el-button data-d1="query-pending-confirm" :loading="applying" :disabled="applying" @click="queryPendingConfirm">
            查询提交回执
          </el-button>
          <el-button data-d1="retry-pending-confirm" type="primary" :loading="applying" :disabled="applying || frozen" @click="retryPendingConfirm">
            用同一请求再次提交
          </el-button>
        </div>
      </el-card>

      <details
        class="settings-group"
        data-d1="settings-group-terms"
        :open="expandedGroups.terms"
        @toggle="onGroupToggle('terms', $event)"
      >
        <summary>其他学期与新建 <span class="muted">学期名称、起止日期、新建</span></summary>
        <el-card class="section group-card" shadow="never">
          <template #header>学期维护</template>
          <div class="row promotion-term-read">
            <el-button
              size="small"
              data-d1="settings-read-promotion-terms"
              :loading="readingPromotionTerms"
              :disabled="frozen || readingPromotionTerms"
              @click="readPromotionTerms"
            >
              读取园所学期名称
            </el-button>
            <span class="muted">仅在已连接在线班级时读取；只填入起止日期唯一匹配的名称，不提交修改。</span>
          </div>
          <el-alert
            v-if="promotionTermNotice"
            type="info"
            :closable="false"
            class="block"
            data-d1="settings-promotion-term-notice"
            :title="promotionTermNotice"
          />
          <div v-for="(form, index) in termForms" :key="form.id" class="term-row" data-d1="term-row" :data-term-id="form.id">
            <el-input v-model="form.name" maxlength="80" class="term-name" :disabled="frozen" />
            <el-date-picker
              v-model="form.start_date"
              type="date"
              value-format="YYYY-MM-DD"
              :clearable="false"
              :disabled="frozen"
              class="term-date"
            />
            <el-date-picker
              v-model="form.end_date"
              type="date"
              value-format="YYYY-MM-DD"
              :clearable="false"
              :disabled="frozen"
              class="term-date"
            />
            <el-button size="small" type="primary" :loading="previewing || applying" :disabled="frozen || !!pendingConfirm || awaitingContextVersion !== null" @click="confirmTermChange(form)">
              确认修改
            </el-button>

          </div>
          <div class="term-row new-term">
            <el-input v-model="newTermName" maxlength="80" placeholder="新学期名称" class="term-name" :disabled="frozen" data-d1="new-term-name" />
            <el-date-picker
              v-model="newTermRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始"
              end-placeholder="结束"
              :disabled="frozen"
            />
            <el-button size="small" data-d1="confirm-new-term" type="primary" :loading="previewing || applying" :disabled="frozen || !!pendingConfirm || awaitingContextVersion !== null" @click="confirmNewTerm">
              确认新增
            </el-button>
          </div>
          <p class="muted">学期闭区间不得重叠或共端点；修改起止日期会生成新的日历修订，已保存计划保留原周次。</p>
          <p class="muted" data-d1="settings-term-history-hint">修改学期名称不会更新旧记录；如需旧记录改用新学期名，请在游戏观察或本机周计划的历史记录中另存为当前学期名版本。</p>
        </el-card>
      </details>

      <details
        class="settings-group"
        data-d1="settings-group-calendar"
        :open="expandedGroups.calendar"
        @toggle="onGroupToggle('calendar', $event)"
      >
        <summary>日历例外 <span class="muted">逐日上课/停课、撤销例外</span></summary>
        <el-card class="section group-card" shadow="never">
          <template #header>日历例外（逐日配置）</template>
          <div class="fields">
            <div class="field">
              <label>学期</label>
              <el-select v-model="overrideTermId" :disabled="frozen" data-d1="override-term">
                <el-option
                  v-for="term in props.context.terms"
                  :key="term.id"
                  :label="`${term.name}（${term.start_date} ~ ${term.end_date}）`"
                  :value="term.id"
                />
              </el-select>
            </div>
            <div class="field">
              <label>日期</label>
              <el-date-picker
                v-model="overrideDate"
                type="date"
                value-format="YYYY-MM-DD"
                :clearable="false"
                :disabled="frozen"
                data-d1="override-date"
              />
            </div>
            <div class="field">
              <label>设置</label>
              <el-select v-model="overrideState" :disabled="frozen" data-d1="override-state">
                <el-option label="例外上课" value="teaching" />
                <el-option label="例外停课" value="non_teaching" />
                <el-option label="撤销例外" value="none" />
              </el-select>
            </div>
            <div v-if="overrideState !== 'none'" class="field">
              <label>原因（1–200 字）</label>
              <el-input v-model="overrideReason" maxlength="200" :disabled="frozen" data-d1="override-reason" />
            </div>
            <el-button data-d1="preview-override" :loading="previewing" :disabled="frozen" @click="previewOverride">
              预览修改
            </el-button>
          </div>
          <p v-if="overrideTerm" class="muted">
            当前学期范围：{{ overrideTerm.start_date }} ~ {{ overrideTerm.end_date }}；日期必须在该范围内。
          </p>
        </el-card>
      </details>

      <AiSettingsPanel ref="aiPanelRef" :frozen="frozen" @draft-active="(value: boolean) => (aiDraftActive = value)" />
      <details
        class="settings-group"
        data-d1="settings-group-games"
        :open="groupOpen('games')"
        @toggle="onGroupToggle('games', $event)"
      >
        <summary>班级游戏配置 <span class="muted">本地配置、来源带入与预览确认</span></summary>
        <GameConfigPanel
          ref="gamePanelRef"
          :frozen="frozen"
          :committed-config-version="committedConfigVersion"
          @draft-active="(value: boolean) => (gameDraftActive = value)"
          @applied="() => requestReload()"
        />
      </details>


      <details
        class="settings-group"
        data-d1="settings-group-backup"
        :open="expandedGroups.backup"
        @toggle="onGroupToggle('backup', $event)"
      >
        <summary>备份与恢复 <span class="muted">完整备份、校验、预览与恢复</span></summary>
        <el-card class="section group-card" shadow="never" data-d1="backup-restore">
          <template #header>备份与恢复</template>
          <p class="muted">
            创建完整本地备份，或从本地备份校验、预览并恢复。恢复前会自动保留完整保护副本。
          </p>
          <el-button data-d1="open-backup-restore" :disabled="frozen" @click="emit('open-maintenance')">
            创建备份 / 从备份恢复
          </el-button>
        </el-card>
      </details>

      <div class="section row">
        <el-button data-d1="cancel-draft" :disabled="frozen" @click="cancelDraft">取消编辑（还原当前配置）</el-button>
      </div>

      <details class="settings-group settings-about" data-d1="settings-group-about">
        <summary>版本与说明</summary>
        <div class="section">
          <el-tag size="small" type="info">配置版本 v{{ props.context.config_version }}</el-tag>
          <el-alert
            type="info"
            :closable="false"
            class="section"
            title="普通姓名、园所、班级和学期修改点一次「确认修改」即先预览后应用；日期例外与批量/游戏配置仍保留预览确认。已有计划保留原表头，不会被改写。"
          />
        </div>
      </details>
    </div>

    <div :hidden="activeSection !== 'collaboration'" class="settings-collaboration">
      <CollaborationPanel
        ref="collaborationPanelRef"
        :frozen="frozen"
        @draft-active="(value: boolean) => (collaborationDraftActive = value)"
      />
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.focus-toolbar {
  align-items: flex-start;
  gap: 16px;
}
.focus-toolbar h2 {
  margin-bottom: 4px;
}
.settings-main[hidden],
.settings-collaboration[hidden] {
  display: none !important;
}
.class-grade-select {
  width: 100%;
  min-width: 140px;
}
.settings-group {
  margin-top: 16px;
  border: 1px solid var(--kgm-border);
  border-radius: 8px;
  background: var(--el-bg-color);
}
.settings-group > summary {
  cursor: pointer;
  padding: 12px 16px;
  font-weight: 600;
  list-style-position: inside;
}
.settings-group[open] > summary {
  border-bottom: 1px solid var(--kgm-border);
}
.settings-group > summary .muted {
  margin-left: 8px;
  font-weight: 400;
}
.settings-group .group-card {
  margin-top: 0;
  border: 0;
  box-shadow: none;
}
.settings-about {
  margin-bottom: 16px;
}
.section {
  margin-top: 16px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.fields {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.field label {
  font-size: 0.85rem;
  color: var(--kgm-muted);
}
.term-row {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.term-name {
  width: 220px;
}
.term-date {
  width: 160px;
}
.new-term {
  border-top: 1px dashed var(--kgm-border);
  padding-top: 12px;
}
.preview-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.diff-block,
.impact-block {
  margin-top: 12px;
}
.weekly-impact-head {
  margin-top: 16px;
}
.row {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.85rem;
}
</style>
