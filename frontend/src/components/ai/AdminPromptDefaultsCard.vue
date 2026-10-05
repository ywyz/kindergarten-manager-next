<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElAlert, ElButton, ElCard, ElInput, ElText } from 'element-plus'
import { auth } from '../../auth'
import * as api from '../../api'
import type { AiPromptDefaultOut, TaskStatusOut } from '../../types'
import {
  aiErrorNotice,
  changedGuidanceFields,
  createEpochGuard,
  taskDisplayName,
} from './ai-settings-shared'

// Admin-only panel for system default guidance. It edits TEXT ONLY: field
// sets, contract versions and protocols come from the server and have no
// editing entry here. State is separate from the admin's own personal
// guidance card (which never shows this panel's data and vice versa).
//
// Per-task in-memory drafts survive task switches (R6): switching away and
// back never silently discards text, and re-clicking the current task
// neither resets nor re-fetches over the draft. During an in-flight publish
// the editors are locked (explicit choice per spec) so later typing cannot
// be overwritten by the response. Nothing is persisted.

type Notice = { type: 'error' | 'warning' | 'success' | 'info'; text: string }

interface AdminTaskState {
  detail: AiPromptDefaultOut
  draft: Record<string, string>
  // T2: the pending conflict and its freshest comparison data belong to the
  // TASK, not the card — re-selecting the current task or A→B→A must keep
  // the gate and the view until the user explicitly picks 载入最新/保留输入.
  conflictLatest: AiPromptDefaultOut | null
  conflictPending: boolean
}

const guard = createEpochGuard()
const tasks = ref<TaskStatusOut[] | null>(null)
const tasksLoading = ref(false)
const selected = ref<string | null>(null)
// Reactive so draft/detail mutations drive the template.
const states = reactive(new Map<string, AdminTaskState>())
const detailLoading = ref(false)
const detailError = ref(false)
const saving = ref(false)
const lastSavedNotice = ref<Notice | null>(null)
const alert = ref<Notice | null>(null)
// T2: per-task conflict view, derived from the selected task's state so the
// template keeps the same names but the data survives task re-selection.
const conflictLatest = computed<AiPromptDefaultOut | null>(
  () => selectedState.value?.conflictLatest ?? null,
)
const conflictPending = computed(() => selectedState.value?.conflictPending ?? false)
const trackedAccount = ref<string | null>(auth.account?.id ?? null)

const selectedState = computed<AdminTaskState | null>(() => {
  const t = selected.value
  if (t === null) return null
  return states.get(t) ?? null
})

function changedFields(state: AdminTaskState | null): string[] {
  if (!state) return []
  return changedGuidanceFields(state.detail.guidance_map, state.draft, state.detail.guidance_fields)
}

const changedCount = computed(() => changedFields(selectedState.value).length)

async function loadTasks() {
  const at = guard.token()
  tasksLoading.value = true
  try {
    const out = await api.listPromptTasks()
    if (!guard.alive(at)) return
    tasks.value = out.items
  } catch (err) {
    if (!guard.alive(at)) return
    tasks.value = null
    const text = aiErrorNotice(err as api.ApiError, '任务列表读取失败，请稍后重试。')
    alert.value = text ? { type: 'error', text } : null
    if ((err as api.ApiError).status === 401) onUnauthorized()
  } finally {
    if (guard.alive(at)) tasksLoading.value = false
  }
}

async function selectTask(taskType: string) {
  guard.bump()
  // New owner clears flags a stale epoch could leak (its finally is dead
  // after the bump and can never unlock anything).
  selected.value = taskType
  alert.value = null
  lastSavedNotice.value = null
  detailError.value = false
  // T2: the conflict view/gate is per-task state — re-selecting the current
  // task or switching away and back must NOT clear it (that would let a
  // stale-baseline PATCH through without an explicit user pick).
  detailLoading.value = false
  saving.value = false
  const cached = states.get(taskType)
  if (cached) {
    // Per-task draft preservation: returning (or re-clicking) keeps text.
    return
  }
  const at = guard.token()
  detailLoading.value = true
  try {
    const out = await api.getAdminPromptDefault(taskType)
    if (!guard.alive(at) || selected.value !== taskType) return
    states.set(taskType, { detail: out, draft: buildDraft(out), conflictLatest: null, conflictPending: false })
  } catch (err) {
    // Ownership FIRST (R4): a late failure for a task the user has already
    // left must not clear the task now being displayed.
    if (!guard.alive(at) || selected.value !== taskType) return
    detailError.value = true
    const text = aiErrorNotice(err as api.ApiError, '默认内容读取失败，请稍后重试。')
    alert.value = text ? { type: 'error', text } : null
    if ((err as api.ApiError).status === 401) onUnauthorized()
  } finally {
    if (guard.alive(at)) detailLoading.value = false
  }
}

function buildDraft(d: AiPromptDefaultOut): Record<string, string> {
  const next: Record<string, string> = {}
  for (const field of d.guidance_fields) {
    next[field] = String(d.guidance_map[field] ?? '')
  }
  return next
}

function hasOwn(map: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(map, key)
}

/**
 * Commit THIS write per R3/R6: submitted fields take the submitted values;
 * fresh typing added after the request left (any other field) survives,
 * genuinely untouched fields land on the committed text.
 */
function commitAdminWrite(out: AiPromptDefaultOut, patch: Record<string, string>): AdminTaskState | null {
  const state = selectedState.value
  if (!state) return null
  state.detail = out
  const next: Record<string, string> = {}
  for (const field of out.guidance_fields) {
    const committed = String(out.guidance_map[field] ?? '')
    if (hasOwn(patch, field)) next[field] = String(patch[field])
    else {
      const cur = hasOwn(state.draft, field) ? String(state.draft[field]) : ''
      next[field] = cur !== committed ? cur : committed
    }
  }
  state.draft = next
  return state
}

async function save() {
  const state = selectedState.value
  const taskType = selected.value
  if (saving.value || detailLoading.value) return
  if (!state || !taskType) return
  // T2: a pending conflict demands an explicit choice — clicking publish
  // again is never an implicit confirmation and must not re-send the old
  // version behind the conflict view. Re-selecting the task must not clear
  // this gate either (per-task state).
  if (state.conflictLatest || state.conflictPending) {
    alert.value = { type: 'warning', text: '存在未处理的冲突：请先选择载入最新默认或保留输入，再发布修改。' }
    return
  }
  const fields = changedFields(state)
  if (fields.length === 0) return
  const at = guard.token()
  saving.value = true
  try {
    // Non-empty partial map of text changes only, guarded by the default
    // revision read as the editing baseline. System fields/protocol have no
    // UI here and are never sent. The editors stay locked until the
    // response arrives, so the response cannot overwrite later typing.
    const patch: Record<string, string> = {}
    for (const field of fields) patch[field] = state.draft[field]
    const out = await api.patchAdminPromptDefault(taskType, {
      expected_default_revision: state.detail.default_revision,
      guidance_map: patch,
    })
    if (!guard.alive(at)) return
    state.conflictLatest = null
    state.conflictPending = false
    alert.value = null
    commitAdminWrite(out, patch)
    lastSavedNotice.value = {
      type: 'success',
      text: `默认指导已发布（本次版本 ${out.default_revision}，契约版本 ${out.contract_version}）。各教师个人指导不会自动更改。`,
    }
  } catch (err) {
    if (!guard.alive(at)) return
    const e = err as api.ApiError
    if (e.status === 401) {
      onUnauthorized()
      return
    }
    const text = aiErrorNotice(e, '保存失败，请稍后重试。')
    alert.value = text ? { type: 'error', text } : null
    if (e.status === 409) {
      // U2: the conflict gate exists from the moment the 409 is identified —
      // set BEFORE the companion GET await. Between the 409 and the GET
      // response `saving` no longer blocks a re-selection, so without this
      // flag re-selecting the task (or A→B→A) during the pending GET would
      // orphan the comparison and re-open the publish path on the stale
      // baseline. The GET result only ever REFINES the already-parked
      // conflict (success adds the comparison data, failure keeps the safe
      // recovery entry); a bumped epoch orphans it without touching the new
      // selection's locks.
      state.conflictPending = true
      // Comparison GET captures its token BEFORE the await (R4); a bump
      // between the calls must kill it as well.
      const at2 = guard.token()
      try {
        const latest = await api.getAdminPromptDefault(taskType)
        if (!guard.alive(at2) || selected.value !== taskType) return
        state.conflictLatest = latest
        state.conflictPending = true
        alert.value = {
          type: 'warning',
          text: '默认内容刚被另一个页面发布过，您的输入已保留。请选择：载入最新默认（覆盖输入），或保留输入并按最新版本重新发布（需要再点一次保存）。',
        }
      } catch (loadErr) {
        if (!guard.alive(at2) || selected.value !== taskType) return
        // S4: the comparison GET itself failed — keep the pending conflict
        // with a visible safe recovery entry; the inputs stay untouched.
        state.conflictPending = true
        const re = loadErr as api.ApiError
        if (re.status === 401) onUnauthorized()
        else {
          const text2 = aiErrorNotice(re, '最新默认读取失败，请稍后重试。')
          if (text2) alert.value = { type: 'warning', text: `最新默认获取未完成（${text2}）；输入已保留，可点击“重新获取最新默认”后选择。` }
        }
      }
    }
  } finally {
    if (guard.alive(at)) saving.value = false
  }
}

/** S4 recovery entry: re-fetch the server default for the parked conflict. */
async function retryConflictLatest() {
  const taskType = selected.value
  const state = selectedState.value
  if (saving.value || detailLoading.value || !taskType || !state) return
  const at2 = guard.token()
  try {
    const latest = await api.getAdminPromptDefault(taskType)
    if (!guard.alive(at2) || selected.value !== taskType) return
    state.conflictLatest = latest
    state.conflictPending = true
    alert.value = {
      type: 'warning',
      text: '已重新获取最新默认，请选择：载入最新默认（覆盖输入），或保留输入并按最新版本重新发布（需要再点一次发布）。',
    }
  } catch (loadErr) {
    if (!guard.alive(at2) || selected.value !== taskType) return
    state.conflictPending = true
    const re = loadErr as api.ApiError
    if (re.status === 401) onUnauthorized()
    else {
      const text2 = aiErrorNotice(re, '最新默认读取失败，请稍后重试。')
      if (text2) alert.value = { type: 'warning', text: `最新默认获取未完成（${text2}）；输入已保留，可稍后再试。` }
    }
  }
}

function detailSnapshotRevision(d: AiPromptDefaultOut): number {
  return d.default_revision
}

function loadLatestIntoInputs() {
  const latest = conflictLatest.value
  const state = selectedState.value
  if (!latest || !state) return
  state.detail = latest
  state.draft = buildDraft(latest)
  state.conflictLatest = null
  state.conflictPending = false
  alert.value = { type: 'info', text: '已载入最新默认内容；检查后请点击“发布修改”。' }
}

function keepInputsRebaseVersion() {
  const state = selectedState.value
  const latest = conflictLatest.value
  if (!state || !latest) return
  // Inputs untouched: only the baseline revision moves to the latest.
  state.detail = { ...latest, guidance_map: { ...latest.guidance_map } }
  state.conflictLatest = null
  state.conflictPending = false
  alert.value = { type: 'info', text: '已按最新默认版本作为保存基线；请检查输入后再次点击“发布修改”（只会提交您修改的字段）。' }
}

function resetDraft() {
  const state = selectedState.value
  if (!state) return
  state.draft = buildDraft(state.detail)
  alert.value = { type: 'info', text: '已放弃未保存的修改；文字回到当前已发布默认。' }
}

function onUnauthorized() {
  // AuthRequired is owned by the global handler; nothing to display here.
}

watch(
  () => auth.account?.id ?? null,
  (id) => {
    if (id === trackedAccount.value) return
    trackedAccount.value = id
    guard.bump()
    tasks.value = null
    selected.value = null
    states.clear() // per-task conflict state dies with the cache (T2)
    alert.value = null
    lastSavedNotice.value = null
    detailError.value = false
    detailLoading.value = false
    saving.value = false
    if (id !== null) void loadTasks()
  },
)

onBeforeUnmount(() => {
  guard.bump()
  states.clear()
})

const hasUnsavedChanges = (): boolean => {
  for (const [, state] of states) {
    if (changedFields(state).length > 0) return true
  }
  return false
}

defineExpose({ hasUnsavedChanges, resetDraft })

void loadTasks()
</script>

<template>
  <el-card data-testid="admin-prompt-defaults-card">
    <template #header>AI 系统默认指导（管理员专用）</template>

    <el-alert
      v-if="alert"
      :closable="true"
      :type="alert.type"
      :title="alert.text"
      show-icon
      class="alert"
      @close="alert = null"
    />
    <el-alert
      v-if="lastSavedNotice"
      :closable="true"
      :type="lastSavedNotice.type"
      :title="lastSavedNotice.text"
      show-icon
      class="alert"
      @close="lastSavedNotice = null"
    />

    <div v-if="!tasks && tasksLoading" class="loading-row">
      <el-button :loading="true" text>正在读取任务列表…</el-button>
    </div>
    <div v-else-if="!tasks" class="loading-row">
      <el-button text @click="loadTasks">重新读取任务列表</el-button>
    </div>
    <template v-else>
      <div class="task-pick">
        <span class="pick-label">选择任务：</span>
        <div class="pick-btns">
          <el-button
            v-for="item in tasks"
            :key="item.task_type"
            size="small"
            :type="selected === item.task_type ? 'primary' : 'default'"
            plain
            @click="selectTask(item.task_type)"
          >{{ taskDisplayName(item.task_type) }}</el-button>
        </div>
      </div>

      <div v-if="selectedState" class="default-detail">
        <div class="meta-row">
          <el-text size="small">
            当前默认版本：{{ selectedState.detail.default_revision }}
            ｜契约版本：{{ selectedState.detail.contract_version }}
          </el-text>
          <el-text type="info" size="small">
            这里只能修改各字段的默认指导文字；字段名称、输出结构和协议由系统维护，本面板不提供修改入口。
          </el-text>
        </div>

        <div v-for="field in selectedState.detail.guidance_fields" :key="field" class="field">
          <div class="field-name">{{ field }}</div>
          <el-input
            v-model="selectedState.draft[field]"
            type="textarea"
            :rows="3"
            maxlength="8000"
            show-word-limit
            :disabled="saving"
          />
        </div>

        <div class="actions">
          <el-button
            type="primary"
            :disabled="saving || detailLoading || changedCount === 0 || conflictLatest !== null || conflictPending"
            :loading="saving"
            @click="save"
          >发布修改</el-button>
          <el-button :disabled="saving || changedCount === 0" @click="resetDraft">放弃修改</el-button>
        </div>

        <div v-if="conflictLatest" class="conflict-actions">
          <el-text type="warning" size="small">
            服务端最新默认版本：{{ conflictLatest.default_revision }}（契约版本 {{ conflictLatest.contract_version }}）
          </el-text>
          <!-- S4: the concrete latest default text is shown beside the kept draft so the user can compare BEFORE 保留输入重新发布. -->
          <div class="cmp-list">
            <div v-for="field in conflictLatest.guidance_fields" :key="field" class="cmp-rows">
              <div class="cmp-label">{{ field }}</div>
              <div class="cmp-cols">
                <div class="cmp-col">
                  <div class="cmp-label">我的输入（未发布）</div>
                  <div class="pre-mini">{{ String((selectedState && selectedState.draft[field]) ?? '') }}</div>
                </div>
                <div class="cmp-col">
                  <div class="cmp-label">服务端最新默认文字</div>
                  <div class="pre-mini">{{ String((conflictLatest.guidance_map ?? {})[field] ?? '') }}</div>
                </div>
              </div>
            </div>
          </div>
          <div class="btn-row">
            <el-button :disabled="saving" @click="loadLatestIntoInputs">载入最新默认</el-button>
            <el-button :disabled="saving" @click="keepInputsRebaseVersion">保留输入，按最新版本重新发布</el-button>
          </div>
        </div>
        <!-- S4: safe recovery entry when the conflict comparison GET failed. -->
        <div v-else-if="conflictPending" class="conflict-actions">
          <el-text type="warning" size="small">最新默认获取未完成；您的输入已保留。</el-text>
          <el-button :disabled="saving || detailLoading" @click="retryConflictLatest">重新获取最新默认</el-button>
        </div>
      </div>
      <div v-else-if="selected && detailError" class="loading-row">
        <el-button text @click="selectTask(selected)">重新读取默认内容</el-button>
      </div>
      <div v-else-if="selected" class="loading-row">
        <el-button :loading="true" text>正在读取默认内容…</el-button>
      </div>
    </template>
  </el-card>
</template>

<style scoped>
.alert { margin-bottom: 16px; }
.task-pick { margin-bottom: 16px; }
.pick-label { color: #606266; font-size: 0.9rem; }
.pick-btns { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.default-detail { border-top: 1px solid #ebeef5; padding-top: 12px; }
.meta-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.field { margin-bottom: 12px; }
.field-name { font-size: 0.9rem; font-weight: 600; word-break: break-all; margin-bottom: 4px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.conflict-actions { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.cmp-list { display: flex; flex-direction: column; gap: 10px; margin: 6px 0; }
.cmp-rows { border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; }
.cmp-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.cmp-col { min-width: 0; }
.cmp-label { color: #909399; font-size: 0.85rem; margin-bottom: 4px; }
.pre-mini { white-space: pre-wrap; word-break: break-word; font-size: 0.9rem; color: #303133; background: #f5f7fa; border-radius: 4px; padding: 6px 10px; min-height: 1em; }
.btn-row { display: flex; gap: 8px; }
.loading-row { padding: 8px 0; }
</style>
