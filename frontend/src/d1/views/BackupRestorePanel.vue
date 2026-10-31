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
  if (props.frozen || passwordChoice.value === null && kind.value === 'backup') {
    return false
  }
  if (kind.value === 'restore') {
    return !selection.value?.encrypted || password.value.length > 0
  }
  if (passwordChoice.value === 'password') return password.value.length > 0
  return passwordChoice.value === 'plaintext' && plaintextAcknowledged.value
})
const passwordRequired = computed(
  () =>
    kind.value === 'restore'
      ? selection.value?.encrypted === true
      : passwordChoice.value === 'password',
)
const progressPercentValue = computed(() => progressPercent(progress.value))
const progressText = computed(() => progressLabel(progress.value))
const errorTextValue = computed(() => errorText(error.value ?? undefined))
const title = computed(() => phaseText(phase.value, kind.value))
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

function resetLocal(): void {
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
  }
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
  startingPhase: 'creating' | 'verifying',
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
    phase.value = 'idle'
    preview.value = null
    selection.value = null
    backupTarget.value = null
    password.value = ''
    passwordChoice.value = null
    plaintextAcknowledged.value = false
    error.value = null
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
    width="560px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="canClose"
    data-d1="backup-restore-panel"
    @update:model-value="onDialogValue"
  >
    <div class="backup-panel">
      <el-alert
        v-if="phase === 'recovery_required'"
        type="error"
        :closable="false"
        data-d1="backup-recovery-required"
        title="上次恢复状态未确认，已停止写入"
        :description="startupDetail || '请重启应用，并按提示处理上次恢复；不会自动猜测成功。'"
      />

      <template v-else-if="phase === 'idle'">
        <p class="muted">
          {{
            props.mode === 'setup'
              ? '当前还没有教师档案。可从本地备份恢复；恢复前会先校验、预览并保留当前空档案的保护副本。'
              : '备份包含全部受管业务、设置、历史与照片；恢复会替换当前档案并保留恢复前完整保护副本。'
          }}
        </p>
        <div class="actions">
          <el-button
            v-if="props.mode === 'settings'"
            type="primary"
            :disabled="!canStartBackup"
            data-d1="backup-create"
            @click="chooseBackupTarget"
          >
            创建完整备份
          </el-button>
          <el-button
            :type="props.mode === 'setup' ? 'primary' : 'default'"
            :disabled="!canStartRestore"
            data-d1="backup-restore"
            @click="chooseRestoreSource"
          >
            从本地备份恢复
          </el-button>
        </div>
      </template>

      <template v-else-if="phase === 'selecting'">
        <p>{{ progressText }}</p>
        <div class="actions">
          <el-button :disabled="props.frozen" data-d1="backup-selecting-cancel" @click="cancel">
            取消
          </el-button>
        </div>
      </template>

      <template v-else-if="phase === 'password'">
        <p v-if="kind === 'backup'" class="muted">
          请选择本次备份是否使用密码。密码丢失后无法找回；不加密文件包含可读业务和照片。
        </p>
        <p v-else class="muted">该备份使用密码加密，请输入密码。</p>
        <p v-if="kind === 'backup' && passwordChoice === null" class="muted" data-d1="backup-password-choose">
          请选择是否使用密码加密。
        </p>
        <el-radio-group
          v-if="kind === 'backup'"
          :model-value="passwordChoice"
          :disabled="props.frozen"
          data-d1="backup-password-mode"
          @update:model-value="onPasswordMode"
        >
          <el-radio value="password">使用密码加密</el-radio>
          <el-radio value="plaintext">不加密（文件含可读业务与照片）</el-radio>
        </el-radio-group>
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
        <div class="actions">
          <el-button
            type="primary"
            :disabled="props.frozen || !canSubmitCredentials"
            data-d1="backup-password-submit"
            @click="submitCredentials"
          >
            {{ kind === 'backup' ? '开始创建' : '校验备份' }}
          </el-button>
          <el-button :disabled="props.frozen" data-d1="backup-password-cancel" @click="cancel">
            取消
          </el-button>
        </div>
      </template>

      <template v-else-if="phase === 'creating' || phase === 'verifying' || phase === 'waiting' || phase === 'protection' || phase === 'switching' || phase === 'reopening'">
        <p>{{ progressText }}</p>
        <el-progress
          v-if="progressPercentValue !== null"
          :percentage="progressPercentValue"
          :stroke-width="10"
        />
        <p v-if="pendingRequestId" class="muted" data-d1="backup-pending-start">
          结果待核对；将按同一请求查询，不会重复发起操作。
        </p>
        <p v-if="startUnconfirmed" class="muted">尚未确认开始结果，请继续查询。</p>
        <el-alert
          v-if="protection"
          type="info"
          :closable="false"
          data-d1="backup-protection-location"
          :title="kind === 'restore' ? '恢复前保护副本' : '备份文件'"
          :description="protection.displayText"
        />
        <div class="actions">
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
        </div>
        <p v-if="cancelRequested" class="muted" data-d1="backup-cancel-requested">
          已请求取消；若已进入完成阶段，将等待真实终态，不报假取消。
        </p>
      </template>

      <template v-else-if="phase === 'preview' && preview">
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
        <div class="actions">
          <el-button
            type="primary"
            :disabled="!canConfirmPreview"
            data-d1="backup-confirm-restore"
            @click="confirmRestoreAction"
          >
            确认替换当前档案
          </el-button>
          <el-button :disabled="props.frozen" data-d1="backup-preview-cancel" @click="cancel">
            取消
          </el-button>
        </div>
      </template>

      <template v-else-if="phase === 'completed'">
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
        <div class="actions">
          <el-button type="primary" data-d1="backup-close" @click="close">关闭</el-button>
        </div>
      </template>

      <template v-else-if="phase === 'cancelled'">
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
        <div class="actions">
          <el-button data-d1="backup-cancelled-close" @click="close">关闭</el-button>
        </div>
      </template>

      <template v-else-if="phase === 'error'">
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
        <div class="actions">
          <el-button v-if="pendingRequestId || startUnconfirmed" :disabled="props.frozen" @click="recheck">
            查询结果
          </el-button>
          <el-button data-d1="backup-error-close" @click="close">关闭</el-button>
        </div>
      </template>

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
  </el-dialog>
</template>

<style scoped>
.backup-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.muted {
  color: #606266;
  font-size: 0.9rem;
  white-space: pre-wrap;
}
.preview {
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  white-space: pre-wrap;
}
</style>
