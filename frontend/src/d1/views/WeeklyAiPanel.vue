<script setup lang="ts">
import type { BlockingDraft } from '../leave'
import type { WeeklyEditorController } from '../weekly-editor'
import type { WeeklyDetail, WeeklyDraftContent } from '../weekly'
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { createWeeklyApi, newWeeklyRequestId } from '../weekly'
import { getSessionEpoch } from '../client'
import { WEEKLY_AI_COLUMNS, candidateLines, createWeeklyAiApi, groupStatus, groupStatusLabel, eligibilityLabel, taskStatusLabel, certaintyLabel, targetLabel, projectWeeklyAiError, previewLines, type WeeklyAiCandidate, type WeeklyAiColumn, type WeeklyAiCreateOut, type WeeklyAiSelection, type WeeklyAiTask, type WeeklyAiAdoptionPreview, type WeeklyAiAdoptionResult } from '../weekly-ai'
const props = withDefaults(defineProps<{ controller: WeeklyEditorController; planId: string; detail: WeeklyDetail | null; disabled?: boolean; profileEpoch?: number; sessionEpoch?: number }>(), { disabled: false, profileEpoch: 0, sessionEpoch: 0 })
const emit = defineEmits<{ (e: 'busy', value: boolean): void; (e: 'blocking', value: BlockingDraft | null): void }>()
const api = createWeeklyAiApi()
const weeklyApi = createWeeklyApi()
const selectedFields = ref<WeeklyAiColumn[]>([])
const tasks = ref<WeeklyAiTask[]>([])
const candidates = ref<WeeklyAiCandidate[]>([])
const batch = ref<WeeklyAiCreateOut | null>(null)
const preview = ref<WeeklyAiAdoptionPreview | null>(null)
const selectedKeys = ref<string[]>([])
const previewSelections = ref<WeeklyAiSelection[]>([])
const submitted = ref<WeeklyDraftContent | null>(null)
const previewGuard = ref<{ identity: string; input_revision: number; sequence: number } | null>(null)
const aiBusy = ref(false)
const error = ref('')
const readError = ref('')
const batchReadPending = ref(false)
const notice = ref('')
const retryAckByTask = ref<Record<string, boolean>>({})
const materialText = ref('')
const materialTouched = ref(false)
let alive = true
let aiBusyToken = 0
let panelRequestFlight = false
let refreshGeneration = 0
function beginAiBusy(): number { const token = ++aiBusyToken; aiBusy.value = true; return token }
function endAiBusy(token: number): void { if (token === aiBusyToken) aiBusy.value = false }
onBeforeUnmount(() => { alive = false; aiBusyToken += 1; refreshGeneration += 1; panelRequestFlight = false; emit('busy', false); emit('blocking', null) })
const progress = ref<Record<string, string>>({})
type PanelEpoch = { session: number; profile: number; plan: string; identity: string; controller: object }
const previewEpoch = ref<PanelEpoch | null>(null)
const pendingCreate = ref<{ kind: 'games' | 'columns' | 'materials'; body: Record<string, unknown>; planId: string; requestId: string; epoch: PanelEpoch } | null>(null)
const pendingAdopt = ref<{ body: Record<string, unknown>; planId: string; preview: WeeklyAiAdoptionPreview; guard: { identity: string; input_revision: number; sequence: number }; submitted: WeeklyDraftContent; epoch: PanelEpoch } | null>(null)
const pendingAction = ref<{ taskId: string; kind: 'cancel' | 'resume' | 'retry'; body: Record<string, unknown>; planId: string; epoch: PanelEpoch } | null>(null)
const blocking = computed<BlockingDraft | null>(() => aiBusy.value ? { kind: 'weekly', message: '周计划 AI 正在处理，请等待或查询原请求' } : preview.value ? { kind: 'candidate', message: 'AI 候选预览尚未采用或关闭，请先处理' } : (pendingCreate.value || pendingAdopt.value || pendingAction.value) ? { kind: 'weekly', message: 'AI 请求结果未确认，请先只读核对这次原操作' } : null)
watch([aiBusy, blocking], () => { emit('busy', aiBusy.value); emit('blocking', blocking.value) }, { immediate: true })
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
  batch.value = null; tasks.value = []; candidates.value = []; selectedKeys.value = []; preview.value = null; previewSelections.value = []; previewGuard.value = null; previewEpoch.value = null; pendingCreate.value = null; pendingAdopt.value = null; pendingAction.value = null; progress.value = {}; error.value = ''; readError.value = ''; batchReadPending.value = false; notice.value = ''
  void refreshBatch()
})
function fail(errorValue: unknown) { const projected = projectWeeklyAiError(errorValue); error.value = projected.message; notice.value = ''; return projected }
function epoch(): PanelEpoch { return { session: getSessionEpoch(), profile: props.profileEpoch, plan: props.planId, identity: props.controller.identity(), controller: props.controller } }
function currentEpoch(value: PanelEpoch): boolean { return alive && toRaw(value.controller) === toRaw(props.controller) && value.session === getSessionEpoch() && value.profile === props.profileEpoch && value.plan === props.planId && value.identity === props.controller.identity() }
function candidateTargets(candidate: WeeklyAiCandidate): WeeklyAiSelection[] { return (candidate.available_targets.length ? candidate.available_targets : [candidate.target]).map((target) => ({ candidate_id: candidate.candidate_id, target })) }
async function ensureSaved(ctx: PanelEpoch): Promise<boolean> {
  try {
    const outcome = await props.controller.saveCurrent()
    if (!currentEpoch(ctx)) return false
    if (outcome !== 'saved' && outcome !== 'unchanged') { fail(new Error(outcome === 'indeterminate' ? '保存结果未确认' : '保存未完成')); return false }
    error.value = ''
    return true
  } catch (errorValue) {
    if (!currentEpoch(ctx)) return false
    fail(errorValue)
    return false
  }
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
function activateBatch(response: WeeklyAiCreateOut): void {
  batch.value = response
  tasks.value = []
  candidates.value = []
  selectedKeys.value = []
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
  const saved = props.controller.savedDraftRef()
  const common = { request_id: newWeeklyRequestId(), expected_draft_version: saved.version }
  const body: Record<string, unknown> = kind === 'columns' ? { ...common, selected_fields: [...selectedFields.value] } : common
  pendingCreate.value = { kind, body, planId: ctx.plan, requestId: common.request_id, epoch: ctx }
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
    if (operation.result && operation.result.weekly_plan_id === pending.planId && Array.isArray(operation.result.tasks)) { activateBatch(operation.result as unknown as WeeklyAiCreateOut); pendingCreate.value = null; await refreshBatch() }
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
    activateBatch(response)
    pendingCreate.value = null
    await refreshBatch()
  } catch (errorValue) {
    if (!currentEpoch(pending.epoch)) return
    fail(errorValue)
  } finally { release(); endAiBusy(busyToken) }
}
async function loadProgress(task: WeeklyAiTask): Promise<void> {
  const ctx = epoch()
  try {
    const value = await api.progress(ctx.plan, task.task_id)
    if (!currentEpoch(ctx)) return
    const raw = value.detail ?? value.state ?? value.available
    progress.value = { ...progress.value, [task.task_id]: typeof raw === 'string' ? raw : '只读进度已读取' }
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
function closePreview(): void { preview.value = null; previewSelections.value = []; previewGuard.value = null; previewEpoch.value = null; selectedKeys.value = [] }
async function openPreview(): Promise<void> {
  if (props.disabled || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) { if (!aiBusy.value) error.value = '请先处理已保留的未确认 AI 请求'; return }
  panelRequestFlight = true
  const ctx = epoch()
  if (!(await ensureSaved(ctx))) { panelRequestFlight = false; return }
  if (!currentEpoch(ctx)) { panelRequestFlight = false; return }
  const selections = candidates.value.flatMap(candidateTargets).filter((item) => selectedKeys.value.includes(`${item.candidate_id}:${item.target}`))
  if (!selections.length) { panelRequestFlight = false; error.value = '请选择至少一个可用候选'; return }
  const guard = props.controller.snapshot()
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const response = await api.adoptionPreview(ctx.plan, { expected_draft_version: props.controller.savedDraftRef().version, selections })
    if (!currentEpoch(ctx)) return
    preview.value = response
    previewSelections.value = selections.map((item) => ({ ...item }))
    submitted.value = props.controller.getContent()
    previewGuard.value = { identity: guard.identity, input_revision: guard.input_revision, sequence: guard.sequence }
    previewEpoch.value = ctx
    error.value = ''
  } catch (errorValue) { if (!currentEpoch(ctx)) return; fail(errorValue) } finally { panelRequestFlight = false; release(); endAiBusy(busyToken) }
}
function currentSelections(): WeeklyAiSelection[] {
  return candidates.value.flatMap(candidateTargets).filter((item) => selectedKeys.value.includes(keyForSelection(item)))
}
function keyForSelection(item: WeeklyAiSelection): string { return `${item.candidate_id}:${item.target}` }
function sameSelections(left: WeeklyAiSelection[], right: WeeklyAiSelection[]): boolean {
  const canonical = (items: WeeklyAiSelection[]) => items.map(keyForSelection).sort().join('|')
  return canonical(left) === canonical(right)
}
async function finishAdopt(pending: { body: Record<string, unknown>; planId: string; guard: { identity: string; input_revision: number; sequence: number }; submitted: WeeklyDraftContent; epoch: PanelEpoch }, result: WeeklyAiAdoptionResult): Promise<void> {
  if (!currentEpoch(pending.epoch)) { if (pendingAdopt.value?.body.request_id === pending.body.request_id) pendingAdopt.value = null; return }
  const detail = await weeklyApi.get(pending.planId)
  if (!currentEpoch(pending.epoch)) { if (pendingAdopt.value?.body.request_id === pending.body.request_id) pendingAdopt.value = null; return }
  const outcome = props.controller.reconcileExternalDraft(detail, pending.guard, pending.submitted, result.draft)
  if (outcome === 'stale') return
  if (outcome === 'conflict') error.value = 'AI 采用回包与当前草稿不一致，请核对'
  else { notice.value = 'AI 候选已采用'; pendingAdopt.value = null; closePreview(); await refreshBatch() }
}
async function adopt(): Promise<void> {
  if (!preview.value || !previewGuard.value || !submitted.value || aiBusy.value || panelRequestFlight || pendingCreate.value || pendingAdopt.value || pendingAction.value) return
  const current = props.controller.snapshot()
  const requestEpoch = previewEpoch.value
  if (!requestEpoch || !currentEpoch(requestEpoch) || current.identity !== previewGuard.value.identity || current.input_revision !== previewGuard.value.input_revision || current.sequence !== previewGuard.value.sequence || !sameSelections(currentSelections(), previewSelections.value)) { error.value = '预览期间输入、候选选择或版本已变化，请重新预览'; return }
  const pending = { body: { request_id: newWeeklyRequestId(), expected_draft_version: preview.value.draft.version, preview_token: preview.value.preview_token }, planId: requestEpoch.plan, guard: previewGuard.value, submitted: submitted.value, epoch: requestEpoch }
  pendingAdopt.value = { ...pending, preview: preview.value }
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try { await finishAdopt(pending, await api.adopt(pending.planId, pending.body as { request_id: string; expected_draft_version: number; preview_token: string })) }
  catch (errorValue) {
    if (!currentEpoch(pending.epoch)) return
    const projected = fail(errorValue)
    if (projected.retry !== 'query') pendingAdopt.value = null
  }
  finally { release(); endAiBusy(busyToken) }
}
async function queryAdopt(): Promise<void> {
  const pending = pendingAdopt.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try {
    const operation = await api.operation(pending.planId, String(pending.body.request_id))
    if (operation.result && operation.result.weekly_plan_id === pending.planId && operation.result.draft) await finishAdopt(pending, operation.result as unknown as WeeklyAiAdoptionResult)
    else error.value = '原采用请求尚未返回可读取的回执，请勿重新预览或重建请求'
  } catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue); error.value = '查询未返回原提交，不能据此视为未提交；请保留原请求' } finally { release(); endAiBusy(busyToken) }
}
async function retryAdopt(): Promise<void> {
  const pending = pendingAdopt.value
  if (!pending || aiBusy.value || !currentEpoch(pending.epoch)) return
  const busyToken = beginAiBusy(); error.value = ''
  const release = props.controller.beginExternalBusy('weekly-ai')
  try { await finishAdopt(pending, await api.adopt(pending.planId, pending.body as { request_id: string; expected_draft_version: number; preview_token: string })) }
  catch (errorValue) { if (!currentEpoch(pending.epoch)) return; fail(errorValue) } finally { release(); endAiBusy(busyToken) }
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
const previewDiff = computed(() => preview.value ? previewLines(preview.value.before, preview.value.after) : [])
</script>

<template>
  <section class="weekly-ai" data-d1="weekly-ai">
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
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-alert v-if="readError" :title="readError" type="warning" :closable="false" />
    <div v-if="readError" class="actions"><el-button :disabled="disabled || aiBusy" @click="refreshBatch">重新读取任务与候选</el-button></div>
    <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <el-alert v-if="pendingCreate" title="AI 创建请求结果未确认；保留这次原操作，请只读核对或按原操作重试" type="warning" :closable="false" />
    <div v-if="pendingCreate" class="actions"><el-button @click="queryCreate">核对原创建</el-button><el-button @click="retryCreate">重试这次原创建</el-button></div>
    <el-alert v-if="pendingAdopt" title="AI 采用请求结果未确认；原预览与这次原操作仍保留，请只读核对或按原操作重试" type="warning" :closable="false" />
    <div v-if="pendingAdopt" class="actions"><el-button @click="queryAdopt">核对原采用</el-button><el-button @click="retryAdopt">重试这次原采用</el-button></div>
    <el-alert v-if="pendingAction" title="AI 任务操作结果未确认；原任务与这次原操作保留，请只读核对或按原操作重试" type="warning" :closable="false" />
    <div v-if="pendingAction" class="actions"><el-button @click="queryAction">核对原任务操作</el-button><el-button @click="retryAction">重试这次原任务操作</el-button></div>
    <template v-if="batch || tasks.length || candidates.length">
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
          <span v-if="progress[task.task_id]">{{ progress[task.task_id] }}</span>
        </div>
      </div>
      <div v-for="candidate in candidates" :key="candidate.candidate_id" class="candidate">
        <div><strong>{{ targetLabel(candidate.target) }} · {{ eligibilityLabel(candidate.eligibility) }}</strong></div>
        <ul><li v-for="line in candidateLines(candidate)" :key="line">{{ line }}</li></ul>
        <el-checkbox v-for="target in candidate.available_targets" :key="target" v-model="selectedKeys" :value="selectionKey(candidate, target)" :disabled="candidate.eligibility !== 'eligible'">{{ targetLabel(target) }}</el-checkbox>
      </div>
      <el-button :disabled="disabled || aiBusy || !selectedKeys.length" @click="openPreview">预览采用</el-button>
    </template>
    <el-card v-if="preview" shadow="never" class="preview">
      <h4>采用预览（只读）</h4>
      <ul><li v-for="(line, index) in previewDiff" :key="index">{{ line }}</li></ul>
      <p>未选择的字段不会改动；所选字段若候选为空，将清空该字段。</p>
      <el-button type="primary" :disabled="disabled || aiBusy" @click="adopt">明确采用</el-button>
      <el-button :disabled="aiBusy" @click="closePreview">关闭预览</el-button>
    </el-card>
    <el-card v-if="materialEditable" shadow="never" class="materials">
      <h4>材料正文（已采用依据保留）</h4>
      <el-input v-model="materialText" type="textarea" :disabled="disabled || aiBusy" @input="onMaterialInput" />
      <el-button :disabled="disabled || aiBusy" @click="saveMaterials">保存材料正文</el-button>
    </el-card>
  </section>
</template>

<style scoped>
.weekly-ai { margin: 1rem 0; }
.actions { display: flex; gap: .4rem; flex-wrap: wrap; margin: .4rem 0; }
.columns { display: flex; gap: .5rem; flex-wrap: wrap; margin: .4rem 0; }
.task, .candidate, .preview, .materials { margin: .6rem 0; }
</style>
