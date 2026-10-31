<script setup lang="ts">
/**
 * Settings / configuration maintenance (D1 spec §10.2): profile, current
 * class, terms and per-day calendar overrides, all through the preview →
 * confirm → apply protocol. Every change shows its real before/after values,
 * the calendar diff and the complete impact facts (existing plans retain
 * their old headers and are listed, never rewritten); confirmed tokens are
 * never reused after an input change or a preview close.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { apiGet, apiPost, ApiError, pathSegment } from '../client'
import type {
  ConfigApplyResult,
  ConfigChange,
  ConfigPreview,
  LocalContext,
} from '../types'
import AiSettingsPanel from './AiSettingsPanel.vue'
import GameConfigPanel from './GameConfigPanel.vue'

const props = defineProps<{ context: LocalContext; frozen?: boolean }>()
const emit = defineEmits<{
  (e: 'reload-context'): Promise<LocalContext>
  (e: 'draft-active', active: boolean): void
  (e: 'leave', run: () => Promise<'left' | 'stayed'> | 'left' | 'stayed'): void
  (e: 'open-maintenance'): void
}>()

const GRADE_LABELS: Record<string, string> = { small: '小班', middle: '中班', large: '大班' }
const STATE_LABELS: Record<string, string> = {
  teaching: '上课',
  non_teaching: '停课',
  unknown: '未备年份',
  outside_term: '学期外',
}

const profileName = ref(props.context.profile?.display_name ?? '')
const schoolName = ref(props.context.school_name ?? '')
const className = ref(props.context.class?.name ?? '')
const classGrade = ref<'small' | 'middle' | 'large'>(
  props.context.class?.grade ?? 'middle',
)

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
const confirmedContext = ref<LocalContext>(props.context)
/** D2 W5: AI settings and class-game panels own their own unsaved drafts. */
const aiDraftActive = ref(false)
const gameDraftActive = ref(false)
let pendingRequestId = ''
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
 * The change applied but not yet reflected in the context: the reload merge
 * only rebases the fields that still carry the submitted values, keeping any
 * other drafts and inputs typed while the apply was in flight (R3).
 */
interface PendingApplied {
  change: ConfigChange
  submitted: ConfigChange
}
let pendingAppliedMerge: PendingApplied | null = null

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
  if (previewData.value) return true
  if (aiDraftActive.value || gameDraftActive.value) return true
  return false
})

watch(draftActive, (value) => emit('draft-active', value), { immediate: true })

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
    if (!form) return null
    return {
      kind: 'term_update',
      term_id: form.id,
      name: form.name,
      start_date: form.start_date,
      end_date: form.end_date,
    }
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
    const left = pageNormalize((current as Record<string, unknown>)[key])
    const right = pageNormalize(
      (normalizedChange as Record<string, unknown>)[key],
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
    confirmedContext.value = fresh
    clearPreview()
    const pending = pendingAppliedMerge
    if (pending) {
      pendingAppliedMerge = null
      mergeAppliedBaseline(fresh, pending)
      return
    }
    // No pending draft: safe to re-sync every field from the fresh context.
    if (!draftActive.value) syncFormsFrom(fresh)
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
  previewBinding = null
})

watch([profileName, schoolName, className, classGrade], () => clearPreview())
watch(termForms, () => clearPreview(), { deep: true })
watch([newTermName, newTermRange], () => clearPreview())
watch([overrideTermId, overrideDate, overrideState, overrideReason], () => clearPreview())

function requestReload(): void {
  emit('reload-context')
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
  }
}

async function previewChange(change: ConfigChange): Promise<void> {
  if (props.frozen) return
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
  await previewChange({
    kind: 'term_update',
    term_id: form.id,
    name: form.name,
    start_date: form.start_date,
    end_date: form.end_date,
  })
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
  if (props.frozen) return
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
    cancelDraft: () => cancelDraft(),
    back: () => backToWorkbench(),
  }
})

onBeforeUnmount(() => {
  delete (window as unknown as { __d1Settings?: object }).__d1Settings
})

function cancelDraft(): void {
  if (props.frozen) return
  profileName.value = confirmedContext.value.profile?.display_name ?? ''
  schoolName.value = confirmedContext.value.school_name ?? ''
  className.value = confirmedContext.value.class?.name ?? ''
  classGrade.value = confirmedContext.value.class?.grade ?? 'middle'
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
</script>

<template>
  <div class="settings">
    <div class="toolbar">
      <h2>设置与配置维护</h2>
      <div class="actions">
        <el-tag size="small" type="info">配置版本 v{{ props.context.config_version }}</el-tag>
        <el-button size="small" data-d1="back-workbench" :disabled="frozen" @click="backToWorkbench">
          返回工作台
        </el-button>
      </div>
    </div>

    <el-card class="section" shadow="never" data-d1="backup-restore">
      <template #header>备份与恢复</template>
      <p class="muted">
        创建完整本地备份，或从本地备份校验、预览并恢复。恢复前会自动保留完整保护副本。
      </p>
      <el-button data-d1="open-backup-restore" :disabled="frozen" @click="emit('open-maintenance')">
        创建备份 / 从备份恢复
      </el-button>
    </el-card>

    <el-alert
      type="info"
      :closable="false"
      class="section"
      title="所有修改都需要先预览影响并确认后才会应用；已有计划保留原表头，不会被改写。"
    />
    <el-alert v-if="errorText" type="error" :closable="false" class="section" data-d1="settings-error" :title="errorText" />
    <el-alert v-if="applyResultText" type="success" :closable="false" class="section" data-d1="settings-applied" :title="applyResultText" />

    <el-card class="section" shadow="never">
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
        <el-button data-d1="preview-profile" :loading="previewing" :disabled="frozen" @click="previewChange(changeProfile())">
          预览修改
        </el-button>
      </div>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header>当前班级（升班沿用同一班级）</template>
      <div class="fields">
        <div class="field">
          <label>班级名称</label>
          <el-input v-model="className" maxlength="80" :disabled="frozen" data-d1="settings-class-name" />
        </div>
        <div class="field">
          <label>年级</label>
          <el-select v-model="classGrade" :disabled="frozen" data-d1="settings-class-grade">
            <el-option label="小班" value="small" />
            <el-option label="中班" value="middle" />
            <el-option label="大班" value="large" />
          </el-select>
        </div>
        <el-button data-d1="preview-class" :loading="previewing" :disabled="frozen" @click="previewChange(changeClass())">
          预览修改
        </el-button>
      </div>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header>学期维护</template>
      <div v-for="(form, index) in termForms" :key="form.id" class="term-row" data-d1="term-row">
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
        <el-button size="small" :loading="previewing" :disabled="frozen" @click="previewTermChange(form)">
          预览修改
        </el-button>
      </div>
      <div class="term-row new-term">
        <el-input v-model="newTermName" maxlength="80" placeholder="新学期名称" class="term-name" :disabled="frozen" />
        <el-date-picker
          v-model="newTermRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始"
          end-placeholder="结束"
          :disabled="frozen"
        />
        <el-button size="small" data-d1="preview-new-term" :loading="previewing" :disabled="frozen" @click="previewNewTerm">
          预览新增
        </el-button>
      </div>
      <p class="muted">学期闭区间不得重叠或共端点；修改起止日期会生成新的日历修订，已保存计划保留原周次。</p>
    </el-card>

    <el-card class="section" shadow="never">
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
          已有计划影响：保留旧表头 {{ previewData.impact.retained_header_count }} 条；本次涉及变化
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
            <template #default="{ row }">{{ row.reasons.join('、') }}</template>
          </el-table-column>
          <el-table-column label="之后可否新建" width="110">
            <template #default="{ row }">
              {{ row.creation_eligible_after ? '可以' : '不可以' }}
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="muted">本条修改不影响任何已保存记录的日期解释。</p>
        <p class="muted">
          已保存计划仍可编辑与导出；其归属、周次、创建日历修订与表头不会被改写。
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

    <AiSettingsPanel :frozen="frozen" @draft-active="(value: boolean) => (aiDraftActive = value)" />
    <GameConfigPanel
      :frozen="frozen"
      @draft-active="(value: boolean) => (gameDraftActive = value)"
      @applied="() => requestReload()"
    />

    <div class="section row">
      <el-button data-d1="cancel-draft" :disabled="frozen" @click="cancelDraft">取消编辑（还原当前配置）</el-button>
    </div>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
  color: #606266;
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
  border-top: 1px dashed #ebeef5;
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
.row {
  display: flex;
  gap: 12px;
  margin-top: 12px;
}
.muted {
  color: #909399;
  font-size: 0.85rem;
}
</style>
