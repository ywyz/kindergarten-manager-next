<script setup lang="ts">
/**
 * Optional online class collaboration (#5/#8).
 *
 * This component is intentionally standalone: the parent shell will mount it
 * later.  It owns only online-collaboration state, never the local SQLite
 * class-game draft.  The local configuration is read only after the teacher
 * explicitly chooses to publish it.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, apiGet } from '../client'
import {
  collaborationErrorMessage,
  collaborationWriteIndeterminate,
  createCollaborationApi,
  isCollaborationConflictError,
  isCollaborationResubmitUncommittedError,
  isCollaborationSessionInvalidError,
  type CollaborationClass,
  type CollaborationClassmate,
  type CollaborationConfirmInput,
  type CollaborationConfirmResult,
  type CollaborationConfig,
  type CollaborationMembership,
  type CollaborationPreview,
  type CollaborationSaveInput,
  type CollaborationSaveResult,
  type CollaborationStatus,
} from '../collaboration'
import type { ClassGames, GameLocation } from '../types'

const props = withDefaults(defineProps<{
  frozen?: boolean
}>(), { frozen: false })

const emit = defineEmits<{
  (e: 'draft-active', active: boolean): void
}>()

const api = createCollaborationApi()
let alive = true
let scopeEpoch = 0

const statusLoaded = ref(false)
const status = ref<CollaborationStatus>({
  configured: false,
  connected: false,
  teacher: null,
  message: '正在读取在线协作配置…',
})
const credential = ref('')
const connecting = ref(false)
const disconnecting = ref(false)
const loadingDirectory = ref(false)
const loadingClass = ref(false)
const selectingClassId = ref('')
const leavingClass = ref(false)
const classSelectionUnknown = ref(false)
const classSelectionUnknownMessage = ref('')
const classes = ref<CollaborationClass[]>([])
const membership = ref<CollaborationMembership | null>(null)
const classmates = ref<CollaborationClassmate[]>([])
const onlineConfig = ref<CollaborationConfig | null>(null)
const preview = ref<CollaborationPreview | null>(null)
const previewStale = ref(false)
const previewingSourceId = ref('')
const publishing = ref(false)

interface PublishDraft {
  classId: string
  classLabel: string
  localClassName: string
  localRevisionNo: number
  expectedVersion: number
  locations: GameLocation[]
  gameScope: string | null
  guidance: string | null
}
const publishPreview = ref<PublishDraft | null>(null)
const publishConflict = ref(false)
const confirming = ref(false)
const querying = ref(false)
const resubmitting = ref(false)
const errorText = ref('')
const noticeText = ref('')

interface PendingSaveWrite {
  kind: 'save'
  requestId: string
  body: CollaborationSaveInput
  classId: string
  teacherId: string
  schoolId: string
  sourceTeacherId: null
}
interface PendingImportWrite {
  kind: 'import'
  requestId: string
  body: CollaborationConfirmInput
  classId: string
  teacherId: string
  schoolId: string
  sourceTeacherId: string
}
type PendingWrite = PendingSaveWrite | PendingImportWrite

const pendingWrite = ref<PendingWrite | null>(null)

function makeSavePending(
  body: CollaborationSaveInput,
  teacherId: string,
  schoolId: string,
): PendingSaveWrite {
  return {
    kind: 'save',
    requestId: body.request_id,
    body,
    classId: body.class_id,
    teacherId,
    schoolId,
    sourceTeacherId: null,
  }
}

function makeImportPending(
  body: CollaborationConfirmInput,
  classId: string,
  teacherId: string,
  schoolId: string,
): PendingImportWrite {
  return {
    kind: 'import',
    requestId: body.request_id,
    body,
    classId,
    teacherId,
    schoolId,
    sourceTeacherId: body.source_teacher_id,
  }
}

const draftActive = computed(
  () =>
    pendingWrite.value !== null
    || preview.value !== null
    || publishPreview.value !== null
    || previewStale.value
    || previewingSourceId.value !== ''
    || publishing.value
    || confirming.value,
)
const draftTargets = computed(() => (draftActive.value ? ['online-collaboration'] : []))

watch(
  draftActive,
  (value) => emit('draft-active', value),
  { immediate: true },
)

const recoveryBusy = computed(() => querying.value || resubmitting.value)
const classTransition = computed(
  () =>
    selectingClassId.value !== ''
    || leavingClass.value
    || loadingDirectory.value
    || loadingClass.value,
)
const canDisconnect = computed(
  () =>
    status.value.connected
    && !props.frozen
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !publishing.value
    && !confirming.value
    && previewingSourceId.value === ''
    && preview.value === null
    && publishPreview.value === null,
)
const canSelectClass = computed(
  () =>
    status.value.connected
    && !props.frozen
    && !classSelectionUnknown.value
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !publishing.value
    && !confirming.value
    && previewingSourceId.value === ''
    && preview.value === null
    && publishPreview.value === null,
)
const canLeaveClass = canSelectClass
const canReadLocalPublish = computed(
  () =>
    status.value.connected
    && !props.frozen
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !publishing.value
    && !confirming.value
    && previewingSourceId.value === ''
    && preview.value === null
    && publishPreview.value === null
    && membership.value !== null
    && onlineConfig.value !== null,
)
const canConfirmPublish = computed(
  () =>
    status.value.connected
    && !props.frozen
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !publishing.value
    && !confirming.value
    && publishPreview.value !== null
    && !publishConflict.value
    && onlineConfig.value !== null
    && onlineConfig.value.config_version === publishPreview.value.expectedVersion,
)
const publishVersionStale = computed(
  () =>
    publishPreview.value !== null
    && (
      publishConflict.value
      || (
        onlineConfig.value !== null
        && onlineConfig.value.config_version !== publishPreview.value.expectedVersion
      )
    ),
)
const canConfirm = computed(
  () =>
    status.value.connected
    && preview.value !== null
    && !previewStale.value
    && !props.frozen
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !confirming.value
    && !publishing.value
    && publishPreview.value === null,
)

function sameLocation(left: GameLocation | null, right: GameLocation | null): boolean {
  if (!left || !right) return false
  return (
    left.kind === right.kind
    && left.name === right.name
    && left.guidance === right.guidance
  )
}

const locationDiffRows = computed(() => {
  const value = preview.value
  if (!value) return []
  const source = value.diff.locations.source
  const target = value.diff.locations.target
  const rows: Array<{
    index: number
    source: GameLocation | null
    target: GameLocation | null
    state: string
  }> = []
  const total = Math.max(source.length, target.length)
  for (let index = 0; index < total; index += 1) {
    const left = source[index] ?? null
    const right = target[index] ?? null
    let state = '相同'
    if (left !== null && right !== null) {
      state = sameLocation(left, right) ? '相同' : '变更'
    } else if (left !== null) {
      state = '对方有、本人无'
    } else {
      state = '本人有、对方无'
    }
    rows.push({ index, source: left, target: right, state })
  }
  return rows
})

function current(epoch: number): boolean {
  return alive && epoch === scopeEpoch
}
function advanceScope(): number {
  scopeEpoch += 1
  return scopeEpoch
}
function clearCredential(): void {
  credential.value = ''
}
function clearClassConfiguration(): void {
  membership.value = null
  classmates.value = []
  onlineConfig.value = null
  preview.value = null
  previewStale.value = false
  publishPreview.value = null
  publishConflict.value = false
}
function clearSessionData(): void {
  classes.value = []
  classSelectionUnknown.value = false
  classSelectionUnknownMessage.value = ''
  clearClassConfiguration()
}
function markClassStateUnknown(message: string): void {
  classSelectionUnknown.value = true
  classSelectionUnknownMessage.value = message
  clearClassConfiguration()
  errorText.value = ''
}
function markDisconnected(): void {
  // Invalidate every late response before clearing the mirror.  A pending
  // write and its preview/draft stay visible even if the connection failed;
  // they are only cleared by a confirmed receipt or an explicit cancel when
  // no write is pending.
  scopeEpoch += 1
  clearCredential()
  if (!pendingWrite.value) clearSessionData()
  connecting.value = false
  disconnecting.value = false
  loadingDirectory.value = false
  loadingClass.value = false
  selectingClassId.value = ''
  leavingClass.value = false
  publishing.value = false
  confirming.value = false
  previewingSourceId.value = ''
  querying.value = false
  resubmitting.value = false
  status.value = {
    ...status.value,
    connected: false,
    teacher: null,
    message: '在线协作连接已失效，请重新连接',
  }
}
function handleError(err: unknown, fallback: string): void {
  errorText.value = collaborationErrorMessage(err, fallback)
  if (isCollaborationSessionInvalidError(err)) {
    markDisconnected()
  }
}
function kindLabel(kind: GameLocation['kind']): string {
  if (kind === 'area') return '区域'
  if (kind === 'special_room') return '专用室'
  return '户外场地'
}
function formatLocation(location: GameLocation | null): string {
  if (!location) return '（无）'
  const guidance = location.guidance ? `（${location.guidance}）` : ''
  return `${kindLabel(location.kind)}：${location.name}${guidance}`
}
function formatText(value: string | null): string {
  return value === null || value === '' ? '（空）' : value
}
function diffState(changed: boolean): string {
  return changed ? '有变化' : '相同'
}

async function refreshStatus(): Promise<void> {
  const epoch = scopeEpoch
  try {
    const result = await api.status()
    if (current(epoch)) {
      status.value = result
      statusLoaded.value = true
    }
  } catch {
    if (current(epoch)) {
      status.value = {
        configured: false,
        connected: false,
        teacher: null,
        message: '无法读取在线协作配置，请确认本地服务可用',
      }
      statusLoaded.value = true
    }
  }
}

async function loadClassData(epoch: number): Promise<void> {
  if (!membership.value) {
    classmates.value = []
    onlineConfig.value = null
    return
  }
  loadingClass.value = true
  try {
    classmates.value = []
    onlineConfig.value = null
    const [mates, own] = await Promise.all([
      api.classmates(),
      api.ownConfig(),
    ])
    if (!current(epoch)) return
    if (own.class_id !== membership.value.class_id) {
      errorText.value = '在线班级已变化，请重新读取班级和配置'
      return
    }
    classmates.value = mates
    onlineConfig.value = own
  } catch (err) {
    if (current(epoch)) handleError(err, '读取同班老师或在线配置失败')
  } finally {
    if (current(epoch)) loadingClass.value = false
  }
}

async function loadDirectory(epoch: number): Promise<void> {
  loadingDirectory.value = true
  try {
    const [classList, currentMembership] = await Promise.all([
      api.classes(),
      api.membership(),
    ])
    if (!current(epoch)) return
    classes.value = classList
    membership.value = currentMembership
    classSelectionUnknown.value = false
    classSelectionUnknownMessage.value = ''
    preview.value = null
    previewStale.value = false
    publishPreview.value = null
    publishConflict.value = false
    if (currentMembership) {
      await loadClassData(epoch)
    } else {
      classmates.value = []
      onlineConfig.value = null
    }
  } catch (err) {
    if (current(epoch)) handleError(err, '读取园所班级目录失败')
  } finally {
    if (current(epoch)) loadingDirectory.value = false
  }
}

async function connect(): Promise<void> {
  if (
    props.frozen
    || connecting.value
    || !statusLoaded.value
    || !status.value.configured
  ) return
  const value = credential.value.trim()
  if (!value) {
    errorText.value = '请输入部署方提供的登录凭据'
    return
  }
  const pending = pendingWrite.value
  if (pending && (!pending.teacherId || !pending.schoolId)) {
    errorText.value = '待核对请求缺少原在线账号绑定，不能恢复；原请求和草稿仍保留'
    return
  }
  const epoch = advanceScope()
  connecting.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.connect(
      value,
      pending
        ? { teacherId: pending.teacherId, schoolId: pending.schoolId }
        : null,
    )
    if (!current(epoch)) return
    if (pending && pendingWrite.value) {
      // The local proxy already verified /me against both IDs before it
      // installed this session.  Keep the original class and preview state.
      status.value = result
      noticeText.value = '已重新连接原在线账号；原请求仍待核对，请只读查询或明确再次提交'
      return
    }
    status.value = result
    await loadDirectory(epoch)
    if (current(epoch) && status.value.connected) {
      noticeText.value = `已连接在线协作：${result.teacher?.display_name ?? '在线教师'}`
    }
  } catch (err) {
    if (!current(epoch)) return
    handleError(err, '连接在线协作失败')
  } finally {
    clearCredential()
    if (current(epoch)) connecting.value = false
  }
}

async function disconnect(): Promise<void> {
  if (disconnecting.value) return
  if (props.frozen || pendingWrite.value) {
    if (pendingWrite.value) errorText.value = '在线写入仍待核对，不能断开或切换账号'
    return
  }
  const epoch = advanceScope()
  disconnecting.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.disconnect()
    if (!current(epoch)) return
    status.value = result
    clearSessionData()
    clearCredential()
    noticeText.value = '已断开在线协作；本地配置未发生变化'
  } catch (err) {
    if (current(epoch)) handleError(err, '断开在线协作失败，请重试')
  } finally {
    if (current(epoch)) disconnecting.value = false
  }
}

async function reloadOnline(): Promise<void> {
  if (
    props.frozen
    || pendingWrite.value
    || connecting.value
    || disconnecting.value
    || publishing.value
    || confirming.value
    || previewingSourceId.value !== ''
    || loadingDirectory.value
    || loadingClass.value
  ) {
    return
  }
  if (!status.value.connected) {
    await refreshStatus()
    if (!status.value.connected) return
  }
  if (publishPreview.value) {
    errorText.value = '请先取消发布预览后再重新读取'
    return
  }
  if (preview.value && !previewStale.value) {
    errorText.value = '请先取消当前预览或确认后再重新读取'
    return
  }
  const epoch = advanceScope()
  errorText.value = ''
  noticeText.value = ''
  preview.value = null
  previewStale.value = false
  await loadDirectory(epoch)
}

async function selectClass(classId: string): Promise<void> {
  if (selectingClassId.value !== '' || leavingClass.value) return
  if (!canSelectClass.value || !status.value.connected) return
  if (preview.value) {
    errorText.value = '请先取消当前预览再切换班级'
    return
  }
  const epoch = advanceScope()
  selectingClassId.value = classId
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.selectClass(classId)
    if (!current(epoch)) return
    membership.value = result
    classmates.value = []
    onlineConfig.value = null
    preview.value = null
    previewStale.value = false
    classSelectionUnknown.value = false
    classSelectionUnknownMessage.value = ''
    await loadClassData(epoch)
    if (current(epoch)) noticeText.value = `已选择在线班级：${result.class_name}`
  } catch (err) {
    if (!current(epoch)) return
    if (collaborationWriteIndeterminate(err)) {
      if (isCollaborationSessionInvalidError(err)) {
        markDisconnected()
      }
      markClassStateUnknown(
        '选择班级结果未确认：已停止使用旧班配置，请重新读取班级目录核对',
      )
      return
    }
    if (
      err instanceof ApiError
      && err.code === 'COLLABORATION_MEMBERSHIP_CHANGED'
    ) {
      markClassStateUnknown(
        '当前班级或同班关系已变化：已停止使用旧班配置，请重新读取班级目录核对',
      )
      return
    }
    handleError(err, '选择在线班级失败')
  } finally {
    if (current(epoch)) selectingClassId.value = ''
  }
}

async function leaveClass(): Promise<void> {
  if (selectingClassId.value !== '' || leavingClass.value) return
  if (!canLeaveClass.value || !status.value.connected) return
  if (preview.value) {
    errorText.value = '请先取消当前预览再退出班级'
    return
  }
  const epoch = advanceScope()
  leavingClass.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    await api.leaveClass()
    if (!current(epoch)) return
    membership.value = null
    classmates.value = []
    onlineConfig.value = null
    preview.value = null
    previewStale.value = false
    classSelectionUnknown.value = false
    classSelectionUnknownMessage.value = ''
    noticeText.value = '已退出当前在线班级；本地配置未发生变化'
  } catch (err) {
    if (!current(epoch)) return
    if (collaborationWriteIndeterminate(err)) {
      if (isCollaborationSessionInvalidError(err)) {
        markDisconnected()
      }
      markClassStateUnknown(
        '退出班级结果未确认：已停止使用旧班配置，请重新读取班级目录核对',
      )
      return
    }
    if (
      err instanceof ApiError
      && err.code === 'COLLABORATION_MEMBERSHIP_CHANGED'
    ) {
      markClassStateUnknown(
        '当前班级或同班关系已变化：已停止使用旧班配置，请重新读取班级目录核对',
      )
      return
    }
    handleError(err, '退出在线班级失败')
  } finally {
    if (current(epoch)) leavingClass.value = false
  }
}

function applySavedConfig(result: CollaborationSaveResult): boolean {
  if (membership.value && result.class_id !== membership.value.class_id) {
    errorText.value = '发布回执属于原在线班级，未更新当前显示的配置'
    return false
  }
  onlineConfig.value = {
    class_id: result.class_id,
    config_version: result.config_version,
    payload: result.payload,
  }
  return true
}

function applyConfirmResult(result: CollaborationConfirmResult): boolean {
  if (membership.value && result.class_id !== membership.value.class_id) {
    errorText.value = '带入回执属于原在线班级，未更新当前显示的配置'
    return false
  }
  onlineConfig.value = {
    class_id: result.class_id,
    config_version: result.config_version,
    payload: result.payload,
  }
  return true
}

async function previewLocalPublish(): Promise<void> {
  if (
    !canReadLocalPublish.value
    || !membership.value
    || !onlineConfig.value
  ) {
    return
  }
  publishing.value = true
  errorText.value = ''
  noticeText.value = ''
  const epoch = scopeEpoch
  let local: ClassGames
  try {
    // Explicit read only after the teacher chooses to inspect the local
    // configuration.  The local class and revision identities never cross
    // the online boundary.
    local = await apiGet<ClassGames>('/api/local/config/class-games')
  } catch (err) {
    if (alive) {
      errorText.value = (
        err instanceof ApiError
        && typeof err.code === 'string'
        && err.code !== ''
        && err.status !== 0
      )
        ? err.message
        : '读取本地班级游戏配置失败，请稍后重试'
    }
    publishing.value = false
    return
  }
  publishing.value = false
  if (!alive || epoch !== scopeEpoch) return
  publishPreview.value = {
    classId: membership.value.class_id,
    classLabel: membership.value.class_name,
    localClassName: local.class_name,
    localRevisionNo: local.revision_no,
    expectedVersion: onlineConfig.value.config_version,
    locations: local.change.locations.map((location) => ({
      kind: location.kind,
      name: location.name,
      guidance: location.guidance,
    })),
    gameScope: local.change.game_scope,
    guidance: local.change.guidance,
  }
  publishConflict.value = false
  noticeText.value = '已读取本地班级游戏配置；确认发布前不会写入在线配置'
}

function cancelLocalPublish(): void {
  if (props.frozen) return
  if (pendingWrite.value) {
    errorText.value = '在线写入仍待核对，不能丢弃当前发布预览'
    return
  }
  if (publishing.value) return
  publishPreview.value = null
  publishConflict.value = false
  errorText.value = ''
  noticeText.value = '已取消发布预览；没有写入在线配置'
}

async function rePreviewLocalPublish(): Promise<void> {
  if (
    props.frozen
    || pendingWrite.value
    || publishing.value
    || confirming.value
  ) {
    return
  }
  const epoch = advanceScope()
  publishPreview.value = null
  publishConflict.value = false
  await loadDirectory(epoch)
  if (!current(epoch)) return
  await previewLocalPublish()
}

async function confirmLocalPublish(): Promise<void> {
  const draft = publishPreview.value
  if (!draft || !canConfirmPublish.value || !membership.value) return
  if (draft.classId !== membership.value.class_id) {
    publishConflict.value = true
    errorText.value = '当前在线班级已变化：请取消发布预览后重新读取'
    return
  }
  const body: CollaborationSaveInput = {
    request_id: crypto.randomUUID(),
    class_id: draft.classId,
    expected_version: draft.expectedVersion,
    change: {
      kind: 'class_games',
      locations: draft.locations.map((location) => ({
        kind: location.kind,
        name: location.name,
        guidance: location.guidance,
      })),
      game_scope: draft.gameScope,
      guidance: draft.guidance,
    },
  }
  const epoch = scopeEpoch
  const pendingTeacherId =
    status.value.teacher?.teacher_id ?? membership.value?.teacher_id ?? ''
  const pendingSchoolId =
    status.value.teacher?.school_id ?? membership.value?.school_id ?? ''
  publishing.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.saveConfig(body)
    if (!alive) return
    if (epoch !== scopeEpoch) {
      pendingWrite.value = makeSavePending(
        body,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '连接状态已变化：已保留原发布请求，请重新连接后核对回执'
      return
    }
    if (!applySavedConfig(result)) return
    publishPreview.value = null
    publishConflict.value = false
    noticeText.value = result.changed
      ? `已发布当前本地班级游戏配置到在线 v${result.config_version}`
      : `在线配置已是最新（v${result.config_version}），未产生变化`
  } catch (err) {
    if (!alive) return
    if (epoch !== scopeEpoch) {
      pendingWrite.value = makeSavePending(
        body,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '连接状态已变化：已保留原发布请求，请重新连接后核对回执'
      return
    }
    if (collaborationWriteIndeterminate(err)) {
      pendingWrite.value = makeSavePending(
        body,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '发布结果未确认：已保留原请求和当前发布预览，请只读查询或明确再次提交'
    } else {
      if (isCollaborationConflictError(err)) {
        publishConflict.value = true
        errorText.value = '在线配置或班级关系已变化：当前发布预览已保留，请重新读取在线配置并预览'
      } else {
        handleError(err, '发布在线班级游戏配置失败')
      }
    }
  } finally {
    publishing.value = false
  }
}

function canPreviewSource(mate: CollaborationClassmate): boolean {
  return (
    status.value.connected
    && !props.frozen
    && !pendingWrite.value
    && !connecting.value
    && !disconnecting.value
    && !classTransition.value
    && !publishing.value
    && !confirming.value
    && previewingSourceId.value === ''
    && preview.value === null
    && publishPreview.value === null
    && membership.value !== null
    && mate.config_version > 0
  )
}

async function previewSource(
  mate: CollaborationClassmate,
  epochArg?: number,
): Promise<void> {
  if (!canPreviewSource(mate)) return
  const epoch = epochArg ?? scopeEpoch
  if (!membership.value) return
  previewingSourceId.value = mate.teacher_id
  preview.value = null
  previewStale.value = false
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.previewImport({
      request_id: crypto.randomUUID(),
      class_id: membership.value.class_id,
      source_teacher_id: mate.teacher_id,
    })
    if (!current(epoch)) return
    if (
      result.class_id !== membership.value.class_id
      || result.source_teacher_id !== mate.teacher_id
    ) {
      errorText.value = '预览返回的班级或来源与请求不一致，未采用'
      return
    }
    preview.value = result
  } catch (err) {
    if (!current(epoch)) return
    handleError(err, '读取带入预览失败')
  } finally {
    if (current(epoch)) previewingSourceId.value = ''
  }
}

async function rePreviewSameSource(): Promise<void> {
  if (
    !status.value.connected
    || !preview.value
    || pendingWrite.value
    || props.frozen
    || confirming.value
    || publishing.value
    || publishPreview.value !== null
  ) {
    return
  }
  const sourceId = preview.value.source_teacher_id
  const epoch = advanceScope()
  errorText.value = ''
  noticeText.value = ''
  preview.value = null
  previewStale.value = false
  await loadDirectory(epoch)
  if (!current(epoch)) return
  const mate = classmates.value.find((item) => item.teacher_id === sourceId)
  if (!mate) {
    errorText.value = '该老师已不在当前班级或没有可用配置'
    return
  }
  await previewSource(mate, epoch)
}

async function confirmPreview(): Promise<void> {
  const value = preview.value
  if (!value || !canConfirm.value) return
  const body: CollaborationConfirmInput = {
    request_id: value.request_id,
    preview_token: value.preview_token,
    source_teacher_id: value.source_teacher_id,
    source_version: value.source_version,
    target_version: value.target_version,
  }
  const epoch = scopeEpoch
  const pendingTeacherId =
    status.value.teacher?.teacher_id ?? membership.value?.teacher_id ?? ''
  const pendingSchoolId =
    status.value.teacher?.school_id ?? membership.value?.school_id ?? ''
  confirming.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = await api.confirmImport(body)
    if (!alive) return
    if (pendingWrite.value) return
    if (epoch !== scopeEpoch) {
      pendingWrite.value = makeImportPending(
        body,
        value.class_id,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '连接状态已变化：已保留原带入请求和当前预览，请重新连接后核对回执'
      return
    }
    if (!applyConfirmResult(result)) return
    preview.value = null
    previewStale.value = false
    noticeText.value = result.changed
      ? `已带入并保存到本人当前在线配置 v${result.config_version}`
      : '双方配置相同，未产生写入变化'
  } catch (err) {
    if (!alive) return
    if (epoch !== scopeEpoch) {
      pendingWrite.value = makeImportPending(
        body,
        value.class_id,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '连接状态已变化：已保留原带入请求和当前预览，请重新连接后核对回执'
      return
    }
    if (collaborationWriteIndeterminate(err)) {
      pendingWrite.value = makeImportPending(
        body,
        value.class_id,
        pendingTeacherId,
        pendingSchoolId,
      )
      errorText.value = '带入结果未确认：已保留原请求和当前预览，请只读查询或明确再次提交'
    } else if (isCollaborationConflictError(err)) {
      previewStale.value = true
      errorText.value = '预览依据的版本或班级关系已变化：已保留当前预览，请重新读取并预览后再确认'
    } else {
      handleError(err, '确认带入失败')
    }
  } finally {
    confirming.value = false
  }
}

function cancelPreview(): void {
  if (props.frozen) return
  if (pendingWrite.value) {
    errorText.value = '在线写入仍待核对，不能丢弃当前预览或浏览上下文'
    return
  }
  if (confirming.value || previewingSourceId.value !== '') return
  preview.value = null
  previewStale.value = false
  errorText.value = ''
  noticeText.value = '已取消预览；没有写入在线配置'
}

async function queryPending(): Promise<void> {
  const pending = pendingWrite.value
  if (!pending || recoveryBusy.value || props.frozen) return
  querying.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const operation = await api.getOperation(pending.requestId)
    if (pendingWrite.value !== pending) return
    if (
      operation.request_id !== pending.requestId
      || operation.kind !== pending.kind
    ) {
      errorText.value = '查询回执与当前待核对请求不一致，未采用'
      return
    }
    finishPending(pending, operation.result)
  } catch (err) {
    if (pendingWrite.value !== pending) return
    if (
      err instanceof ApiError
      && (err.status === 404 || err.code === 'COLLABORATION_OPERATION_NOT_FOUND')
    ) {
      noticeText.value = '尚未查到提交回执；原请求仍待核对，不会自动重发'
    } else if (isCollaborationSessionInvalidError(err)) {
      markDisconnected()
      errorText.value = '在线协作连接已失效或变化；原请求仍待核对，请用原账号重连后查询'
    } else {
      errorText.value = '查询暂不可用：原请求仍待核对，请稍后重试'
    }
  } finally {
    querying.value = false
  }
}

function finishPending(
  pending: PendingWrite,
  result: CollaborationSaveResult | CollaborationConfirmResult,
): void {
  let applied = true
  if (pending.kind === 'save') {
    applied = applySavedConfig(result as CollaborationSaveResult)
    if (applied) {
      publishPreview.value = null
      publishConflict.value = false
      noticeText.value = '已通过原请求回执确认在线发布结果'
    }
  } else {
    applied = applyConfirmResult(result as CollaborationConfirmResult)
    if (applied) {
      preview.value = null
      previewStale.value = false
      noticeText.value = '已通过原请求回执确认带入结果'
    }
  }
  pendingWrite.value = null
  if (applied) errorText.value = ''
}

async function resubmitPending(): Promise<void> {
  const pending = pendingWrite.value
  if (!pending || recoveryBusy.value || props.frozen) return
  resubmitting.value = true
  errorText.value = ''
  noticeText.value = ''
  try {
    const result = pending.kind === 'save'
      ? await api.saveConfig(pending.body)
      : await api.confirmImport(pending.body)
    if (pendingWrite.value !== pending) return
    finishPending(pending, result)
  } catch (err) {
    if (pendingWrite.value !== pending) return
    if (collaborationWriteIndeterminate(err)) {
      if (
        err instanceof ApiError
        && err.code === 'COLLABORATION_SESSION_CHANGED'
      ) {
        markDisconnected()
        errorText.value = '在线协作连接已变化：原请求和 request_id 已保留，请用原账号重连后查询'
      } else {
        errorText.value = '再次提交仍未确认：原请求和 request_id 已保留，请继续只读查询'
      }
    } else if (isCollaborationResubmitUncommittedError(err, pending.kind)) {
      // The service checked this request's receipt first, then rejected the
      // same request on an expiry/version/membership recheck.  That proves
      // this request did not commit; restore its preview for an explicit
      // re-read/re-preview instead of leaving an unknowable receipt.
      pendingWrite.value = null
      errorText.value = ''
      if (pending.kind === 'import') {
        previewStale.value = true
        noticeText.value = '服务端确认原带入请求未提交：已恢复原预览，请重新读取并预览后再确认'
      } else {
        publishConflict.value = true
        noticeText.value = '服务端确认原发布请求未提交：已恢复发布预览，请重新读取后再发布'
      }
    } else {
      errorText.value = collaborationErrorMessage(
        err,
        '再次提交被拒绝：原请求仍待核对，请继续只读查询',
      )
      if (isCollaborationSessionInvalidError(err)) markDisconnected()
    }
  } finally {
    resubmitting.value = false
  }
}

onMounted(() => {
  void refreshStatus()
})

onBeforeUnmount(() => {
  alive = false
  scopeEpoch += 1
  clearCredential()
  emit('draft-active', false)
})

defineExpose({
  isDraftActive: () => draftActive.value,
  draftTargets: () => draftTargets.value,
  currentStatus: () => status.value,
  currentPreview: () => preview.value,
  currentPublishPreview: () => publishPreview.value,
  pendingWrite: () => pendingWrite.value,
  connect,
  disconnect,
  reloadOnline,
  cancelPreview,
  cancelLocalPublish,
})
</script>

<template>
  <el-card class="collaboration" shadow="never" data-d1="collaboration">
    <template #header>
      <div class="head">
        <span>在线协作（独立于本地）</span>
        <el-tag v-if="status.connected" size="small" type="success">已连接</el-tag>
        <el-tag v-else size="small" type="info">未连接</el-tag>
        <el-tag v-if="pendingWrite" size="small" type="danger">有未决写入</el-tag>
        <el-tag v-if="preview" size="small" type="warning">预览中（未写入）</el-tag>
      </div>
    </template>

    <el-alert
      title="在线协作使用独立的在线配置；本地 SQLite、本地班级游戏设置和本地记录不会被自动上传。凭据只用于本次连接，保存在本机进程内存，不写入数据库或浏览器存储。"
      type="info"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="statusLoaded && !status.configured"
      :title="status.message ?? '未配置在线协作服务地址，请联系部署方'"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-button
      v-if="statusLoaded && !status.configured"
      size="small"
      :disabled="frozen"
      @click="refreshStatus"
    >
      重新读取本地配置
    </el-button>
    <el-alert
      v-if="classSelectionUnknown"
      :title="classSelectionUnknownMessage || '班级变更结果未确认：已停止使用旧班配置，不能继续读取或发布班级游戏配置。请重新读取园所班级目录核对后再操作。'"
      type="warning"
      :closable="false"
      show-icon
      data-d1="collaboration-class-unknown"
    />
    <el-button
      v-if="classSelectionUnknown"
      size="small"
      :loading="loadingDirectory"
      :disabled="frozen || pendingWrite !== null || connecting || disconnecting"
      @click="reloadOnline"
    >
      重新读取班级目录
    </el-button>
    <el-alert
      v-if="pendingWrite"
      :title="`有未确认的在线写入（request_id：${pendingWrite.requestId}）。待核对期间不能换班、换账号或丢弃预览；请只读查询或明确再次提交原请求。若连接已断开，可用原账号凭据重新连接后查询。`"
      type="warning"
      :closable="false"
      show-icon
      data-d1="collaboration-pending"
    />
    <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" data-d1="collaboration-error" />
    <el-alert v-if="noticeText" :title="noticeText" type="success" :closable="false" data-d1="collaboration-notice" />
    <div v-if="pendingWrite" class="pending-actions" data-d1="collaboration-pending-actions">
      <el-button size="small" :loading="querying" :disabled="frozen || recoveryBusy" @click="queryPending">只读查询原请求</el-button>
      <el-button size="small" type="warning" :loading="resubmitting" :disabled="frozen || recoveryBusy" @click="resubmitPending">
        明确再次提交原请求
      </el-button>
    </div>

    <section class="step" data-d1="collaboration-connect">
      <h3>1. 连接在线协作</h3>
      <template v-if="!status.connected">
        <p class="muted">输入部署方发给你的登录凭据。连接前会先验证在线身份。</p>
        <div class="connect-row">
          <el-input
            v-model="credential"
            type="password"
            autocomplete="off"
            placeholder="部署方提供的登录凭据"
            :disabled="frozen || connecting || !statusLoaded || !status.configured"
            data-d1="collaboration-credential"
            @keyup.enter="connect"
          />
          <el-button
            type="primary"
            :loading="connecting"
            :disabled="frozen || connecting || !statusLoaded || !status.configured || !credential.trim()"
            data-d1="collaboration-connect-button"
            @click="connect"
          >
            连接在线协作
          </el-button>
        </div>
      </template>
      <template v-else>
        <p>
          已连接：{{ status.teacher?.display_name ?? '在线教师' }}
          <span class="muted">（{{ status.teacher?.school_name ?? '在线园所' }}）</span>
        </p>
        <el-button
          size="small"
          :loading="disconnecting"
          :disabled="!canDisconnect"
          data-d1="collaboration-disconnect"
          @click="disconnect"
        >
          断开在线协作
        </el-button>
      </template>
    </section>

    <template v-if="status.connected || pendingWrite">
      <section class="step" data-d1="collaboration-classes">
        <h3>2. 选择园所目录中的系统班级</h3>
        <p class="muted">只使用服务端返回的真实班级 ID；显示名称仅用于辨认，不按同名班级配对。</p>
        <el-button
          size="small"
          :loading="loadingDirectory"
          :disabled="frozen || pendingWrite !== null || connecting || disconnecting"
          data-d1="collaboration-load-classes"
          @click="reloadOnline"
        >
          读取 / 刷新班级目录
        </el-button>
        <div v-if="classes.length" class="class-list">
          <div v-for="item in classes" :key="item.class_id" class="class-row" data-d1="collaboration-class">
            <span>{{ item.display_name }}</span>
            <code class="class-id" :title="item.class_id">{{ item.class_id }}</code>
            <el-tag v-if="membership?.class_id === item.class_id" size="small" type="success">当前班级</el-tag>
            <el-button
              size="small"
              :loading="selectingClassId === item.class_id"
              :disabled="!canSelectClass || membership?.class_id === item.class_id"
              @click="selectClass(item.class_id)"
            >
              选择此班
            </el-button>
          </div>
        </div>
        <p v-else class="muted">尚未读取班级目录。</p>
        <div v-if="membership" class="membership" data-d1="collaboration-membership">
          <p>
            当前在线班级：{{ membership.class_name }}
            <span class="muted">（稳定 ID：{{ membership.class_id }}）</span>
          </p>
          <el-button
            size="small"
            :loading="leavingClass"
            :disabled="!canLeaveClass"
            @click="leaveClass"
          >
            退出当前在线班级
          </el-button>
        </div>
        <p v-else class="muted">请从上方目录选择一个班级。</p>
      </section>

      <section v-if="membership" class="step" data-d1="collaboration-game-config">
        <h3>3. 在线班级游戏配置与同班老师</h3>
        <p class="muted">在线配置与本地配置分开显示；在线写入只影响在线协作，不改写本地 SQLite。</p>
        <div v-if="onlineConfig" class="online-current" data-d1="collaboration-online-config">
          <p>本人当前在线配置 v{{ onlineConfig.config_version }}</p>
          <p v-if="onlineConfig.payload.locations.length">
            地点：{{ onlineConfig.payload.locations.map(formatLocation).join('；') }}
          </p>
          <p v-else class="muted">本人尚未设置在线地点。</p>
          <p>游戏范围：{{ formatText(onlineConfig.payload.game_scope) }}</p>
          <p>通用限制 / 指导：{{ formatText(onlineConfig.payload.guidance) }}</p>
        </div>
        <p v-else class="muted">正在读取本人当前在线配置…</p>
        <div class="actions">
          <el-button
            size="small"
            :disabled="frozen || pendingWrite !== null || publishing || confirming || previewingSourceId !== ''"
            @click="reloadOnline"
          >
            重新读取在线配置
          </el-button>
          <el-button
            size="small"
            type="primary"
            :loading="publishing"
            :disabled="!canReadLocalPublish"
            data-d1="collaboration-publish-local"
            @click="previewLocalPublish"
          >
            读取本地配置并预览发布
          </el-button>
        </div>
        <p class="muted">
          只有点击上方按钮时才读取本地“班级游戏配置”。随后先显示预览，教师再次确认才写入在线配置；只发送地点、游戏范围和班级游戏指导，不会读取或上传日计划、幼儿档案、照片或 AI 内容。
        </p>
        <div v-if="publishPreview" class="preview publish-preview" data-d1="collaboration-publish-preview">
          <h4>本地配置发布预览（尚未写入）</h4>
          <p>
            本地班级：{{ publishPreview.localClassName }} · 本地修订
            #{{ publishPreview.localRevisionNo }} → 在线班级：
            {{ publishPreview.classLabel }} · 基准在线版本
            v{{ publishPreview.expectedVersion }}
          </p>
          <el-alert
            v-if="publishVersionStale"
            title="在线配置或班级关系已变化。当前发布预览已保留，但不能再确认；请重新读取在线配置并预览，或取消预览。"
            type="warning"
            :closable="false"
            data-d1="collaboration-publish-stale"
          />
          <div class="diff-block">
            <h5>地点</h5>
            <p v-if="publishPreview.locations.length">
              {{ publishPreview.locations.map(formatLocation).join('；') }}
            </p>
            <p v-else class="muted">（无）</p>
          </div>
          <div class="diff-block">
            <h5>游戏范围</h5>
            <p>{{ formatText(publishPreview.gameScope) }}</p>
          </div>
          <div class="diff-block">
            <h5>通用限制 / 指导</h5>
            <p>{{ formatText(publishPreview.guidance) }}</p>
          </div>
          <div class="actions">
            <el-button
              size="small"
              type="primary"
              :loading="publishing"
              :disabled="!canConfirmPublish"
              data-d1="collaboration-confirm-publish"
              @click="confirmLocalPublish"
            >
              确认发布（一次写入本人当前在线配置）
            </el-button>
            <el-button
              size="small"
              :disabled="frozen || pendingWrite !== null || publishing"
              @click="cancelLocalPublish"
            >
              取消发布预览（零写）
            </el-button>
            <el-button
              v-if="publishVersionStale"
              size="small"
              :disabled="frozen || pendingWrite !== null || publishing"
              @click="rePreviewLocalPublish"
            >
              重新读取在线配置并预览本地
            </el-button>
          </div>
        </div>

        <h4>同班老师</h4>
        <p class="muted">只显示服务端按当前班级自动配对的同班老师；班级关系由服务端重新检查。</p>
        <el-table
          v-if="classmates.length"
          :data="classmates"
          size="small"
          data-d1="collaboration-classmates"
        >
          <el-table-column prop="display_name" label="同班老师" min-width="140" />
          <el-table-column label="在线配置版本" width="120">
            <template #default="{ row }">
              <span v-if="row.config_version > 0">v{{ row.config_version }}</span>
              <span v-else class="muted">尚无配置</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button
                size="small"
                :loading="previewingSourceId === row.teacher_id"
                :disabled="!canPreviewSource(row)"
                @click="previewSource(row)"
              >
                预览带入
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="muted">当前班级暂无其他同班老师。</p>

        <div v-if="preview" class="preview" data-d1="collaboration-preview">
          <h4>带入预览（尚未写入）</h4>
          <p>
            对方：{{ preview.source_teacher_name }} · 来源 v{{ preview.source_version }}
            <span class="muted"> → 本人基准 v{{ preview.target_version }}</span>
          </p>
          <el-alert
            v-if="previewStale"
            title="预览依据的版本或班级关系已变化。当前预览已保留，但不能再确认；请重新读取并预览，或取消预览。"
            type="warning"
            :closable="false"
            data-d1="collaboration-preview-stale"
          />
          <div class="diff-block">
            <h5>地点</h5>
            <el-table :data="locationDiffRows" size="small">
              <el-table-column label="对方" min-width="180">
                <template #default="{ row }">{{ formatLocation(row.source) }}</template>
              </el-table-column>
              <el-table-column label="本人" min-width="180">
                <template #default="{ row }">{{ formatLocation(row.target) }}</template>
              </el-table-column>
              <el-table-column label="差异" width="110">
                <template #default="{ row }">{{ row.state }}</template>
              </el-table-column>
            </el-table>
            <p v-if="!locationDiffRows.length" class="muted">双方都没有地点。</p>
          </div>
          <div class="diff-block">
            <h5>游戏范围 <el-tag size="small">{{ diffState(preview.diff.game_scope.changed) }}</el-tag></h5>
            <p>对方：{{ formatText(preview.diff.game_scope.source) }}</p>
            <p>本人：{{ formatText(preview.diff.game_scope.target) }}</p>
          </div>
          <div class="diff-block">
            <h5>通用限制 / 指导 <el-tag size="small">{{ diffState(preview.diff.guidance.changed) }}</el-tag></h5>
            <p>对方：{{ formatText(preview.diff.guidance.source) }}</p>
            <p>本人：{{ formatText(preview.diff.guidance.target) }}</p>
          </div>
          <div class="actions">
            <el-button
              size="small"
              type="primary"
              :loading="confirming"
              :disabled="!canConfirm"
              data-d1="collaboration-confirm-import"
              @click="confirmPreview"
            >
              确认带入（一次写入本人当前在线配置）
            </el-button>
            <el-button
              size="small"
              :disabled="frozen || pendingWrite !== null || confirming || previewingSourceId !== ''"
              @click="cancelPreview"
            >
              取消预览（零写）
            </el-button>
            <el-button
              v-if="previewStale"
              size="small"
              :disabled="pendingWrite !== null || confirming || publishing"
              @click="rePreviewSameSource"
            >
              重新读取并预览
            </el-button>
          </div>
        </div>

      </section>
    </template>
  </el-card>
</template>

<style scoped>
.collaboration { margin-bottom: 1rem; }
.head { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.step { margin-top: 1rem; }
.connect-row { display: flex; gap: 0.5rem; align-items: center; max-width: 620px; }
.class-list { margin: 0.5rem 0; }
.class-row { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; padding: 0.35rem 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.class-id { font-family: var(--el-font-family-mono, monospace); font-size: 0.75rem; color: var(--el-text-color-secondary); word-break: break-all; }
.membership { margin-top: 0.5rem; padding: 0.5rem; background: var(--el-fill-color-lighter); }
.online-current { margin: 0.5rem 0; padding: 0.5rem; background: var(--el-fill-color-lighter); }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.5rem 0; }
.preview { margin-top: 1rem; padding: 0.75rem; border: 1px solid var(--el-color-warning-light-5); }
.diff-block { margin-top: 0.75rem; }
.pending-actions { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
.muted { color: var(--el-text-color-secondary); }
</style>
