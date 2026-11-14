<script setup lang="ts">
/**
 * Stage-3 shared weekly plan for the currently edited local week.
 *
 * Only the shared allowlist crosses the online boundary.  Local IDs, headers,
 * theme, columns, materials, activity bodies, photos and Word files stay local.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiGetBlob, ApiError } from '../client'
import {
  collaborationWriteIndeterminate,
  createCollaborationApi,
  isCollaborationSessionInvalidError,
  type CollaborationPromotionTerm,
} from '../collaboration'
import {
  WEEKLY_SHARED_SLOT_LABELS,
  cloneSharedContent,
  createWeeklyCollaborationApi,
  emptySharedContent,
  mergeSharedDays,
  projectWeeklySharedContent,
  sharedContentEqual,
  weekDatesInTerm,
  weeklySharedWordPath,
  type WeeklyShared,
  type WeeklySharedConfirmation,
  type WeeklySharedContent,
  type WeeklySharedGame,
  type WeeklySharedOperation,
  type WeeklySharedSlot,
  type WeeklySharedSaveInput,
} from '../weekly-collaboration'
import { hostGlobal, type HostApi, type SaveDocxResult } from '../bridge'
import type { BlockingDraft } from '../leave'
import type { WeeklyDetail } from '../weekly'

const props = withDefaults(defineProps<{
  open: boolean
  localDetail: WeeklyDetail
  host?: HostApi | null
  disabled?: boolean
}>(), { host: null, disabled: false })

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
  (e: 'blocking', value: BlockingDraft | null): void
  (e: 'open-history'): void
}>()

const api = createWeeklyCollaborationApi()
const online = createCollaborationApi()
const weekStart = computed(() => props.localDetail.plan.week_anchor_date)
const localDraftVersion = computed(() => props.localDetail.draft.version)
const localPlanId = computed(() => props.localDetail.plan.id)

const onlineLoading = ref(false)
const onlineError = ref('')
const classId = ref('')
const className = ref('')
const termOptions = ref<CollaborationPromotionTerm[]>([])
const selectedTermId = ref('')
const loading = ref(false)
const errorText = ref('')
const noticeText = ref('')
const shared = ref<WeeklyShared | null>(null)
const serverContent = ref<WeeklySharedContent | null>(null)
const comparisonContent = ref<WeeklySharedContent | null>(null)
const comparisonVersion = ref<number | null>(null)
const comparisonAcknowledged = ref(true)
const draft = ref<WeeklySharedContent | null>(null)
const baseline = ref('')
const saving = ref(false)
const confirming = ref(false)
const conflict = ref(false)
const conflictVersion = ref<number | null>(null)
const pending = ref<{
  kind: 'save' | 'confirm'
  requestId: string
  body: WeeklySharedSaveInput | { request_id: string; expected_version: number }
  classId: string
  termId: string
  weekStart: string
} | null>(null)
const querying = ref(false)
const resubmitting = ref(false)
const confirmationView = ref<WeeklySharedConfirmation | null>(null)
const useLocalForWord = ref(false)
const exportBusy = ref(false)
const exportText = ref('')
const localProjectionAvailable = computed(() => Boolean(props.localDetail.draft.content))

let alive = true
let scopeEpoch = 0

const selectedTerm = computed(
  () => termOptions.value.find((term) => term.term_id === selectedTermId.value) ?? null,
)
const slotKeys = Object.keys(WEEKLY_SHARED_SLOT_LABELS) as WeeklySharedSlot[]
const selectedDateRange = computed(() => selectedTerm.value
  ? weekDatesInTerm(weekStart.value, selectedTerm.value.start_date, selectedTerm.value.end_date)
  : [])
const dirty = computed(
  () => draft.value !== null
    && baseline.value !== ''
    && !sharedContentEqual(draft.value, JSON.parse(baseline.value) as WeeklySharedContent),
)
const termLocked = computed(
  () => dirty.value || pending.value !== null || saving.value || confirming.value,
)
const busy = computed(
  () => saving.value || confirming.value || querying.value || resubmitting.value || exportBusy.value || pending.value !== null,
)
const blockingDraft = computed<BlockingDraft | null>(() => {
  if (pending.value) {
    return {
      kind: 'weekly',
      message: '共享周计划写入结果待核对；不能关闭或离开，请只读查询原请求',
    }
  }
  if (saving.value || confirming.value) {
    return {
      kind: 'weekly',
      message: '共享周计划正在保存或确认；请等待结果后再离开',
    }
  }
  if (dirty.value) {
    return {
      kind: 'weekly',
      message: '共享周计划有未保存的编辑；请保存、确认或取消本次共享编辑后再离开',
    }
  }
  if (conflict.value) {
    return {
      kind: 'weekly',
      message: '共享周计划版本冲突；请重新读取服务端版本并核对未提交输入后再离开',
    }
  }
  if (exportBusy.value) {
    return {
      kind: 'weekly',
      message: '共享周计划确认版正在导出；请等待原生保存结果后再离开',
    }
  }
  return null
})

watch(
  busy,
  (value) => emit('busy', value),
  { immediate: true },
)
watch(
  blockingDraft,
  (value) => emit('blocking', value),
  { immediate: true },
)
watch(
  () => props.open,
  (value) => {
    if (value) void loadOnline()
  },
  { immediate: true },
)

function current(epoch: number): boolean {
  return alive && epoch === scopeEpoch
}

function close(): void {
  if (blockingDraft.value) {
    errorText.value = blockingDraft.value.message
    return
  }
  emit('update:open', false)
}

function beforeClose(done: () => void): void {
  if (blockingDraft.value) {
    errorText.value = blockingDraft.value.message
    return
  }
  done()
}

function cancelSharedEdit(): void {
  if (pending.value || saving.value || confirming.value) {
    errorText.value = '共享写入仍待处理，不能取消当前输入'
    return
  }
  draft.value = serverContent.value
    ? cloneSharedContent(serverContent.value)
    : null
  baseline.value = draft.value ? JSON.stringify(draft.value) : ''
  comparisonContent.value = null
  comparisonVersion.value = null
  comparisonAcknowledged.value = true
  conflict.value = false
  noticeText.value = '已取消本次共享编辑；在线共享版未改变'
  close()
}

function clearSharedState(): void {
  shared.value = null
  serverContent.value = null
  comparisonContent.value = null
  comparisonVersion.value = null
  comparisonAcknowledged.value = true
  draft.value = null
  baseline.value = ''
  conflict.value = false
  conflictVersion.value = null
  confirmationView.value = null
  pending.value = null
  exportText.value = ''
}

async function loadOnline(): Promise<void> {
  const epoch = ++scopeEpoch
  onlineLoading.value = true
  onlineError.value = ''
  errorText.value = ''
  clearSharedState()
  try {
    const status = await online.status()
    if (!current(epoch)) return
    if (!status.connected) {
      onlineError.value = '请先在设置中连接在线协作并选择当前班级'
      return
    }
    const membership = await online.membership()
    if (!current(epoch)) return
    if (!membership) {
      onlineError.value = '尚未选择在线班级，请先在设置中选择班级'
      return
    }
    classId.value = membership.class_id
    className.value = membership.class_name
    const promotion = await online.getPromotion()
    if (!current(epoch)) return
    const matching = promotion.terms.filter(
      (term) => weekDatesInTerm(
        weekStart.value,
        term.start_date,
        term.end_date,
      ).length > 0,
    )
    termOptions.value = matching
    if (!matching.some((term) => term.term_id === selectedTermId.value)) {
      selectedTermId.value = matching.length === 1 ? matching[0].term_id : ''
    }
    if (selectedTermId.value) await loadShared(epoch)
  } catch (err) {
    if (current(epoch)) onlineError.value = collaborationMessage(err, '读取在线班级或学期失败')
  } finally {
    if (current(epoch)) onlineLoading.value = false
  }
}

async function loadShared(epochArg?: number): Promise<void> {
  const epoch = epochArg ?? scopeEpoch
  if (!classId.value || !selectedTermId.value || props.disabled) return
  loading.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.get(classId.value, selectedTermId.value, weekStart.value)
    if (!current(epoch)) return
    const range = selectedDateRange.value
    if (range.length === 0) {
      errorText.value = '本地周与所选在线学期没有交集日期，未发送保存或确认'
      return
    }
    const serverDays = mergeSharedDays(
      result.content.days,
      range,
      props.localDetail.draft.content,
    )
    const serverProjection: WeeklySharedContent = {
      ...result.content,
      days: serverDays,
    }
    const hadUnsaved = dirty.value
    const versionChanged = shared.value !== null && result.version !== shared.value.version
    shared.value = result
    serverContent.value = serverProjection
    confirmationView.value = result.confirmation
    if (hadUnsaved) {
      // Keep the teacher's unsaved input.  A changed server version is shown
      // side by side and requires an explicit acknowledgment before saving.
      comparisonContent.value = versionChanged ? serverProjection : null
      comparisonVersion.value = versionChanged ? result.version : null
      comparisonAcknowledged.value = !versionChanged
      conflict.value = false
      conflictVersion.value = null
      noticeText.value = versionChanged
        ? '服务端共享版已更新；本页未提交输入已保留，请核对服务端当前逐日和游戏值后再保存'
        : '已重新读取共享版；本页未提交输入已保留'
      return
    }
    draft.value = result.version === 0
      ? projectWeeklySharedContent(props.localDetail, props.localDetail.draft.content, range)
      : cloneSharedContent(serverProjection)
    baseline.value = JSON.stringify(draft.value)
    comparisonContent.value = null
    comparisonVersion.value = null
    comparisonAcknowledged.value = true
    conflict.value = false
    conflictVersion.value = null
  } catch (err) {
    if (current(epoch)) errorText.value = collaborationMessage(err, '读取共享周计划失败')
  } finally {
    if (current(epoch)) loading.value = false
  }
}

function useLocalProjection(): void {
  if (!draft.value || saving.value || confirming.value || pending.value) return
  draft.value = projectWeeklySharedContent(
    props.localDetail,
    props.localDetail.draft.content,
    selectedDateRange.value,
  )
  noticeText.value = '已从本人已保存周计划提取活动名称和日期；尚未写入在线共享版'
}

function setDayField(index: number, key: 'morning_talk_topic' | 'group_activity_theme', value: string): void {
  const day = draft.value?.days[index]
  if (day) day[key] = value
}

function setGameName(slot: WeeklySharedSlot, value: string): void {
  if (!draft.value) return
  const currentGame = draft.value.games[slot]
  const name = value.trim()
  if (name === '') {
    draft.value.games[slot] = null
    return
  }
  draft.value.games[slot] = {
    name,
    date: currentGame?.date ?? null,
  }
}

function setGameDate(slot: WeeklySharedSlot, value: string): void {
  if (!draft.value) return
  const currentGame = draft.value.games[slot]
  if (!currentGame) return
  currentGame.date = value || null
}

function game(slot: WeeklySharedSlot): WeeklySharedGame | null {
  return draft.value?.games[slot] ?? null
}

function makeSaveBody(): WeeklySharedSaveInput {
  return {
    request_id: crypto.randomUUID(),
    expected_version: shared.value?.version ?? 0,
    content: cloneSharedContent(draft.value ?? emptySharedContent()),
  }
}

async function save(): Promise<void> {
  if (!draft.value || !classId.value || !selectedTermId.value || saving.value || confirming.value || pending.value) return
  if (comparisonContent.value && !comparisonAcknowledged.value) {
    errorText.value = '请先核对服务端当前逐日和游戏值，勾选确认后再保存'
    return
  }
  const body = makeSaveBody()
  saving.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.save(classId.value, selectedTermId.value, weekStart.value, body)
    applySaveResult(result)
  } catch (err) {
    if (collaborationWriteIndeterminate(err)) {
      pending.value = {
        kind: 'save',
        requestId: body.request_id,
        body,
        classId: classId.value,
        termId: selectedTermId.value,
        weekStart: weekStart.value,
      }
      errorText.value = '共享保存结果未确认：已保留当前输入和原请求 ID，请只读查询；不会自动重发'
    } else if (isConflict(err)) {
      conflict.value = true
      conflictVersion.value = readCurrentVersion(err)
      errorText.value = conflictMessage('保存')
    } else if (isCollaborationSessionInvalidError(err)) {
      errorText.value = '在线协作连接已失效；当前共享输入已保留，请重新连接后重读'
    } else {
      errorText.value = collaborationMessage(err, '保存共享周计划失败')
    }
  } finally {
    saving.value = false
  }
}

async function confirm(): Promise<void> {
  if (!shared.value || !classId.value || !selectedTermId.value || dirty.value || saving.value || confirming.value || pending.value) {
    if (dirty.value) errorText.value = '请先保存共享编辑，再确认最新已保存版本'
    return
  }
  const body = {
    request_id: crypto.randomUUID(),
    expected_version: shared.value.version,
  }
  confirming.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.confirm(classId.value, selectedTermId.value, weekStart.value, body)
    applyConfirmResult(result)
  } catch (err) {
    if (collaborationWriteIndeterminate(err)) {
      pending.value = {
        kind: 'confirm',
        requestId: body.request_id,
        body,
        classId: classId.value,
        termId: selectedTermId.value,
        weekStart: weekStart.value,
      }
      errorText.value = '确认结果未确认：已保留原请求 ID；请只读查询，不会自动重发'
    } else if (isConflict(err)) {
      conflict.value = true
      conflictVersion.value = readCurrentVersion(err)
      errorText.value = conflictMessage('确认')
    } else if (isCollaborationSessionInvalidError(err)) {
      errorText.value = '在线协作连接已失效；请重新连接后重读共享版'
    } else {
      errorText.value = collaborationMessage(err, '确认共享周计划失败')
    }
  } finally {
    confirming.value = false
  }
}

function applySaveResult(result: Awaited<ReturnType<typeof api.save>>): void {
  shared.value = result
  serverContent.value = result.content
  confirmationView.value = result.confirmation
  draft.value = cloneSharedContent(result.content)
  baseline.value = JSON.stringify(draft.value)
  comparisonContent.value = null
  comparisonVersion.value = null
  comparisonAcknowledged.value = true
  conflict.value = false
  conflictVersion.value = null
  noticeText.value = result.replayed
    ? `已读取原保存回执，共享版 v${result.version}`
    : `共享周计划已保存为 v${result.version}`
}

function applyConfirmResult(result: Awaited<ReturnType<typeof api.confirm>>): void {
  confirmationView.value = result
  shared.value = {
    ...(shared.value as WeeklyShared),
    version: result.version,
    confirmation: result,
  }
  baseline.value = JSON.stringify(draft.value)
  comparisonContent.value = null
  comparisonVersion.value = null
  comparisonAcknowledged.value = true
  conflict.value = false
  conflictVersion.value = null
  noticeText.value = result.replayed
    ? `已读取原确认回执，确认版 v${result.confirmation_version}`
    : `已确认共享版 v${result.confirmation_version}`
}

async function readServerAfterConflict(): Promise<void> {
  if (!classId.value || !selectedTermId.value) return
  try {
    const result = await api.get(classId.value, selectedTermId.value, weekStart.value)
    const serverProjection: WeeklySharedContent = {
      ...result.content,
      days: mergeSharedDays(
        result.content.days,
        selectedDateRange.value,
        props.localDetail.draft.content,
      ),
    }
    shared.value = result
    serverContent.value = serverProjection
    comparisonContent.value = serverProjection
    comparisonVersion.value = result.version
    comparisonAcknowledged.value = false
    confirmationView.value = result.confirmation
    conflict.value = false
    conflictVersion.value = result.version
    noticeText.value = `已读取服务端共享版 v${result.version}；未提交输入保留，请核对逐日和游戏值后明确保存`
  } catch (err) {
    errorText.value = collaborationMessage(err, '重新读取服务端共享版失败；未提交输入仍保留')
  }
}

async function queryPending(): Promise<void> {
  const value = pending.value
  if (!value || querying.value || props.disabled) return
  querying.value = true
  errorText.value = ''
  try {
    const operation: WeeklySharedOperation = await api.getOperation(
      value.classId,
      value.termId,
      value.weekStart,
      value.requestId,
    )
    if (pending.value !== value) return
    if (operation.request_id !== value.requestId || operation.kind !== value.kind) {
      errorText.value = '查询回执与当前待核对请求不一致，未采用'
      return
    }
    if (operation.kind === 'save') applySaveResult(operation.result)
    else applyConfirmResult(operation.result)
    pending.value = null
  } catch (err) {
    if (pending.value !== value) return
    if (err instanceof ApiError && err.status === 404) {
      noticeText.value = '尚未查到回执；原请求仍待核对，不会自动重发'
    } else if (isCollaborationSessionInvalidError(err)) {
      errorText.value = '在线连接已失效；原请求仍待核对，请重新连接后查询'
    } else {
      errorText.value = collaborationMessage(err, '查询回执失败；原请求仍待核对')
    }
  } finally {
    querying.value = false
  }
}

async function resubmitPending(): Promise<void> {
  const value = pending.value
  if (!value || resubmitting.value || querying.value || props.disabled) return
  if (
    classId.value !== value.classId
    || selectedTermId.value !== value.termId
    || weekStart.value !== value.weekStart
  ) {
    errorText.value = '当前身份、班级或周已变化，不能按原请求重提；请重新读取核对'
    return
  }
  resubmitting.value = true
  errorText.value = ''
  try {
    if (value.kind === 'save') {
      const result = await api.save(
        value.classId,
        value.termId,
        value.weekStart,
        value.body as WeeklySharedSaveInput,
      )
      applySaveResult(result)
    } else {
      const result = await api.confirm(
        value.classId,
        value.termId,
        value.weekStart,
        value.body as { request_id: string; expected_version: number },
      )
      applyConfirmResult(result)
    }
    pending.value = null
  } catch (err) {
    if (collaborationWriteIndeterminate(err)) {
      errorText.value = '原请求重提仍未确认：请求 ID 与内容已保留，可继续查询'
    } else if (isCollaborationSessionInvalidError(err)) {
      errorText.value = '在线连接已失效；原请求仍待核对，请重新连接后查询'
    } else {
      errorText.value = collaborationMessage(
        err,
        '原请求重提未完成；可继续按原请求核对',
      )
    }
  } finally {
    resubmitting.value = false
  }
}

async function readConfirmation(): Promise<void> {
  if (!confirmationView.value || !classId.value || !selectedTermId.value) return
  try {
    confirmationView.value = await api.getConfirmation(
      classId.value,
      selectedTermId.value,
      weekStart.value,
      confirmationView.value.confirmation_id,
    )
    noticeText.value = '已读取当前确认版快照'
  } catch (err) {
    errorText.value = collaborationMessage(err, '读取确认版失败')
  }
}

function gameLabel(slot: WeeklySharedSlot): string {
  return WEEKLY_SHARED_SLOT_LABELS[slot]
}

function resolveHostApi(): HostApi | null {
  const candidate = props.host ?? hostGlobal()?.api
  return candidate && typeof candidate.save_docx === 'function'
    ? candidate
    : null
}

async function exportWord(): Promise<void> {
  const confirmation = confirmationView.value
  const host = resolveHostApi()
  if (!confirmation || !host?.save_docx || !classId.value || !selectedTermId.value) {
    errorText.value = '未找到确认版或桌面原生保存接口，未导出'
    return
  }
  if (exportBusy.value) return
  exportBusy.value = true
  exportText.value = ''
  errorText.value = ''
  try {
    const local = useLocalForWord.value
      ? { weeklyPlanId: localPlanId.value, draftVersion: localDraftVersion.value }
      : undefined
    const blob = await apiGetBlob(
      weeklySharedWordPath(
        classId.value,
        selectedTermId.value,
        weekStart.value,
        confirmation.confirmation_id,
        local,
      ),
    )
    const result = await saveDocx(host, blob, crypto.randomUUID())
    applySaveResultText(result)
  } catch (err) {
    if (isCollaborationSessionInvalidError(err)) {
      errorText.value = '在线协作连接已失效；未导出确认版'
    } else {
      errorText.value = collaborationMessage(err, '导出确认版失败')
    }
  } finally {
    exportBusy.value = false
  }
}

async function saveDocx(host: HostApi, blob: Blob, requestId: string): Promise<SaveDocxResult> {
  const base64 = await blobToBase64(blob)
  try {
    return await host.save_docx!({
      request_id: requestId,
      filename: `共享周计划-${weekStart.value}.docx`,
      payload_base64: base64,
    })
  } catch {
    if (!host.get_save_result) return { status: 'unknown' }
    return host.get_save_result({ request_id: requestId })
  }
}

function applySaveResultText(result: SaveDocxResult): void {
  if (result.status === 'saved') {
    exportText.value = `确认版已保存${result.filename ? `：${result.filename}` : ''}`
  } else if (result.status === 'canceled') {
    exportText.value = '已取消原生保存，未写入文件'
  } else if (result.status === 'failed') {
    errorText.value = result.message || '确认版保存失败，未写入文件'
  } else {
    exportText.value = '保存结果未确认；请按原请求核对，未自动重写'
  }
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('无法读取文档数据'))
    reader.onload = () => {
      const text = String(reader.result ?? '')
      resolve(text.includes(',') ? text.slice(text.indexOf(',') + 1) : text)
    }
    reader.readAsDataURL(blob)
  })
}

function isConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409
}

function readCurrentVersion(err: unknown): number | null {
  if (!(err instanceof ApiError)) return null
  const value = err.details?.current_version
  return typeof value === 'number' ? value : null
}

function conflictMessage(action: string): string {
  const version = conflictVersion.value
  return version === null
    ? `${action}遇到共享版冲突：当前未提交输入已保留，请读取服务端版本核对后再保存`
    : `${action}遇到共享版冲突：服务端当前为 v${version}，当前未提交输入已保留；请核对后重新保存`
}

function collaborationMessage(err: unknown, fallback: string): string {
  if (
    err instanceof ApiError
    && typeof err.code === 'string'
    && err.code.startsWith('COLLABORATION_')
  ) return err.message
  return fallback
}

function loadLocalProjection(): void {
  useLocalProjection()
}

function openLocalHistory(): void {
  if (blockingDraft.value) {
    errorText.value = blockingDraft.value.message
    return
  }
  emit('open-history')
}

onBeforeUnmount(() => {
  alive = false
  scopeEpoch += 1
  emit('busy', false)
  emit('blocking', null)
})

defineExpose({
  loadOnline,
  loadShared,
  save,
  confirm,
  queryPending,
  readConfirmation,
  exportWord,
  loadLocalProjection,
  isDirty: () => dirty.value,
  isBlocking: () => blockingDraft.value !== null,
  currentShared: () => shared.value,
  currentDraft: () => draft.value,
  currentConfirmation: () => confirmationView.value,
})
</script>

<template>
  <el-dialog
    :model-value="open"
    title="共享本周周计划"
    width="920px"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    @update:model-value="(value: boolean) => { if (value) emit('update:open', true); else close() }"
  >
    <div data-d1="weekly-collaboration">
      <el-alert
        v-if="onlineLoading || loading"
        title="正在读取在线班级、学期与共享版"
        type="info"
        :closable="false"
      />
      <el-alert v-if="onlineError" :title="onlineError" type="warning" :closable="false" />
      <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" data-d1="weekly-collaboration-error" />
      <el-alert v-if="noticeText" :title="noticeText" type="success" :closable="false" data-d1="weekly-collaboration-notice" />
      <el-alert
        v-if="pending"
        :title="'共享周计划写入结果未确认。当前输入与绑定已保留；请查询原请求或按原请求重新提交，不会自动重发。'"
        type="warning"
        :closable="false"
        data-d1="weekly-collaboration-pending"
      />
      <div v-if="pending" class="actions">
        <el-button size="small" :loading="querying" data-d1="weekly-collaboration-query" @click="queryPending">查询原请求</el-button>
        <el-button
          size="small"
          type="warning"
          :loading="resubmitting"
          data-d1="weekly-collaboration-resubmit"
          @click="resubmitPending"
        >
          按原请求重新提交
        </el-button>
      </div>

      <template v-if="!onlineError">
        <p class="context">
          本地周：{{ weekStart }} ·
          在线班级：{{ className || '—' }} ·
          <span v-if="selectedTerm">在线学期：{{ selectedTerm.name }}</span>
          <span v-else>请在匹配学期中明确选择</span>
        </p>
        <div v-if="termOptions.length > 1" class="actions">
          <el-select v-model="selectedTermId" placeholder="选择在线学期" data-d1="weekly-collaboration-term">
            <el-option
              v-for="term in termOptions"
              :key="term.term_id"
              :label="`${term.name}（${term.start_date} 至 ${term.end_date}）`"
              :value="term.term_id"
            />
          </el-select>
          <el-button size="small" :disabled="!selectedTermId || loading" @click="loadShared()">读取共享版</el-button>
        </div>
        <p v-else-if="termOptions.length === 0" class="muted">本地周日期不在当前在线学期范围内，未发送请求。</p>

        <template v-if="shared && draft">
          <div class="actions">
            <el-button size="small" :disabled="saving || confirming || !!pending" @click="loadShared()">重新读取</el-button>
            <el-button
              size="small"
              :disabled="saving || confirming || !!pending || !localProjectionAvailable"
              @click="loadLocalProjection"
            >
              从本地已保存周计划带入名称/日期
            </el-button>
            <el-button
              size="small"
              type="primary"
              :loading="saving"
              :disabled="saving || confirming || !!pending || conflict || (!!comparisonContent && !comparisonAcknowledged)"
              @click="save"
            >
              保存共享版
            </el-button>
            <el-button size="small" type="primary" :loading="confirming" :disabled="saving || confirming || !!pending || conflict || dirty" @click="confirm">确认最新已保存版</el-button>
          </div>
          <el-alert
            v-if="conflict"
            :title="`共享版冲突${conflictVersion !== null ? `：服务端当前 v${conflictVersion}` : ''}。未提交输入已保留；请核对服务端版本后再保存。`"
            type="warning"
            :closable="false"
            data-d1="weekly-collaboration-conflict"
          />
          <div v-if="conflict" class="actions">
            <el-button size="small" @click="readServerAfterConflict">读取服务端版本（保留本页输入）</el-button>
          </div>
          <div
            v-if="comparisonContent"
            class="comparison-block"
            data-d1="weekly-collaboration-comparison"
          >
            <h4>服务端当前共享版 v{{ comparisonVersion }}（只读，供核对）</h4>
            <el-table :data="comparisonContent.days" size="small">
              <el-table-column prop="date" label="日期" width="110" />
              <el-table-column prop="morning_talk_topic" label="晨谈" />
              <el-table-column prop="group_activity_theme" label="集体活动" />
            </el-table>
            <p v-for="slot in slotKeys" :key="`server-${slot}`" class="muted">
              {{ gameLabel(slot) }}：
              {{ comparisonContent.games[slot]?.name ?? '（空）' }}
              <span v-if="comparisonContent.games[slot]?.date">
                · {{ comparisonContent.games[slot]?.date }}
              </span>
            </p>
            <el-checkbox
              v-model="comparisonAcknowledged"
              data-d1="weekly-collaboration-comparison-ack"
            >
              我已核对服务端当前逐日和游戏值，保留本页输入并明确保存
            </el-checkbox>
          </div>
          <p class="muted">共享 v{{ shared.version }} · 只共享晨谈、集体活动和游戏名称/日期；本地表头、主题、栏目、材料、正文和文件不上传。</p>

          <el-table :data="draft.days" size="small" data-d1="weekly-collaboration-days">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column label="晨谈">
              <template #default="{ row, $index }">
                <el-input
                  :model-value="row.morning_talk_topic"
                  :disabled="saving || confirming || !!pending"
                  @update:model-value="(value: string) => setDayField($index, 'morning_talk_topic', value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="集体活动">
              <template #default="{ row, $index }">
                <el-input
                  :model-value="row.group_activity_theme"
                  :disabled="saving || confirming || !!pending"
                  @update:model-value="(value: string) => setDayField($index, 'group_activity_theme', value)"
                />
              </template>
            </el-table-column>
          </el-table>

          <h4>游戏</h4>
          <div v-for="slot in slotKeys" :key="slot" class="game-row">
            <span class="game-label">{{ gameLabel(slot) }}</span>
            <el-input
              :model-value="game(slot)?.name ?? ''"
              placeholder="游戏/区域名称"
              :disabled="saving || confirming || !!pending"
              @update:model-value="(value: string) => setGameName(slot, value)"
            />
            <el-input
              :model-value="game(slot)?.date ?? ''"
              placeholder="日期（可空）"
              :disabled="saving || confirming || !!pending || !game(slot)"
              @update:model-value="(value: string) => setGameDate(slot, value)"
            />
          </div>

          <div v-if="confirmationView" class="confirmation-block" data-d1="weekly-collaboration-confirmation">
            <h4>确认版 v{{ confirmationView.confirmation_version }}</h4>
            <p class="muted">
              {{ confirmationView.class_name }} · {{ confirmationView.term_name }} ·
              {{ confirmationView.week_start }}
            </p>
            <details class="confirmation-content" data-d1="weekly-collaboration-confirmation-content">
              <summary>查看确认版共享内容</summary>
              <el-table :data="confirmationView.content.days" size="small">
                <el-table-column prop="date" label="日期" width="110" />
                <el-table-column prop="morning_talk_topic" label="晨谈" />
                <el-table-column prop="group_activity_theme" label="集体活动" />
              </el-table>
              <p
                v-for="slot in slotKeys"
                :key="`confirmed-${slot}`"
                class="muted"
              >
                {{ gameLabel(slot) }}：
                {{ confirmationView.content.games[slot]?.name ?? '（空）' }}
                <span v-if="confirmationView.content.games[slot]?.date">
                  · {{ confirmationView.content.games[slot]?.date }}
                </span>
              </p>
            </details>
            <el-button size="small" :disabled="exportBusy" @click="readConfirmation">重新读取确认版</el-button>
            <el-checkbox v-model="useLocalForWord" :disabled="exportBusy" data-d1="weekly-collaboration-use-local-word">
              用当前已保存本地周稿补齐 Word 表头/栏目/材料
            </el-checkbox>
            <el-button
              size="small"
              type="primary"
              :loading="exportBusy"
              data-d1="weekly-collaboration-export"
              @click="exportWord"
            >
              导出确认版 Word
            </el-button>
            <p v-if="exportText" class="notice">{{ exportText }}</p>
          </div>
          <p v-else class="muted">当前共享周尚无确认版；确认后才能导出。</p>
        </template>
      </template>
    </div>
    <template #footer>
      <el-button data-d1="weekly-shared-history" :disabled="!!pending || saving || confirming || exportBusy" @click="openLocalHistory">本地确认历史</el-button>
      <el-button :disabled="!!pending || saving || confirming || exportBusy" @click="close">关闭</el-button>
      <el-button
        :disabled="!!pending || saving || confirming || !dirty"
        @click="cancelSharedEdit"
      >
        取消本次共享编辑
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.actions { display: flex; gap: .5rem; flex-wrap: wrap; margin: .6rem 0; align-items: center; }
.context { margin: .5rem 0; }
.muted { color: var(--el-text-color-secondary); }
.game-row { display: grid; grid-template-columns: 110px minmax(180px, 1fr) 160px; gap: .5rem; align-items: center; margin: .4rem 0; }
.game-label { color: var(--el-text-color-secondary); }
.confirmation-block { margin-top: 1rem; padding: .75rem; border: 1px solid var(--el-border-color-lighter); }
.confirmation-content { margin: .6rem 0; }
.notice { color: var(--el-color-success); }
</style>
