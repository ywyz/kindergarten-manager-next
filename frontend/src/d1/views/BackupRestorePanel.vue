<script setup lang="ts">
/**
 * B2 backup/restore panel.
 *
 * The panel owns presentation and the local confirmation/password state only.
 * Native file selection, file handles, page ticket/session, operation
 * idempotency and the actual backup/restore work are supplied by the host
 * adapter.  No path, PID, command, URL or base64 payload is handled here.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  canCancelPhase,
  canClosePhase,
  errorText,
  isActivePhase,
  isPhaseRegression,
  isTerminalPhase,
  newRequestId,
  operationRefOf,
  phaseText,
  progressLabel,
  progressPercent,
  REOPEN_FAILED_MESSAGE,
  resolveWebdavHost,
  statusMatchesRef,
  type BackupRestoreHost,
  type BackupTargetSelection,
  type MaintenanceCompletion,
  type MaintenanceErrorView,
  type MaintenanceKind,
  type MaintenanceOperationRef,
  type MaintenancePhase,
  type MaintenanceProgress,
  type MaintenanceStatus,
  type RestorePreviewView,
  type RestoreSelection,
  type WebdavConfigView,
  type WebdavVersionView,
} from '../backupMaintenance'

const props = defineProps<{
  open: boolean
  mode: 'setup' | 'settings'
  host: BackupRestoreHost
  frozen?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'busy', value: boolean): void
  (e: 'blocking', value: boolean): void
  (e: 'completed', value: MaintenanceCompletion): void
  (e: 'recovered'): void
}>()

const POLL_MS = 350

const webdav = resolveWebdavHost(props.host)

let disposed = false
let epoch = 0
let pollTimer: ReturnType<typeof setTimeout> | null = null
let polling = false
let cancelInFlight: Promise<void> | null = null

const phase = ref<MaintenancePhase>('idle')
const kind = ref<MaintenanceKind>('backup')
const startupDetail = ref('')
const progress = ref<MaintenanceProgress | undefined>()
const preview = ref<RestorePreviewView | null>(null)
const protection = ref<{ displayText: string } | null>(null)
const error = ref<MaintenanceErrorView | null>(null)
const backupTarget = ref<BackupTargetSelection | null>(null)
const selection = ref<RestoreSelection | null>(null)
const password = ref('')
const passwordChoice = ref<'password' | 'plaintext' | null>(null)
const plaintextAcknowledged = ref(false)
const confirmChecked = ref(false)
const operation = ref<MaintenanceOperationRef | null>(null)
const pendingRequestId = ref('')
const startUnconfirmed = ref(false)
const cancelRequested = ref(false)

// WebDAV (remote backup / cross-machine restore).  The endpoint password is
// only ever held in these local input refs until the host stores it with
// machine-local DPAPI protection; it is never part of a DTO or log.
const webdavAvailable = ref(true)
const webdavConfig = ref<WebdavConfigView | null>(null)
const webdavView = ref<'none' | 'config' | 'versions'>('none')
const webdavLoading = ref(false)
const webdavError = ref('')
const webdavNotice = ref('')
const webdavUrl = ref('')
const webdavUsername = ref('')
const webdavPassword = ref('')
const webdavVersions = ref<WebdavVersionView[]>([])
const webdavFingerprint = ref('')
const webdavSelected = ref<WebdavVersionView | null>(null)
const webdavPasswordOnly = ref(false)
const webdavSelectionId = ref('')
const backupTargetKind = ref<'local' | 'webdav'>('local')

const webdavConfigured = computed(
  () =>
    webdavAvailable.value &&
    webdavConfig.value?.configured === true &&
    webdavConfig.value?.passwordAvailable === true,
)
const webdavPasswordUnavailable = computed(
  () =>
    webdavConfig.value?.configured === true &&
    webdavConfig.value?.passwordAvailable === false,
)

const busy = computed(
  () =>
    props.open &&
    (pendingRequestId.value !== '' || isActivePhase(phase.value)),
)
const blocking = computed(
  () => props.open && (pendingRequestId.value !== '' || !isTerminalPhase(phase.value)),
)
const canStartBackup = computed(
  () => props.mode === 'settings' && phase.value === 'idle' && !props.frozen,
)
const canStartRestore = computed(
  () => phase.value === 'idle' && !props.frozen,
)
const canCancel = computed(
  () => props.open && !props.frozen && canCancelPhase(phase.value),
)
const canClose = computed(
  () =>
    props.open &&
    !props.frozen &&
    canClosePhase(phase.value) &&
    pendingRequestId.value === '',
)
const canConfirmPreview = computed(
  () =>
    phase.value === 'preview' &&
    preview.value !== null &&
    confirmChecked.value &&
    operation.value !== null &&
    !props.frozen,
)
const canSubmitCredentials = computed(() => {
  if (props.frozen) return false
  if (kind.value === 'backup' && webdavPasswordOnly.value) {
    return password.value.length > 0
  }
  if (passwordChoice.value === null && kind.value === 'backup') {
    return false
  }
  if (kind.value === 'restore') {
    return !selection.value?.encrypted || password.value.length > 0
  }
  if (passwordChoice.value === 'password') return password.value.length > 0
  return passwordChoice.value === 'plaintext' && plaintextAcknowledged.value
})
const passwordRequired = computed(() =>
  kind.value === 'restore'
    ? selection.value?.encrypted === true
    : webdavPasswordOnly.value || passwordChoice.value === 'password',
)
const canStartWebdavBackup = computed(
  () =>
    props.mode === 'settings' &&
    phase.value === 'idle' &&
    webdavConfigured.value &&
    !props.frozen &&
    webdavView.value === 'none',
)
const canOpenWebdavVersions = computed(
  () =>
    phase.value === 'idle' &&
    webdavConfigured.value &&
    !props.frozen,
)
const progressPercentValue = computed(() => progressPercent(progress.value))
const progressText = computed(() => progressLabel(progress.value))
const errorTextValue = computed(() => errorText(error.value ?? undefined))
const title = computed(() => {
  // The shared panel is also the first-setup entry; there it must not claim
  // that only a local file can be used.
  if (phase.value === 'idle' && props.mode === 'setup' && kind.value === 'restore') {
    return '从备份恢复'
  }
  return phaseText(phase.value, kind.value)
})
const credentialLabel = computed(() => {
  switch (preview.value?.credentialAvailability) {
    case 'available':
      return '同机加密凭据仍可用'
    case 'needs_reentry':
      return 'AI 凭据需重新填写'
    default:
      return 'AI 凭据可用性未知'
  }
})

watch(
  [busy, blocking],
  () => {
    emit('busy', busy.value)
    emit('blocking', blocking.value)
  },
  { immediate: true },
)

watch(
  () => [props.open, props.mode] as const,
  ([open]) => {
    if (open) void initialize()
    else resetLocal()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  disposed = true
  epoch += 1
  clearPoll()
  cancelInFlight = null
  password.value = ''
  webdavPassword.value = ''
  // A delivered WebDAV staging selection that was not consumed by a verify is
  // released here; the host refuses while an operation still owns it.
  releaseHeldWebdavSelection()
  emit('busy', false)
  emit('blocking', false)
})

function clearPoll(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  polling = false
}

function releaseHeldWebdavSelection(): void {
  const selectionId = webdavSelectionId.value
  webdavSelectionId.value = ''
  if (!selectionId) return
  void webdav.releaseWebdavSelection(selectionId).catch(() => undefined)
}

function resetWebdavView(): void {
  webdavView.value = 'none'
  webdavLoading.value = false
  webdavError.value = ''
  webdavNotice.value = ''
  webdavSelected.value = null
  webdavVersions.value = []
  webdavFingerprint.value = ''
  webdavPassword.value = ''
  webdavPasswordOnly.value = false
  backupTargetKind.value = 'local'
}

function resetLocal(): void {
  releaseHeldWebdavSelection()
  epoch += 1
  clearPoll()
  cancelInFlight = null
  phase.value = 'idle'
  kind.value = props.mode === 'setup' ? 'restore' : 'backup'
  startupDetail.value = ''
  progress.value = undefined
  preview.value = null
  protection.value = null
  error.value = null
  backupTarget.value = null
  selection.value = null
  password.value = ''
  passwordChoice.value = null
  plaintextAcknowledged.value = false
  confirmChecked.value = false
  operation.value = null
  pendingRequestId.value = ''
  startUnconfirmed.value = false
  cancelRequested.value = false
  resetWebdavView()
}

async function initialize(): Promise<void> {
  resetLocal()
  const myEpoch = epoch
  kind.value = props.mode === 'setup' ? 'restore' : 'backup'
  try {
    const state = await props.host.getStartupMaintenanceState()
    if (!active(myEpoch)) return
    if (state.state === 'recovery_required') {
      phase.value = 'recovery_required'
      startupDetail.value = state.detail ?? ''
    }
  } catch {
    if (!active(myEpoch)) return
    phase.value = 'error'
    error.value = {
      code: 'HOST_UNAVAILABLE',
      message: '无法读取维护状态，请重启应用后重试',
      committed: false,
      nextAction: 'restart_app',
    }
    return
  }
  void loadWebdavConfig(myEpoch)
}

async function loadWebdavConfig(myEpoch: number): Promise<void> {
  try {
    const result = await webdav.getWebdavConfig()
    if (!active(myEpoch)) return
    webdavAvailable.value = result.available
    webdavConfig.value = result.config
    if (result.config.url) webdavUrl.value = result.config.url
    if (result.config.username) webdavUsername.value = result.config.username
  } catch {
    if (!active(myEpoch)) return
    webdavAvailable.value = false
    webdavConfig.value = null
  }
}

function openWebdavConfig(): void {
  if (phase.value !== 'idle' || props.frozen) return
  webdavView.value = 'config'
  webdavError.value = ''
  webdavNotice.value = ''
  webdavPassword.value = ''
  if (webdavConfig.value?.url) webdavUrl.value = webdavConfig.value.url
  if (webdavConfig.value?.username) webdavUsername.value = webdavConfig.value.username
}

function closeWebdavView(): void {
  if (webdavLoading.value) return
  resetWebdavView()
}

async function saveWebdavConfigAction(): Promise<void> {
  if (webdavLoading.value || props.frozen) return
  if (!webdavUrl.value.trim() || !webdavUsername.value.trim() || !webdavPassword.value) {
    webdavError.value = '请填写 HTTPS 地址、用户名和密码'
    return
  }
  webdavError.value = ''
  webdavNotice.value = ''
  webdavLoading.value = true
  const myEpoch = epoch
  try {
    const result = await webdav.saveWebdavConfig({
      url: webdavUrl.value.trim(),
      username: webdavUsername.value.trim(),
      password: webdavPassword.value,
    })
    if (!active(myEpoch)) return
    webdavConfig.value = result.config
    webdavPassword.value = ''
    webdavNotice.value = 'WebDAV 已连接并保存到本机'
    webdavView.value = 'none'
  } catch (err) {
    if (!active(myEpoch)) return
    webdavError.value = webdavErrorMessage(err)
  } finally {
    if (active(myEpoch)) webdavLoading.value = false
  }
}

async function openWebdavVersions(): Promise<void> {
  if (!canOpenWebdavVersions.value || webdavLoading.value) return
  webdavView.value = 'versions'
  webdavError.value = ''
  webdavNotice.value = ''
  webdavSelected.value = null
  webdavVersions.value = []
  webdavLoading.value = true
  const myEpoch = epoch
  try {
    const result = await webdav.listWebdavVersions()
    if (!active(myEpoch)) return
    webdavVersions.value = result.versions
    webdavFingerprint.value = result.endpointFingerprint
    if (result.versions.length === 0) {
      webdavNotice.value = '远端还没有可恢复的备份版本'
    }
  } catch (err) {
    if (!active(myEpoch)) return
    webdavError.value = webdavErrorMessage(err)
  } finally {
    if (active(myEpoch)) webdavLoading.value = false
  }
}

function selectWebdavVersion(version: WebdavVersionView): void {
  if (webdavLoading.value || props.frozen) return
  webdavSelected.value = version
  webdavError.value = ''
}

async function downloadWebdavVersion(): Promise<void> {
  const chosen = webdavSelected.value
  if (!chosen || webdavLoading.value || props.frozen) return
  if (!webdavFingerprint.value) {
    webdavError.value = '请重新读取远端版本列表'
    return
  }
  releaseHeldWebdavSelection()
  webdavError.value = ''
  webdavView.value = 'none'
  kind.value = 'restore'
  await beginStart('downloading', (requestId) =>
    webdav.startWebdavDownload({
      requestId,
      versionName: chosen.name,
      endpointFingerprint: webdavFingerprint.value,
    }),
  )
}

function openWebdavBackupPassword(): void {
  if (!canStartWebdavBackup.value) return
  webdavError.value = ''
  webdavNotice.value = ''
  webdavPassword.value = ''
  webdavPasswordOnly.value = true
  kind.value = 'backup'
  passwordChoice.value = 'password'
  phase.value = 'password'
}

async function startWebdavBackup(): Promise<void> {
  if (!webdavPasswordOnly.value || !password.value) return
  const secret = password.value
  webdavPasswordOnly.value = false
  backupTargetKind.value = 'webdav'
  await beginStart('creating', (requestId) =>
    webdav.startWebdavBackup({ requestId, password: secret }),
  )
}

function webdavErrorMessage(err: unknown): string {
  // Cross-realm safe: the host adapter and this panel may not share an Error
  // constructor, but every host error carries a teacher-facing message.
  if (
    err &&
    typeof err === 'object' &&
    typeof (err as { message?: unknown }).message === 'string' &&
    (err as { message: string }).message
  ) {
    return (err as { message: string }).message
  }
  return 'WebDAV 操作失败，请稍后重试'
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '—'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GiB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KiB`
  return `${bytes} B`
}

function active(myEpoch: number): boolean {
  return !disposed && props.open && myEpoch === epoch
}

function statusMatches(status: MaintenanceStatus): boolean {
  if (disposed || !props.open || status.stale) return false
  if (pendingRequestId.value) {
    return statusMatchesRef({ requestId: pendingRequestId.value }, status)
  }
  if (operation.value) {
    return statusMatchesRef(
      {
        operationId: operation.value.operationId,
        generation: operation.value.generation,
      },
      status,
    )
  }
  return false
}

async function chooseBackupTarget(): Promise<void> {
  if (!canStartBackup.value || phase.value !== 'idle') return
  error.value = null
  progress.value = { stage: '正在打开本地保存位置…', indeterminate: true }
  phase.value = 'selecting'
  const myEpoch = epoch
  try {
    const result = await props.host.chooseBackupTarget()
    if (!active(myEpoch)) return
    if (!result.ok) {
      phase.value = 'idle'
      progress.value = undefined
      return
    }
    backupTarget.value = result.target
    kind.value = 'backup'
    passwordChoice.value = null
    password.value = ''
    plaintextAcknowledged.value = false
    phase.value = 'password'
    progress.value = undefined
  } catch {
    if (!active(myEpoch)) return
    phase.value = 'error'
    progress.value = undefined
    error.value = {
      code: 'HOST_UNAVAILABLE',
      message: '无法打开本地保存位置，请稍后重试',
      committed: false,
      nextAction: 'retry',
    }
  }
}

async function chooseRestoreSource(): Promise<void> {
  if (!canStartRestore.value || phase.value !== 'idle') return
  error.value = null
  progress.value = { stage: '正在打开本地备份文件…', indeterminate: true }
  phase.value = 'selecting'
  const myEpoch = epoch
  try {
    const result = await props.host.chooseRestoreSource()
    if (!active(myEpoch)) return
    if (!result.ok) {
      phase.value = 'idle'
      progress.value = undefined
      return
    }
    selection.value = result.selection
    kind.value = 'restore'
    password.value = ''
    progress.value = undefined
    if (result.selection.encrypted) {
      phase.value = 'password'
    } else {
      await startRestoreVerify()
    }
  } catch {
    if (!active(myEpoch)) return
    phase.value = 'error'
    progress.value = undefined
    error.value = {
      code: 'HOST_UNAVAILABLE',
      message: '无法打开本地备份文件，请稍后重试',
      committed: false,
      nextAction: 'retry',
    }
  }
}

function choosePasswordMode(value: 'password' | 'plaintext'): void {
  if (phase.value !== 'password' || kind.value !== 'backup') return
  passwordChoice.value = value
  plaintextAcknowledged.value = false
  password.value = ''
  error.value = null
}

function onPasswordMode(value: unknown): void {
  if (value === 'password' || value === 'plaintext') {
    choosePasswordMode(value)
  }
}

async function submitCredentials(): Promise<void> {
  if (phase.value !== 'password' || props.frozen) return
  if (kind.value === 'backup') {
    if (webdavPasswordOnly.value) {
      if (!password.value) {
        error.value = {
          code: 'PASSWORD_REQUIRED',
          message: '请输入密码；WebDAV 备份必须加密',
          committed: false,
          nextAction: 'retry',
        }
        return
      }
      await startWebdavBackup()
      return
    }
    if (passwordChoice.value === null) {
      error.value = {
        code: 'PASSWORD_MODE_REQUIRED',
        message: '请选择是否使用密码加密',
        committed: false,
        nextAction: 'retry',
      }
      return
    }
    if (passwordChoice.value === 'password' && !password.value) {
      error.value = {
        code: 'PASSWORD_REQUIRED',
        message: '请输入密码；不会自动降级为明文',
        committed: false,
        nextAction: 'retry',
      }
      return
    }
    if (
      passwordChoice.value === 'plaintext' &&
      !plaintextAcknowledged.value
    ) {
      error.value = {
        code: 'PLAINTEXT_NOT_ACKNOWLEDGED',
        message: '请确认明文备份包含可读业务和照片',
        committed: false,
        nextAction: 'retry',
      }
      return
    }
    await startBackup()
    return
  }
  if (selection.value?.encrypted && !password.value) {
    error.value = {
      code: 'PASSWORD_REQUIRED',
      message: '请输入备份密码',
      committed: false,
      nextAction: 'retry_password',
    }
    return
  }
  await startRestoreVerify()
}

async function startBackup(): Promise<void> {
  if (!backupTarget.value || phase.value !== 'password') return
  const target = backupTarget.value
  const choice = passwordChoice.value
  if (choice === null) return
  const secret = choice === 'password' ? password.value : null
  if (choice === 'password' && !secret) return
  if (choice === 'plaintext' && !plaintextAcknowledged.value) return
  kind.value = 'backup'
  backupTargetKind.value = 'local'
  await beginStart('creating', (requestId) =>
    props.host.startBackup({
      requestId,
      targetId: target.targetId,
      password: secret,
      explicitPlaintext: choice === 'plaintext',
    }),
  )
}

async function startRestoreVerify(): Promise<void> {
  if (!selection.value) return
  if (selection.value.encrypted && !password.value) return
  const selected = selection.value
  const secret = selected.encrypted ? password.value : null
  kind.value = 'restore'
  await beginStart('verifying', (requestId) =>
    props.host.startRestoreVerify({
      requestId,
      selectionId: selected.selectionId,
      password: secret,
    }),
  )
}

async function beginStart(
  startingPhase: 'creating' | 'verifying' | 'downloading',
  call: (requestId: string) => Promise<MaintenanceOperationRef>,
): Promise<void> {
  const requestId = newRequestId()
  const myEpoch = ++epoch
  pendingRequestId.value = requestId
  startUnconfirmed.value = false
  operation.value = null
  error.value = null
  cancelRequested.value = false
  phase.value = startingPhase
  progress.value = {
    stage:
      startingPhase === 'creating'
        ? '正在创建完整备份，请稍候…'
        : startingPhase === 'downloading'
          ? '正在下载远端备份…'
          : '正在校验备份并准备预览…',
    indeterminate: true,
  }
  password.value = ''
  try {
    const ref = await call(requestId)
    if (!active(myEpoch)) return
    if (!ref || ref.requestId !== requestId || !ref.operationId) {
      await queryPendingStart(myEpoch)
      return
    }
    operation.value = ref
    pendingRequestId.value = ''
    schedulePoll()
  } catch {
    if (!active(myEpoch)) return
    await queryPendingStart(myEpoch)
  }
}

async function queryPendingStart(myEpoch: number): Promise<void> {
  const requestId = pendingRequestId.value
  if (!requestId) return
  startUnconfirmed.value = true
  progress.value = {
    stage: '开始结果待核对，正在按同一请求查询…',
    indeterminate: true,
  }
  try {
    const result = await props.host.queryMaintenance({ requestId })
    if (!active(myEpoch) || pendingRequestId.value !== requestId) return
    if (result.state === 'found') {
      adoptStatus(result.status)
      return
    }
  } catch {
    // Keep the same request pending; never start a second side effect.
  }
  if (!active(myEpoch)) return
  startUnconfirmed.value = true
  progress.value = {
    stage: '开始结果尚未确认，请继续查询；不会重复发起操作',
    indeterminate: true,
  }
  schedulePoll()
}

async function recheckStart(): Promise<void> {
  if (!pendingRequestId.value || props.frozen) return
  await queryPendingStart(epoch)
}

async function refreshStatus(): Promise<void> {
  if (disposed || !props.open || polling) return
  const ref = pendingRequestId.value
    ? { requestId: pendingRequestId.value }
    : operation.value
      ? {
          operationId: operation.value.operationId,
          generation: operation.value.generation,
        }
      : null
  if (!ref) return
  polling = true
  try {
    const result = await props.host.queryMaintenance(ref)
    if (disposed || !props.open) return
    if (result.state === 'found') adoptStatus(result.status)
  } catch {
    // A lost/late status reply changes nothing; the next poll/retry may answer.
  } finally {
    polling = false
  }
}

function schedulePoll(): void {
  clearPoll()
  if (disposed || !props.open) return
  pollTimer = setTimeout(() => {
    pollTimer = null
    void refreshStatus().then(() => {
      if (
        !disposed &&
        props.open &&
        (pendingRequestId.value !== '' || shouldPoll(phase.value))
      ) {
        schedulePoll()
      }
    })
  }, POLL_MS)
}

function shouldPoll(value: MaintenancePhase): boolean {
  return (
    pendingRequestId.value !== '' ||
    value === 'creating' ||
    value === 'verifying' ||
    value === 'downloading' ||
    value === 'waiting' ||
    value === 'protection' ||
    value === 'switching' ||
    value === 'reopening'
  )
}

function adoptStatus(status: MaintenanceStatus): void {
  if (!statusMatches(status)) return
  if (isTerminalPhase(phase.value)) return
  const sameOperation =
    operation.value !== null &&
    status.operationId === operation.value.operationId &&
    status.generation === operation.value.generation
  if (
    sameOperation &&
    status.error?.code !== 'WRONG_PASSWORD' &&
    isPhaseRegression(phase.value, status.phase)
  ) {
    return
  }
  if (!operation.value) {
    operation.value = operationRefOf(status)
  }
  pendingRequestId.value = operation.value ? '' : pendingRequestId.value
  startUnconfirmed.value = false
  progress.value = status.progress
  if (status.preview) preview.value = status.preview
  if (status.protection) protection.value = status.protection
  if (status.error) error.value = status.error
  if (typeof status.cancelRequested === 'boolean') {
    cancelRequested.value = status.cancelRequested
  }
  if (status.phase === 'password' && status.error?.code === 'WRONG_PASSWORD') {
    phase.value = 'password'
    password.value = ''
    error.value = status.error
    operation.value = null
    pendingRequestId.value = ''
    clearPoll()
    return
  }
  if (status.phase === 'downloaded') {
    // A WebDAV version finished downloading into private staging.  This is a
    // hand-off, not a restore: continue with the same verify/preview/confirm
    // chain the local flow uses, and keep the selection for a wrong-password
    // retry (the host retains its staging).
    clearPoll()
    password.value = ''
    operation.value = null
    pendingRequestId.value = ''
    const handed = status.selection
    if (!handed) {
      phase.value = 'error'
      error.value = {
        code: 'WEBDAV_DOWNLOAD_FAILED',
        message: '远端备份未返回可恢复的选择，请重新下载',
        committed: false,
        nextAction: 'retry',
      }
      return
    }
    selection.value = handed
    webdavSelectionId.value = handed.selectionId
    kind.value = 'restore'
    if (handed.encrypted) {
      phase.value = 'password'
    } else {
      void startRestoreVerify()
    }
    return
  }
  phase.value = status.phase
  if (status.phase === 'preview') {
    clearPoll()
    return
  }
  if (status.phase === 'completed') {
    complete(status)
    return
  }
  if (status.phase === 'cancelled') {
    clearPoll()
    password.value = ''
    operation.value = null
    pendingRequestId.value = ''
    return
  }
  if (status.phase === 'error') {
    clearPoll()
    password.value = ''
    return
  }
}

function complete(status: MaintenanceStatus): void {
  clearPoll()
  password.value = ''
  if (kind.value === 'restore' && status.reopened !== true) {
    phase.value = 'error'
    error.value = {
      code: 'REOPEN_FAILED',
      message: REOPEN_FAILED_MESSAGE,
      committed: true,
      nextAction: 'restart_app',
    }
    return
  }
  phase.value = 'completed'
  const completion: MaintenanceCompletion = {
    kind: kind.value,
    requestId: status.requestId,
    operationId: status.operationId,
    committed: true,
    reopened: kind.value === 'restore' ? status.reopened === true : false,
    protectionDisplay: protection.value?.displayText,
  }
  if (kind.value === 'backup') {
    completion.target = backupTargetKind.value
  }
  emit('completed', completion)
  if (completion.kind === 'restore' && completion.reopened) {
    emit('recovered')
  }
}

async function confirmRestoreAction(): Promise<void> {
  if (!canConfirmPreview.value || !preview.value || !operation.value) return
  const previewOperation = operation.value
  const requestId = newRequestId()
  const myEpoch = ++epoch
  pendingRequestId.value = requestId
  startUnconfirmed.value = false
  phase.value = 'waiting'
  progress.value = {
    stage: '正在保存当前工作并等待已接受操作完成…',
    indeterminate: true,
  }
  error.value = null
  try {
    const ref = await props.host.confirmRestore({
      requestId,
      operationId: previewOperation.operationId,
      generation: previewOperation.generation,
      confirmationToken: preview.value.confirmationToken,
    })
    if (!active(myEpoch)) return
    const validReply =
      ref !== null &&
      ref.requestId === requestId &&
      ref.operationId === previewOperation.operationId &&
      ref.generation >= previewOperation.generation
    if (validReply) {
      operation.value = {
        requestId,
        operationId: previewOperation.operationId,
        generation: ref.generation,
      }
      pendingRequestId.value = ''
      schedulePoll()
      return
    }
    await queryPendingConfirm(myEpoch, requestId)
  } catch {
    if (!active(myEpoch)) return
    await queryPendingConfirm(myEpoch, requestId)
  }
}

async function queryPendingConfirm(
  myEpoch: number,
  requestId: string,
): Promise<void> {
  try {
    const result = await props.host.queryMaintenance({ requestId })
    if (!active(myEpoch) || pendingRequestId.value !== requestId) return
    if (result.state === 'found') {
      adoptStatus(result.status)
      return
    }
  } catch {
    // Keep waiting on the same confirm request; never send a second confirm.
  }
  if (!active(myEpoch)) return
  startUnconfirmed.value = true
  phase.value = 'waiting'
  progress.value = {
    stage: '确认结果尚未返回，正在按同一请求核对；不会重复提交',
    indeterminate: true,
  }
  schedulePoll()
}

async function cancel(): Promise<void> {
  if (!canCancel.value) return
  if (phase.value === 'selecting') {
    epoch += 1
    phase.value = 'idle'
    progress.value = undefined
    return
  }
  if (phase.value === 'password' && !operation.value && !pendingRequestId.value) {
    epoch += 1
    if (kind.value === 'restore') releaseHeldWebdavSelection()
    phase.value = 'idle'
    preview.value = null
    selection.value = null
    backupTarget.value = null
    password.value = ''
    passwordChoice.value = null
    plaintextAcknowledged.value = false
    error.value = null
    webdavPasswordOnly.value = false
    return
  }
  if (cancelInFlight) return cancelInFlight
  const ref = pendingRequestId.value
    ? { requestId: pendingRequestId.value }
    : operation.value
      ? {
          operationId: operation.value.operationId,
          generation: operation.value.generation,
        }
      : null
  if (!ref) {
    epoch += 1
    phase.value = 'idle'
    return
  }
  const myEpoch = ++epoch
  const inFlight = performCancel(myEpoch, ref)
  cancelInFlight = inFlight
  try {
    await inFlight
  } finally {
    if (cancelInFlight === inFlight) cancelInFlight = null
  }
}

function cancelStillCurrent(
  myEpoch: number,
  ref:
    | { requestId: string }
    | { operationId: string; generation: number },
): boolean {
  if (disposed || !props.open || myEpoch !== epoch) return false
  if ('operationId' in ref) {
    return (
      operation.value?.operationId === ref.operationId &&
      operation.value?.generation === ref.generation
    )
  }
  return (
    pendingRequestId.value === ref.requestId ||
    operation.value?.requestId === ref.requestId
  )
}

async function performCancel(
  myEpoch: number,
  ref:
    | { requestId: string }
    | { operationId: string; generation: number },
): Promise<void> {
  cancelRequested.value = true
  if (phase.value === 'switching' || phase.value === 'reopening') {
    progress.value = {
      stage: '正在完成，无法安全取消，请等待终态…',
      indeterminate: true,
    }
  }
  try {
    const ack = await props.host.cancelMaintenance(ref)
    if (!cancelStillCurrent(myEpoch, ref)) return
    if (ack.state === 'completed') {
      cancelRequested.value = true
      await refreshStatus()
      if (!disposed && !isTerminalPhase(phase.value)) schedulePoll()
      return
    }
    if (ack.state === 'too_late') {
      phase.value = 'switching'
      cancelRequested.value = true
      progress.value = {
        stage: '操作已进入完成阶段，正在等待终态…',
        indeterminate: true,
      }
      schedulePoll()
      return
    }
    if (ack.state === 'cancelled') {
      epoch += 1
      phase.value = 'cancelled'
      clearPoll()
      password.value = ''
      preview.value = null
      operation.value = null
      pendingRequestId.value = ''
      progress.value = undefined
      return
    }
    // unknown / not accepted: keep the current state; no fake cancellation.
    if (!disposed) schedulePoll()
  } catch {
    if (!cancelStillCurrent(myEpoch, ref)) return
    // A lost cancel reply is not a cancel; keep polling the operation.
    schedulePoll()
  }
}

async function recheck(): Promise<void> {
  if (pendingRequestId.value) {
    await recheckStart()
  } else {
    await refreshStatus()
  }
}

function close(): void {
  if (!canClose.value) return
  emit('update:open', false)
  resetLocal()
}

function onDialogValue(value: boolean): void {
  if (value) {
    emit('update:open', true)
    return
  }
  close()
}
</script>

<template>
  <el-dialog
    :model-value="props.open"
    :title="title"
    width="900px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="canClose"
    data-d1="backup-restore-panel"
    @update:model-value="onDialogValue"
  >
    <div class="backup-panel">
      <div class="kgm-page-layout">
        <div class="kgm-page-main">
          <div class="kgm-sheet">
            <div class="kgm-sheet-header">{{ kind === 'backup' ? '创建完整备份' : (props.mode === 'setup' ? '从备份恢复' : '从本地备份恢复') }}</div>
            <div class="kgm-preview-wrap">
              <table class="kgm-preview-table" data-d1="backup-status-table">
                <thead>
                  <tr><th>操作</th><th>当前状态</th><th>进度</th></tr>
                </thead>
                <tbody>
                  <tr data-d1="backup-operation-status">
                    <td>{{ kind === 'backup' ? '完整备份' : '从本地备份恢复' }}</td>
                    <td>{{ title }}</td>
                    <td>{{ progressText || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <el-alert
            v-if="phase === 'recovery_required'"
            type="error"
            :closable="false"
            data-d1="backup-recovery-required"
            title="上次恢复状态未确认，已停止写入"
            :description="startupDetail || '请重启应用，并按提示处理上次恢复；不会自动猜测成功。'"
          />

          <div v-if="phase === 'idle'" class="kgm-sheet">
            <div class="kgm-sheet-header">{{ kind === 'backup' ? '备份设置' : '恢复说明' }}</div>
            <p class="muted sheet-note">
              {{
                props.mode === 'setup'
                  ? '当前还没有教师档案。可从本地备份文件或 WebDAV 备份恢复；恢复前会先校验、预览并保留当前空档案的保护副本。'
                  : '备份包含全部受管业务、设置、历史与照片；恢复会替换当前档案并保留恢复前完整保护副本。'
              }}
            </p>
            <div class="kgm-preview-wrap">
              <table class="kgm-preview-table" data-d1="backup-operations-table">
                <thead>
                  <tr><th>操作</th><th>说明</th><th>当前阶段</th></tr>
                </thead>
                <tbody>
                  <tr v-if="props.mode === 'settings'" data-d1="backup-operation-backup">
                    <td>完整备份</td>
                    <td>选择本地保存位置后，再明确选择密码加密或明文。</td>
                    <td>可在右侧创建</td>
                  </tr>
                  <tr data-d1="backup-operation-restore">
                    <td>从本地备份恢复</td>
                    <td>校验后先显示预览，再确认替换并保留保护副本。</td>
                    <td>可在右侧校验</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="kgm-sheet-header" data-d1="backup-webdav-header">WebDAV 远端备份</div>
            <p class="muted sheet-note">
              远端备份必须使用密码加密；WebDAV 密码只保存在本机受保护存储，
              不会写入备份包或日志。两台电脑连接同一 WebDAV 地址即可跨机恢复。
            </p>

            <el-alert
              v-if="webdavError"
              type="error"
              :closable="false"
              role="alert"
              data-d1="backup-webdav-error"
              :title="webdavError"
            />
            <el-alert
              v-if="webdavNotice"
              type="success"
              :closable="false"
              data-d1="backup-webdav-notice"
              :title="webdavNotice"
            />

            <div v-if="webdavView === 'config'" class="preview" data-d1="backup-webdav-config">
              <p class="muted">请输入 WebDAV 的 HTTPS 地址、用户名和密码。保存前会先连接并校验目录。</p>
              <div class="webdav-field">
                <span class="muted">https 地址（集合目录）</span>
                <el-input
                  v-model="webdavUrl"
                  :disabled="props.frozen || webdavLoading"
                  data-d1="backup-webdav-url"
                  placeholder="https://example.com/dav/kgm-backups/"
                />
              </div>
              <div class="webdav-field">
                <span class="muted">用户名</span>
                <el-input
                  v-model="webdavUsername"
                  :disabled="props.frozen || webdavLoading"
                  data-d1="backup-webdav-username"
                  autocomplete="username"
                />
              </div>
              <div class="webdav-field">
                <span class="muted">密码</span>
                <el-input
                  v-model="webdavPassword"
                  type="password"
                  autocomplete="new-password"
                  :disabled="props.frozen || webdavLoading"
                  data-d1="backup-webdav-password"
                />
              </div>
              <div class="actions">
                <el-button
                  type="primary"
                  :loading="webdavLoading"
                  :disabled="props.frozen"
                  data-d1="backup-webdav-save"
                  @click="saveWebdavConfigAction"
                >
                  连接并保存到本机
                </el-button>
                <el-button :disabled="webdavLoading" data-d1="backup-webdav-cancel" @click="closeWebdavView">
                  取消
                </el-button>
              </div>
            </div>

            <div v-else-if="webdavView === 'versions'" class="preview" data-d1="backup-webdav-versions">
              <p class="muted">选择一个远端版本，下载到独立暂存后再走本地校验、预览和确认替换。</p>
              <el-alert
                v-if="webdavLoading"
                type="info"
                :closable="false"
                title="正在读取远端版本列表…"
              />
              <div v-if="webdavVersions.length" class="kgm-preview-wrap">
                <table class="kgm-preview-table" data-d1="backup-webdav-version-table">
                  <thead>
                    <tr><th>版本文件</th><th>大小</th><th>选择</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="version in webdavVersions" :key="version.name">
                      <td>
                        {{ version.name }}
                        <span v-if="version.modifiedAt" class="muted"> · {{ version.modifiedAt }}</span>
                      </td>
                      <td>{{ formatSize(version.size) }}</td>
                      <td>
                        <el-radio
                          :model-value="webdavSelected?.name ?? ''"
                          :value="version.name"
                          :disabled="props.frozen || webdavLoading"
                          :data-d1="`backup-webdav-version-${version.name}`"
                          @update:model-value="selectWebdavVersion(version)"
                        >
                          选择
                        </el-radio>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="actions">
                <el-button
                  type="primary"
                  :disabled="!webdavSelected || props.frozen || webdavLoading"
                  data-d1="backup-webdav-download"
                  @click="downloadWebdavVersion"
                >
                  下载并校验
                </el-button>
                <el-button :disabled="webdavLoading" data-d1="backup-webdav-versions-close" @click="closeWebdavView">
                  关闭
                </el-button>
              </div>
            </div>

            <div v-else class="preview" data-d1="backup-webdav-summary">
              <p v-if="webdavConfigured">
                已配置：{{ webdavConfig?.url }}（用户 {{ webdavConfig?.username }}）
              </p>
              <p v-else-if="webdavPasswordUnavailable" class="muted">
                本机保存的 WebDAV 密码不可用（可能来自其他 Windows 用户或电脑），请重新填写。
              </p>
              <p v-else-if="!webdavAvailable" class="muted">
                本机维护服务未提供 WebDAV；仍可使用上面的本地备份与恢复。
              </p>
              <p v-else class="muted">尚未配置 WebDAV。配置后可备份到远端或从远端恢复。</p>
              <div class="actions">
                <el-button
                  :disabled="props.frozen || webdavLoading"
                  data-d1="backup-webdav-configure"
                  @click="openWebdavConfig"
                >
                  {{ webdavConfigured ? '修改 WebDAV 配置' : '配置 WebDAV' }}
                </el-button>
                <el-button
                  :disabled="!canOpenWebdavVersions || webdavLoading"
                  data-d1="backup-webdav-list"
                  @click="openWebdavVersions"
                >
                  从 WebDAV 恢复
                </el-button>
              </div>
            </div>
          </div>

          <div v-else-if="phase === 'selecting'" class="kgm-sheet">
            <div class="kgm-sheet-header">选择本地位置</div>
            <p class="sheet-note">{{ progressText }}</p>
          </div>

          <div v-else-if="phase === 'password'" class="kgm-sheet">
            <div class="kgm-sheet-header">
              {{
                kind === 'backup'
                  ? webdavPasswordOnly
                    ? 'WebDAV 备份密码'
                    : '备份密码'
                  : '输入备份密码'
              }}
            </div>
            <p v-if="kind === 'backup' && webdavPasswordOnly" class="muted sheet-note">
              远端备份必须使用密码加密；请设置本次备份密码。密码丢失后无法从该备份恢复。
            </p>
            <p v-else-if="kind === 'backup'" class="muted sheet-note">
              请选择本次备份是否使用密码。密码丢失后无法找回；不加密文件包含可读业务和照片。
            </p>
            <p v-else class="muted sheet-note">该备份使用密码加密，请输入密码。</p>
            <p v-if="kind === 'backup' && !webdavPasswordOnly && passwordChoice === null" class="muted sheet-note" data-d1="backup-password-choose">
              请选择是否使用密码加密。
            </p>
          </div>

          <div
            v-else-if="phase === 'creating' || phase === 'verifying' || phase === 'downloading' || phase === 'waiting' || phase === 'protection' || phase === 'switching' || phase === 'reopening'"
            class="kgm-sheet"
          >
            <div class="kgm-sheet-header">{{ title }}</div>
            <p class="sheet-note">{{ progressText }}</p>
            <el-progress
              v-if="progressPercentValue !== null"
              :percentage="progressPercentValue"
              :stroke-width="10"
            />
            <p v-if="pendingRequestId" class="muted sheet-note" data-d1="backup-pending-start">
              结果待核对；将按同一请求查询，不会重复发起操作。
            </p>
            <p v-if="startUnconfirmed" class="muted sheet-note">尚未确认开始结果，请继续查询。</p>
            <el-alert
              v-if="protection"
              type="info"
              :closable="false"
              data-d1="backup-protection-location"
              :title="kind === 'restore' ? '恢复前保护副本' : '备份文件'"
              :description="protection.displayText"
            />
            <p v-if="cancelRequested" class="muted sheet-note" data-d1="backup-cancel-requested">
              已请求取消；若已进入完成阶段，将等待真实终态，不报假取消。
            </p>
          </div>

          <div v-else-if="phase === 'preview' && preview" class="kgm-sheet">
            <div class="kgm-sheet-header">恢复预览（尚未替换）</div>
            <div class="preview" data-d1="backup-preview">
              <p><strong>{{ preview.displayName }}</strong></p>
              <p class="muted">
                创建时间 {{ preview.createdAt }} · 应用 {{ preview.appVersion }} ·
                格式 {{ preview.formatVersion }} · 数据库 {{ preview.dbRevision }}
              </p>
              <p v-if="preview.profileLabel">档案：{{ preview.profileLabel }}</p>
              <p v-if="preview.classLabel">班级：{{ preview.classLabel }}</p>
              <p v-if="preview.termLabel">学期：{{ preview.termLabel }}</p>
              <p>
                日计划 {{ preview.counts.plans }} · 观察 {{ preview.counts.observations }} ·
                照片 {{ preview.counts.photos }}<span v-if="preview.counts.others"> · 其他 {{ preview.counts.others }}</span>
              </p>
              <p class="muted">{{ credentialLabel }}</p>
            </div>
            <el-checkbox v-model="confirmChecked" :disabled="props.frozen" data-d1="backup-confirm-check">
              我了解将替换当前档案；恢复前完整保护副本会保留，且不自动删除。
            </el-checkbox>
          </div>

          <div v-else-if="phase === 'completed'" class="kgm-sheet">
            <el-result
              icon="success"
              :title="kind === 'restore' ? '恢复完成' : '备份完成'"
              :sub-title="kind === 'restore' ? '资料已恢复并重新打开。' : '备份已完成并校验。'"
            />
            <el-alert
              v-if="protection"
              type="info"
              :closable="false"
              data-d1="backup-protection-location-complete"
              :title="kind === 'restore' ? '恢复前保护副本' : '备份文件'"
              :description="protection.displayText"
            />
          </div>

          <div v-else-if="phase === 'cancelled'" class="kgm-sheet">
            <el-alert
              type="info"
              :closable="false"
              data-d1="backup-cancelled"
              title="已取消，当前档案未更改"
            />
            <el-alert
              v-if="protection"
              type="info"
              :closable="false"
              data-d1="backup-protection-location-cancelled"
              :title="kind === 'restore' ? '恢复前保护副本' : '备份文件'"
              :description="protection.displayText"
            />
          </div>

          <div v-else-if="phase === 'error'" class="kgm-sheet">
            <el-alert
              type="error"
              :closable="false"
              data-d1="backup-error"
              :title="errorTextValue"
              :description="error?.committed ? '当前档案已被替换；请按提示重启或联系维护者。' : '当前档案未更改。'"
            />
            <el-alert
              v-if="protection"
              type="info"
              :closable="false"
              data-d1="backup-protection-location-error"
              :title="kind === 'restore' ? '恢复前保护副本' : '备份文件'"
              :description="protection.displayText"
            />
          </div>

          <el-alert
            v-if="error && phase !== 'error' && phase !== 'password'"
            type="error"
            :closable="false"
            data-d1="backup-inline-error"
            :title="errorTextValue"
          />
          <el-alert
            v-if="error && phase === 'password'"
            type="error"
            :closable="false"
            data-d1="backup-password-error"
            :title="errorTextValue"
          />
        </div>

        <aside class="kgm-page-rail" aria-label="备份与恢复操作">
          <div class="kgm-rail-panel">
            <h3 class="kgm-rail-title">操作</h3>
            <template v-if="phase === 'idle'">
              <el-button
                v-if="props.mode === 'settings'"
                type="primary"
                class="kgm-primary-action"
                :disabled="!canStartBackup"
                data-d1="backup-create"
                @click="chooseBackupTarget"
              >
                创建完整备份
              </el-button>
              <el-button
                :type="props.mode === 'setup' ? 'primary' : 'default'"
                :class="{ 'kgm-primary-action': props.mode === 'setup' }"
                :disabled="!canStartRestore"
                data-d1="backup-restore"
                @click="chooseRestoreSource"
              >
                从本地备份恢复
              </el-button>
              <el-button
                v-if="props.mode === 'settings'"
                type="success"
                :disabled="!canStartWebdavBackup"
                data-d1="backup-webdav-create"
                @click="openWebdavBackupPassword"
              >
                备份到 WebDAV
              </el-button>
            </template>

            <template v-else-if="phase === 'selecting'">
              <el-button :disabled="props.frozen" data-d1="backup-selecting-cancel" @click="cancel">
                取消
              </el-button>
            </template>

            <template v-else-if="phase === 'password'">
              <div v-if="kind === 'backup' && !webdavPasswordOnly" class="rail-field">
                <span class="muted">密码方式</span>
                <el-radio-group
                  :model-value="passwordChoice"
                  :disabled="props.frozen"
                  data-d1="backup-password-mode"
                  @update:model-value="onPasswordMode"
                >
                  <el-radio value="password">使用密码加密</el-radio>
                  <el-radio value="plaintext">不加密（文件含可读业务与照片）</el-radio>
                </el-radio-group>
              </div>
              <p v-if="webdavPasswordOnly" class="muted" data-d1="backup-webdav-password-only">
                WebDAV 远端备份必须加密，不提供明文选项。
              </p>
              <el-input
                v-if="passwordRequired"
                v-model="password"
                type="password"
                autocomplete="new-password"
                :disabled="props.frozen"
                data-d1="backup-password"
                placeholder="请输入密码"
              />
              <el-checkbox
                v-if="kind === 'backup' && passwordChoice === 'plaintext'"
                v-model="plaintextAcknowledged"
                :disabled="props.frozen"
                data-d1="backup-plaintext-ack"
              >
                我了解明文备份包含可读业务和照片
              </el-checkbox>
              <el-button
                type="primary"
                class="kgm-primary-action"
                :disabled="props.frozen || !canSubmitCredentials"
                data-d1="backup-password-submit"
                @click="submitCredentials"
              >
                {{ kind === 'backup' ? (webdavPasswordOnly ? '上传到 WebDAV' : '开始创建') : '校验备份' }}
              </el-button>
              <el-button :disabled="props.frozen" data-d1="backup-password-cancel" @click="cancel">
                取消
              </el-button>
            </template>

            <template v-else-if="phase === 'creating' || phase === 'verifying' || phase === 'downloading' || phase === 'waiting' || phase === 'protection' || phase === 'switching' || phase === 'reopening'">
              <el-button
                v-if="pendingRequestId || startUnconfirmed"
                :disabled="props.frozen"
                data-d1="backup-recheck"
                @click="recheck"
              >
                查询结果
              </el-button>
              <el-button
                :disabled="props.frozen || !canCancel"
                data-d1="backup-cancel"
                @click="cancel"
              >
                取消
              </el-button>
            </template>

            <template v-else-if="phase === 'preview' && preview">
              <el-button
                type="primary"
                class="kgm-primary-action"
                :disabled="!canConfirmPreview"
                data-d1="backup-confirm-restore"
                @click="confirmRestoreAction"
              >
                确认替换当前档案
              </el-button>
              <el-button :disabled="props.frozen" data-d1="backup-preview-cancel" @click="cancel">
                取消
              </el-button>
            </template>

            <template v-else-if="phase === 'completed'">
              <el-button type="primary" class="kgm-primary-action" data-d1="backup-close" @click="close">
                关闭
              </el-button>
            </template>

            <template v-else-if="phase === 'cancelled'">
              <el-button data-d1="backup-cancelled-close" @click="close">关闭</el-button>
            </template>

            <template v-else-if="phase === 'error'">
              <el-button v-if="pendingRequestId || startUnconfirmed" :disabled="props.frozen" @click="recheck">
                查询结果
              </el-button>
              <el-button data-d1="backup-error-close" @click="close">关闭</el-button>
            </template>

            <p class="muted">备份位置、密码、恢复预览和替换确认均按原流程；WebDAV 版本先下载到独立暂存再校验，本面板不会自动猜测未确认结果。</p>
          </div>
        </aside>
      </div>
    </div>
  </el-dialog>
</template>


<style scoped>
.backup-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.sheet-note {
  margin: 0;
  padding: 0 18px 16px;
}
.rail-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rail-field :deep(.el-radio-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.webdav-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.muted {
  color: var(--kgm-muted);
  font-size: 0.9rem;
  white-space: pre-wrap;
}
.preview {
  padding: 10px 12px;
  border: 1px solid var(--kgm-border);
  border-radius: 6px;
  white-space: pre-wrap;
}
</style>
